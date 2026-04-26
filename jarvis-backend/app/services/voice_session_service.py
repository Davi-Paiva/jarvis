from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Deque, Dict, Iterable, List, Optional, Sequence

from app.models.chat import ChatMessage, ChatMessageRole, ChatSession, ChatSessionStatus
from app.models.events import ManagerEvent, ManagerEventType
from app.models.repository import RepositoryAgentState
from app.models.turns import TurnRequest, TurnType
from app.models.voice_protocol import (
    AIResponseMessage,
    PendingTurnMessage,
    PendingTurnSummary,
    RepoSummary,
    ServerToClientMessage,
    SessionStateMessage,
    VoiceChatMessage,
)
from app.services.openai_client import LLMClient
from app.services.orchestrator import JarvisOrchestrator
from app.services.repo_discovery import RepoDiscoveryCandidate, RepoDiscoveryService
from app.services.voice_command_router import VoiceCommandRouter, VoiceCommandType


@dataclass
class PendingVoicePrompt:
    kind: str
    target_repo_agent_id: Optional[str] = None
    turn_id: Optional[str] = None
    repo_query: Optional[str] = None
    candidates: List[RepoDiscoveryCandidate] = field(default_factory=list)


@dataclass
class VoiceSessionRuntime:
    session_id: str
    user_id: str = "demo"
    enable_audio: bool = True  # Whether to synthesize audio for this session
    active_repo_agent_id: Optional[str] = None
    active_chat_id: Optional[str] = None
    chat_by_repo: Dict[str, str] = field(default_factory=dict)
    pending_prompt: Optional[PendingVoicePrompt] = None
    queued_interruptions: Deque[PendingVoicePrompt] = field(default_factory=deque)
    announced_turn_ids: set = field(default_factory=set)


