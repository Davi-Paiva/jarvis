from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional, Tuple
from uuid import uuid4

from app.config import Settings
from app.models.repository import RepositoryAgentState, RepositoryRecord
from app.models.task import TaskAgentState
from app.services.errors import InvalidRepositoryPathError, RepositoryPathNotAllowedError
from app.services.memory_service import MemoryService
from app.services.persistence import SQLitePersistence


class RepositoryRegistry:
    def __init__(
        self,
        settings: Settings,
        persistence: SQLitePersistence,
        memory_service: MemoryService,
    ) -> None:
        self.settings = settings
        self.persistence = persistence
        self.memory_service = memory_service

    def create_repo_agent(
        self,
        repo_path: str,
        display_name: Optional[str] = None,
        branch_name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> RepositoryAgentState:
        state, _created = self.get_or_create_repo_agent(
            repo_path=repo_path,
            display_name=display_name,
            branch_name=branch_name,
            user_id=user_id,
        )
        return state

    def get_or_create_repo_agent(
        self,
        repo_path: str,
        display_name: Optional[str] = None,
        branch_name: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> Tuple[RepositoryAgentState, bool]:
        resolved_repo_path = self._resolve_allowed_repo_path(repo_path)
        owner = user_id or self.settings.jarvis_user_id
        existing_state = self.find_agent_by_repo_path(str(resolved_repo_path), owner)
        if existing_state is not None:
            self.memory_service.initialize_agent_memory(existing_state)
            return existing_state, False

        record = RepositoryRecord(
            user_id=owner,
            repo_path=str(resolved_repo_path),
            display_name=display_name or resolved_repo_path.name,
        )
        repo_agent_id = "repo_agent_" + uuid4().hex
        state = RepositoryAgentState(
            repo_agent_id=repo_agent_id,
            user_id=record.user_id,
            repo_id=record.repo_id,
            repo_path=record.repo_path,
            branch_name=branch_name,
            thread_id="repo_agent:%s" % repo_agent_id,
        )
        self.persistence.save_repository(record)
        self.persistence.save_repo_agent(state)
        self.memory_service.initialize_agent_memory(state)
        return state, True

    def find_agent_by_repo_path(
        self,
        repo_path: str,
        user_id: Optional[str] = None,
    ) -> Optional[RepositoryAgentState]:
        resolved_repo_path = self._resolve_allowed_repo_path(repo_path)
        owner = user_id or self.settings.jarvis_user_id
        for state in self.persistence.list_repo_agents(user_id=owner):
            if Path(state.repo_path).expanduser().resolve() == resolved_repo_path:
                return state
        return None

    def get_agent_state(self, repo_agent_id: str) -> RepositoryAgentState:
        state = self.persistence.get_repo_agent(repo_agent_id)
        if state is None:
            raise KeyError("Unknown repo_agent_id: %s" % repo_agent_id)
        return state

    def save_agent_state(self, state: RepositoryAgentState) -> RepositoryAgentState:
        state.touch()
        self.persistence.save_repo_agent(state)
        return state

    def list_agents(self, user_id: Optional[str] = None) -> List[RepositoryAgentState]:
        return self.persistence.list_repo_agents(user_id=user_id)

    def delete_agent(self, repo_agent_id: str) -> None:
        state = self.get_agent_state(repo_agent_id)
        self.memory_service.delete_agent_memory(state)
        self.persistence.delete_repo_agent(repo_agent_id)

    def save_task_state(self, state: TaskAgentState) -> TaskAgentState:
        state.touch()
        self.persistence.save_task_agent(state)
        return state

    def list_task_agents(self, repo_agent_id: str) -> List[TaskAgentState]:
        return self.persistence.list_task_agents(repo_agent_id)

    def _resolve_allowed_repo_path(self, repo_path: str) -> Path:
        path = Path(repo_path).expanduser().resolve()
        if not path.exists() or not path.is_dir():
            raise InvalidRepositoryPathError(
                "Repository path does not exist or is not a directory: %s" % repo_path
            )

        allowed_roots = self._allowed_roots()
        if not allowed_roots:
            return path
        if not any(_is_relative_to(path, root) for root in allowed_roots):
            raise RepositoryPathNotAllowedError(
                "Repository path is outside allowed roots: %s" % path
            )
        return path

    def _allowed_roots(self) -> List[Path]:
        roots = []
        for root in self.settings.jarvis_allowed_repo_roots:
            root_path = Path(root).expanduser()
            if root_path.exists():
                roots.append(root_path.resolve())
        return roots


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath([str(path), str(root)])
    except ValueError:
        return False
    return common == str(root)
