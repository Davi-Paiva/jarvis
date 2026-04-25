from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.models.state import RepositoryAgentPhase, TaskAgentStatus
from app.models.turns import TurnType
from app.services.openai_client import FakeLLMClient, TaskImplementationResult
from app.services.orchestrator import JarvisOrchestrator


class LiveNoPatchLLM(FakeLLMClient):
    def is_live(self) -> bool:
        return True

    async def implement_task(
        self,
        repo_state,
        task_state,
        repo_context,
        memory_context,
    ) -> TaskImplementationResult:
        return TaskImplementationResult(result_summary="Reviewed repository without patch.")


class LiveUsesRepoStructureBeforeAskingLLM(FakeLLMClient):
    def __init__(self):
        self.repo_contexts = []
        self.calls = 0

    def is_live(self) -> bool:
        return True

    async def split_tasks(self, state, plan):
        from app.models.task import TaskPlanItem

        return [
            TaskPlanItem(
                title="Add the wallet link action",
                description="Update the frontend user options menu to add a link-wallet action.",
                scope=["src"],
            )
        ]

    async def implement_task(
        self,
        repo_state,
        task_state,
        repo_context,
        memory_context,
    ) -> TaskImplementationResult:
        self.calls += 1
        self.repo_contexts.append(repo_context)
        if self.calls == 1:
            return TaskImplementationResult(
                result_summary="I need to inspect the exact menu component before editing.",
                needed_files=["src/menu.tsx"],
            )
        return TaskImplementationResult(
            result_summary="I could not identify the exact frontend component that owns the user options menu, so I could not apply a safe patch.",
        )


class LiveCapturesScopeFallbackLLM(FakeLLMClient):
    def __init__(self):
        self.repo_contexts = []

    def is_live(self) -> bool:
        return True

    async def split_tasks(self, state, plan):
        from app.models.task import TaskPlanItem

        return [
            TaskPlanItem(
                title="Update the dashboard page",
                description="Adjust the dashboard page and shared layout.",
                scope=["frontend/pages-that-do-not-exist"],
            )
        ]

    async def implement_task(
        self,
        repo_state,
        task_state,
        repo_context,
        memory_context,
    ) -> TaskImplementationResult:
        self.repo_contexts.append(repo_context)
        return TaskImplementationResult(result_summary="Reviewed fallback context without patch.")


class LiveRetriesUpToFiveLLM(FakeLLMClient):
    def __init__(self):
        self.calls = 0
        self.repo_contexts = []

    def is_live(self) -> bool:
        return True

    async def split_tasks(self, state, plan):
        from app.models.task import TaskPlanItem

        return [
            TaskPlanItem(
                title="Update the homepage hero",
                description="Add a short line in the hero area.",
                scope=["src"],
            )
        ]

    async def implement_task(
        self,
        repo_state,
        task_state,
        repo_context,
        memory_context,
    ) -> TaskImplementationResult:
        self.calls += 1
        self.repo_contexts.append(repo_context)
        return TaskImplementationResult(
            result_summary="Still need another file before editing.",
            needed_files=["src/file%s.tsx" % self.calls],
        )


class BrokenPlanningLLM(FakeLLMClient):
    async def split_tasks(self, state, plan):
        return [{"title": "Inspect", "description": "Review the repo", "scope": "Repository inspection"}]


class BrokenPlanRevisionLLM(FakeLLMClient):
    async def revise_plan_step(
        self,
        state,
        current_step,
        user_feedback,
        repo_context,
        memory_context,
    ):
        return {"title": None, "description": {"unexpected": "shape"}, "scope": {"label": "Repository inspection"}}


class ExplodingPlanningLLM(FakeLLMClient):
    async def split_tasks(self, state, plan):
        raise RuntimeError("planner returned unusable scope payload")


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


def test_live_modification_flow_fails_without_extra_question_when_no_code_changes_are_proposed(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path, llm_client=LiveNoPatchLLM())

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.handle_user_message(
            agent.repo_agent_id,
            "implement a websocket endpoint",
        )
        branch_answer = await orchestrator.submit_user_response(started.next_turn.id, "no")

        turn = branch_answer.next_turn
        while turn is not None and turn.type == TurnType.PLAN_STEP_REVIEW:
            reviewed = await orchestrator.submit_user_response(turn.id, "yes")
            turn = reviewed.next_turn

        assert turn is not None
        assert turn.type == TurnType.EXECUTION_APPROVAL

        finished = await orchestrator.submit_user_response(turn.id, "yes")
        assert finished.agent.phase == RepositoryAgentPhase.FAILED
        assert finished.next_turn is None
        assert "did not produce any code changes" in (finished.agent.last_error or "").lower()

    asyncio.run(scenario())

def test_live_flow_retries_with_requested_file_contents(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "menu.tsx").write_text("export const menu = [];\n", encoding="utf-8")
    llm = LiveUsesRepoStructureBeforeAskingLLM()
    orchestrator = _orchestrator(tmp_path, llm_client=llm)

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.handle_user_message(
            agent.repo_agent_id,
            "add a link wallet action to the user options menu",
        )
        branch_answer = await orchestrator.submit_user_response(started.next_turn.id, "no")

        turn = branch_answer.next_turn
        while turn is not None and turn.type == TurnType.PLAN_STEP_REVIEW:
            reviewed = await orchestrator.submit_user_response(turn.id, "yes")
            turn = reviewed.next_turn

        assert turn is not None
        assert turn.type == TurnType.EXECUTION_APPROVAL

        finished = await orchestrator.submit_user_response(turn.id, "yes")
        assert finished.agent.phase == RepositoryAgentPhase.FAILED
        assert finished.next_turn is None
        assert len(llm.repo_contexts) == 2
        assert "Execution attempt: 1/5" in llm.repo_contexts[0]
        assert "Execution attempt: 2/5" in llm.repo_contexts[1]
        assert "Repository tree:" in llm.repo_contexts[0]
        assert "Requested file contents:" in llm.repo_contexts[1]
        assert "File: src/menu.tsx" in llm.repo_contexts[1]
        assert "linkWallet" not in (repo / "src" / "menu.tsx").read_text(encoding="utf-8")

    asyncio.run(scenario())


