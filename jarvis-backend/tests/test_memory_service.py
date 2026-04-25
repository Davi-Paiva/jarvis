from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.memory import CompletedTaskMemory
from app.models.repository import RepositoryAgentState
from app.models.task import TaskAgentState
from app.services.memory_service import MemoryService


def test_memory_service_creates_structured_markdown_and_limited_view(tmp_path):
    service = MemoryService(
        str(tmp_path / "memory"),
        view_max_chars=220,
        useful_commands=["npm test", "npm run build", "npm test"],
    )
    state = _repo_state(str(tmp_path / "repo"))

    memory = service.initialize_agent_memory(state)
    path = service.path_for_agent(state.repo_agent_id)
    content = path.read_text(encoding="utf-8")

    assert content.startswith("---\n")
    assert "repo_agent_id: repo_agent_test" in content
    assert "memory_version: 1" in content
    assert "# Repository Memory" in content
    for title in [
        "Current Summary",
        "User Preferences",
        "Active Conventions",
        "Repository Learnings",
        "Useful Commands",
        "Active Decisions",
        "Known Risks",
        "Completed Tasks",
    ]:
        assert "## %s" % title in content

    memory.repository_learnings = ["Learning %s %s" % (index, "x" * 80) for index in range(20)]
    service.save_memory(memory)

    view = service.render_memory_for_llm(state.repo_agent_id, max_chars=220)
    assert view.truncated is True
    assert len(view.text) <= 220
    assert view.source_path == str(path)


def test_memory_service_sanitizes_dedupes_and_extracts_reusable_memory(tmp_path):
    service = MemoryService(str(tmp_path / "memory"), useful_commands=["npm test"])
    repo_state = _repo_state(str(tmp_path / "repo"))
    repo_state.task_goal = "Add API client test coverage"
    repo_state.acceptance_criteria = [
        "Prefer short explanations",
        "Prefer short explanations",
        "Do not add dependencies",
    ]
    repo_state.plan = "Use existing pytest setup.\nDo not add dependencies."
    repo_state.branch_name = "feature/api-tests"
    repo_state.changed_files = ["src/api/client.ts", "src/api/client.ts"]
    repo_state.test_results = [
        "command=npm test exit_code=0 stdout=%s stderr=" % ("x" * 800),
    ]
    repo_state.final_report = "Risks:\n- No visual regression tests currently exist."
    task = TaskAgentState(
        repo_agent_id=repo_state.repo_agent_id,
        title="API test task",
        description="Add tests",
    )
    task.result_summary = (
        "Reusable Learnings:\n"
        "- API calls are centralized in `src/api/client.ts`.\n"
        "- API calls are centralized in `src/api/client.ts`.\n"
        "\n"
        "Risks:\n"
        "- No visual regression tests currently exist.\n"
        "\n"
        "Raw stdout sk-test-secret should never be persisted."
    )

    service.initialize_agent_memory(repo_state)
    service.record_task_started(repo_state)
    service.record_plan_proposed(repo_state)
    service.record_task_completed(repo_state, [task])

    content = service.path_for_agent(repo_state.repo_agent_id).read_text(encoding="utf-8")
    loaded = service.load_memory(repo_state.repo_agent_id)

    assert loaded.user_preferences == ["Prefer short explanations"]
    assert content.count("API calls are centralized") == 2
    assert "command=npm test exit_code=0" in content
    assert "stdout=" not in content
    assert "sk-test-secret" not in content
    assert "Do not add dependencies" in content
    assert len(loaded.completed_tasks) == 1
    assert loaded.completed_tasks[0].changed_files == ["src/api/client.ts"]


def test_memory_service_compacts_and_archives_old_completed_tasks(tmp_path):
    service = MemoryService(
        str(tmp_path / "memory"),
        max_chars=800,
        max_completed_tasks=2,
    )
    state = _repo_state(str(tmp_path / "repo"))
    memory = service.initialize_agent_memory(state)
    memory.completed_tasks = [
        CompletedTaskMemory(
            title="Task %s" % index,
            goal="Goal %s" % index,
            reusable_learnings=["Learning %s %s" % (index, "x" * 120)],
        )
        for index in range(5)
    ]

    service.save_memory(memory)

    compacted = service.load_memory(state.repo_agent_id)
    archives = list((tmp_path / "memory" / "archive").glob("*.md"))

    assert len(compacted.completed_tasks) == 2
    assert [task.title for task in compacted.completed_tasks] == ["Task 3", "Task 4"]
    assert archives
    assert "Task 0" in archives[0].read_text(encoding="utf-8")


def test_memory_service_repairs_missing_or_legacy_memory_on_initialize(tmp_path):
    service = MemoryService(str(tmp_path / "memory"))
    state = _repo_state(str(tmp_path / "repo"))
    path = service.path_for_agent(state.repo_agent_id)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# Legacy memory\nold format\n", encoding="utf-8")

    service.initialize_agent_memory(state)

    content = path.read_text(encoding="utf-8")
    archives = list((tmp_path / "memory" / "archive").glob("*legacy*.md"))

    assert content.startswith("---\n")
    assert "# Repository Memory" in content
    assert archives


def _repo_state(repo_path: str) -> RepositoryAgentState:
    return RepositoryAgentState(
        repo_agent_id="repo_agent_test",
        user_id="demo",
        repo_id="repo_test",
        repo_path=repo_path,
        branch_name=None,
        thread_id="repo_agent:repo_agent_test",
    )
