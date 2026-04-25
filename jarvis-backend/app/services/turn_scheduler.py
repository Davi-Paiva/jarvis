from __future__ import annotations

from typing import Optional

from app.models.turns import TurnRequest
from app.services.persistence import SQLitePersistence


class TurnScheduler:
    def __init__(self, persistence: SQLitePersistence) -> None:
        self.persistence = persistence
        self.intake_lock_agent_id: Optional[str] = None

    def acquire_intake_lock(self, repo_agent_id: str) -> None:
        self.intake_lock_agent_id = repo_agent_id

    def release_intake_lock(self, repo_agent_id: str) -> None:
        if self.intake_lock_agent_id == repo_agent_id:
            self.intake_lock_agent_id = None

    def enqueue(self, turn: TurnRequest) -> TurnRequest:
        self.persistence.save_turn(turn)
        return turn

    def get_turn(self, turn_id: str) -> Optional[TurnRequest]:
        return self.persistence.get_turn(turn_id)

    def mark_handled(self, turn_id: str) -> Optional[TurnRequest]:
        turn = self.persistence.get_turn(turn_id)
        if turn is None:
            return None
        turn.handled = True
        self.persistence.save_turn(turn)
        return turn

    def next_turn(self, user_id: str = "demo") -> Optional[TurnRequest]:
        candidates = [
            turn
            for turn in self.persistence.list_turns(user_id=user_id)
            if not turn.handled and turn.requires_user_response
        ]
        if self.intake_lock_agent_id:
            candidates = [
                turn for turn in candidates if turn.repo_agent_id == self.intake_lock_agent_id
            ]
        if not candidates:
            return None
        return sorted(candidates, key=lambda turn: (-turn.priority, turn.created_at))[0]
