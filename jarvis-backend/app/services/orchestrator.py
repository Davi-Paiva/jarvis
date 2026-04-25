from __future__ import annotations

import unicodedata
from typing import Any, List, Optional, Tuple

from app.agents.repository_agent import RepositoryAgent
from app.config import Settings
from app.models.repository import RepositoryAgentState
from app.models.schemas import AgentStateOutput, CreateRepoAgentOutput
from app.models.state import RepositoryAgentPhase
from app.models.turns import TurnRequest
from app.models.voice_protocol import PendingTurnSummary, RepoSummary
from app.services.global_manager import GlobalManager
from app.services.graph_checkpointer import create_langgraph_sqlite_checkpointer
from app.services.local_executor import LocalExecutor
from app.models.memory import RenderedMemoryView
from app.services.memory_service import MemoryService
from app.services.openai_client import LLMClient, OpenAIAgentsClient
from app.services.persistence import SQLitePersistence
from app.services.repo_discovery import RepoDiscoveryCandidate, RepoDiscoveryService
from app.services.repository_registry import RepositoryRegistry
from app.services.turn_scheduler import TurnScheduler


class JarvisOrchestrator:
    """Facade intended to be called by tests now and API adapters later."""

    def __init__(
        self,
        settings: Settings,
        registry: RepositoryRegistry,
        manager: GlobalManager,
        executor: LocalExecutor,
        llm_client: LLMClient,
        memory_service: MemoryService,
        graph_checkpointer: Optional[Any] = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.manager = manager
        self.executor = executor
        self.llm_client = llm_client
        self.memory_service = memory_service
        self.memory_store = memory_service
        self.graph_checkpointer = graph_checkpointer
        self.repo_discovery = RepoDiscoveryService(settings=settings, registry=registry)

    @classmethod
    def create(
        cls,
        settings: Settings,
        llm_client: Optional[LLMClient] = None,
    ) -> "JarvisOrchestrator":
        settings.ensure_directories()
        persistence = SQLitePersistence(settings.jarvis_db_path)
        memory_service = MemoryService(
            settings.jarvis_memory_dir,
            max_chars=settings.jarvis_memory_max_chars,
            view_max_chars=settings.jarvis_memory_view_max_chars,
            max_completed_tasks=settings.jarvis_memory_max_completed_tasks,
            useful_commands=settings.jarvis_allowed_commands,
        )
        registry = RepositoryRegistry(settings, persistence, memory_service)
        scheduler = TurnScheduler(persistence)
        manager = GlobalManager(scheduler, persistence)
        executor = LocalExecutor(settings)
        graph_checkpointer = create_langgraph_sqlite_checkpointer(settings.jarvis_db_path)
        return cls(
            settings=settings,
            registry=registry,
            manager=manager,
            executor=executor,
            llm_client=llm_client or OpenAIAgentsClient(settings),
            memory_service=memory_service,
            graph_checkpointer=graph_checkpointer,
        )

    async def create_repo_agent(
        self,
        repo_path: str,
        display_name: Optional[str] = None,
        branch_name: Optional[str] = None,
    ) -> RepositoryAgentState:
        state, _created = self.registry.get_or_create_repo_agent(
            repo_path=repo_path,
            display_name=display_name,
            branch_name=branch_name,
            user_id=self.settings.jarvis_user_id,
        )
        return state

    async def activate_repo_agent(
        self,
        repo_path: str,
        display_name: Optional[str] = None,
        branch_name: Optional[str] = None,
    ) -> Tuple[RepositoryAgentState, bool]:
        return self.registry.get_or_create_repo_agent(
            repo_path=repo_path,
            display_name=display_name,
            branch_name=branch_name,
            user_id=self.settings.jarvis_user_id,
        )

    def to_create_repo_agent_output(
        self,
        state: RepositoryAgentState,
    ) -> CreateRepoAgentOutput:
        return CreateRepoAgentOutput(
            repo_agent_id=state.repo_agent_id,
            repo_id=state.repo_id,
            thread_id=state.thread_id,
            phase=state.phase.value,
        )

    async def start_task(
        self,
        repo_agent_id: str,
        message: str,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> AgentStateOutput:
        state = self.registry.get_agent_state(repo_agent_id)
        agent = self._repository_agent(state)
        updated = await agent.start_task(message, acceptance_criteria=acceptance_criteria)
        return AgentStateOutput(
            agent=updated,
            next_turn=self.manager.get_next_turn(updated.user_id),
        )

    async def handle_user_message(
        self,
        repo_agent_id: str,
        message: str,
        acceptance_criteria: Optional[List[str]] = None,
    ) -> AgentStateOutput:
        state = self.registry.get_agent_state(repo_agent_id)
        agent = self._repository_agent(state)
        intent_type = self._classify_user_intent(message)

        state.intent_type = intent_type
        state.original_user_prompt = message
        self.registry.save_agent_state(state)

        if intent_type == "EXPLAIN_CODE":
            if hasattr(agent, "answer_code_question"):
                updated = await agent.answer_code_question(message)
            else:
                # Temporary fallback until RepositoryAgent.answer_code_question lands.
                state.phase = RepositoryAgentPhase.ANSWERING_QUESTION
                state.last_explanation = (
                    "Question received, but the explanation flow is not implemented yet."
                )
                self.registry.save_agent_state(state)
                updated = state
            return AgentStateOutput(
                agent=updated,
                next_turn=self.manager.get_next_turn(updated.user_id),
            )

        if hasattr(agent, "start_modification_flow"):
            updated = await agent.start_modification_flow(message, acceptance_criteria or [])
        else:
            # TODO: replace this compatibility fallback once RepositoryAgent.start_modification_flow exists.
            updated = await agent.start_task(message, acceptance_criteria=acceptance_criteria)
        return AgentStateOutput(
            agent=updated,
            next_turn=self.manager.get_next_turn(updated.user_id),
        )

    async def submit_user_response(
        self,
        turn_id: str,
        response: str,
        approved: Optional[bool] = None,
    ) -> AgentStateOutput:
        turn = self.manager.get_turn(turn_id)
        if turn is None:
            raise KeyError("Unknown turn_id: %s" % turn_id)
        turn_response = self.manager.record_user_response(
            turn_id=turn_id,
            response=response,
            approved=approved,
        )
        state = self.registry.get_agent_state(turn.repo_agent_id)
        agent = self._repository_agent(state)
        updated = await agent.handle_user_response(turn, turn_response)
        return AgentStateOutput(
            agent=updated,
            next_turn=self.manager.get_next_turn(updated.user_id),
        )

    async def get_next_turn(self, user_id: Optional[str] = None) -> Optional[TurnRequest]:
        return self.manager.get_next_turn(user_id or self.settings.jarvis_user_id)

    async def get_agent_state(self, repo_agent_id: str) -> RepositoryAgentState:
        return self.registry.get_agent_state(repo_agent_id)

    async def list_repo_agents(self) -> List[RepositoryAgentState]:
        return self.registry.list_agents(user_id=self.settings.jarvis_user_id)

    async def list_pending_turns(self, user_id: Optional[str] = None) -> List[TurnRequest]:
        return self.manager.list_pending_turns(user_id or self.settings.jarvis_user_id)

    async def get_repo_summaries(self, user_id: Optional[str] = None) -> List[RepoSummary]:
        summaries = []
        for state in self.registry.list_agents(user_id=user_id or self.settings.jarvis_user_id):
            record = self.registry.persistence.get_repository(state.repo_id)
            summaries.append(
                RepoSummary(
                    repoAgentId=state.repo_agent_id,
                    repoId=state.repo_id,
                    displayName=(record.display_name if record is not None else None) or state.repo_path.split("/")[-1],
                    repoPath=state.repo_path,
                    branchName=state.branch_name,
                    phase=state.phase.value,
                    status=_status_from_phase(state.phase.value),
                    activeChatId=None,
                    pendingTurns=len(
                        [
                            turn
                            for turn in self.manager.list_pending_turns(state.user_id)
                            if turn.repo_agent_id == state.repo_agent_id
                        ]
                    ),
                )
            )
        return summaries

    async def resolve_repo_by_name(self, query: str) -> Optional[RepoDiscoveryCandidate]:
        resolved, _candidates = self.repo_discovery.resolve_repo_by_name(
            query,
            user_id=self.settings.jarvis_user_id,
        )
        return resolved

    async def get_memory_view(
        self,
        repo_agent_id: str,
        max_chars: Optional[int] = None,
    ) -> RenderedMemoryView:
        return self.memory_service.render_memory_for_llm(repo_agent_id, max_chars=max_chars)

    def _repository_agent(self, state: RepositoryAgentState) -> RepositoryAgent:
        return RepositoryAgent(
            state=state,
            registry=self.registry,
            manager=self.manager,
            executor=self.executor,
            llm_client=self.llm_client,
            memory_service=self.memory_service,
            graph_checkpointer=self.graph_checkpointer,
        )

    def _classify_user_intent(self, message: str) -> str:
        normalized = _normalize_intent_text(message)
        explain_markers = [
            "explain this",
            "explain how",
            "what does this do",
            "what does this file do",
            "what does",
            "how does this work",
            "how does",
            "why does this happen",
            "why does",
            "where is this implemented",
            "where is this defined",
            "where is",
            "describe this",
            "summarize this",
            "summarize",
            "help me understand this",
            "help me understand",
            "walk me through this code",
            "walk me through",
            "explica",
            "explicame",
            "que hace",
            "como funciona",
            "por que",
            "donde esta",
            "describe",
            "resumen",
            "ayudame a entender",
        ]
        modify_markers = [
            "change this",
            "modify this",
            "implement this",
            "add support for",
            "add a new",
            "fix this",
            "fix the bug",
            "create",
            "refactor",
            "remove",
            "delete",
            "update",
            "make it so",
            "i want to change",
            "can you add",
            "can you fix",
            "let's implement",
            "modifica",
            "cambia",
            "implementa",
            "anade",
            "agrega",
            "arregla",
            "corrige",
            "fix",
            "crea",
            "refactoriza",
            "elimina",
            "borra",
        ]
        has_modify_signal = any(marker in normalized for marker in modify_markers)
        has_explain_signal = any(marker in normalized for marker in explain_markers)

        if has_modify_signal:
            return "MODIFY_CODE"
        if has_explain_signal:
            return "EXPLAIN_CODE"
        return "MODIFY_CODE"


def _status_from_phase(phase: str) -> str:
    if phase in {
        "WAITING_APPROVAL",
        "BRANCH_PERMISSION",
        "BRANCH_NAME",
        "BRANCH_CONFIRMATION",
        "PLAN_STEP_REVIEW",
        "WAITING_EXECUTION_APPROVAL",
    }:
        return "waiting_approval"
    if phase in {
        "INTAKE",
        "PLANNING",
        "ANSWERING_QUESTION",
        "EXECUTING",
        "FINALIZING",
        "WAITING_FOR_USER",
    }:
        return "running"
    return "idle"


def _normalize_intent_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return " ".join(normalized.lower().split())
