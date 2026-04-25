from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.turns import TurnRequest, TurnType
from app.services.persistence import SQLitePersistence
from app.services.turn_scheduler import TurnScheduler


def test_turn_scheduler_uses_priority_then_age(tmp_path):
    persistence = SQLitePersistence(str(tmp_path / "jarvis.db"))
    scheduler = TurnScheduler(persistence)
    low = TurnRequest(
        agent_id="agent_a",
        repo_agent_id="agent_a",
        type=TurnType.PROGRESS,
        priority=20,
        message="low",
    )
    high = TurnRequest(
        agent_id="agent_b",
        repo_agent_id="agent_b",
        type=TurnType.BLOCKING_QUESTION,
        priority=80,
        message="high",
        requires_user_response=True,
    )

    scheduler.enqueue(low)
    scheduler.enqueue(high)

    assert scheduler.next_turn().id == high.id
    scheduler.mark_handled(high.id)
    assert scheduler.next_turn().id == low.id


def test_turn_scheduler_respects_intake_lock(tmp_path):
    persistence = SQLitePersistence(str(tmp_path / "jarvis.db"))
    scheduler = TurnScheduler(persistence)
    locked = TurnRequest(
        agent_id="agent_a",
        repo_agent_id="agent_a",
        type=TurnType.INTAKE,
        priority=100,
        message="locked",
        requires_user_response=True,
    )
    other = TurnRequest(
        agent_id="agent_b",
        repo_agent_id="agent_b",
        type=TurnType.BLOCKING_QUESTION,
        priority=80,
        message="other",
        requires_user_response=True,
    )

    scheduler.enqueue(other)
    scheduler.enqueue(locked)
    scheduler.acquire_intake_lock("agent_a")

    assert scheduler.next_turn().id == locked.id
    scheduler.release_intake_lock("agent_a")
    scheduler.mark_handled(locked.id)
    assert scheduler.next_turn().id == other.id

