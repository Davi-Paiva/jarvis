from __future__ import annotations

import json
from typing import List, Optional

from pydantic import BaseModel, Field

from app.config import Settings
from app.models.repository import RepositoryAgentState
from app.models.task import TaskAgentState, TaskPlanItem


class TaskImplementationResult(BaseModel):
    result_summary: str
    proposed_patch: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)
    test_command: Optional[str] = None


class LLMClient:
    async def extract_requirements(
        self,
        task_goal: str,
        acceptance_criteria: List[str],
        repo_context: str,
        memory_context: str,
    ) -> List[str]:
        raise NotImplementedError

    async def create_plan(
        self,
        state: RepositoryAgentState,
        repo_context: str,
        memory_context: str,
    ) -> str:
        raise NotImplementedError

    async def split_tasks(
        self,
        state: RepositoryAgentState,
        plan: str,
    ) -> List[TaskPlanItem]:
        raise NotImplementedError

    async def implement_task(
        self,
        repo_state: RepositoryAgentState,
        task_state: TaskAgentState,
        repo_context: str,
        memory_context: str,
    ) -> TaskImplementationResult:
        raise NotImplementedError

    async def final_report(
        self,
        repo_state: RepositoryAgentState,
        task_states: List[TaskAgentState],
    ) -> str:
        raise NotImplementedError


class FakeLLMClient(LLMClient):
    """Deterministic LLM substitute for tests and offline hackathon demos."""

    async def extract_requirements(
        self,
        task_goal: str,
        acceptance_criteria: List[str],
        repo_context: str,
        memory_context: str,
    ) -> List[str]:
        if acceptance_criteria:
            return acceptance_criteria
        return ["Understand the repository context", "Implement the requested goal safely"]

    async def create_plan(
        self,
        state: RepositoryAgentState,
        repo_context: str,
        memory_context: str,
    ) -> str:
        goal = state.task_goal or "No task goal provided"
        criteria = "\n".join("- %s" % item for item in state.acceptance_criteria) or "- Demo-safe completion"
        return (
            "Goal: %s\n\n"
            "Acceptance criteria:\n%s\n\n"
            "Plan:\n"
            "1. Inspect relevant repository files.\n"
            "2. Create scoped task agents for the work.\n"
            "3. Apply only approved, scoped changes through LocalExecutor.\n"
            "4. Run allowed validation commands when requested.\n"
            "5. Produce a final report."
        ) % (goal, criteria)

    async def split_tasks(
        self,
        state: RepositoryAgentState,
        plan: str,
    ) -> List[TaskPlanItem]:
        return [
            TaskPlanItem(
                title="Repository inspection and implementation",
                description=state.task_goal or "Execute approved repository task",
                scope=[],
            )
        ]

    async def implement_task(
        self,
        repo_state: RepositoryAgentState,
        task_state: TaskAgentState,
        repo_context: str,
        memory_context: str,
    ) -> TaskImplementationResult:
        return TaskImplementationResult(
            result_summary=(
                "Offline demo task completed. No filesystem mutations were proposed by FakeLLMClient."
            )
        )

    async def final_report(
        self,
        repo_state: RepositoryAgentState,
        task_states: List[TaskAgentState],
    ) -> str:
        completed = [task for task in task_states if task.result_summary]
        return (
            "Task finished for `%s`.\n\n"
            "- Subtasks completed: %s\n"
            "- Changed files: %s\n"
            "- Tests: %s"
        ) % (
            repo_state.repo_path,
            len(completed),
            ", ".join(repo_state.changed_files) or "none",
            ", ".join(repo_state.test_results) or "not run",
        )


class OpenAIAgentsClient(FakeLLMClient):
    """OpenAI Agents SDK adapter with deterministic fallback behavior.

    The class keeps the rest of the backend independent from a concrete SDK.
    If the SDK is not installed or no key is configured, it behaves like
    FakeLLMClient so tests remain local and stable.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        try:
            from agents import Agent, Runner  # type: ignore

            self._agent_cls = Agent
            self._runner_cls = Runner
            self._available = bool(settings.openai_api_key)
        except Exception:
            self._agent_cls = None
            self._runner_cls = None
            self._available = False

    async def extract_requirements(
        self,
        task_goal: str,
        acceptance_criteria: List[str],
        repo_context: str,
        memory_context: str,
    ) -> List[str]:
        if not self._available:
            return await super().extract_requirements(
                task_goal, acceptance_criteria, repo_context, memory_context
            )
        prompt = (
            "Extract concise engineering requirements as a JSON array of strings.\n"
            "Goal: %s\nAcceptance criteria: %s\nRepo context:\n%s\nMemory:\n%s"
        ) % (task_goal, acceptance_criteria, repo_context, memory_context)
        output = await self._run_agent("Repository intake agent", prompt)
        try:
            parsed = json.loads(output)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except Exception:
            pass
        return [line.strip("- ").strip() for line in output.splitlines() if line.strip()]

    async def create_plan(
        self,
        state: RepositoryAgentState,
        repo_context: str,
        memory_context: str,
    ) -> str:
        if not self._available:
            return await super().create_plan(state, repo_context, memory_context)
        prompt = (
            "Create a concise implementation plan. Do not include auth or production-only work.\n"
            "State: %s\nRepo context:\n%s\nMemory:\n%s"
        ) % (state.model_dump(mode="json"), repo_context, memory_context)
        return await self._run_agent("Repository planning agent", prompt)

    async def split_tasks(
        self,
        state: RepositoryAgentState,
        plan: str,
    ) -> List[TaskPlanItem]:
        if not self._available:
            return await super().split_tasks(state, plan)
        prompt = (
            "Split this plan into a JSON array of objects with title, description, scope.\n"
            "Plan:\n%s"
        ) % plan
        output = await self._run_agent("Task splitter agent", prompt)
        try:
            parsed = json.loads(output)
            return [TaskPlanItem.model_validate(item) for item in parsed]
        except Exception:
            return await super().split_tasks(state, plan)

    async def implement_task(
        self,
        repo_state: RepositoryAgentState,
        task_state: TaskAgentState,
        repo_context: str,
        memory_context: str,
    ) -> TaskImplementationResult:
        if not self._available:
            return await super().implement_task(repo_state, task_state, repo_context, memory_context)
        prompt = (
            "Propose implementation output as JSON with result_summary, proposed_patch, changed_files, test_command.\n"
            "Only include patches inside scope. Task: %s\nRepo context:\n%s\nMemory:\n%s"
        ) % (task_state.model_dump(mode="json"), repo_context, memory_context)
        output = await self._run_agent("Task implementation agent", prompt)
        try:
            return TaskImplementationResult.model_validate(json.loads(output))
        except Exception:
            return TaskImplementationResult(result_summary=output)

    async def final_report(
        self,
        repo_state: RepositoryAgentState,
        task_states: List[TaskAgentState],
    ) -> str:
        if not self._available:
            return await super().final_report(repo_state, task_states)
        prompt = (
            "Create a concise final report for the user.\nState: %s\nTasks: %s"
        ) % (
            repo_state.model_dump(mode="json"),
            [task.model_dump(mode="json") for task in task_states],
        )
        return await self._run_agent("Final report agent", prompt)

    async def _run_agent(self, name: str, prompt: str) -> str:
        agent = self._agent_cls(  # type: ignore[misc]
            name=name,
            model=self.settings.openai_model,
            instructions="You are a backend coding assistant for a local repository orchestration demo.",
        )
        result = await self._runner_cls.run(agent, prompt)  # type: ignore[union-attr]
        return str(result.final_output)

