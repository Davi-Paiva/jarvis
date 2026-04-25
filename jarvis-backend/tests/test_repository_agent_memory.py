from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.models.repository import RepositoryAgentState
from app.models.task import TaskAgentState
from app.services.openai_client import FakeLLMClient, TaskImplementationResult
from app.services.orchestrator import JarvisOrchestrator


class CapturingMemoryLLM(FakeLLMClient):
    def __init__(self) -> None:
        self.memory_contexts: List[str] = []

    async def extract_requirements(
        self,
        task_goal: str,
        acceptance_criteria: List[str],
        repo_context: str,
        memory_context: str,
    ) -> List[str]:
        self.memory_contexts.append(memory_context)
        return await super().extract_requirements(
            task_goal,
            acceptance_criteria,
            repo_context,
            memory_context,
        )

    async def create_plan(
        self,
        state: RepositoryAgentState,
        repo_context: str,
        memory_context: str,
    ) -> str:
        self.memory_contexts.append(memory_context)
        return "Use existing project style.\nDo not add dependencies."

    async def implement_task(
        self,
        repo_state: RepositoryAgentState,
        task_state: TaskAgentState,
        repo_context: str,
        memory_context: str,
    ) -> TaskImplementationResult:
        self.memory_contexts.append(memory_context)
        return TaskImplementationResult(
            result_summary=(
                "Reusable Learnings:\n"
                "- API calls are centralized in `src/api/client.ts`.\n"
                "\n"
                "Risks:\n"
                "- No visual regression tests currently exist.\n"
                "\n"
                "Raw stdout contains sk-test-secret but SQLite may retain it."
            ),
            changed_files=["src/api/client.ts"],
        )

    async def final_report(
        self,
        repo_state: RepositoryAgentState,
        task_states: List[TaskAgentState],
    ) -> str:
        return "Task finished.\nRisks:\n- No visual regression tests currently exist."


def test_repository_agent_uses_structured_compact_memory(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    llm = CapturingMemoryLLM()
    orchestrator = _orchestrator(tmp_path, llm)

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        memory = orchestrator.memory_service.load_memory(agent.repo_agent_id)
        memory.repository_learnings = [
            "Old learning %s %s" % (index, "x" * 80) for index in range(30)
        ]
        orchestrator.memory_service.save_memory(memory, compact=False)

        started = await orchestrator.start_task(
            agent.repo_agent_id,
            "Add API client test coverage",
            ["Prefer short explanations", "Do not add dependencies"],
        )
        await orchestrator.submit_user_response(
            started.next_turn.id,
            "approved",
            approved=True,
        )

        content = orchestrator.memory_service.path_for_agent(
            agent.repo_agent_id
        ).read_text(encoding="utf-8")
        tasks = orchestrator.registry.list_task_agents(agent.repo_agent_id)

        assert llm.memory_contexts
        assert all(len(context) <= 700 for context in llm.memory_contexts)
        assert content.startswith("---\n")
        assert "## Completed Tasks" in content
        assert "API calls are centralized in `src/api/client.ts`." in content
        assert "src/api/client.ts" in content
        assert "Task Intake" not in content
        assert "Proposed Plan" not in content
        assert "Final Report" not in content
        assert "sk-test-secret" not in content
        assert "stdout" not in content
        assert tasks and "sk-test-secret" in (tasks[0].result_summary or "")

        view = await orchestrator.get_memory_view(agent.repo_agent_id, max_chars=400)
        assert len(view.text) <= 400

    asyncio.run(scenario())


def _orchestrator(tmp_path, llm):
    settings = Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
        jarvis_memory_view_max_chars=700,
        jarvis_memory_max_chars=50000,
    )
    return JarvisOrchestrator.create(settings=settings, llm_client=llm)

