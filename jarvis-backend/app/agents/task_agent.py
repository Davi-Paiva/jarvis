from __future__ import annotations

import re
from typing import Any, List, Optional

from app.graphs.task_agent_graph import build_task_agent_graph
from app.models.repository import RepositoryAgentState
from app.models.state import TaskAgentStatus
from app.models.task import TaskAgentState
from app.services.local_executor import LocalExecutor
from app.services.memory_service import MemoryService
from app.services.openai_client import LLMClient
from app.services.repo_context_builder import (
    build_file_content_sections,
    filter_scope,
    pick_candidate_files,
    render_repo_tree,
    select_context_files,
    summarize_repo_files,
)
from app.services.repository_registry import RepositoryRegistry


class TaskAgent:
    def __init__(
        self,
        state: TaskAgentState,
        registry: RepositoryRegistry,
        executor: LocalExecutor,
        llm_client: LLMClient,
        memory_service: MemoryService,
        graph_checkpointer: Optional[Any] = None,
    ) -> None:
        self.state = state
        self.registry = registry
        self.executor = executor
        self.llm_client = llm_client
        self.memory_service = memory_service
        self.graph = build_task_agent_graph(checkpointer=graph_checkpointer)

    async def execute(self, repo_state: RepositoryAgentState) -> TaskAgentState:
        try:
            self._set_status(TaskAgentStatus.INSPECTING)
            memory_context = self.memory_service.render_memory_for_llm(
                repo_state.repo_agent_id
            ).text
            available_files = self.executor.list_files(repo_state.repo_path, max_files=2000)
            focus_scope = self.state.scope or _focus_paths_from_description(self.state.description)
            visible_files = filter_scope(available_files, focus_scope)
            if not visible_files:
                visible_files = available_files
            repo_context = self._build_repo_context(repo_state, available_files)
            requested_file_contents: List[str] = []
            attempt_feedback: List[str] = []
            max_attempts = 5 if repo_state.intent_type == "MODIFY_CODE" and self.llm_client.is_live() else 1

            self._set_status(TaskAgentStatus.WORKING)
            result = None
            for attempt in range(1, max_attempts + 1):
                attempt_repo_context = _compose_attempt_context(
                    repo_context,
                    requested_file_contents,
                    attempt_feedback,
                    attempt,
                    max_attempts,
                )
                result = await self.llm_client.implement_task(
                    repo_state=repo_state,
                    task_state=self.state,
                    repo_context=attempt_repo_context,
                    memory_context=memory_context,
                )
                self.state.result_summary = result.result_summary
                self.state.proposed_patch = result.proposed_patch

                if result.proposed_patch:
                    try:
                        changed = await self.executor.apply_patch(
                            repo_path=repo_state.repo_path,
                            patch_text=result.proposed_patch,
                            scope=_patch_scope(repo_state, self.state),
                        )
                        self.state.changed_files = changed
                        break
                    except Exception as exc:
                        attempt_feedback.append(
                            "Attempt %s patch failed: %s" % (attempt, str(exc))
                        )
                        if attempt < max_attempts:
                            auto_contents = self._load_auto_candidate_file_contents(
                                repo_path=repo_state.repo_path,
                                visible_files=visible_files,
                                already_loaded=requested_file_contents,
                            )
                            if auto_contents:
                                requested_file_contents.extend(auto_contents)
                        if attempt >= max_attempts:
                            self.state.last_error = _build_patch_failure_error(attempt_feedback)
                            self._set_status(TaskAgentStatus.FAILED)
                            return self.state
                        continue

                if result.changed_files:
                    self.state.changed_files = result.changed_files
                    break

                if result.needed_files:
                    new_contents = self._load_requested_file_contents(
                        repo_path=repo_state.repo_path,
                        available_files=available_files,
                        needed_files=result.needed_files,
                        already_loaded=requested_file_contents,
                    )
                    if new_contents:
                        requested_file_contents.extend(new_contents)
                        continue
                    if attempt < max_attempts:
                        attempt_feedback.append(
                            _build_unresolved_files_feedback(result.needed_files)
                        )
                        continue
                    break

                if attempt < max_attempts and _should_retry_without_changes(result.result_summary):
                    auto_contents = self._load_auto_candidate_file_contents(
                        repo_path=repo_state.repo_path,
                        visible_files=visible_files,
                        already_loaded=requested_file_contents,
                    )
                    if auto_contents:
                        requested_file_contents.extend(auto_contents)
                    attempt_feedback.append(
                        _build_missing_diff_feedback(result.result_summary)
                    )
                    continue
                if attempt < max_attempts and _needs_full_file_context(result.result_summary):
                    auto_contents = self._load_auto_candidate_file_contents(
                        repo_path=repo_state.repo_path,
                        visible_files=visible_files,
                        already_loaded=requested_file_contents,
                    )
                    if auto_contents:
                        requested_file_contents.extend(auto_contents)
                        attempt_feedback.append(
                            _build_full_context_feedback(result.result_summary)
                        )
                        continue
                break

            if result is None:
                raise RuntimeError("Implementation task did not return a result.")

            self.state.result_summary = result.result_summary
            self.state.proposed_patch = result.proposed_patch
            if not self.state.changed_files:
                self.state.changed_files = result.changed_files

            if (
                repo_state.intent_type == "MODIFY_CODE"
                and self.llm_client.is_live()
                and not self.state.changed_files
                and not self.state.proposed_patch
            ):
                self.state.last_error = _build_no_change_error(self.state, result.result_summary)
                self._set_status(TaskAgentStatus.FAILED)
                return self.state

            self._set_status(TaskAgentStatus.VALIDATING)
            if result.test_command:
                code, stdout, stderr = await self.executor.run_allowed_command(
                    repo_state.repo_path,
                    result.test_command,
                )
                self.state.test_results.append(
                    "command=%s exit_code=%s stdout=%s stderr=%s"
                    % (result.test_command, code, stdout.strip(), stderr.strip())
                )

            self._set_status(TaskAgentStatus.DONE)
            return self.state
        except Exception as exc:
            self.state.last_error = str(exc)
            self._set_status(TaskAgentStatus.FAILED)
            return self.state

    def mark_dead(self) -> TaskAgentState:
        self._set_status(TaskAgentStatus.DEAD)
        return self.state

    def _set_status(self, status: TaskAgentStatus) -> None:
        self.state.status = status
        self.registry.save_task_state(self.state)

    def _build_repo_context(self, repo_state: RepositoryAgentState, available_files: List[str]) -> str:
        repo_path = repo_state.repo_path
        files = available_files
        effective_scope = self.state.scope or _focus_paths_from_description(self.state.description)
        visible_files = filter_scope(files, effective_scope)
        scope_fallback_used = False
        if not visible_files:
            visible_files = files
            scope_fallback_used = bool(effective_scope)
        context_files = select_context_files(_context_text_chunks(repo_state, self.state), visible_files)

        sections = []
        if scope_fallback_used:
            sections.append(
                "Scope fallback:\n"
                "The planned scope did not match any repository files, so execution is using the broader repository context."
            )
        sections.append(
            "Repository capability summary:\n%s" % summarize_repo_files(visible_files)
        )
        sections.extend(
            [
                "Visible files:\n%s" % "\n".join("- %s" % item for item in context_files[:120]),
                "Repository tree:\n%s" % render_repo_tree(context_files[:120]),
            ]
        )
        previews = self._build_candidate_file_previews(repo_state, visible_files)
        if previews:
            sections.append("Initial candidate file previews:\n%s" % previews)
        return "\n\n".join(sections)

    def _build_candidate_file_previews(
        self,
        repo_state: RepositoryAgentState,
        visible_files: List[str],
    ) -> str:
        return build_file_content_sections(
            repo_path=repo_state.repo_path,
            files=pick_candidate_files(_context_text_chunks(repo_state, self.state), visible_files),
            read_file=self.executor.read_file,
            max_files=8,
            max_chars=2500,
            max_lines=80,
        )

    def _load_requested_file_contents(
        self,
        repo_path: str,
        available_files: List[str],
        needed_files: List[str],
        already_loaded: List[str],
    ) -> List[str]:
        loaded_paths = {
            _loaded_file_path(section)
            for section in already_loaded
            if _loaded_file_path(section)
        }
        contents: List[str] = []
        for requested in needed_files:
            matched = _resolve_requested_file(requested, available_files)
            if not matched or matched in loaded_paths:
                continue
            try:
                content = self.executor.read_file(repo_path, matched, max_chars=12000)
            except Exception:
                continue
            contents.append("File: %s\n%s" % (matched, content))
            loaded_paths.add(matched)
        return contents

    def _load_auto_candidate_file_contents(
        self,
        repo_path: str,
        visible_files: List[str],
        already_loaded: List[str],
    ) -> List[str]:
        loaded_paths = {
            _loaded_file_path(section)
            for section in already_loaded
            if _loaded_file_path(section)
        }
        candidate_paths = pick_candidate_files(
            _task_text_chunks(self.state),
            visible_files,
            limit=12,
        )
        contents: List[str] = []
        for matched in candidate_paths:
            if matched in loaded_paths:
                continue
            try:
                content = self.executor.read_file(repo_path, matched, max_chars=12000)
            except Exception:
                continue
            contents.append("File: %s\n%s" % (matched, content))
            loaded_paths.add(matched)
        return contents


