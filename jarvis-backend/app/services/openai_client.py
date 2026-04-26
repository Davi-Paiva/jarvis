from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, Field, field_validator

from app.config import Settings
from app.models.repository import RepositoryAgentState
from app.models.task import TaskAgentState, TaskPlanItem


class TaskImplementationResult(BaseModel):
    result_summary: str
    proposed_patch: Optional[str] = None
    replacement_files: Dict[str, Optional[str]] = Field(default_factory=dict)
    changed_files: List[str] = Field(default_factory=list)
    needed_files: List[str] = Field(default_factory=list)
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

    @field_validator("needed_files", mode="before")
    @classmethod
    def _normalize_needed_files(cls, value: Optional[Any]) -> List[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return _dedupe_strings(re.split(r"[\n,]+", value))
        if isinstance(value, (list, tuple, set)):
            return _dedupe_strings(str(item) for item in value)
        return []

    @field_validator("replacement_files", mode="before")
    @classmethod
    def _normalize_replacement_files(cls, value: Optional[Any]) -> Dict[str, Optional[str]]:
        if value is None:
            return {}
        if isinstance(value, dict):
            normalized: Dict[str, Optional[str]] = {}
            for raw_path, raw_content in value.items():
                path = str(raw_path).strip()
                if not path:
                    continue
                normalized[path] = None if raw_content is None else str(raw_content)
            return normalized
        if isinstance(value, (list, tuple)):
            normalized: Dict[str, Optional[str]] = {}
            for item in value:
                if not isinstance(item, dict):
                    continue
                path = str(item.get("path", "")).strip()
                if not path:
                    continue
                normalized[path] = None if item.get("content") is None else str(item.get("content"))
            return normalized
        return {}


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

    async def classify_user_intent(
        self,
        user_message: str,
        current_step: TaskPlanItem,
    ) -> str:
        """Classify if user intent is 'QUESTION' or 'REVISION'."""
        raise NotImplementedError

    async def discuss_plan_step(
        self,
        state: RepositoryAgentState,
        current_step: TaskPlanItem,
        user_question: str,
        repo_context: str,
        memory_context: str,
    ) -> str:
        """Answer user questions about a plan step conversationally."""
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
        return (
            "I'll review the current code, make the necessary changes for %s, "
            "and validate everything works as expected."
        ) % goal

    async def split_tasks(
        self,
        state: RepositoryAgentState,
        plan: str,
    ) -> List[TaskPlanItem]:
        goal = state.task_goal or "Execute approved repository task"
        return [
            TaskPlanItem(
                title="Implement changes",
                description=f"I'll make the code changes for {goal} and verify they work",
                scope=[],
            ),
        ]

    async def classify_user_intent(
        self,
        user_message: str,
        current_step: TaskPlanItem,
    ) -> str:
        """Classify if user intent is 'QUESTION' or 'REVISION'."""
        # Simple heuristic classification for demo mode
        question_indicators = [
            "what", "why", "how", "which", "when", "where", "who",
            "explain", "tell me", "can you", "could you", "would you",
            "?", "clarify", "understand", "mean", "about"
        ]
        revision_indicators = [
            "change", "modify", "update", "use", "instead", "add", "remove",
            "replace", "don't", "shouldn't", "should", "need to", "make it"
        ]
        
        lower_msg = user_message.lower()
        has_question = any(indicator in lower_msg for indicator in question_indicators)
        has_revision = any(indicator in lower_msg for indicator in revision_indicators)
        
        if has_question and not has_revision:
            return "QUESTION"
        if has_revision:
            return "REVISION"
        # Default to question for ambiguous cases to encourage discussion
        return "QUESTION"

    async def discuss_plan_step(
        self,
        state: RepositoryAgentState,
        current_step: TaskPlanItem,
        user_question: str,
        repo_context: str,
        memory_context: str,
    ) -> str:
        """Answer user questions about a plan step conversationally."""
        # Helper to format file paths for voice
        from pathlib import Path
        
        def format_files(paths):
            if not paths:
                return "general codebase changes"
            if len(paths) == 1:
                p = Path(paths[0])
                name = p.name  # Full filename with extension
                folder = p.parent.name if p.parent and str(p.parent) != '.' else None
                if folder:
                    return f"{name} in the {folder} folder"
                return f"{name}"
            return "several files across the codebase"
        
        return (
            f"So for {current_step.title} - {current_step.description}. "
            f"We'll be working with {format_files(current_step.scope)}. "
            f"This helps us {state.task_goal}. "
            f"Does that answer your question about {user_question}? Let me know if you want more details or if you're good to proceed."
        )

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
        
        # Format changed files naturally
        if repo_state.changed_files:
            from pathlib import Path
            file_desc = []
            for f in repo_state.changed_files[:3]:
                p = Path(f)
                name = p.name  # Full filename with extension
                folder = p.parent.name if p.parent and str(p.parent) != '.' else None
                if folder:
                    file_desc.append(f"{name} in {folder}")
                else:
                    file_desc.append(f"{name}")
            if len(repo_state.changed_files) > 3:
                file_desc.append(f"and {len(repo_state.changed_files) - 3} others")
            files_text = ", ".join(file_desc) if file_desc else "none"
        else:
            files_text = "none"
        
        return (
            f"Task finished for the project. "
            f"Subtasks completed: {len(completed)}. "
            f"Changed files: {files_text}. "
            f"Tests: {', '.join(repo_state.test_results) or 'not run'}. "
            f"Execution mode: offline demo, no live patch generation."
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
            "Create a SHORT high-level plan summary in natural spoken language.\n\n"
            "IMPORTANT:\n"
            "- Keep it to 2-3 sentences MAX\n"
            "- Focus ONLY on the key changes that matter\n"
            "- NO markdown formatting - no asterisks, no bold, no headers\n"
            "- Write like you're texting a coworker\n"
            "- Mention key files/components only if truly important\n"
            "- When mentioning files, say 'client.py in services' not 'services/client.py'\n"
            "- Skip implementation details - just the main approach\n"
            "- Use contractions and casual tone\n\n"
            "Task goal: %s\n"
            "Requirements: %s\n\n"
            "Repository context:\n%s\n\n"
            "Memory context:\n%s\n\n"
            "Provide a brief plan (2-3 sentences):"
        ) % (
            state.task_goal,
            state.requirements,
            repo_context,
            memory_context,
        )
        return await self._run_agent("Repository planning agent", prompt)

    async def split_tasks(
        self,
        state: RepositoryAgentState,
        plan: str,
    ) -> List[TaskPlanItem]:
        self._require_live_agent()
        prompt = (
            "Create a SINGLE step that covers the implementation as a JSON array with one item.\n"
            "The item must have title, description, and scope.\n\n"
            "IMPORTANT REQUIREMENTS:\n"
            "- Return exactly ONE step that covers all the work\n"
            "- Title should be SHORT - max 4-5 words\n"
            "- Description should be 1 sentence explaining what will change\n"
            "- Write like you're texting a coworker - use 'I'll' or 'We'll'\n"
            "- Be casual and conversational - contractions are good\n"
            "- When mentioning files, use natural language like 'client.py in services'\n"
            "- One sentence per description - keep it brief\n"
            "- In the 'scope' array, include actual file paths or patterns for technical processing\n\n"
            "Task goal: %s\n"
            "Requirements: %s\n"
            "Plan text:\n%s\n\n"
            "Return a JSON array of step objects with casual, coworker-style descriptions:"
        ) % (state.task_goal, state.requirements, plan)
        parsed = await self._run_json_agent(
            "Task splitter agent",
            prompt,
            "Return a JSON array of step objects.",
        )
        return _normalize_task_plan_items(parsed)

    async def classify_user_intent(
        self,
        user_message: str,
        current_step: TaskPlanItem,
    ) -> str:
        """Classify if user intent is 'QUESTION' or 'REVISION'."""
        self._require_live_agent()
        prompt = (
            "Classify the user's intent as either 'QUESTION' or 'REVISION'.\n\n"
            "QUESTION: User is asking for clarification, explanation, or more details about the plan step. "
            "Examples: 'What files will this change?', 'Why do we need this step?', 'How does this work?', "
            "'Can you explain the approach?', 'What are the implications?'\n\n"
            "REVISION: User wants to change, modify, or update the plan step. "
            "Examples: 'Change this to use Redis', 'Add error handling', 'Use a different approach', "
            "'Don't modify that file', 'Instead, let's do X'\n\n"
            "Current step being discussed:\n"
            "Title: %s\n"
            "Description: %s\n\n"
            "User message: %s\n\n"
            "Return only one word: QUESTION or REVISION"
        ) % (current_step.title, current_step.description, user_message)
        result = await self._run_agent("Intent classification agent", prompt)
        normalized = result.strip().upper()
        if "QUESTION" in normalized:
            return "QUESTION"
        if "REVISION" in normalized:
            return "REVISION"
        # Default to question to encourage discussion
        return "QUESTION"

    async def discuss_plan_step(
        self,
        state: RepositoryAgentState,
        current_step: TaskPlanItem,
        user_question: str,
        repo_context: str,
        memory_context: str,
    ) -> str:
        """Answer user questions about a plan step conversationally."""
        self._require_live_agent()
        prompt = (
            "You are a helpful coding assistant discussing an implementation plan with a developer. "
            "Answer their question conversationally with detailed explanations.\n\n"
            "IMPORTANT GUIDELINES:\n"
            "- Provide 2-4 paragraph responses with good depth\n"
            "- Explain the high-level approach and reasoning\n"
            "- Mention specific relevant modules, files, or components that will be affected\n"
            "- Explain WHY this approach was chosen and what it accomplishes\n"
            "- Use conversational, friendly tone\n"
            "- Don't say 'I revised' - this is just discussion, no changes yet\n"
            "- DO NOT use markdown formatting - no asterisks, no bold, no headers\n"
            "- Write naturally for voice output - avoid special characters and formatting\n"
            "- When mentioning file paths, describe them naturally like a coworker would\n"
            "- For example, say 'client.py in the services folder' not 'services/client.py'\n"
            "- End by asking if they have more questions or are ready to approve\n\n"
            "Current plan step being discussed:\n"
            "Title: %s\n"
            "Description: %s\n"
            "Scope: %s\n\n"
            "Overall task goal: %s\n\n"
            "User's question: %s\n\n"
            "Repository context (files available):\n%s\n\n"
            "Memory context:\n%s\n\n"
            "Provide a detailed, conversational response without any markdown:"
        ) % (
            current_step.title,
            current_step.description,
            ', '.join(current_step.scope) if current_step.scope else 'general codebase',
            state.task_goal,
            user_question,
            repo_context[:1000],  # Limit context size
            memory_context[:500],
        )
        return await self._run_agent("Plan discussion agent", prompt)

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
            "Make the description detailed and conversational (2-3 sentences explaining the approach).\n"
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
            "RESPOND WITH JSON ONLY - NO EXPLANATORY TEXT.\n\n"
            "Propose implementation output as JSON with result_summary, proposed_patch, changed_files, needed_files, test_command, replacement_files.\n"
            "This is a real repository modification flow, not an analysis-only flow.\n"
            "This is the execution phase. Do not ask the user for more context from this prompt.\n\n"
            "TWO WAYS TO MAKE CODE CHANGES:\n"
            "1. PATCH APPROACH: Return a unified git diff in `proposed_patch` (preferred for small targeted changes)\n"
            "2. REPLACEMENT APPROACH: Return complete file contents in `replacement_files` as a dict mapping file paths to their new full content\n\n"
            "WHEN TO USE replacement_files:\n"
            "- If the feedback says 'Switch strategy now: return replacement_files' - you MUST use this approach\n"
            "- If previous patch attempts failed validation or git apply\n"
            "- If you're having trouble with diff syntax\n"
            "- For large refactors where a patch would be complex\n"
            "Format: {\"src/path/file.tsx\": \"complete new file content here\"}\n"
            "Include ONLY files you're modifying. Each value should be the complete new file content.\n\n"
            "You must either produce changes via patch/replacement_files, or request more repository files through `needed_files`.\n\n"
            "HOW TO REQUEST FILES - CRITICAL:\n"
            "- If you mention 'need', 'needed', 'require', 'not available', 'cannot access', or similar in your result_summary, "
            "you MUST populate the `needed_files` array with exact file paths.\n"
            "- Example: needed_files = [\"src/pages/Home/Home.tsx\", \"src/App.tsx\", \"src/components/Hero.tsx\"]\n"
            "- Do NOT say you need files in result_summary without adding them to needed_files - this will cause execution to fail.\n"
            "- If you can see enough file content to implement safely, do NOT request more files - just implement.\n"
            "- NEVER say files are 'not available as repository files' - if you know the path, add it to needed_files.\n\n"
            "The initial file previews show the most relevant files with up to 50KB and 800 lines each - these are NOT truncated.\n"
            "If you see a file preview that appears complete, use it directly. Only request more files if truly needed.\n"
            "The task payload is an implementation brief synthesized from approved conversational plan steps.\n"
            "Treat inspection, design, and validation steps in that brief as context, not as permission to stop without changes.\n"
            "Treat the repository capability summary and visible files as authoritative grounding.\n"
            "If the task requires a new page, stylesheet, endpoint, template, or other feature surface and no exact target file exists yet, you may create the minimal new files needed as long as they fit the detected stack and repository structure.\n"
            "Do not stop just because an exact target file is missing if the brief explicitly allows creating the smallest grounded addition.\n"
            "Prefer integrating into an existing app shell when one is visible. If none is visible, create the smallest viable grounded entrypoint consistent with the detected stack instead of inventing an unrelated framework.\n"
            "If the repo context includes previous patch application errors, strongly consider using `replacement_files` instead of trying another patch.\n"
            "If using PATCH APPROACH with `proposed_patch`, it must be a raw unified git diff string.\n"
            "Every modified file must include its own full header block: `diff --git`, `---`, `+++`, then hunks.\n"
            "Never return hunk-only fragments that start directly with `@@`.\n"
            "Do not wrap the patch in markdown fences.\n"
            "Do not add commentary before or after the diff.\n"
            "Use `needed_files` only when you need additional specific files before proposing a safe change; otherwise return an empty list.\n"
            "Never return a placeholder response such as saying you will produce changes in the next step, that this attempt is only an inspection pass, or that no diff has been applied yet.\n"
            "If you already have enough grounding to describe the implementation, you must return the concrete changes now (via patch or replacement_files).\n"
            "For MODIFY_CODE tasks, do not set both `proposed_patch` and `replacement_files` to null/empty unless the repository already fully satisfies the request or you need more files through `needed_files`.\n"
            "If no more repository files would help and you cannot produce changes, explain the blocker in `result_summary` and leave `needed_files` empty.\n"
            "`test_command` must be either null or a real shell command that can be executed from the repository root.\n"
            "Never use explanatory prose in `test_command`.\n"
            "Treat `scope` as a hard constraint only when it is non-empty. If `scope` is empty, use the approved focus paths and visible repository files as guidance for a minimal grounded implementation.\n\n"
            "OUTPUT FORMAT - CRITICAL:\n"
            "Return ONLY a valid JSON object. Do NOT add any explanatory text before or after the JSON.\n"
            "Required JSON structure:\n"
            "{\n"
            "  \"result_summary\": \"string describing what was done\",\n"
            "  \"proposed_patch\": \"unified diff string or null\",\n"
            "  \"replacement_files\": {\"path/to/file\": \"complete content\"} or {},\n"
            "  \"changed_files\": [\"list\", \"of\", \"paths\"] or [],\n"
            "  \"needed_files\": [\"list\", \"of\", \"paths\"] or [],\n"
            "  \"test_command\": \"shell command or null\"\n"
            "}\n\n"
            "Task: %s\nRepo context:\n%s\nMemory:\n%s"
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
            "Create a concise final report for the user in natural spoken language.\\n"
            "DO NOT use markdown formatting - no asterisks, no bold, no headers, no bullet points.\\n"
            "Write naturally for voice output. Use complete sentences.\\n"
            "When mentioning file paths, describe them naturally like a coworker would.\\n"
            "For example, say 'client.py in the services folder' not 'services/client.py'.\\n"
            "Summarize what was done, which files were changed, and test results.\\n"
            "State: %s\\nTasks: %s"
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
        # Override agent creation for JSON-specific instructions
        self._require_live_agent()
        agent = self._agent_cls(  # type: ignore[misc]
            name=name,
            model=self.settings.openai_model,
            instructions=(
                "You are a backend coding assistant that returns structured JSON output only. "
                "Never add explanatory text, markdown formatting, or commentary. "
                "Your entire response must be valid JSON that can be parsed directly. "
                "If the prompt asks for JSON, respond with ONLY the JSON object or array."
            ),
        )
        result = await self._runner_cls.run(agent, prompt)  # type: ignore[union-attr]
        raw_output = str(result.final_output)
        
        parsed = _extract_json_payload(raw_output)
        if parsed is not None:
            return parsed

        # First repair attempt: explicit JSON extraction request
        repair_prompt = (
            "Convert the following model output into strict JSON only.\n"
            "%s\n"
            "Do not add markdown fences or commentary.\n"
            "Return ONLY the JSON object or array.\n"
            "Original output:\n%s"
        ) % (shape_hint, raw_output)
        
        # Use regular _run_agent for repair (not recursive)
        repair_agent = self._agent_cls(  # type: ignore[misc]
            name=f"{name} JSON repair",
            model=self.settings.openai_model,
            instructions="Extract and return only valid JSON from the given text. No other text.",
        )
        repair_result = await self._runner_cls.run(repair_agent, repair_prompt)  # type: ignore[union-attr]
        repaired_output = str(repair_result.final_output)
        
        repaired = _extract_json_payload(repaired_output)
        if repaired is not None:
            return repaired
        
        # Log the failure with truncated output for debugging
        output_preview = raw_output[:500] if len(raw_output) > 500 else raw_output
        error_msg = (
            "%s did not return valid JSON output. "
            "First 500 chars of output: %s... "
            "Check if the model is returning explanatory text instead of JSON."
        ) % (name, output_preview)
        raise RuntimeError(error_msg)


def _extract_json_payload(raw_output: str) -> Optional[Any]:
    candidates = []
    
    # Try direct parse first
    candidates.append(raw_output.strip())
    
    # Extract from markdown code fences
    fenced_json = re.findall(r"```(?:json)?\s*(.*?)```", raw_output, flags=re.DOTALL)
    candidates.extend(item.strip() for item in fenced_json if item.strip())
    
    # Find all potential JSON objects (greedy match for largest JSON)
    # Match from first { to last }
    object_matches = re.finditer(r"\{", raw_output)
    for start_match in object_matches:
        # Find matching closing brace
        depth = 0
        start_pos = start_match.start()
        for i in range(start_pos, len(raw_output)):
            if raw_output[i] == '{':
                depth += 1
            elif raw_output[i] == '}':
                depth -= 1
                if depth == 0:
                    candidates.append(raw_output[start_pos:i+1].strip())
                    break
    
    # Find all potential JSON arrays
    array_matches = re.finditer(r"\[", raw_output)
    for start_match in array_matches:
        depth = 0
        start_pos = start_match.start()
        for i in range(start_pos, len(raw_output)):
            if raw_output[i] == '[':
                depth += 1
            elif raw_output[i] == ']':
                depth -= 1
                if depth == 0:
                    candidates.append(raw_output[start_pos:i+1].strip())
                    break

    # Try parsing each candidate, preferring longer ones (more complete)
    seen: Set[str] = set()
    # Sort by length descending to try larger (potentially more complete) JSON first
    candidates_sorted = sorted(set(candidates), key=len, reverse=True)
    
    for candidate in candidates_sorted:
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
            # Verify it's a dict or list, not just a string/number
            if isinstance(parsed, (dict, list)):
                return parsed
        except Exception:
            continue
    
    return None


def _dedupe_strings(values) -> List[str]:
    items: List[str] = []
    seen = set()
    for value in values:
        normalized = " ".join(str(value).strip().strip("`'\"").split())
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
    return items


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
