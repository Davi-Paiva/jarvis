from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import List, Optional

from pydantic import BaseModel, Field

from app.config import Settings
from app.models.repository import RepositoryAgentState
from app.models.schemas import AnalyzeLineExplanation, AnalyzeOutput
from app.models.task import TaskAgentState, TaskPlanItem


@dataclass
class ParsedChangedLine:
    line_number: int
    added_text: str = ""
    removed_text: str = ""


class TaskImplementationResult(BaseModel):
    result_summary: str
    proposed_patch: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)
    test_command: Optional[str] = None


class LLMClient:
    async def explain_file_change(
        self,
        file_name: str,
        content: str,
        diff: str,
    ) -> AnalyzeOutput:
        raise NotImplementedError

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

    async def explain_file_change(
        self,
        file_name: str,
        content: str,
        diff: str,
    ) -> AnalyzeOutput:
        added_lines, removed_lines = self._split_diff_lines(diff)
        added_examples = self._collect_examples(added_lines)
        removed_examples = self._collect_examples(removed_lines)
        focus = self._infer_change_focus(file_name, added_lines + removed_lines)
        reason = self._infer_change_reason(added_lines + removed_lines)
        impact = self._infer_impact(focus, reason)
        change_text = self._describe_change(added_examples, removed_examples)
        line_explanations = self._build_line_explanations(diff, reason)

        return AnalyzeOutput(
            summary=(
                f"{file_name} changes {focus} by {change_text}. "
                f"This update {reason}."
            ),
            steps=[
                f"What changed: {change_text}.",
                f"Why: {reason}.",
                f"Impact: {impact}.",
            ],
            lineExplanations=line_explanations,
        )

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

    def _split_diff_lines(self, diff: str) -> tuple[List[str], List[str]]:
        added_lines: List[str] = []
        removed_lines: List[str] = []
        ignored_prefixes = (
            "diff --git ",
            "index ",
            "@@",
            "--- ",
            "+++ ",
            "new file mode ",
            "deleted file mode ",
            "similarity index ",
            "rename from ",
            "rename to ",
        )
        for raw_line in diff.splitlines():
            if raw_line.startswith(ignored_prefixes):
                continue
            if raw_line.startswith("+"):
                added_lines.append(raw_line[1:].strip())
            elif raw_line.startswith("-"):
                removed_lines.append(raw_line[1:].strip())
        return added_lines, removed_lines

    def _collect_examples(self, lines: List[str], limit: int = 2) -> List[str]:
        examples: List[str] = []
        for line in lines:
            if not line or line in {"{", "}", "(", ")", "[", "]"}:
                continue
            if line not in examples:
                examples.append(line if len(line) <= 80 else line[:77] + "...")
            if len(examples) == limit:
                break
        return examples

    def _describe_change(
        self,
        added_examples: List[str],
        removed_examples: List[str],
    ) -> str:
        if added_examples and removed_examples:
            return (
                f"replacing {self._join_examples(removed_examples)} "
                f"with {self._join_examples(added_examples)}"
            )
        if added_examples:
            return f"adding {self._join_examples(added_examples)}"
        if removed_examples:
            return f"removing {self._join_examples(removed_examples)}"
        return "updating the file contents"

    def _build_line_explanations(
        self,
        diff: str,
        reason: str,
    ) -> List[AnalyzeLineExplanation]:
        return [
            AnalyzeLineExplanation(
                lineNumber=changed_line.line_number,
                summary=self._build_line_summary(changed_line, reason),
            )
            for changed_line in self._parse_changed_lines(diff)
        ]

    def _parse_changed_lines(self, diff: str) -> List[ParsedChangedLine]:
        changes: List[ParsedChangedLine] = []
        current_new_line: Optional[int] = None
        pending_removed: List[str] = []
        pending_removed_anchor: Optional[int] = None
        active_removed_context: List[str] = []

        def flush_deletions() -> None:
            nonlocal pending_removed, pending_removed_anchor, active_removed_context
            if pending_removed:
                changes.append(
                    ParsedChangedLine(
                        line_number=max(1, pending_removed_anchor or 1),
                        removed_text=" / ".join(item for item in pending_removed if item),
                    )
                )
                pending_removed = []
                pending_removed_anchor = None
            active_removed_context = []

        for raw_line in diff.splitlines():
            hunk_match = HUNK_HEADER_REGEX.match(raw_line)
            if hunk_match is not None:
                flush_deletions()
                current_new_line = int(hunk_match.group(1))
                continue

            if raw_line.startswith(IGNORED_DIFF_PREFIXES):
                continue

            if current_new_line is None:
                continue

            if raw_line.startswith(" "):
                flush_deletions()
                current_new_line += 1
                continue

            if raw_line.startswith("-"):
                if pending_removed_anchor is None:
                    pending_removed_anchor = max(1, current_new_line)
                pending_removed.append(raw_line[1:].strip())
                continue

            if raw_line.startswith("+"):
                if pending_removed:
                    active_removed_context = pending_removed.copy()
                    pending_removed = []
                    pending_removed_anchor = None

                changes.append(
                    ParsedChangedLine(
                        line_number=max(1, current_new_line),
                        added_text=raw_line[1:].strip(),
                        removed_text=" / ".join(item for item in active_removed_context if item),
                    )
                )
                current_new_line += 1

        flush_deletions()
        return changes

    def _build_line_summary(self, changed_line: ParsedChangedLine, reason: str) -> str:
        if changed_line.added_text and changed_line.removed_text:
            return (
                f"Replaces `{self._shorten_text(changed_line.removed_text)}` with "
                f"`{self._shorten_text(changed_line.added_text)}`. This change {reason}."
            )
        if changed_line.added_text:
            return (
                f"Adds `{self._shorten_text(changed_line.added_text)}`. "
                f"This change {reason}."
            )
        return (
            f"Removes `{self._shorten_text(changed_line.removed_text)}`. "
            f"This change {reason}."
        )

    def _join_examples(self, examples: List[str]) -> str:
        if len(examples) == 1:
            return f"`{examples[0]}`"
        return ", ".join(f"`{example}`" for example in examples)

    def _shorten_text(self, value: str, max_length: int = 90) -> str:
        return value if len(value) <= max_length else value[: max_length - 3] + "..."

    def _infer_change_focus(self, file_name: str, lines: List[str]) -> str:
        hints = f"{file_name}\n" + "\n".join(lines).lower()
        if any(token in hints for token in ("http", "request", "response", "http_1_1")):
            return "HTTP request handling"
        if any(token in hints for token in ("git diff", "git ls-files", "untracked", "changed file")):
            return "git change detection"
        if any(token in hints for token in ("test_", "assert ", "expect(")):
            return "test coverage"
        if any(token in hints for token in ("schema", "basemodel", "pydantic", "field(")):
            return "the request and response contract"
        if any(token in hints for token in ("router", "endpoint", "apirouter", "post(")):
            return "API behavior"
        return "the file's implementation"

    def _infer_change_reason(self, lines: List[str]) -> str:
        hints = "\n".join(lines).lower()
        if any(token in hints for token in ("http_1_1", "content-type", "timeout", "localhost")):
            return "forces the client to use a compatible HTTP transport for backend requests"
        if any(token in hints for token in ("git diff", "git ls-files", "untracked", "changed file")):
            return "broadens the set of repository changes that Jarvis can analyze"
        if any(token in hints for token in ("schema", "basemodel", "pydantic", "field(")):
            return "updates the request payload or response shape used by the backend"
        if any(token in hints for token in ("assert ", "test_", "expect(")):
            return "locks the changed behavior in with a regression test"
        if any(token in hints for token in ("router", "endpoint", "apirouter", "post(")):
            return "changes how the API endpoint handles requests"
        return "updates the implementation to match the new behavior"

    def _infer_impact(self, focus: str, reason: str) -> str:
        if focus == "HTTP request handling":
            return "backend analyze requests now use the expected transport behavior"
        if focus == "git change detection":
            return "new and modified files are surfaced together for analysis"
        if focus == "test coverage":
            return "future regressions in this path are easier to catch"
        if focus == "the request and response contract":
            return "the plugin and backend can exchange the new fields consistently"
        if focus == "API behavior":
            return "the endpoint behavior now matches the updated contract"
        return reason[0].upper() + reason[1:]


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

    async def explain_file_change(
        self,
        file_name: str,
        content: str,
        diff: str,
    ) -> AnalyzeOutput:
        if not self._available:
            return await super().explain_file_change(file_name, content, diff)
        prompt = (
            "Explain the code change as strict JSON with keys summary, steps, and lineExplanations.\n"
            "Rules:\n"
            "- summary must be 1 to 2 sentences about what changed and why.\n"
            "- steps must be an array of exactly 3 strings in this order: What changed, Why, Impact.\n"
            "- lineExplanations must be an array of objects with lineNumber and summary.\n"
            "- Each lineExplanations summary must briefly explain the concrete line change and why it was made.\n"
            "- Include one entry for every changed line on the new side of the diff. For deletion-only hunks, use the destination line number from the hunk header.\n"
            "- Do not use hedging words such as likely, probably, maybe, appears, or seems.\n"
            "- Base the explanation only on the provided diff and current file content.\n"
            "- Be concrete about the change.\n\n"
            "File: %s\n\n"
            "Diff:\n%s\n\n"
            "Current file content:\n%s"
        ) % (
            file_name,
            self._trim_for_prompt(diff),
            self._trim_for_prompt(content),
        )
        output = await self._run_agent("Code change explainer", prompt)
        try:
            parsed = AnalyzeOutput.model_validate(json.loads(output))
            if parsed.lineExplanations:
                return parsed
        except Exception:
            match = re.search(r"\{.*\}", output, re.DOTALL)
            if match is not None:
                try:
                    parsed = AnalyzeOutput.model_validate(json.loads(match.group(0)))
                    if parsed.lineExplanations:
                        return parsed
                except Exception:
                    pass
            return await super().explain_file_change(file_name, content, diff)
        return await super().explain_file_change(file_name, content, diff)

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

    def _trim_for_prompt(self, text: str, max_chars: int = 12000) -> str:
        if len(text) <= max_chars:
            return text
        return text[:max_chars] + "\n...<truncated>"


IGNORED_DIFF_PREFIXES = (
    "diff --git ",
    "index ",
    "--- ",
    "+++ ",
    "new file mode ",
    "deleted file mode ",
    "similarity index ",
    "rename from ",
    "rename to ",
)
HUNK_HEADER_REGEX = re.compile(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")

