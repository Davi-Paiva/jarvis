from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.services.openai_client import FakeLLMClient


VOICE_TERMINAL_TYPES = {"AI_RESPONSE", "AUDIO_STREAM_END"}
VOICE_STREAM_TYPES = {"AUDIO_STREAM_START", "AUDIO_STREAM_CHUNK", "AUDIO_STREAM_END"}


def test_voice_websocket_can_activate_repo_and_run_task(tmp_path):
    repo = tmp_path / "alpha-app"
    repo.mkdir()
    (repo / ".git").mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")

    with TestClient(_app(tmp_path)) as client:
        with client.websocket_connect("/ws") as websocket:
            websocket.send_json({"type": "SESSION_START"})

            state_message = websocket.receive_json()
            guidance_events = collect_until_voice_response(websocket)

            assert state_message["type"] == "SESSION_STATE"
            assert _has_voice_response(guidance_events)
            session_id = state_message["sessionId"]

            websocket.send_json(
                {
                    "type": "USER_TRANSCRIPT",
                    "sessionId": session_id,
                    "text": "open repo alpha app",
                }
            )

            opened_voice = collect_until_voice_response(websocket)
            opened_state = websocket.receive_json()

            assert opened_state["activeAgent"]["displayName"] == "alpha-app"
            assert opened_state["type"] == "SESSION_STATE"
            opened_ai = _find_event(opened_voice, "AI_RESPONSE")
            if opened_ai is not None and opened_ai.get("repoAgentId") is not None:
                assert opened_ai["repoAgentId"] == opened_state["activeRepoAgentId"]
            else:
                assert _has_stream_end(opened_voice)

            websocket.send_json(
                {
                    "type": "USER_TRANSCRIPT",
                    "sessionId": session_id,
                    "repoAgentId": opened_state["activeRepoAgentId"],
                    "text": "Prepare a safe backend demo",
                }
            )

            task_messages = collect_events_until(
                websocket,
                predicate=lambda events: (
                    _find_event(events, "PENDING_TURN") is not None
                    and _find_event(events, "SESSION_STATE") is not None
                    and _has_voice_response(events)
                ),
                max_events=500,
            )
            task_pending = next(item for item in task_messages if item["type"] == "PENDING_TURN")
            task_state = next(item for item in task_messages if item["type"] == "SESSION_STATE")
            task_text = extract_voice_response_text(task_messages)

            assert any(item["type"] == "CHAT_MESSAGE" and item["role"] == "user" for item in task_messages)
            assert any(
                item["type"] == "CHAT_MESSAGE" and item["role"] == "assistant"
                for item in task_messages
            )
            assert task_pending["pendingTurn"]["repoAgentId"] == opened_state["activeRepoAgentId"]
            if task_text:
                assert (
                    "Do you want me to create a new branch" in task_text
                    or "Do you want me to continue" in task_text
                )
            else:
                assert _has_stream_end(task_messages)
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

            followup_messages = collect_events_until(
                websocket,
                predicate=lambda events: (
                    _find_event(events, "PENDING_TURN") is not None
                    and _find_event(events, "SESSION_STATE") is not None
                    and _has_voice_response(events)
                ),
                max_events=500,
            )
            followup_pending = next(item for item in followup_messages if item["type"] == "PENDING_TURN")
            followup_state = next(item for item in followup_messages if item["type"] == "SESSION_STATE")
            followup_text = extract_voice_response_text(followup_messages)

            assert any(item["type"] == "CHAT_MESSAGE" and item["role"] == "user" for item in followup_messages)
            assert any(
                item["type"] == "CHAT_MESSAGE" and item["role"] == "assistant"
                for item in followup_messages
            )
            assert followup_pending["pendingTurn"]["repoAgentId"] == opened_state["activeRepoAgentId"]
            assert followup_pending["pendingTurn"]["type"] == "BRANCH_NAME"
            if followup_text:
                assert "What name should I use for the new branch" in followup_text
            else:
                assert _has_stream_end(followup_messages)
            assert followup_state["activeAgent"]["status"] == "waiting_approval"


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
            initial_guidance = collect_until_voice_response(websocket)
            assert _has_voice_response(initial_guidance)

            asyncio.run(
                orchestrator.handle_user_message(
                    beta_state.repo_agent_id,
                    "fix this backend flow",
                )
            )

            notified = collect_events_until(
                websocket,
                predicate=lambda events: (
                    _find_event(events, "PENDING_TURN") is not None and _has_voice_response(events)
                ),
                max_events=500,
            )
            pending = next(item for item in notified if item["type"] == "PENDING_TURN")
            spoken_text = extract_voice_response_text(notified)

            assert pending["pendingTurn"]["repoAgentId"] == beta_state.repo_agent_id
            assert pending["pendingTurn"]["type"] == "BRANCH_PERMISSION"
            if spoken_text:
                assert "Do you want to switch" in spoken_text
            else:
                assert _has_stream_end(notified)


