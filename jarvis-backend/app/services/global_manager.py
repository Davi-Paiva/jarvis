from __future__ import annotations

import asyncio
from typing import List, Optional, Tuple

from app.models.events import ManagerEvent, ManagerEventType
from app.models.turns import TurnRequest, TurnResponse
from app.services.persistence import SQLitePersistence
from app.services.turn_scheduler import TurnScheduler


class GlobalManager:
    """Deterministic coordinator for turns, locks and manager events."""

    def __init__(self, scheduler: TurnScheduler, persistence: SQLitePersistence) -> None:
        self.scheduler = scheduler
        self.persistence = persistence
        self._listeners: List[Tuple[asyncio.AbstractEventLoop, asyncio.Queue]] = []

    def acquire_intake_lock(self, repo_agent_id: str) -> None:
        self.scheduler.acquire_intake_lock(repo_agent_id)

    def release_intake_lock(self, repo_agent_id: str) -> None:
        self.scheduler.release_intake_lock(repo_agent_id)

    def enqueue_turn(self, turn: TurnRequest) -> TurnRequest:
        saved = self.scheduler.enqueue(turn)
        event_type = (
            ManagerEventType.APPROVAL_REQUIRED
            if turn.requires_user_response
            else ManagerEventType.TURN_CREATED
        )
        self.emit_event(
            ManagerEvent(
                type=event_type,
                repo_agent_id=turn.repo_agent_id,
                turn_id=turn.id,
                message=turn.message,
            )
        )
        return saved

    def get_turn(self, turn_id: str) -> Optional[TurnRequest]:
        return self.scheduler.get_turn(turn_id)

    def get_next_turn(self, user_id: str = "demo") -> Optional[TurnRequest]:
        return self.scheduler.next_turn(user_id=user_id)

    def list_pending_turns(self, user_id: str = "demo") -> List[TurnRequest]:
        turns = [turn for turn in self.persistence.list_turns(user_id=user_id) if not turn.handled]
        return sorted(turns, key=lambda turn: (-turn.priority, turn.created_at))

    def register_listener(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        self._listeners.append((loop, queue))
        return queue

    def unregister_listener(self, queue: asyncio.Queue) -> None:
        self._listeners = [item for item in self._listeners if item[1] is not queue]

    def record_user_response(
        self,
        turn_id: str,
        response: str,
        approved: Optional[bool] = None,
    ) -> TurnResponse:
        turn = self.scheduler.mark_handled(turn_id)
        if turn is None:
            raise KeyError("Unknown turn_id: %s" % turn_id)
        turn_response = TurnResponse(turn_id=turn_id, response=response, approved=approved)
        self.emit_event(
            ManagerEvent(
                type=ManagerEventType.USER_RESPONSE_RECEIVED,
                repo_agent_id=turn.repo_agent_id,
                turn_id=turn_id,
                message=response,
            )
        )
        return turn_response

    def emit_progress(self, repo_agent_id: str, message: str) -> None:
        self.emit_event(
            ManagerEvent(
                type=ManagerEventType.AGENT_PROGRESS,
                repo_agent_id=repo_agent_id,
                message=message,
            )
        )

    def emit_completed(self, repo_agent_id: str, message: str) -> None:
        self.emit_event(
            ManagerEvent(
                type=ManagerEventType.AGENT_COMPLETED,
                repo_agent_id=repo_agent_id,
                message=message,
            )
        )

    def emit_failed(self, repo_agent_id: str, message: str) -> None:
        self.emit_event(
            ManagerEvent(
                type=ManagerEventType.AGENT_FAILED,
                repo_agent_id=repo_agent_id,
                message=message,
            )
        )

    def emit_event(self, event: ManagerEvent) -> ManagerEvent:
        self.persistence.save_event(event)
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        for loop, listener in list(self._listeners):
            if loop.is_closed():
                continue
            try:
                if current_loop is loop:
                    listener.put_nowait(event)
                else:
                    loop.call_soon_threadsafe(listener.put_nowait, event)
            except Exception:
                continue
        return event

    def list_events(self) -> List[ManagerEvent]:
        return self.persistence.list_events()
