from __future__ import annotations

from typing import Any, List, Optional

from app.graphs.task_agent_graph import build_task_agent_graph
from app.models.repository import RepositoryAgentState
from app.models.state import TaskAgentStatus
from app.models.task import TaskAgentState
from app.services.local_executor import LocalExecutor
from app.services.memory_service import MemoryService
from app.services.openai_client import LLMClient
from app.services.repository_registry import RepositoryRegistry


class TaskAgent:
    def __init__(
        self,
        state: TaskAgentState,
        registry: RepositoryRegistry,
        executor: LocalExecutor,
        llm_client: LLMClient,
        memory_service: MemoryService,
        graph_checkpointer: Optional[Any] = None,
    ) -> None:
        self.state = state
        self.registry = registry
        self.executor = executor
        self.llm_client = llm_client
        self.memory_service = memory_service
        self.graph = build_task_agent_graph(checkpointer=graph_checkpointer)

    async def execute(self, repo_state: RepositoryAgentState) -> TaskAgentState:
        try:
            self._set_status(TaskAgentStatus.INSPECTING)
            repo_context = self._build_repo_context(repo_state.repo_path)
            memory_context = self.memory_service.render_memory_for_llm(
                repo_state.repo_agent_id
            ).text

            self._set_status(TaskAgentStatus.WORKING)
            result = await self.llm_client.implement_task(
                repo_state=repo_state,
                task_state=self.state,
                repo_context=repo_context,
                memory_context=memory_context,
            )
            self.state.result_summary = result.result_summary
            self.state.proposed_patch = result.proposed_patch

            if result.proposed_patch:
                changed = await self.executor.apply_patch(
                    repo_path=repo_state.repo_path,
                    patch_text=result.proposed_patch,
                    scope=self.state.scope,
                )
                self.state.changed_files = changed
            else:
                self.state.changed_files = result.changed_files

            self._set_status(TaskAgentStatus.VALIDATING)
            if result.test_command:
                code, stdout, stderr = await self.executor.run_allowed_command(
                    repo_state.repo_path,
                    result.test_command,
                )
                self.state.test_results.append(
                    "command=%s exit_code=%s stdout=%s stderr=%s"
                    % (result.test_command, code, stdout.strip(), stderr.strip())
                )

            self._set_status(TaskAgentStatus.DONE)
            return self.state
        except Exception as exc:
            self.state.last_error = str(exc)
            self._set_status(TaskAgentStatus.FAILED)
            return self.state

    def mark_dead(self) -> TaskAgentState:
        self._set_status(TaskAgentStatus.DEAD)
        return self.state

    def _set_status(self, status: TaskAgentStatus) -> None:
        self.state.status = status
        self.registry.save_task_state(self.state)

    def _build_repo_context(self, repo_path: str) -> str:
        files = self.executor.list_files(repo_path, max_files=120)
        visible_files = _filter_scope(files, self.state.scope)
        return "Visible files:\n%s" % "\n".join("- %s" % item for item in visible_files[:120])


def _filter_scope(files: List[str], scope: List[str]) -> List[str]:
    if not scope:
        return files
    normalized_scope = [item.strip().strip("/") for item in scope if item.strip()]
    return [
        path
        for path in files
        if any(path == item or path.startswith(item + "/") for item in normalized_scope)
    ]