def test_voice_websocket_switch_repo_message_updates_session_without_user_chat(tmp_path):
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
            session_id = initial_state["sessionId"]
            initial_guidance = collect_until_voice_response(websocket)
            assert _has_voice_response(initial_guidance)

            websocket.send_json(
                {
                    "type": "SWITCH_REPO",
                    "sessionId": session_id,
                    "repoAgentId": beta_state.repo_agent_id,
                }
            )

            switch_events = collect_events_until(
                websocket,
                predicate=lambda events: (
                    _find_event(events, "SESSION_STATE") is not None and any(
                        event.get("type") == "SESSION_STATE"
                        and event.get("activeRepoAgentId") == beta_state.repo_agent_id
                        for event in events
                    )
                ),
                max_events=500,
            )
            switched_state = next(
                item
                for item in switch_events
                if item["type"] == "SESSION_STATE" and item["activeRepoAgentId"] == beta_state.repo_agent_id
            )
            switch_text = extract_voice_response_text(switch_events)

            assert switched_state["activeAgent"]["repoAgentId"] == beta_state.repo_agent_id
            assert not any(
                item.get("type") == "CHAT_MESSAGE" and item.get("role") == "user"
                for item in switch_events
            )
            if switch_text:
                assert "Switched to beta-app" in switch_text
            else:
                assert _has_stream_end(switch_events)


def collect_events_until(websocket, predicate, max_events=500):
    events = []
    for _ in range(max_events):
        event = websocket.receive_json()
        events.append(event)
        if predicate(events):
            return events
    raise AssertionError(f"Expected websocket events were not observed within {max_events} events: {events}")


def collect_until_voice_response(websocket, max_events=500):
    events = collect_events_until(
        websocket,
        predicate=lambda current: _has_voice_response(current),
        max_events=max_events,
    )
    _assert_valid_voice_response_pattern(events)
    return events


def extract_voice_response_text(events):
    ai_event = _find_event(events, "AI_RESPONSE")
    if ai_event is not None:
        return ai_event.get("responseText", "")
    stream_start = _find_event(events, "AUDIO_STREAM_START")
    if stream_start is not None:
        return stream_start.get("responseText", "") or ""
    return ""


def _find_event(events, event_type):
    for event in events:
        if event.get("type") == event_type:
            return event
    return None


def _has_voice_response(events):
    return any(event.get("type") in VOICE_TERMINAL_TYPES for event in events)


def _has_stream_end(events):
    return any(event.get("type") == "AUDIO_STREAM_END" for event in events)


def _assert_valid_voice_response_pattern(events):
    event_types = [event.get("type") for event in events]
    if "AI_RESPONSE" in event_types:
        return

    if not any(event_type in VOICE_STREAM_TYPES for event_type in event_types):
        raise AssertionError(f"Expected AI_RESPONSE or streaming events, got: {event_types}")

    stream_start_idx = event_types.index("AUDIO_STREAM_START") if "AUDIO_STREAM_START" in event_types else -1
    stream_end_idx = event_types.index("AUDIO_STREAM_END") if "AUDIO_STREAM_END" in event_types else -1
    if stream_start_idx == -1 or stream_end_idx == -1 or stream_end_idx < stream_start_idx:
        raise AssertionError(f"Invalid streaming order. Expected START ... END, got: {event_types}")


def _app(tmp_path, llm_client=None):
    settings = Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )
    return create_app(settings=settings, llm_client=llm_client or FakeLLMClient())
