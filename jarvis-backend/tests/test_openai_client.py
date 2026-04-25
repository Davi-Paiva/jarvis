from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.models.repository import RepositoryAgentState
from app.models.task import TaskPlanItem
from app.services.openai_client import (
    OpenAIAgentsClient,
    TaskImplementationResult,
    _normalize_task_plan_items,
)


def test_task_implementation_result_drops_non_command_test_placeholders():
    result = TaskImplementationResult(
        result_summary="done",
        test_command="No tests run (inspection only).",
    )

    assert result.test_command is None


def test_task_implementation_result_keeps_real_test_command():
    result = TaskImplementationResult(
        result_summary="done",
        test_command="pytest tests/test_api.py",
    )

    assert result.test_command == "pytest tests/test_api.py"


def test_task_implementation_result_normalizes_needed_files():
    result = TaskImplementationResult(
        result_summary="need files",
        needed_files="src/App.tsx, src/layout.tsx\nsrc/App.tsx",
    )

    assert result.needed_files == ["src/App.tsx", "src/layout.tsx"]


def test_openai_agents_client_does_not_fallback_when_runtime_is_unavailable(tmp_path):
    settings = Settings(
        openai_api_key=None,
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )
    client = OpenAIAgentsClient(settings)
    state = RepositoryAgentState(
        repo_id="repo_demo",
        repo_path=str(tmp_path),
        thread_id="repo_agent:demo",
    )

    async def scenario():
        try:
            await client.split_tasks(state, "plan")
            raise AssertionError("client should require the live OpenAI agents runtime")
        except RuntimeError as exc:
            assert "OpenAI Agents runtime is not available" in str(exc)

    asyncio.run(scenario())


def test_task_plan_item_discards_descriptive_scope_strings():
    item = TaskPlanItem(
        title="Inspect repo",
        description="Look at the routing layer.",
        scope="Repository inspection",
    )

    assert item.scope == []


def test_task_plan_item_accepts_path_like_scope_strings():
    item = TaskPlanItem(
        title="Inspect repo",
        description="Look at the routing layer.",
        scope="app/api, app/services\nsrc/routes",
    )

    assert item.scope == ["app/api", "app/services", "src/routes"]


def test_normalize_task_plan_items_accepts_wrapped_payload_and_nested_steps():
    parsed = {
        "result": {
            "steps": [
                {
                    "step": {
                        "name": "Inspect the purchase flow",
                        "details": "Review the websocket and purchase handlers.",
                        "scope": "app/api/websocket.py",
                    }
                },
                "Add a notification step",
            ]
        }
    }

    items = _normalize_task_plan_items(parsed)

    assert [item.title for item in items] == [
        "Inspect the purchase flow",
        "Implementation step 2",
    ]
    assert items[0].scope == ["app/api/websocket.py"]
    assert items[1].description == "Add a notification step"
