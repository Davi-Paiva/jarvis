from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional

from app.models.base import model_from_json, model_to_json
from app.models.chat import ChatMessage, ChatSession, ChatSessionStatus
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
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_sessions (chat_id TEXT PRIMARY KEY, repo_agent_id TEXT NOT NULL, user_id TEXT NOT NULL, active INTEGER NOT NULL, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_messages (message_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL, repo_agent_id TEXT NOT NULL, user_id TEXT NOT NULL, payload TEXT NOT NULL)"
            )

    def save_repository(self, record: RepositoryRecord) -> None:
        self._upsert("repositories", "repo_id", record.repo_id, model_to_json(record))

    def get_repository(self, repo_id: str) -> Optional[RepositoryRecord]:
        payload = self._get_payload("repositories", "repo_id", repo_id)
        return model_from_json(RepositoryRecord, payload) if payload else None

    def list_repositories(self, user_id: Optional[str] = None) -> List[RepositoryRecord]:
        repositories = [
            model_from_json(RepositoryRecord, payload)
            for payload in self._list_payloads("repositories")
        ]
        if user_id is not None:
            repositories = [record for record in repositories if record.user_id == user_id]
        return sorted(repositories, key=lambda item: item.created_at)

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

    def delete_repo_agent(self, repo_agent_id: str) -> None:
        # First fetch all turns to identify which ones belong to this repo
        turns_to_delete = [
            turn.id for turn in self.list_turns() if turn.repo_agent_id == repo_agent_id
        ]
        
        with self._connect() as conn:
            conn.execute("DELETE FROM repo_agents WHERE repo_agent_id = ?", (repo_agent_id,))
            conn.execute("DELETE FROM task_agents WHERE repo_agent_id = ?", (repo_agent_id,))
            conn.execute("DELETE FROM chat_sessions WHERE repo_agent_id = ?", (repo_agent_id,))
            conn.execute("DELETE FROM chat_messages WHERE repo_agent_id = ?", (repo_agent_id,))
            
            # Clean up orphaned turns for this repo
            for turn_id in turns_to_delete:
                conn.execute("DELETE FROM turns WHERE turn_id = ?", (turn_id,))

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

    def save_chat_session(self, session: ChatSession) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chat_sessions (chat_id, repo_agent_id, user_id, active, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    session.chat_id,
                    session.repo_agent_id,
                    session.user_id,
                    1 if session.status == ChatSessionStatus.ACTIVE else 0,
                    model_to_json(session),
                ),
            )

    def get_chat_session(self, chat_id: str) -> Optional[ChatSession]:
        payload = self._get_payload("chat_sessions", "chat_id", chat_id)
        return model_from_json(ChatSession, payload) if payload else None

    def list_chat_sessions(
        self,
        repo_agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        active_only: bool = False,
    ) -> List[ChatSession]:
        sessions = [
            model_from_json(ChatSession, payload)
            for payload in self._list_payloads("chat_sessions")
        ]
        if repo_agent_id is not None:
            sessions = [item for item in sessions if item.repo_agent_id == repo_agent_id]
        if user_id is not None:
            sessions = [item for item in sessions if item.user_id == user_id]
        if active_only:
            sessions = [item for item in sessions if item.status == ChatSessionStatus.ACTIVE]
        return sorted(sessions, key=lambda item: item.created_at)

    def get_active_chat_session(self, repo_agent_id: str) -> Optional[ChatSession]:
        sessions = self.list_chat_sessions(repo_agent_id=repo_agent_id, active_only=True)
        return sessions[-1] if sessions else None

    def save_chat_message(self, message: ChatMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO chat_messages (message_id, chat_id, repo_agent_id, user_id, payload) VALUES (?, ?, ?, ?, ?)",
                (
                    message.message_id,
                    message.chat_id,
                    message.repo_agent_id,
                    message.user_id,
                    model_to_json(message),
                ),
            )

    def list_chat_messages(self, chat_id: str) -> List[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT payload FROM chat_messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchall()
        messages = [model_from_json(ChatMessage, row[0]) for row in rows]
        return sorted(messages, key=lambda item: item.created_at)

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
