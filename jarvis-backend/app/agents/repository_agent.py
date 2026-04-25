from __future__ import annotations

from typing import Any, List, Optional

from app.agents.task_agent import TaskAgent
from app.graphs.repository_agent_graph import build_repository_agent_graph
from app.models.repository import RepositoryAgentState
from app.models.state import RepositoryAgentPhase, TaskAgentStatus
from app.models.task import TaskAgentState
from app.models.turns import TurnRequest, TurnResponse, TurnType
from app.services.global_manager import GlobalManager
from app.services.local_executor import LocalExecutor
from app.services.memory_service import MemoryService
from app.services.openai_client import LLMClient
from app.services.repository_registry import RepositoryRegistry


class RepositoryAgent:
    def __init__(
        self,
        state: RepositoryAgentState,
        registry: RepositoryRegistry,
        manager: GlobalManager,
        executor: LocalExecutor,
        llm_client: LLMClient,
        memory_service: MemoryService,
        graph_checkpointer: Optional[Any] = None,
    ) -> None:
        self.state = state
        self.registry = registry
        self.manager = manager
        self.executor = executor
        self.llm_client = llm_client
        self.memory_service = memory_service
        self.graph_checkpointer = graph_checkpointer
        self.graph = build_repository_agent_graph(checkpointer=graph_checkpointer)

    async def start_task(
        self,
        message: str,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> RepositoryAgentState:
        self.manager.acquire_intake_lock(self.state.repo_agent_id)
        self.state.phase = RepositoryAgentPhase.INTAKE
        self.state.task_goal = message
        self.state.acceptance_criteria = acceptance_criteria or []
        self.registry.save_agent_state(self.state)
        self.memory_service.record_task_started(self.state)

        self.manager.emit_progress(self.state.repo_agent_id, "Intake started.")
        repo_context = self._build_repo_context()
        memory_context = self.memory_service.render_memory_for_llm(self.state.repo_agent_id).text

        self.state.phase = RepositoryAgentPhase.PLANNING
        self.state.requirements = await self.llm_client.extract_requirements(
            task_goal=message,
            acceptance_criteria=self.state.acceptance_criteria,
            repo_context=repo_context,
            memory_context=memory_context,
        )
        self.state.plan = await self.llm_client.create_plan(
            state=self.state,
            repo_context=repo_context,
            memory_context=memory_context,
        )
        self.state.phase = RepositoryAgentPhase.WAITING_APPROVAL
        self.registry.save_agent_state(self.state)
        self.memory_service.record_plan_proposed(self.state)

        self.manager.enqueue_turn(
            TurnRequest(
                user_id=self.state.user_id,
                agent_id=self.state.repo_agent_id,
                repo_agent_id=self.state.repo_agent_id,
                type=TurnType.APPROVAL,
                priority=60,
                message=(
                    "Plan ready for `%s`.\n\n%s\n\nApprove this plan to start execution?"
                    % (self.state.repo_path, self.state.plan or "")
                ),
                context="RepositoryAgent is waiting for plan approval.",
                requires_user_response=True,
            )
        )
        return self.state

    async def handle_user_response(
        self,
        turn: TurnRequest,
        response: TurnResponse,
    ) -> RepositoryAgentState:
        if turn.type == TurnType.APPROVAL:
            approved = response.approved
            if approved is None:
                approved = _looks_like_approval(response.response)
            if not approved:
                return self._handle_plan_rejection(response.response)
            return await self.execute_approved_plan()
        return self.state

    async def execute_approved_plan(self) -> RepositoryAgentState:
        self.manager.release_intake_lock(self.state.repo_agent_id)
        self.state.phase = RepositoryAgentPhase.EXECUTING
        self.registry.save_agent_state(self.state)
        self.manager.emit_progress(self.state.repo_agent_id, "Plan approved. Execution started.")

        task_plan = await self.llm_client.split_tasks(self.state, self.state.plan or "")
        task_states: List[TaskAgentState] = []
        for task_item in task_plan:
            task_state = TaskAgentState(
                repo_agent_id=self.state.repo_agent_id,
                title=task_item.title,
                description=task_item.description,
                scope=task_item.scope,
            )
            self.registry.save_task_state(task_state)
            self.state.task_agents.append(task_state.task_agent_id)
            self.registry.save_agent_state(self.state)

            task_agent = TaskAgent(
                state=task_state,
                registry=self.registry,
                executor=self.executor,
                llm_client=self.llm_client,
                memory_service=self.memory_service,
                graph_checkpointer=self.graph_checkpointer,
            )
            completed_task = await task_agent.execute(self.state)
            task_states.append(completed_task)
            self.state.changed_files.extend(
                item for item in completed_task.changed_files if item not in self.state.changed_files
            )
            self.state.test_results.extend(completed_task.test_results)
            if completed_task.status == TaskAgentStatus.FAILED:
                self.state.phase = RepositoryAgentPhase.FAILED
                self.state.last_error = completed_task.last_error
                self.registry.save_agent_state(self.state)
                self.manager.emit_failed(
                    self.state.repo_agent_id,
                    completed_task.last_error or "Task agent failed.",
                )
                return self.state

        self.state.phase = RepositoryAgentPhase.FINALIZING
        self.registry.save_agent_state(self.state)
        self.state.final_report = await self.llm_client.final_report(self.state, task_states)
        self.state.phase = RepositoryAgentPhase.DONE
        self.registry.save_agent_state(self.state)
        self.memory_service.record_task_completed(self.state, task_states)

        for task_state in task_states:
            task_agent = TaskAgent(
                state=task_state,
                registry=self.registry,
                executor=self.executor,
                llm_client=self.llm_client,
                memory_service=self.memory_service,
                graph_checkpointer=self.graph_checkpointer,
            )
            task_agent.mark_dead()

        self.manager.enqueue_turn(
            TurnRequest(
                user_id=self.state.user_id,
                agent_id=self.state.repo_agent_id,
                repo_agent_id=self.state.repo_agent_id,
                type=TurnType.COMPLETION,
                priority=40,
                message=self.state.final_report or "Repository task completed.",
                context="RepositoryAgent final report.",
                requires_user_response=False,
            )
        )
        self.manager.emit_completed(self.state.repo_agent_id, "Execution completed.")
        return self.state

    def _handle_plan_rejection(self, feedback: str) -> RepositoryAgentState:
        self.state.phase = RepositoryAgentPhase.INTAKE
        self.registry.save_agent_state(self.state)
        self.manager.enqueue_turn(
            TurnRequest(
                user_id=self.state.user_id,
                agent_id=self.state.repo_agent_id,
                repo_agent_id=self.state.repo_agent_id,
                type=TurnType.INTAKE,
                priority=100,
                message="Plan rejected. Add the missing requirements or clarifications.",
                context=feedback,
                requires_user_response=True,
            )
        )
        return self.state

    def _build_repo_context(self) -> str:
        files = self.executor.list_files(self.state.repo_path, max_files=160)
        return "Repository files:\n%s" % "\n".join("- %s" % item for item in files[:160])


def _looks_like_approval(response: str) -> bool:
    normalized = response.strip().lower()
    approvals = {"yes", "y", "si", "sí", "approve", "approved", "ok", "okay", "dale"}
    return normalized in approvals or normalized.startswith("approve")


def _format_list(items: List[str]) -> str:
    if not items:
        return "- Not provided"
    return "\n".join("- %s" % item for item in items)
