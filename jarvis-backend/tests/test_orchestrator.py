from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.models.state import RepositoryAgentPhase, TaskAgentStatus
from app.models.turns import TurnType
from app.services.openai_client import FakeLLMClient
from app.services.orchestrator import JarvisOrchestrator


def test_orchestrator_creates_agent_runs_approval_flow(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")

    orchestrator = _orchestrator(tmp_path)

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo), display_name="Demo Repo")
        assert agent.phase == RepositoryAgentPhase.INTAKE
        assert agent.thread_id == "repo_agent:%s" % agent.repo_agent_id

        started = await orchestrator.start_task(
            agent.repo_agent_id,
            "Prepare a safe demo implementation",
            ["Do not add auth", "Keep it backend-only"],
        )
        assert started.agent.phase == RepositoryAgentPhase.WAITING_APPROVAL
        assert started.next_turn is not None
        assert started.next_turn.type == TurnType.APPROVAL

        finished = await orchestrator.submit_user_response(
            started.next_turn.id,
            "approved",
            approved=True,
        )
        assert finished.agent.phase == RepositoryAgentPhase.DONE
        assert finished.agent.final_report
        assert finished.next_turn is None

        tasks = orchestrator.registry.list_task_agents(agent.repo_agent_id)
        assert len(tasks) == 4
        assert all(task.status == TaskAgentStatus.DEAD for task in tasks)
        assert (tmp_path / "memory" / ("%s.md" % agent.repo_agent_id)).exists()

    asyncio.run(scenario())


def test_orchestrator_explanations_do_not_stay_pending(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path)

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))

        first = await orchestrator.handle_user_message(agent.repo_agent_id, "what does this do")
        second = await orchestrator.handle_user_message(agent.repo_agent_id, "how does this work")

        assert first.agent.last_explanation is not None
        assert second.agent.last_explanation is not None
        assert first.next_turn is None
        assert second.next_turn is None
        assert await orchestrator.list_pending_turns() == []

    asyncio.run(scenario())


def test_modification_flow_treats_its_ok_as_step_approval(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path)

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.handle_user_message(
            agent.repo_agent_id,
            "fix this endpoint",
        )
        assert started.next_turn is not None
        assert started.next_turn.type == TurnType.BRANCH_PERMISSION

        branch_answer = await orchestrator.submit_user_response(
            started.next_turn.id,
            "no",
        )
        assert branch_answer.next_turn is not None
        assert branch_answer.next_turn.type == TurnType.PLAN_STEP_REVIEW

        reviewed = await orchestrator.submit_user_response(
            branch_answer.next_turn.id,
            "its ok",
        )
        assert reviewed.agent.plan_steps[0]["status"] == "APPROVED"

    asyncio.run(scenario())


def test_orchestrator_rejection_keeps_intake_lock(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "README.md").write_text("# demo\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path)

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.start_task(agent.repo_agent_id, "Make a risky change")
        rejected = await orchestrator.submit_user_response(
            started.next_turn.id,
            "Needs more constraints",
            approved=False,
        )
        assert rejected.agent.phase == RepositoryAgentPhase.INTAKE
        assert rejected.next_turn is not None
        assert rejected.next_turn.type == TurnType.INTAKE
        assert orchestrator.manager.scheduler.intake_lock_agent_id == agent.repo_agent_id

    asyncio.run(scenario())


def test_orchestrator_activate_repo_agent_is_idempotent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path)

    async def scenario():
        first_state, created_first = await orchestrator.activate_repo_agent(str(repo))
        second_state, created_second = await orchestrator.activate_repo_agent(str(repo))

        assert created_first is True
        assert created_second is False
        assert first_state.repo_agent_id == second_state.repo_agent_id
        assert first_state.repo_id == second_state.repo_id
        assert (tmp_path / "memory" / ("%s.md" % first_state.repo_agent_id)).exists()

    asyncio.run(scenario())


def _orchestrator(tmp_path):
    settings = Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )
    return JarvisOrchestrator.create(settings=settings, llm_client=FakeLLMClient())
