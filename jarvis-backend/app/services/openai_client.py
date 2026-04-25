from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Set

from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.models.repository import RepositoryAgentState
from app.models.task import TaskAgentState, TaskPlanItem


class TaskImplementationResult(BaseModel):
    result_summary: str
    proposed_patch: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)
    test_command: Optional[str] = None

    @field_validator("test_command", mode="before")
    @classmethod
    def _normalize_test_command(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        normalized = " ".join(value.strip().split())
        if not normalized:
            return None
        lowered = normalized.lower()
        non_command_markers = (
            "no tests",
            "not run",
            "none",
            "n/a",
            "inspection only",
            "skip",
            "skipped",
        )
        if any(marker in lowered for marker in non_command_markers):
            return None
        if normalized.endswith(".") and re.fullmatch(r"[A-Za-z0-9 ()/_-]+\.", normalized):
            return None
        return normalized


class LLMClient:
    def is_live(self) -> bool:
        return True

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

    async def revise_plan_step(
        self,
        state: RepositoryAgentState,
        current_step: TaskPlanItem,
        user_feedback: str,
        repo_context: str,
        memory_context: str,
    ) -> TaskPlanItem:
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

    def is_live(self) -> bool:
        return False

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
        goal = state.task_goal or "Execute approved repository task"
        return [
            TaskPlanItem(
                title="Inspect the current implementation",
                description=(
                    "Locate the files, endpoint handlers, and scoring flow involved in this request "
                    f"so we understand how `{goal}` fits into the current code."
                ),
                scope=[],
            ),
            TaskPlanItem(
                title="Design the alternative flow",
                description=(
                    "Define the new endpoint behavior, how the RAG-only path should work, "
                    "and what should stay compatible with the existing API."
                ),
                scope=[],
            ),
            TaskPlanItem(
                title="Implement the backend changes",
                description=(
                    "Update the relevant route, service, and supporting code to deliver the new "
                    "behavior without affecting the existing endpoint more than necessary."
                ),
                scope=[],
            ),
            TaskPlanItem(
                title="Validate the result",
                description=(
                    "Review changed files and run the most relevant checks we can execute for this repository."
                ),
                scope=[],
            ),
        ]

    async def revise_plan_step(
        self,
        state: RepositoryAgentState,
        current_step: TaskPlanItem,
        user_feedback: str,
        repo_context: str,
        memory_context: str,
    ) -> TaskPlanItem:
        revised_description = (
            f"{current_step.description} Revised with user feedback: {user_feedback.strip()}"
        ).strip()
        return TaskPlanItem(
            title=current_step.title,
            description=revised_description,
            scope=current_step.scope,
        )

    async def implement_task(
        self,
        repo_state: RepositoryAgentState,
        task_state: TaskAgentState,
        repo_context: str,
        memory_context: str,
    ) -> TaskImplementationResult:
        return TaskImplementationResult(
            result_summary=(
                "Offline demo mode completed the task planning, but it did not propose filesystem "
                "changes because no live coding model was available."
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
            "- Tests: %s\n"
            "- Execution mode: offline demo (no live patch generation)"
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

    def is_live(self) -> bool:
        return self._available

    def _require_live_agent(self) -> None:
        if self._available:
            return
        raise RuntimeError(
            "OpenAI Agents runtime is not available. "
            "Configure OPENAI_API_KEY and install the `agents` package with Python 3.9+."
        )

    async def extract_requirements(
        self,
        task_goal: str,
        acceptance_criteria: List[str],
        repo_context: str,
        memory_context: str,
    ) -> List[str]:
        self._require_live_agent()
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
        self._require_live_agent()
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
        self._require_live_agent()
        prompt = (
            "Turn this implementation request into 2 to 5 concrete reviewable steps as a JSON array.\n"
            "Each item must have title, description, and scope.\n"
            "Requirements:\n"
            "- Do not just paraphrase the user's request.\n"
            "- Do not quote or copy the user's original prompt verbatim in any step description.\n"
            "- Make each step specific to repository work.\n"
            "- Separate inspection/design work from implementation and validation.\n"
            "- Keep descriptions concise but actionable.\n"
            "State: %s\n"
            "Plan:\n%s"
        ) % (state.model_dump(mode="json"), plan)
        parsed = await self._run_json_agent(
            "Task splitter agent",
            prompt,
            "Return a JSON array of step objects.",
        )
        return _normalize_task_plan_items(parsed)

    async def revise_plan_step(
        self,
        state: RepositoryAgentState,
        current_step: TaskPlanItem,
        user_feedback: str,
        repo_context: str,
        memory_context: str,
    ) -> TaskPlanItem:
        self._require_live_agent()
        prompt = (
            "Rewrite this implementation step based on user feedback and return a JSON object "
            "with title, description, and scope.\n"
            "Keep the step reviewable and specific.\n"
            "Do not quote the user's original task verbatim.\n"
            "Current step: %s\n"
            "User feedback: %s\n"
            "Repo context:\n%s\n"
            "Memory:\n%s"
        ) % (
            current_step.model_dump(mode="json"),
            user_feedback,
            repo_context,
            memory_context,
        )
        parsed = await self._run_json_agent(
            "Plan revision agent",
            prompt,
            "Return a JSON object with title, description, and scope.",
        )
        items = _normalize_task_plan_items(parsed)
        if not items:
            raise RuntimeError("Plan revision agent did not return a usable plan step.")
        return items[0]

    async def implement_task(
        self,
        repo_state: RepositoryAgentState,
        task_state: TaskAgentState,
        repo_context: str,
        memory_context: str,
    ) -> TaskImplementationResult:
        prompt = (
            "Propose implementation output as JSON with result_summary, proposed_patch, changed_files, test_command.\n"
            "This is a real repository modification flow, not an analysis-only flow.\n"
            "If code changes are needed, `proposed_patch` must be a raw unified git diff string.\n"
            "Do not wrap the patch in markdown fences.\n"
            "Do not add commentary before or after the diff.\n"
            "For MODIFY_CODE tasks, do not set `proposed_patch` to null unless the repository already fully satisfies the request.\n"
            "`test_command` must be either null or a real shell command that can be executed from the repository root.\n"
            "Never use explanatory prose in `test_command`.\n"
            "Only include patches inside scope. Task: %s\nRepo context:\n%s\nMemory:\n%s"
        ) % (task_state.model_dump(mode="json"), repo_context, memory_context)
        parsed = await self._run_json_agent(
            "Task implementation agent",
            prompt,
            "Return a JSON object matching TaskImplementationResult.",
        )
        return TaskImplementationResult.model_validate(parsed)

    async def final_report(
        self,
        repo_state: RepositoryAgentState,
        task_states: List[TaskAgentState],
    ) -> str:
        self._require_live_agent()
        prompt = (
            "Create a concise final report for the user.\nState: %s\nTasks: %s"
        ) % (
            repo_state.model_dump(mode="json"),
            [task.model_dump(mode="json") for task in task_states],
        )
        return await self._run_agent("Final report agent", prompt)

    async def _run_agent(self, name: str, prompt: str) -> str:
        self._require_live_agent()
        agent = self._agent_cls(  # type: ignore[misc]
            name=name,
            model=self.settings.openai_model,
            instructions="You are a backend coding assistant for a local repository orchestration demo.",
        )
        result = await self._runner_cls.run(agent, prompt)  # type: ignore[union-attr]
        return str(result.final_output)

    async def _run_json_agent(self, name: str, prompt: str, shape_hint: str) -> Any:
        raw_output = await self._run_agent(name, prompt)
        parsed = _extract_json_payload(raw_output)
        if parsed is not None:
            return parsed

        repair_prompt = (
            "Convert the following model output into strict JSON only.\n"
            "%s\n"
            "Do not add markdown fences or commentary.\n"
            "Original output:\n%s"
        ) % (shape_hint, raw_output)
        repaired_output = await self._run_agent(f"{name} JSON repair", repair_prompt)
        repaired = _extract_json_payload(repaired_output)
        if repaired is not None:
            return repaired
        raise RuntimeError("%s did not return valid JSON output." % name)


def _extract_json_payload(raw_output: str) -> Optional[Any]:
    candidates = [raw_output.strip()]

    fenced_json = re.findall(r"```(?:json)?\s*(.*?)```", raw_output, flags=re.DOTALL)
    candidates.extend(item.strip() for item in fenced_json if item.strip())

    array_match = re.search(r"(\[\s*[\s\S]*\])", raw_output)
    if array_match:
        candidates.append(array_match.group(1).strip())

    object_match = re.search(r"(\{\s*[\s\S]*\})", raw_output)
    if object_match:
        candidates.append(object_match.group(1).strip())

    seen: Set[str] = set()
    for candidate in candidates:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            return json.loads(candidate)
        except Exception:
            continue
    return None


def _normalize_task_plan_items(parsed: Any) -> List[TaskPlanItem]:
    raw_items = _unwrap_task_plan_payload(parsed)
    plan_items: List[TaskPlanItem] = []
    for index, item in enumerate(raw_items):
        normalized = _coerce_task_plan_item(item, index)
        if normalized is None:
            continue
        plan_items.append(TaskPlanItem.model_validate(normalized))
    if not plan_items:
        raise RuntimeError("Planning agent did not return any usable plan steps.")
    return plan_items


def _unwrap_task_plan_payload(parsed: Any) -> List[Any]:
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for key in ("steps", "plan_steps", "items", "tasks", "plan", "result", "data"):
            value = parsed.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict):
                if any(
                    field in value
                    for field in ("title", "description", "name", "details", "step")
                ):
                    return [value]
                nested = _unwrap_task_plan_payload(value)
                if nested and nested != [value]:
                    return nested
        return [parsed]
    return [parsed]


def _coerce_task_plan_item(item: Any, index: int) -> Optional[dict]:
    if isinstance(item, TaskPlanItem):
        return item.model_dump(mode="python")

    if isinstance(item, str):
        description = item.strip()
        if not description:
            return None
        return {
            "title": "Implementation step %s" % (index + 1),
            "description": description,
            "scope": [],
        }

    if isinstance(item, list):
        flattened = " ".join(str(part).strip() for part in item if str(part).strip())
        if not flattened:
            return None
        return {
            "title": "Implementation step %s" % (index + 1),
            "description": flattened,
            "scope": [],
        }

    if not isinstance(item, dict):
        return {
            "title": "Implementation step %s" % (index + 1),
            "description": str(item).strip(),
            "scope": [],
        }

    nested_step = _first_present(
        item,
        ["step", "item", "task", "plan_step", "payload"],
    )
    if isinstance(nested_step, dict):
        merged = dict(nested_step)
        for key, value in item.items():
            merged.setdefault(key, value)
        item = merged

    title = _first_text(
        item,
        ["title", "name", "step", "summary", "label"],
    ) or "Implementation step %s" % (index + 1)
    description = _first_text(
        item,
        [
            "description",
            "details",
            "content",
            "objective",
            "reasoning",
            "summary",
            "body",
            "instruction",
            "task",
            "title",
        ],
    ) or title
    scope = _first_present(
        item,
        ["scope", "scopes", "paths", "files", "modules", "directories", "areas", "targets"],
    )

    return {
        "title": title,
        "description": description,
        "scope": scope or [],
    }


def _first_text(payload: dict, keys: List[str]) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if value is None:
            continue
        if isinstance(value, str) and value.strip():
            return value.strip()
        if not isinstance(value, (dict, list, tuple, set)):
            text = str(value).strip()
            if text:
                return text
    return None


def _first_present(payload: dict, keys: List[str]) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return None