def test_live_flow_falls_back_to_repo_wide_context_when_scope_matches_no_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "App.tsx").write_text("export default function App() { return null; }\n", encoding="utf-8")
    (repo / "src" / "layout.tsx").write_text("export const Layout = () => null;\n", encoding="utf-8")
    llm = LiveCapturesScopeFallbackLLM()
    orchestrator = _orchestrator(tmp_path, llm_client=llm)

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.handle_user_message(
            agent.repo_agent_id,
            "update the dashboard page",
        )
        branch_answer = await orchestrator.submit_user_response(started.next_turn.id, "no")

        turn = branch_answer.next_turn
        while turn is not None and turn.type == TurnType.PLAN_STEP_REVIEW:
            reviewed = await orchestrator.submit_user_response(turn.id, "yes")
            turn = reviewed.next_turn

        assert turn is not None
        assert turn.type == TurnType.EXECUTION_APPROVAL

        finished = await orchestrator.submit_user_response(turn.id, "yes")
        assert finished.agent.phase == RepositoryAgentPhase.FAILED
        assert len(llm.repo_contexts) == 1
        assert "Scope fallback:" in llm.repo_contexts[0]
        assert "- src/App.tsx" in llm.repo_contexts[0]
        assert "Repository tree:" in llm.repo_contexts[0]
        assert "- src/" in llm.repo_contexts[0]

    asyncio.run(scenario())


def test_live_flow_stops_after_five_internal_retries(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    for index in range(1, 6):
        (repo / "src" / ("file%s.tsx" % index)).write_text(
            "export const File%s = null;\n" % index,
            encoding="utf-8",
        )
    llm = LiveRetriesUpToFiveLLM()
    orchestrator = _orchestrator(tmp_path, llm_client=llm)

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.handle_user_message(
            agent.repo_agent_id,
            "update the homepage hero",
        )
        branch_answer = await orchestrator.submit_user_response(started.next_turn.id, "no")

        turn = branch_answer.next_turn
        while turn is not None and turn.type == TurnType.PLAN_STEP_REVIEW:
            reviewed = await orchestrator.submit_user_response(turn.id, "yes")
            turn = reviewed.next_turn

        assert turn is not None
        assert turn.type == TurnType.EXECUTION_APPROVAL

        finished = await orchestrator.submit_user_response(turn.id, "yes")
        assert finished.agent.phase == RepositoryAgentPhase.FAILED
        assert llm.calls == 5
        assert "Execution attempt: 5/5" in llm.repo_contexts[-1]

    asyncio.run(scenario())


def test_modification_flow_normalizes_non_list_scope_from_planner(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path, llm_client=BrokenPlanningLLM())

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.handle_user_message(agent.repo_agent_id, "add a websocket endpoint")
        planned = await orchestrator.submit_user_response(started.next_turn.id, "no")

        assert planned.agent.phase == RepositoryAgentPhase.PLAN_STEP_REVIEW
        assert planned.agent.plan_steps[0]["scope"] == []
        assert planned.next_turn is not None
        assert planned.next_turn.type == TurnType.PLAN_STEP_REVIEW

    asyncio.run(scenario())


def test_modification_flow_fails_gracefully_when_revised_step_is_invalid(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path, llm_client=BrokenPlanRevisionLLM())

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.handle_user_message(agent.repo_agent_id, "add a websocket endpoint")
        branch_answer = await orchestrator.submit_user_response(started.next_turn.id, "no")
        assert branch_answer.next_turn is not None

        revised = await orchestrator.submit_user_response(branch_answer.next_turn.id, "change it")

        assert revised.agent.phase == RepositoryAgentPhase.PLAN_STEP_REVIEW
        assert revised.agent.plan_steps[0]["title"] == ""
        assert revised.agent.plan_steps[0]["description"] == "{'unexpected': 'shape'}"
        assert revised.agent.plan_steps[0]["scope"] == []
        assert revised.next_turn is not None
        assert revised.next_turn.type == TurnType.PLAN_STEP_REVIEW

    asyncio.run(scenario())


def test_modification_flow_reports_planning_failure_without_crashing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("print('hello')\n", encoding="utf-8")
    orchestrator = _orchestrator(tmp_path, llm_client=ExplodingPlanningLLM())

    async def scenario():
        agent = await orchestrator.create_repo_agent(str(repo))
        started = await orchestrator.handle_user_message(agent.repo_agent_id, "add a websocket endpoint")
        planned = await orchestrator.submit_user_response(started.next_turn.id, "no")

        assert planned.agent.phase == RepositoryAgentPhase.FAILED
        assert "planner returned unusable scope payload" in (planned.agent.last_error or "")
        assert planned.next_turn is None
        pending_turns = await orchestrator.list_pending_turns()
        assert pending_turns == []

    asyncio.run(scenario())


def _orchestrator(tmp_path, llm_client=None):
    settings = Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )
    return JarvisOrchestrator.create(settings=settings, llm_client=llm_client or FakeLLMClient())
