from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional

from app.models.base import model_from_json, model_to_json
from app.models.events import ManagerEvent
from app.models.repository import RepositoryAgentState, RepositoryRecord
from app.models.task import TaskAgentState
from app.models.turns import TurnRequest


class SQLitePersistence:
    """Small SQLite persistence layer for demo-scale local state."""

    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS repositories (repo_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS repo_agents (repo_agent_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS task_agents (task_agent_id TEXT PRIMARY KEY, repo_agent_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS turns (turn_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )

    def save_repository(self, record: RepositoryRecord) -> None:
        self._upsert("repositories", "repo_id", record.repo_id, model_to_json(record))

    def get_repository(self, repo_id: str) -> Optional[RepositoryRecord]:
        payload = self._get_payload("repositories", "repo_id", repo_id)
        return model_from_json(RepositoryRecord, payload) if payload else None

    def save_repo_agent(self, state: RepositoryAgentState) -> None:
        self._upsert("repo_agents", "repo_agent_id", state.repo_agent_id, model_to_json(state))

    def get_repo_agent(self, repo_agent_id: str) -> Optional[RepositoryAgentState]:
        payload = self._get_payload("repo_agents", "repo_agent_id", repo_agent_id)
        return model_from_json(RepositoryAgentState, payload) if payload else None

    def list_repo_agents(self, user_id: Optional[str] = None) -> List[RepositoryAgentState]:
        agents = [
            model_from_json(RepositoryAgentState, payload)
            for payload in self._list_payloads("repo_agents")
        ]
        if user_id is not None:
            agents = [agent for agent in agents if agent.user_id == user_id]
        return sorted(agents, key=lambda item: item.created_at)

    def save_task_agent(self, state: TaskAgentState) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task_agents (task_agent_id, repo_agent_id, payload) VALUES (?, ?, ?)",
                (state.task_agent_id, state.repo_agent_id, model_to_json(state)),
            )

    def get_task_agent(self, task_agent_id: str) -> Optional[TaskAgentState]:
        payload = self._get_payload("task_agents", "task_agent_id", task_agent_id)
        return model_from_json(TaskAgentState, payload) if payload else None

    def list_task_agents(self, repo_agent_id: str) -> List[TaskAgentState]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM task_agents WHERE repo_agent_id = ?",
                (repo_agent_id,),
            ).fetchall()
        tasks = [model_from_json(TaskAgentState, row[0]) for row in rows]
        return sorted(tasks, key=lambda item: item.created_at)

    def save_turn(self, turn: TurnRequest) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO turns (turn_id, user_id, payload) VALUES (?, ?, ?)",
                (turn.id, turn.user_id, model_to_json(turn)),
            )

    def get_turn(self, turn_id: str) -> Optional[TurnRequest]:
        payload = self._get_payload("turns", "turn_id", turn_id)
        return model_from_json(TurnRequest, payload) if payload else None

    def list_turns(self, user_id: Optional[str] = None) -> List[TurnRequest]:
        if user_id is None:
            payloads = self._list_payloads("turns")
        else:
            with self._connect() as conn:
                rows = conn.execute("SELECT payload FROM turns WHERE user_id = ?", (user_id,)).fetchall()
            payloads = [row[0] for row in rows]
        turns = [model_from_json(TurnRequest, payload) for payload in payloads]
        return sorted(turns, key=lambda item: item.created_at)

    def save_event(self, event: ManagerEvent) -> None:
        self._upsert("events", "event_id", event.id, model_to_json(event))

    def list_events(self) -> List[ManagerEvent]:
        return [model_from_json(ManagerEvent, payload) for payload in self._list_payloads("events")]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _upsert(self, table: str, key_name: str, key: str, payload: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO %s (%s, payload) VALUES (?, ?)" % (table, key_name),
                (key, payload),
            )

    def _get_payload(self, table: str, key_name: str, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload FROM %s WHERE %s = ?" % (table, key_name),
                (key,),
            ).fetchone()
        return row[0] if row else None

    def _list_payloads(self, table: str) -> List[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT payload FROM %s" % table).fetchall()
        return [row[0] for row in rows]

