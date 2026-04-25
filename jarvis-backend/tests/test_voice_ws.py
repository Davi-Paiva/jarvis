from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.openai_client import FakeLLMClient


def test_voice_websocket_can_activate_repo_and_run_task(tmp_path):
    repo = tmp_path / "alpha-app"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")

    with TestClient(_app(tmp_path)) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "SESSION_START"})

            state_message = websocket.receive_json()
            guidance_message = websocket.receive_json()

            assert state_message["type"] == "SESSION_STATE"
            assert guidance_message["type"] == "AI_RESPONSE"
            session_id = state_message["sessionId"]

            websocket.send_json(
                {
                    "type": "USER_TRANSCRIPT",
                    "sessionId": session_id,
                    "text": "open repo alpha app",
                }
            )

            opened = [websocket.receive_json(), websocket.receive_json()]
            opened_state = next(item for item in opened if item["type"] == "SESSION_STATE")
            opened_ai = next(item for item in opened if item["type"] == "AI_RESPONSE")

            assert opened_state["activeAgent"]["displayName"] == "alpha-app"
            assert opened_ai["repoAgentId"] == opened_state["activeRepoAgentId"]

            websocket.send_json(
                {
                    "type": "USER_TRANSCRIPT",
                    "sessionId": session_id,
                    "repoAgentId": opened_state["activeRepoAgentId"],
                    "text": "Prepare a safe backend demo",
                }
            )

            task_messages = [websocket.receive_json() for _ in range(5)]
            task_pending = next(item for item in task_messages if item["type"] == "PENDING_TURN")
            task_ai = next(item for item in task_messages if item["type"] == "AI_RESPONSE")
            task_state = next(item for item in task_messages if item["type"] == "SESSION_STATE")

            assert any(item["type"] == "CHAT_MESSAGE" and item["role"] == "user" for item in task_messages)
            assert any(
                item["type"] == "CHAT_MESSAGE" and item["role"] == "assistant"
                for item in task_messages
            )
            assert task_pending["pendingTurn"]["repoAgentId"] == opened_state["activeRepoAgentId"]
            assert "Do you want me to continue" in task_ai["responseText"]
            assert task_state["activeAgent"]["status"] == "waiting_approval"

            websocket.send_json(
                {
                    "type": "USER_TRANSCRIPT",
                    "sessionId": session_id,
                    "repoAgentId": opened_state["activeRepoAgentId"],
                    "turnId": task_pending["pendingTurn"]["turnId"],
                    "text": "sí",
                }
            )

            completion_messages = [websocket.receive_json() for _ in range(5)]
            completion_ai = next(item for item in completion_messages if item["type"] == "AI_RESPONSE")
            completion_state = next(item for item in completion_messages if item["type"] == "SESSION_STATE")

            assert any(item["type"] == "CHAT_MESSAGE" and item["role"] == "user" for item in completion_messages)
            assert any(
                item["type"] == "CHAT_MESSAGE" and item["role"] == "assistant"
                for item in completion_messages
            )
            assert "Task finished" in completion_ai["responseText"]
            assert completion_state["activeAgent"]["status"] == "idle"


def test_voice_websocket_notifies_pending_turn_from_another_repo(tmp_path):
    repo_one = tmp_path / "alpha-app"
    repo_two = tmp_path / "beta-app"
    repo_one.mkdir()
    repo_two.mkdir()
    (repo_one / ".git").mkdir()
    (repo_two / ".git").mkdir()
    (repo_one / "main.py").write_text("print('one')\n", encoding="utf-8")
    (repo_two / "main.py").write_text("print('two')\n", encoding="utf-8")

    app = _app(tmp_path)
    orchestrator = app.state.orchestrator

    alpha_state, _ = asyncio.run(orchestrator.activate_repo_agent(str(repo_one)))
    beta_state, _ = asyncio.run(orchestrator.activate_repo_agent(str(repo_two)))

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "SESSION_START"})
            initial_state = websocket.receive_json()
            assert initial_state["type"] == "SESSION_STATE"
            assert initial_state["activeRepoAgentId"] == alpha_state.repo_agent_id

            asyncio.run(
                orchestrator.start_task(
                    beta_state.repo_agent_id,
                    "Need approval for beta",
                    ["Keep it safe"],
                )
            )

            notified = [websocket.receive_json() for _ in range(3)]
            pending = next(item for item in notified if item["type"] == "PENDING_TURN")
            spoken = next(item for item in notified if item["type"] == "AI_RESPONSE")

            assert pending["pendingTurn"]["repoAgentId"] == beta_state.repo_agent_id
            assert "Do you want to switch" in spoken["responseText"]


def _app(tmp_path):
    settings = Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )
    return create_app(settings=settings, llm_client=FakeLLMClient())
