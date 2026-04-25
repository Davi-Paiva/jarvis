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
            repo_context = self._build_repo_context(repo_state, available_files)
            requested_file_contents: List[str] = []
            patch_errors: List[str] = []
            max_attempts = 5 if repo_state.intent_type == "MODIFY_CODE" and self.llm_client.is_live() else 1

            self._set_status(TaskAgentStatus.WORKING)
            result = None
            for attempt in range(1, max_attempts + 1):
                attempt_repo_context = _compose_attempt_context(
                    repo_context,
                    requested_file_contents,
                    patch_errors,
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
                        patch_errors.append(
                            "Attempt %s patch failed: %s" % (attempt, str(exc))
                        )
                        if attempt >= max_attempts:
                            self.state.last_error = _build_patch_failure_error(patch_errors)
                            self._set_status(TaskAgentStatus.FAILED)
                            return self.state
                        continue

                if result.changed_files:
                    self.state.changed_files = result.changed_files
                    break

                if attempt >= max_attempts or not result.needed_files:
                    break

                new_contents = self._load_requested_file_contents(
                    repo_path=repo_state.repo_path,
                    available_files=available_files,
                    needed_files=result.needed_files,
                    already_loaded=requested_file_contents,
                )
                if not new_contents:
                    break
                requested_file_contents.extend(new_contents)

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
        visible_files = _filter_scope(files, self.state.scope)
        scope_fallback_used = False
        if not visible_files:
            visible_files = files
            scope_fallback_used = bool(self.state.scope)
        context_files = _select_context_files(repo_state, self.state, visible_files)

        sections = []
        if scope_fallback_used:
            sections.append(
                "Scope fallback:\n"
                "The planned scope did not match any repository files, so execution is using the broader repository context."
            )
        sections.append(
            "Repository capability summary:\n%s" % _summarize_repo_files(visible_files)
        )
        sections.extend(
            [
                "Visible files:\n%s" % "\n".join("- %s" % item for item in context_files[:120]),
                "Repository tree:\n%s" % _render_repo_tree(context_files[:120]),
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
        previews: List[str] = []
        for relative_path in _pick_candidate_files(repo_state, self.state, visible_files):
            try:
                content = self.executor.read_file(repo_state.repo_path, relative_path, max_chars=2500)
            except Exception:
                continue
            preview = "\n".join(content.splitlines()[:80]).strip()
            if not preview:
                continue
            previews.append("File: %s\n%s" % (relative_path, preview))
        return "\n\n".join(previews)

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


def _filter_scope(files: List[str], scope: List[str]) -> List[str]:
    if not scope:
        return files
    normalized_scope = [item.strip().strip("/") for item in scope if item.strip()]
    return [
        path
        for path in files
        if any(path == item or path.startswith(item + "/") for item in normalized_scope)
    ]


def _render_repo_tree(files: List[str], max_lines: int = 80) -> str:
    if not files:
        return "- (no visible files)"
    lines: List[str] = []
    seen = set()
    for file_path in files:
        parts = file_path.split("/")
        for depth, part in enumerate(parts):
            key = tuple(parts[: depth + 1])
            if key in seen:
                continue
            seen.add(key)
            indent = "  " * depth
            suffix = "/" if depth < len(parts) - 1 else ""
            lines.append("%s- %s%s" % (indent, part, suffix))
            if len(lines) >= max_lines:
                lines.append("  ...")
                return "\n".join(lines)
    return "\n".join(lines)


def _pick_candidate_files(
    repo_state: RepositoryAgentState,
    task_state: TaskAgentState,
    visible_files: List[str],
    limit: int = 8,
) -> List[str]:
    if not visible_files:
        return []
    keywords = _task_keywords(repo_state, task_state)
    priority_names = {
        "app",
        "homepage",
        "home",
        "layout",
        "routes",
        "router",
        "index",
        "main",
        "page",
        "hero",
        "landing",
        "style",
        "styles",
    }
    scored = []
    for index, path in enumerate(visible_files):
        lowered = path.lower()
        filename = lowered.rsplit("/", 1)[-1]
        stem = filename.rsplit(".", 1)[0]
        score = 0
        for keyword in keywords:
            if keyword and keyword in stem:
                score += 5
            elif keyword and keyword in lowered:
                score += 3
        if stem in priority_names:
            score += 4
        if any(part in lowered for part in ("/pages/", "/components/", "/routes/", "/app/")):
            score += 2
        if filename.endswith((".tsx", ".ts", ".jsx", ".js", ".css", ".scss")):
            score += 1
        scored.append((score, index, path))

    scored.sort(key=lambda item: (-item[0], item[1]))
    selected = [path for score, _index, path in scored[:limit] if score > 0]
    if selected:
        return selected
    return visible_files[: min(limit, len(visible_files))]


def _select_context_files(
    repo_state: RepositoryAgentState,
    task_state: TaskAgentState,
    visible_files: List[str],
    limit: int = 120,
) -> List[str]:
    if len(visible_files) <= limit:
        return visible_files

    selected: List[str] = []
    seen = set()

    def add(path: str) -> None:
        if path in seen or len(selected) >= limit:
            return
        seen.add(path)
        selected.append(path)

    for path in _pick_candidate_files(repo_state, task_state, visible_files, limit=min(24, limit)):
        add(path)

    keywords = _task_keywords(repo_state, task_state)
    favored_segments = (
        "src/",
        "app/",
        "pages/",
        "components/",
        "routes/",
        "templates/",
        "static/",
        "public/",
        "docs/",
    )
    favored_extensions = (
        ".tsx",
        ".ts",
        ".jsx",
        ".js",
        ".css",
        ".scss",
        ".html",
        ".md",
        ".py",
    )

    for path in visible_files:
        lowered = path.lower()
        if any(segment in lowered for segment in favored_segments) or lowered.endswith(favored_extensions):
            add(path)
        if len(selected) >= limit:
            break

    if keywords and len(selected) < limit:
        for path in visible_files:
            lowered = path.lower()
            if any(keyword in lowered for keyword in keywords):
                add(path)
            if len(selected) >= limit:
                break

    if len(selected) < limit:
        for path in visible_files:
            add(path)
            if len(selected) >= limit:
                break

    return selected


def _task_keywords(repo_state: RepositoryAgentState, task_state: TaskAgentState) -> List[str]:
    text = " ".join(
        item
        for item in [
            repo_state.task_goal or "",
            repo_state.original_user_prompt or "",
            task_state.title,
            task_state.description,
            " ".join(task_state.scope),
        ]
        if item
    ).lower()
    words = re.findall(r"[a-z0-9_/-]{3,}", text)
    stop_words = {
        "the",
        "and",
        "for",
        "with",
        "this",
        "that",
        "you",
        "implementation",
        "approved",
        "change",
        "repository",
        "context",
        "phase",
        "code",
        "files",
        "steps",
    }
    keywords: List[str] = []
    seen = set()
    for word in words:
        normalized = word.strip("/-_")
        if not normalized or normalized in stop_words or normalized in seen:
            continue
        seen.add(normalized)
        keywords.append(normalized)
    return keywords[:24]


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


def _summarize_repo_files(files: List[str]) -> str:
    if not files:
        return "- No visible repository files."

    lowered = [path.lower() for path in files]
    frontend = [
        path for path in files
        if path.lower().endswith((".html", ".css", ".scss", ".tsx", ".jsx", ".ts", ".js"))
        or any(segment in path.lower() for segment in ("/src/", "/pages/", "/components/", "/templates/", "/static/", "/public/"))
    ]
    docs = [path for path in files if path.lower().startswith("docs/") or path.lower().endswith(".md")]
    python = [path for path in files if path.lower().endswith(".py")]
    server_entries = [
        path for path in files
        if path.lower().endswith(".py") and path.lower().rsplit("/", 1)[-1] in {"main.py", "app.py", "server.py"}
    ]
    lines = [
        "- Visible file count: %s" % len(files),
        "- Frontend/template/static surface detected: %s" % ("yes" if frontend else "no"),
        "- Python source detected: %s" % ("yes" if python else "no"),
        "- Docs or markdown detected: %s" % ("yes" if docs else "no"),
    ]
    if frontend:
        lines.append("- Example UI files: %s" % ", ".join(frontend[:5]))
    if server_entries:
        lines.append("- Example app entry files: %s" % ", ".join(server_entries[:5]))
    elif python:
        lines.append("- Example Python files: %s" % ", ".join(python[:5]))
    if docs:
        lines.append("- Example docs files: %s" % ", ".join(docs[:5]))
    return "\n".join(lines)


def _patch_scope(repo_state: RepositoryAgentState, task_state: TaskAgentState) -> List[str]:
    if repo_state.intent_type == "MODIFY_CODE" and task_state.title == "Implement approved repository change":
        return []
    return task_state.scope


def _compose_attempt_context(
    base_repo_context: str,
    requested_file_contents: List[str],
    patch_errors: List[str],
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
    if patch_errors:
        sections.append(
            "Previous patch application errors:\n%s\n\n"
            "Return a corrected unified git diff. Do not repeat the same malformed patch."
            % "\n".join("- %s" % item for item in patch_errors[-3:])
        )
    return "\n\n".join(section for section in sections if section.strip())


def _loaded_file_path(section: str) -> Optional[str]:
    first_line = section.splitlines()[0].strip() if section else ""
    if not first_line.startswith("File: "):
        return None
    path = first_line[len("File: ") :].strip()
    return path or None
