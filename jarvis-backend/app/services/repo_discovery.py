from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

from pydantic import BaseModel

from app.config import Settings
from app.models.repository import RepositoryAgentState
from app.services.repository_registry import RepositoryRegistry


class RepoDiscoveryCandidate(BaseModel):
    repo_path: str
    display_name: str
    already_active: bool = False
    repo_agent_id: Optional[str] = None
    score: int = 0


class RepoDiscoveryService:
    def __init__(
        self,
        settings: Settings,
        registry: RepositoryRegistry,
        max_depth: int = 4,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.max_depth = max_depth

    def resolve_repo_by_name(
        self,
        query: str,
        user_id: Optional[str] = None,
    ) -> Tuple[Optional[RepoDiscoveryCandidate], List[RepoDiscoveryCandidate]]:
        candidates = self.find_candidates(query, user_id=user_id)
        if not candidates:
            return None, []
        if len(candidates) == 1:
            return candidates[0], candidates
        if candidates[0].score >= candidates[1].score + 15:
            return candidates[0], candidates
        return None, candidates[:5]

    def find_candidates(
        self,
        query: str,
        user_id: Optional[str] = None,
        limit: int = 5,
    ) -> List[RepoDiscoveryCandidate]:
        normalized_query = _normalize_name(query)
        if not normalized_query:
            return []

        candidates = self._active_repo_candidates(user_id=user_id)
        for discovered_path in self._discover_repo_paths():
            if any(item.repo_path == str(discovered_path) for item in candidates):
                continue
            candidates.append(
                RepoDiscoveryCandidate(
                    repo_path=str(discovered_path),
                    display_name=discovered_path.name,
                )
            )

        scored = []
        for candidate in candidates:
            score = _score_candidate(normalized_query, candidate.display_name, candidate.repo_path)
            if score > 0:
                candidate.score = score
                scored.append(candidate)

        scored.sort(key=lambda item: (-item.score, item.display_name.lower(), item.repo_path))
        return scored[:limit]

    def _active_repo_candidates(self, user_id: Optional[str] = None) -> List[RepoDiscoveryCandidate]:
        result = []
        owner = user_id or self.settings.jarvis_user_id
        for state in self.registry.list_agents(user_id=owner):
            display_name = self._display_name_for_state(state)
            result.append(
                RepoDiscoveryCandidate(
                    repo_path=state.repo_path,
                    display_name=display_name,
                    already_active=True,
                    repo_agent_id=state.repo_agent_id,
                )
            )
        return result

    def _display_name_for_state(self, state: RepositoryAgentState) -> str:
        record = self.registry.persistence.get_repository(state.repo_id)
        if record is not None and record.display_name:
            return record.display_name
        return Path(state.repo_path).name

    def _discover_repo_paths(self) -> List[Path]:
        discovered = []
        seen = set()
        for root in self.settings.jarvis_allowed_repo_roots:
            root_path = Path(root).expanduser()
            if not root_path.exists():
                continue
            for repo_path in _walk_git_repositories(root_path.resolve(), max_depth=self.max_depth):
                key = str(repo_path)
                if key in seen:
                    continue
                seen.add(key)
                discovered.append(repo_path)
        return discovered


def _walk_git_repositories(root: Path, max_depth: int) -> List[Path]:
    repositories = []
    for current_root, dirnames, _filenames in os.walk(str(root)):
        current_path = Path(current_root)
        try:
            depth = len(current_path.relative_to(root).parts)
        except ValueError:
            depth = 0
        if ".git" in dirnames:
            repositories.append(current_path.resolve())
            dirnames[:] = []
            continue
        if depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [name for name in dirnames if not name.startswith(".")]
    return repositories


def _normalize_name(value: str) -> str:
    cleaned = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    cleaned = cleaned.lower().strip()
    cleaned = re.sub(r"\b(?:repo|repositorio|repository|project|proyecto)\b", " ", cleaned)
    cleaned = re.sub(r"[^a-z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


def _score_candidate(query: str, display_name: str, repo_path: str) -> int:
    display = _normalize_name(display_name)
    basename = _normalize_name(Path(repo_path).name)
    if query == display or query == basename:
        return 100
    if display.startswith(query) or basename.startswith(query):
        return 85
    if query in display or query in basename:
        return 70
    query_tokens = set(query.split())
    if not query_tokens:
        return 0
    display_tokens = set(display.split()) | set(basename.split())
    overlap = len(query_tokens & display_tokens)
    if overlap == len(query_tokens):
        return 60
    if overlap:
        return 45
    return 0