def _resolve_requested_file(requested: str, available_files: List[str]) -> Optional[str]:
    normalized = _normalize_requested_path(requested)
    if not normalized:
        return None

    normalized_map = {_normalize_requested_path(path): path for path in available_files}
    exact = normalized_map.get(normalized)
    if exact:
        return exact

    suffix_matches = [
        path
        for path in available_files
        if _normalize_requested_path(path).endswith("/" + normalized)
        or _normalize_requested_path(path).endswith(normalized)
    ]
    if len(suffix_matches) == 1:
        return suffix_matches[0]

    basename = normalized.rsplit("/", 1)[-1]
    basename_matches = [
        path
        for path in available_files
        if _normalize_requested_path(path).rsplit("/", 1)[-1] == basename
    ]
    if len(basename_matches) == 1:
        return basename_matches[0]

    lowered = normalized.lower()
    case_matches = [
        path
        for path in available_files
        if _normalize_requested_path(path).lower() == lowered
    ]
    if len(case_matches) == 1:
        return case_matches[0]

    return None


def _normalize_requested_path(path: str) -> str:
    normalized = str(path).strip().strip("`'\"").replace("\\", "/")
    normalized = normalized.lstrip("./")
    for prefix in ("a/", "b/"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    return normalized.strip("/")


def _build_no_change_error(task_state: TaskAgentState, result_summary: Optional[str]) -> str:
    summary = " ".join((result_summary or "").split()).strip()
    if summary:
        return (
            "Execution failed because the implementation phase exhausted its internal file-grounded attempts "
            "and did not produce any code changes. Model summary: %s"
        ) % summary
    return (
        "Execution failed because the implementation phase exhausted its internal file-grounded attempts "
        "and did not produce any code changes "
        "for '%s'."
    ) % (task_state.title or "this task")


def _build_patch_failure_error(patch_errors: List[str]) -> str:
    last_error = patch_errors[-1] if patch_errors else "Patch could not be applied."
    return (
        "Execution failed because the implementation phase produced patches, but none passed "
        "the repository patch check after internal retries. %s"
    ) % last_error


def _patch_scope(repo_state: RepositoryAgentState, task_state: TaskAgentState) -> List[str]:
    if repo_state.intent_type == "MODIFY_CODE" and task_state.title == "Implement approved repository change":
        return []
    return task_state.scope


def _compose_attempt_context(
    base_repo_context: str,
    requested_file_contents: List[str],
    attempt_feedback: List[str],
    attempt: int,
    max_attempts: int,
) -> str:
    sections = [
        "Execution attempt: %s/%s" % (attempt, max_attempts),
        base_repo_context,
    ]
    if requested_file_contents:
        sections.append(
            "Requested file contents:\n%s" % "\n\n".join(requested_file_contents)
        )
    if attempt_feedback:
        sections.append(
            "Previous execution feedback:\n%s\n\n"
            "Your next response must either return a valid unified git diff in `proposed_patch` or request additional repository files through `needed_files`."
            % "\n".join("- %s" % item for item in attempt_feedback[-3:])
        )
    return "\n\n".join(section for section in sections if section.strip())


def _loaded_file_path(section: str) -> Optional[str]:
    first_line = section.splitlines()[0].strip() if section else ""
    if not first_line.startswith("File: "):
        return None
    path = first_line[len("File: ") :].strip()
    return path or None


def _focus_paths_from_description(description: str) -> List[str]:
    marker = "Focus paths from the approved plan:"
    if marker not in description:
        return []
    section = description.split(marker, 1)[1]
    lines = []
    for raw_line in section.splitlines():
        line = raw_line.strip()
        if not line:
            if lines:
                break
            continue
        if line.endswith(":") and not line.startswith("- "):
            if lines:
                break
            continue
        if line.startswith("- "):
            lines.append(line[2:].strip())
        elif lines:
            break
    return [line for line in lines if line]


def _context_text_chunks(repo_state: RepositoryAgentState, task_state: TaskAgentState) -> List[str]:
    return [
        repo_state.task_goal or "",
        repo_state.original_user_prompt or "",
        task_state.title,
        task_state.description,
        " ".join(task_state.scope),
    ]


def _task_text_chunks(task_state: TaskAgentState) -> List[str]:
    return [
        task_state.title,
        task_state.description,
        " ".join(task_state.scope),
    ]


def _build_missing_diff_feedback(result_summary: Optional[str]) -> str:
    summary = " ".join((result_summary or "").split()).strip()
    if summary:
        return (
            "The previous attempt returned no patch and no requested files. "
            "Do not return a placeholder, plan, or 'next step' message. "
            "Return an actual grounded unified diff now, or request the exact additional files you still need. "
            "Previous summary: %s"
        ) % summary
    return (
        "The previous attempt returned no patch and no requested files. "
        "Do not return a placeholder or planning message. "
        "Return an actual grounded unified diff now, or request the exact additional files you still need."
    )


def _build_unresolved_files_feedback(needed_files: List[str]) -> str:
    return (
        "The previous attempt requested additional files, but none of these requests could be resolved "
        "to repository files: %s. Request exact relative paths, unique basenames, or unique path suffixes."
    ) % ", ".join(needed_files[:10])


def _build_full_context_feedback(result_summary: Optional[str]) -> str:
    summary = " ".join((result_summary or "").split()).strip()
    if summary:
        return (
            "Additional full candidate file contents were added because the previous attempt indicated "
            "that truncated previews or incomplete component context were preventing a grounded patch. "
            "Return a concrete unified diff now using those full files. Previous summary: %s"
        ) % summary
    return (
        "Additional full candidate file contents were added because the previous attempt indicated "
        "that truncated previews or incomplete component context were preventing a grounded patch. "
        "Return a concrete unified diff now using those full files."
    )


def _needs_full_file_context(result_summary: Optional[str]) -> bool:
    summary = " ".join((result_summary or "").lower().split())
    if not summary:
        return False
    signals = (
        "truncated",
        "full current contents",
        "full component content",
        "full contents of the page components",
        "shared component files",
        "need the full current contents",
        "visible file previews are truncated",
        "before the full component content needed",
        "current repository snapshot",
    )
    return any(signal in summary for signal in signals)


def _should_retry_without_changes(result_summary: Optional[str]) -> bool:
    summary = " ".join((result_summary or "").lower().split())
    if not summary:
        return False
    placeholder_signals = (
        "placeholder",
        "next step",
        "next attempt",
        "none has been applied yet",
        "no diff has been applied yet",
        "current response is a placeholder",
        "need to produce the actual patch",
        "produce the actual patch against the repository contents in the next step",
        "i can implement",
        "i can produce the patch",
        "however, i need to produce the actual patch",
        "this attempt is only",
        "not been applied yet",
    )
    return any(signal in summary for signal in placeholder_signals)