class VoiceSessionService:
    def __init__(
        self,
        orchestrator: JarvisOrchestrator,
        discovery_service: Optional[RepoDiscoveryService] = None,
        command_router: Optional[VoiceCommandRouter] = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.persistence = orchestrator.registry.persistence
        self.discovery_service = discovery_service or RepoDiscoveryService(
            settings=orchestrator.settings,
            registry=orchestrator.registry,
        )
        self.command_router = command_router or VoiceCommandRouter()
        self.sessions: Dict[str, VoiceSessionRuntime] = {}

    def start_session(self, session_id: Optional[str] = None, enable_audio: bool = True) -> List[ServerToClientMessage]:
        runtime = self._get_or_create_runtime(session_id=session_id, enable_audio=enable_audio)
        self._hydrate_runtime(runtime)
        messages: List[ServerToClientMessage] = [self._build_session_state(runtime)]
        if runtime.active_repo_agent_id is None:
            messages.append(
                AIResponseMessage(
                    responseText=(
                        "I do not have an active repository yet. "
                        "Say open repo and the repository name to begin."
                    )
                )
            )
        return messages

    async def handle_user_transcript(
        self,
        session_id: str,
        text: str,
        repo_agent_id: Optional[str] = None,
        turn_id: Optional[str] = None,
    ) -> List[ServerToClientMessage]:
        runtime = self._get_or_create_runtime(session_id=session_id)
        if repo_agent_id:
            runtime.active_repo_agent_id = repo_agent_id

        text = text.strip()
        if not text:
            return []

        pending_prompt_messages = await self._handle_pending_prompt(runtime, text)
        if pending_prompt_messages is not None:
            return pending_prompt_messages

        command = self.command_router.parse(text)
        if command.type == VoiceCommandType.OPEN_REPO:
            return await self._handle_open_repo(runtime, command.repo_query or "")
        if command.type == VoiceCommandType.SWITCH_REPO:
            return await self._handle_switch_repo(runtime, command.repo_query or "")
        if command.type == VoiceCommandType.NEW_CHAT:
            return self._handle_new_chat(runtime)
        if command.type == VoiceCommandType.END_CHAT:
            return self._handle_end_chat(runtime)
        if command.type == VoiceCommandType.LIST_PENDING:
            return self._handle_list_pending(runtime)

        active_pending_turn = self._pending_turn_for_repo(runtime.active_repo_agent_id, explicit_turn_id=turn_id)
        if active_pending_turn is not None:
            return await self._handle_turn_response(runtime, active_pending_turn, text, command.type)

        if runtime.active_repo_agent_id is None:
            return [
                AIResponseMessage(
                    responseText=(
                        "I still need a repository. "
                        "Say open repo and the repository name to continue."
                    )
                )
            ]

        return await self._handle_repo_request(runtime, text)

    async def handle_switch_repo_by_id(
        self,
        session_id: str,
        repo_agent_id: str,
    ) -> List[ServerToClientMessage]:
        runtime = self._get_or_create_runtime(session_id=session_id)
        self._hydrate_runtime(runtime)

        known_repo_ids = {
            state.repo_agent_id
            for state in self.orchestrator.registry.list_agents(user_id=runtime.user_id)
        }
        if repo_agent_id not in known_repo_ids:
            return [
                AIResponseMessage(
                    responseText="I couldn't find that repository in this session."
                ),
                self._build_session_state(runtime),
            ]

        runtime.active_repo_agent_id = repo_agent_id
        runtime.active_chat_id = self._maybe_get_active_chat_id(repo_agent_id)
        if runtime.active_chat_id is not None:
            runtime.chat_by_repo[repo_agent_id] = runtime.active_chat_id

        messages: List[ServerToClientMessage] = [
            AIResponseMessage(
                responseText="Switched to %s." % self._display_name_for_repo_id(repo_agent_id),
                repoAgentId=repo_agent_id,
                chatId=runtime.active_chat_id,
            ),
            self._build_session_state(runtime),
        ]
        messages.extend(self._maybe_prompt_for_active_turn(runtime))
        return messages

    async def handle_manager_event(
        self,
        session_id: str,
        event: ManagerEvent,
    ) -> List[ServerToClientMessage]:
        runtime = self.sessions.get(session_id)
        if runtime is None:
            return []

        if event.type == ManagerEventType.AGENT_PROGRESS:
            if event.repo_agent_id != runtime.active_repo_agent_id:
                return []
            if not event.message:
                return []
            chat_id = self._maybe_get_active_chat_id(runtime.active_repo_agent_id)
            if chat_id is None:
                return []
            return [self._append_chat_message(chat_id, event.repo_agent_id or "", ChatMessageRole.SYSTEM, event.message)]

        if event.type == ManagerEventType.AGENT_FAILED and event.repo_agent_id == runtime.active_repo_agent_id:
            chat_id = self._ensure_active_chat(runtime, event.repo_agent_id)
            failure_text = event.message or "The active repository agent failed."
            return self._assistant_messages(runtime, failure_text, chat_id=chat_id, repo_agent_id=event.repo_agent_id)

        if event.turn_id is None:
            return []

        turn = self.orchestrator.manager.get_turn(event.turn_id)
        if turn is None or turn.id in runtime.announced_turn_ids:
            return []
        if turn.handled and turn.requires_user_response:
            return []

        # Check if the repo still exists before processing the turn
        try:
            self.orchestrator.registry.get_agent_state(turn.repo_agent_id)
        except KeyError:
            # Repo was deleted, ignore this turn
            return []

        summary = self._build_pending_turn(turn)
        if event.repo_agent_id == runtime.active_repo_agent_id:
            runtime.announced_turn_ids.add(turn.id)
            return self._messages_for_turn(runtime, turn, summary)

        if not turn.requires_user_response and turn.type != TurnType.COMPLETION:
            return []

        runtime.announced_turn_ids.add(turn.id)
        prompt = PendingVoicePrompt(
            kind="switch_repo",
            target_repo_agent_id=turn.repo_agent_id,
            turn_id=turn.id,
        )
        if runtime.pending_prompt is None:
            runtime.pending_prompt = prompt
            return [
                PendingTurnMessage(pendingTurn=summary),
                AIResponseMessage(
                    responseText=(
                        "%s has something pending. Do you want to switch to it?"
                        % summary.repoName
                    ),
                    repoAgentId=summary.repoAgentId,
                    turnId=summary.turnId,
                ),
                self._build_session_state(runtime),
            ]

        runtime.queued_interruptions.append(prompt)
        return [
            PendingTurnMessage(pendingTurn=summary),
            self._build_session_state(runtime),
        ]

    async def get_repo_summaries(self, user_id: Optional[str] = None) -> List[RepoSummary]:
        return [
            self._build_repo_summary(state)
            for state in self.orchestrator.registry.list_agents(
                user_id=user_id or self.orchestrator.settings.jarvis_user_id
            )
        ]

    async def list_pending_turns(self, user_id: Optional[str] = None) -> List[PendingTurnSummary]:
        return [
            self._build_pending_turn(turn)
            for turn in self.orchestrator.manager.list_pending_turns(
                user_id=user_id or self.orchestrator.settings.jarvis_user_id
            )
        ]

    async def resolve_repo_by_name(self, query: str) -> Optional[RepoDiscoveryCandidate]:
        resolved, _candidates = self.discovery_service.resolve_repo_by_name(
            query,
            user_id=self.orchestrator.settings.jarvis_user_id,
        )
        return resolved

    def _get_or_create_runtime(self, session_id: Optional[str] = None, enable_audio: bool = True) -> VoiceSessionRuntime:
        actual_session_id = session_id or self._new_session_id()
        if actual_session_id not in self.sessions:
            self.sessions[actual_session_id] = VoiceSessionRuntime(
                session_id=actual_session_id,
                user_id=self.orchestrator.settings.jarvis_user_id,
                enable_audio=enable_audio,
            )
        return self.sessions[actual_session_id]

    def _hydrate_runtime(self, runtime: VoiceSessionRuntime) -> None:
        if runtime.active_repo_agent_id is not None:
            try:
                self.orchestrator.registry.get_agent_state(runtime.active_repo_agent_id)
                return
            except KeyError:
                runtime.active_repo_agent_id = None
                runtime.active_chat_id = None
        agents = self.orchestrator.registry.list_agents(user_id=runtime.user_id)
        if not agents:
            return
        runtime.active_repo_agent_id = agents[0].repo_agent_id
        runtime.active_chat_id = self._maybe_get_active_chat_id(runtime.active_repo_agent_id)
        if runtime.active_chat_id:
            runtime.chat_by_repo[runtime.active_repo_agent_id] = runtime.active_chat_id

    async def _handle_open_repo(
        self,
        runtime: VoiceSessionRuntime,
        repo_query: str,
    ) -> List[ServerToClientMessage]:
        resolved, candidates = self.discovery_service.resolve_repo_by_name(repo_query, user_id=runtime.user_id)
        if resolved is None and not candidates:
            return [
                AIResponseMessage(
                    responseText="I could not find a repository with that name under the allowed roots."
                )
            ]
        if resolved is None:
            runtime.pending_prompt = PendingVoicePrompt(
                kind="resolve_repo",
                repo_query=repo_query,
                candidates=candidates,
            )
            names = ", ".join(candidate.display_name for candidate in candidates[:3])
            return [
                AIResponseMessage(
                    responseText=(
                        "I found several repositories matching %s: %s. "
                        "Please say the one you want."
                    )
                    % (repo_query, names)
                )
            ]

        state, _created = await self.orchestrator.activate_repo_agent(
            repo_path=resolved.repo_path,
            display_name=resolved.display_name,
        )
        runtime.active_repo_agent_id = state.repo_agent_id
        runtime.active_chat_id = self._maybe_get_active_chat_id(state.repo_agent_id)
        if runtime.active_chat_id is not None:
            runtime.chat_by_repo[state.repo_agent_id] = runtime.active_chat_id
        messages: List[ServerToClientMessage] = [
            AIResponseMessage(
                responseText="Repository %s is now active." % self._display_name_for_repo(state),
                repoAgentId=state.repo_agent_id,
                chatId=runtime.active_chat_id,
            ),
            self._build_session_state(runtime),
        ]
        messages.extend(self._maybe_prompt_for_active_turn(runtime))
        return messages

    async def _handle_switch_repo(
        self,
        runtime: VoiceSessionRuntime,
        repo_query: str,
    ) -> List[ServerToClientMessage]:
        state = self._find_activated_repo_by_name(repo_query)
        if state is None:
            return [
                AIResponseMessage(
                    responseText=(
                        "I do not have that repository active yet. "
                        "Say open repo and the repository name if you want me to activate it."
                    )
                )
            ]

        runtime.active_repo_agent_id = state.repo_agent_id
        runtime.active_chat_id = self._maybe_get_active_chat_id(state.repo_agent_id)
        if runtime.active_chat_id is not None:
            runtime.chat_by_repo[state.repo_agent_id] = runtime.active_chat_id
        messages: List[ServerToClientMessage] = [
            AIResponseMessage(
                responseText="Switched to %s." % self._display_name_for_repo(state),
                repoAgentId=state.repo_agent_id,
                chatId=runtime.active_chat_id,
            ),
            self._build_session_state(runtime),
        ]
        messages.extend(self._maybe_prompt_for_active_turn(runtime))
        return messages

    def _handle_new_chat(self, runtime: VoiceSessionRuntime) -> List[ServerToClientMessage]:
        if runtime.active_repo_agent_id is None:
            return [AIResponseMessage(responseText="Choose a repository before starting a new chat.")]

        current_chat_id = self._maybe_get_active_chat_id(runtime.active_repo_agent_id)
        if current_chat_id is not None:
            chat = self.persistence.get_chat_session(current_chat_id)
            if chat is not None and chat.status == ChatSessionStatus.ACTIVE:
                chat.close()
                self.persistence.save_chat_session(chat)

        chat = ChatSession(
            repo_agent_id=runtime.active_repo_agent_id,
            user_id=runtime.user_id,
            title="Voice chat for %s" % self._display_name_for_repo_id(runtime.active_repo_agent_id),
        )
        self.persistence.save_chat_session(chat)
        runtime.active_chat_id = chat.chat_id
        runtime.chat_by_repo[runtime.active_repo_agent_id] = chat.chat_id
        return [
            AIResponseMessage(
                responseText="Started a new chat for %s." % self._display_name_for_repo_id(runtime.active_repo_agent_id),
                repoAgentId=runtime.active_repo_agent_id,
                chatId=chat.chat_id,
            ),
            self._build_session_state(runtime),
        ]

    def _handle_end_chat(self, runtime: VoiceSessionRuntime) -> List[ServerToClientMessage]:
        if runtime.active_repo_agent_id is None:
            return [AIResponseMessage(responseText="There is no active repository chat to close.")]

        current_chat_id = self._maybe_get_active_chat_id(runtime.active_repo_agent_id)
        if current_chat_id is None:
            return [AIResponseMessage(responseText="There is no active chat to close for this repository.")]

        chat = self.persistence.get_chat_session(current_chat_id)
        if chat is not None and chat.status == ChatSessionStatus.ACTIVE:
            chat.close()
            self.persistence.save_chat_session(chat)

        runtime.active_chat_id = None
        runtime.chat_by_repo.pop(runtime.active_repo_agent_id, None)
        return [
            AIResponseMessage(
                responseText="Closed the active chat for %s." % self._display_name_for_repo_id(runtime.active_repo_agent_id),
                repoAgentId=runtime.active_repo_agent_id,
            ),
            self._build_session_state(runtime),
        ]

    def _handle_list_pending(self, runtime: VoiceSessionRuntime) -> List[ServerToClientMessage]:
        pending = [
            self._build_pending_turn(turn)
            for turn in self.orchestrator.manager.list_pending_turns(user_id=runtime.user_id)
        ]
        if not pending:
            return [AIResponseMessage(responseText="There are no pending approvals or questions right now.")]

        names = ", ".join("%s (%s)" % (item.repoName, item.type) for item in pending[:3])
        messages: List[ServerToClientMessage] = [
            AIResponseMessage(responseText="Pending items: %s." % names),
            self._build_session_state(runtime),
        ]
        messages.extend(PendingTurnMessage(pendingTurn=item) for item in pending[:3])
        return messages

    async def _handle_turn_response(
        self,
        runtime: VoiceSessionRuntime,
        turn: TurnRequest,
        text: str,
        command_type: VoiceCommandType,
    ) -> List[ServerToClientMessage]:
        approved = None
        if command_type == VoiceCommandType.APPROVE:
            approved = True
        elif command_type == VoiceCommandType.REJECT:
            approved = False

        chat_id = self._ensure_active_chat(runtime, turn.repo_agent_id)
        user_message = self._append_chat_message(
            chat_id,
            turn.repo_agent_id,
            ChatMessageRole.USER,
            text,
            turn_id=turn.id,
        )
        result = await self.orchestrator.submit_user_response(turn.id, text, approved=approved)
        messages: List[ServerToClientMessage] = [user_message]
        if result.next_turn is not None:
            runtime.announced_turn_ids.add(result.next_turn.id)
            pending_summary = self._build_pending_turn(result.next_turn)
            messages.extend(self._messages_for_turn(runtime, result.next_turn, pending_summary))
        else:
            messages.append(self._build_session_state(runtime))
        return messages

    async def _handle_repo_request(
        self,
        runtime: VoiceSessionRuntime,
        text: str,
    ) -> List[ServerToClientMessage]:
        chat_id = self._ensure_active_chat(runtime, runtime.active_repo_agent_id)
        messages: List[ServerToClientMessage] = [
            self._append_chat_message(
                chat_id,
                runtime.active_repo_agent_id or "",
                ChatMessageRole.USER,
                text,
            )
        ]

        result = await self.orchestrator.handle_user_message(
            repo_agent_id=runtime.active_repo_agent_id or "",
            message=text,
        )
        if result.next_turn is not None:
            runtime.announced_turn_ids.add(result.next_turn.id)
            pending_summary = self._build_pending_turn(result.next_turn)
            messages.extend(self._messages_for_turn(runtime, result.next_turn, pending_summary))
        else:
            messages.append(self._build_session_state(runtime))
        return messages

    async def _handle_pending_prompt(
        self,
        runtime: VoiceSessionRuntime,
        text: str,
    ) -> Optional[List[ServerToClientMessage]]:
        if runtime.pending_prompt is None:
            return None

        command = self.command_router.parse(text)
        prompt = runtime.pending_prompt
        runtime.pending_prompt = None

        if prompt.kind == "switch_repo":
            if command.type == VoiceCommandType.APPROVE and prompt.target_repo_agent_id:
                runtime.active_repo_agent_id = prompt.target_repo_agent_id
                runtime.active_chat_id = self._maybe_get_active_chat_id(prompt.target_repo_agent_id)
                if runtime.active_chat_id is not None:
                    runtime.chat_by_repo[prompt.target_repo_agent_id] = runtime.active_chat_id
                messages = [
                    AIResponseMessage(
                        responseText="Switched to %s." % self._display_name_for_repo_id(prompt.target_repo_agent_id),
                        repoAgentId=prompt.target_repo_agent_id,
                        turnId=prompt.turn_id,
                    ),
                    self._build_session_state(runtime),
                ]
                messages.extend(self._maybe_prompt_for_active_turn(runtime))
                return messages
            if command.type == VoiceCommandType.REJECT:
                messages = [AIResponseMessage(responseText="Okay, I will stay on the current repository.")]
                messages.extend(self._advance_interruption_queue(runtime))
                return messages
            runtime.pending_prompt = prompt
            return [AIResponseMessage(responseText="Please answer yes or no.")]

        if prompt.kind == "resolve_repo":
            if command.type == VoiceCommandType.REJECT:
                return [AIResponseMessage(responseText="Okay, I cancelled that repository switch.")]
            matched = self._match_repo_candidate(text, prompt.candidates)
            if matched is None:
                runtime.pending_prompt = prompt
                names = ", ".join(candidate.display_name for candidate in prompt.candidates[:3])
                return [
                    AIResponseMessage(
                        responseText="I still need you to choose one of these repositories: %s."
                        % names
                    )
                ]
            return await self._handle_open_repo(runtime, matched.display_name)

        return None

    def _messages_for_turn(
        self,
        runtime: VoiceSessionRuntime,
        turn: TurnRequest,
        summary: PendingTurnSummary,
    ) -> List[ServerToClientMessage]:
        chat_id = self._maybe_get_active_chat_id(turn.repo_agent_id)
        messages: List[ServerToClientMessage] = []
        assistant_text = self._summarize_turn(turn, summary.repoName)
        if chat_id is not None:
            messages.append(
                self._append_chat_message(
                    chat_id,
                    turn.repo_agent_id,
                    ChatMessageRole.ASSISTANT,
                    assistant_text,
                    turn_id=turn.id,
                )
            )
        messages.append(
            AIResponseMessage(
                responseText=assistant_text,
                repoAgentId=turn.repo_agent_id,
                chatId=chat_id,
                turnId=turn.id,
            )
        )
        if turn.requires_user_response or turn.type in {TurnType.APPROVAL, TurnType.BLOCKING_QUESTION}:
            messages.append(PendingTurnMessage(pendingTurn=summary))
        messages.append(self._build_session_state(runtime))
        return messages

    def _assistant_messages(
        self,
        runtime: VoiceSessionRuntime,
        text: str,
        repo_agent_id: Optional[str],
        chat_id: Optional[str],
        turn_id: Optional[str] = None,
    ) -> List[ServerToClientMessage]:
        messages: List[ServerToClientMessage] = []
        if chat_id is not None and repo_agent_id is not None:
            messages.append(
                self._append_chat_message(
                    chat_id,
                    repo_agent_id,
                    ChatMessageRole.ASSISTANT,
                    text,
                    turn_id=turn_id,
                )
            )
        messages.append(
            AIResponseMessage(
                responseText=text,
                repoAgentId=repo_agent_id,
                chatId=chat_id,
                turnId=turn_id,
            )
        )
        messages.append(self._build_session_state(runtime))
        return messages

    def _append_chat_message(
        self,
        chat_id: str,
        repo_agent_id: str,
        role: ChatMessageRole,
        content: str,
        turn_id: Optional[str] = None,
    ) -> VoiceChatMessage:
        message = ChatMessage(
            chat_id=chat_id,
            repo_agent_id=repo_agent_id,
            user_id=self.orchestrator.settings.jarvis_user_id,
            role=role,
            content=content,
            turn_id=turn_id,
        )
        self.persistence.save_chat_message(message)
        return VoiceChatMessage(
            id=message.message_id,
            chatId=message.chat_id,
            repoAgentId=message.repo_agent_id,
            role=message.role.value,
            content=message.content,
            turnId=message.turn_id,
            createdAt=message.created_at,
        )

    def _build_session_state(self, runtime: VoiceSessionRuntime) -> SessionStateMessage:
        active_repo_id = runtime.active_repo_agent_id
        
        # Validate that the active repo still exists
        if active_repo_id is not None:
            try:
                self.orchestrator.registry.get_agent_state(active_repo_id)
            except KeyError:
                # Active repo was deleted, clear it
                active_repo_id = None
                runtime.active_repo_agent_id = None
                runtime.active_chat_id = None
        
        active_chat_id = self._maybe_get_active_chat_id(active_repo_id)
        runtime.active_chat_id = active_chat_id
        if active_repo_id and active_chat_id:
            runtime.chat_by_repo[active_repo_id] = active_chat_id

        active_messages = []
        if active_chat_id is not None:
            active_messages = [
                VoiceChatMessage(
                    id=item.message_id,
                    chatId=item.chat_id,
                    repoAgentId=item.repo_agent_id,
                    role=item.role.value,
                    content=item.content,
                    turnId=item.turn_id,
                    createdAt=item.created_at,
                )
                for item in self.persistence.list_chat_messages(active_chat_id)
            ]

        repos = [
            self._build_repo_summary(state)
            for state in self.orchestrator.registry.list_agents(user_id=runtime.user_id)
        ]
        active_agent = next((item for item in repos if item.repoAgentId == active_repo_id), None)
        
        # Filter out pending turns for deleted repos
        all_pending_turns = self.orchestrator.manager.list_pending_turns(user_id=runtime.user_id)
        valid_repo_ids = {state.repo_agent_id for state in self.orchestrator.registry.list_agents(user_id=runtime.user_id)}
        pending = [
            self._build_pending_turn(turn)
            for turn in all_pending_turns
            if turn.repo_agent_id in valid_repo_ids
        ]
        
        return SessionStateMessage(
            sessionId=runtime.session_id,
            activeRepoAgentId=active_repo_id,
            activeChatId=active_chat_id,
            repos=repos,
            activeAgent=active_agent,
            pendingTurns=pending,
            messages=active_messages,
        )

    def _build_repo_summary(self, state: RepositoryAgentState) -> RepoSummary:
        pending_count = len(
            [
                turn
                for turn in self.orchestrator.manager.list_pending_turns(user_id=state.user_id)
                if turn.repo_agent_id == state.repo_agent_id
            ]
        )
        return RepoSummary(
            repoAgentId=state.repo_agent_id,
            repoId=state.repo_id,
            displayName=self._display_name_for_repo(state),
            repoPath=state.repo_path,
            branchName=state.branch_name,
            phase=state.phase.value,
            status=_status_from_phase(state.phase.value),
            activeChatId=self._maybe_get_active_chat_id(state.repo_agent_id),
            pendingTurns=pending_count,
        )

    def _build_pending_turn(self, turn: TurnRequest) -> PendingTurnSummary:
        try:
            state = self.orchestrator.registry.get_agent_state(turn.repo_agent_id)
            repo_name = self._display_name_for_repo(state)
        except KeyError:
            repo_name = "Unknown repository"
        return PendingTurnSummary(
            turnId=turn.id,
            repoAgentId=turn.repo_agent_id,
            repoName=repo_name,
            type=turn.type.value,
            message=turn.message,
            requiresUserResponse=turn.requires_user_response,
            priority=turn.priority,
            createdAt=turn.created_at,
        )

    def _display_name_for_repo(self, state: RepositoryAgentState) -> str:
        record = self.persistence.get_repository(state.repo_id)
        if record is not None and record.display_name:
            return record.display_name
        return Path(state.repo_path).name

    def _display_name_for_repo_id(self, repo_agent_id: str) -> str:
        state = self.orchestrator.registry.get_agent_state(repo_agent_id)
        return self._display_name_for_repo(state)

    def _maybe_get_active_chat_id(self, repo_agent_id: Optional[str]) -> Optional[str]:
        if repo_agent_id is None:
            return None
        chat = self.persistence.get_active_chat_session(repo_agent_id)
        return chat.chat_id if chat is not None else None

    def _ensure_active_chat(self, runtime: VoiceSessionRuntime, repo_agent_id: Optional[str]) -> str:
        if repo_agent_id is None:
            raise ValueError("Cannot create a chat without an active repository.")
        existing = self.persistence.get_active_chat_session(repo_agent_id)
        if existing is not None:
            runtime.active_chat_id = existing.chat_id
            runtime.chat_by_repo[repo_agent_id] = existing.chat_id
            return existing.chat_id
        chat = ChatSession(
            repo_agent_id=repo_agent_id,
            user_id=runtime.user_id,
            title="Voice chat for %s" % self._display_name_for_repo_id(repo_agent_id),
        )
        self.persistence.save_chat_session(chat)
        runtime.active_chat_id = chat.chat_id
        runtime.chat_by_repo[repo_agent_id] = chat.chat_id
        return chat.chat_id

    def _find_activated_repo_by_name(self, repo_query: str) -> Optional[RepositoryAgentState]:
        normalized = _normalize_name(repo_query)
        if not normalized:
            return None
        candidates = []
        for state in self.orchestrator.registry.list_agents(
            user_id=self.orchestrator.settings.jarvis_user_id
        ):
            display_name = _normalize_name(self._display_name_for_repo(state))
            basename = _normalize_name(Path(state.repo_path).name)
            if normalized == display_name or normalized == basename:
                return state
            if normalized in display_name or normalized in basename:
                candidates.append(state)
        return candidates[0] if len(candidates) == 1 else None

    def _pending_turn_for_repo(
        self,
        repo_agent_id: Optional[str],
        explicit_turn_id: Optional[str] = None,
    ) -> Optional[TurnRequest]:
        if explicit_turn_id:
            turn = self.orchestrator.manager.get_turn(explicit_turn_id)
            if turn is not None and not turn.handled:
                return turn
        if repo_agent_id is None:
            return None
        pending = [
            turn
            for turn in self.orchestrator.manager.list_pending_turns(
                user_id=self.orchestrator.settings.jarvis_user_id
            )
            if turn.repo_agent_id == repo_agent_id and turn.requires_user_response
        ]
        return pending[0] if pending else None

    def _summarize_turn(self, turn: TurnRequest, repo_name: str) -> str:
        cleaned = " ".join(turn.message.replace("`", "").split())
        if turn.type == TurnType.APPROVAL:
            return "I have a plan for %s. %s" % (repo_name, cleaned)
        if turn.type == TurnType.COMPLETION:
            return cleaned
        if turn.type == TurnType.BLOCKING_QUESTION:
            return "I need your input for %s. %s" % (repo_name, cleaned)
        if turn.type == TurnType.EXPLANATION:
            return cleaned
        if turn.type == TurnType.BRANCH_PERMISSION:
            return cleaned
        if turn.type == TurnType.BRANCH_NAME:
            return cleaned
        if turn.type == TurnType.BRANCH_CONFIRMATION:
            return cleaned
        if turn.type == TurnType.PLAN_STEP_REVIEW:
            return cleaned
        if turn.type == TurnType.EXECUTION_APPROVAL:
            return cleaned
        return cleaned

    def _maybe_prompt_for_active_turn(self, runtime: VoiceSessionRuntime) -> List[ServerToClientMessage]:
        active_turn = self._pending_turn_for_repo(runtime.active_repo_agent_id)
        if active_turn is None:
            return []
        if active_turn.id in runtime.announced_turn_ids:
            return [PendingTurnMessage(pendingTurn=self._build_pending_turn(active_turn))]
        runtime.announced_turn_ids.add(active_turn.id)
        return self._messages_for_turn(runtime, active_turn, self._build_pending_turn(active_turn))

    def _advance_interruption_queue(self, runtime: VoiceSessionRuntime) -> List[ServerToClientMessage]:
        while runtime.queued_interruptions:
            next_prompt = runtime.queued_interruptions.popleft()
            if next_prompt.turn_id and self.orchestrator.manager.get_turn(next_prompt.turn_id) is None:
                continue
            runtime.pending_prompt = next_prompt
            if next_prompt.target_repo_agent_id is None:
                continue
            repo_name = self._display_name_for_repo_id(next_prompt.target_repo_agent_id)
            return [
                AIResponseMessage(
                    responseText="%s has something pending. Do you want to switch to it?" % repo_name,
                    repoAgentId=next_prompt.target_repo_agent_id,
                    turnId=next_prompt.turn_id,
                )
            ]
        return []

    def _match_repo_candidate(
        self,
        text: str,
        candidates: Sequence[RepoDiscoveryCandidate],
    ) -> Optional[RepoDiscoveryCandidate]:
        normalized = _normalize_name(text)
        if not normalized:
            return None
        matches = [
            candidate
            for candidate in candidates
            if normalized in _normalize_name(candidate.display_name)
            or normalized == _normalize_name(Path(candidate.repo_path).name)
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def _new_session_id(self) -> str:
        from uuid import uuid4

        return "voice_session_" + uuid4().hex


def _normalize_name(value: str) -> str:
    return " ".join(value.lower().replace("`", "").split())


def _shorten(value: str, limit: int) -> str:
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _status_from_phase(phase: str) -> str:
    if phase == "WAITING_APPROVAL":
        return "waiting_approval"
    if phase in {"BRANCH_PERMISSION", "BRANCH_NAME", "BRANCH_CONFIRMATION", "PLAN_STEP_REVIEW", "WAITING_EXECUTION_APPROVAL"}:
        return "waiting_approval"
    if phase in {"PLANNING", "EXECUTING", "FINALIZING", "WAITING_FOR_USER", "ANSWERING_QUESTION", "INTAKE"}:
        return "running"
    if phase in {"DONE", "FAILED"}:
        return "idle"
    return "idle"
