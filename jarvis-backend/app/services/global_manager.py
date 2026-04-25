from __future__ import annotations

from typing import List, Optional

from app.models.events import ManagerEvent, ManagerEventType
from app.models.turns import TurnRequest, TurnResponse
from app.services.persistence import SQLitePersistence
from app.services.turn_scheduler import TurnScheduler


class GlobalManager:
    """Deterministic coordinator for turns, locks and manager events."""

    def __init__(self, scheduler: TurnScheduler, persistence: SQLitePersistence) -> None:
        self.scheduler = scheduler
        self.persistence = persistence

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
        return event

    def list_events(self) -> List[ManagerEvent]:
        return self.persistence.list_events()

