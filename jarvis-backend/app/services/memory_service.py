from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.models.memory import (
    CompletedTaskMemory,
    MemoryFrontMatter,
    RenderedMemoryView,
    RepositoryMemory,
)
from app.models.repository import RepositoryAgentState
from app.models.task import TaskAgentState
from app.models.turns import utc_now


SECTION_TITLES = [
    "Current Summary",
    "User Preferences",
    "Active Conventions",
    "Repository Learnings",
    "Useful Commands",
    "Active Decisions",
    "Known Risks",
    "Completed Tasks",
]

DEFAULT_CONVENTIONS = [
    "Use existing project style.",
    "Prefer minimal patches.",
    "Do not add dependencies unless approved.",
]

DEFAULT_COMMANDS = ["git status", "git diff"]

SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)\b(api[_-]?key|secret|password|bearer|token)\b\s*[:=]"),
]

PATCH_PREFIXES = ("diff --git", "@@", "+++", "---")


class MemoryService:
    """Structured Markdown memory for repository agents.

    SQLite remains the complete operational record. This service writes a small,
    reusable Markdown memory optimized for future LLM context.
    """

    def __init__(
        self,
        memory_dir: str,
        max_chars: int = 30000,
        view_max_chars: int = 12000,
        max_completed_tasks: int = 12,
        useful_commands: Optional[Iterable[str]] = None,
    ) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir = self.memory_dir / "archive"
        self.max_chars = max_chars
        self.view_max_chars = view_max_chars
        self.max_completed_tasks = max_completed_tasks
        self.default_useful_commands = _dedupe(
            list(DEFAULT_COMMANDS) + list(useful_commands or []),
            max_items=12,
        )

    def path_for_agent(self, repo_agent_id: str) -> Path:
        return self.memory_dir / ("%s.md" % repo_agent_id)

    def initialize_agent_memory(self, state: RepositoryAgentState) -> RepositoryMemory:
        path = self.path_for_agent(state.repo_agent_id)
        if path.exists() and self._is_structured_memory(path):
            return self.load_memory(state.repo_agent_id)
        if path.exists():
            self._archive_legacy_memory(path, state.repo_agent_id)

        memory = RepositoryMemory(
            front_matter=MemoryFrontMatter(
                repo_agent_id=state.repo_agent_id,
                repo_id=state.repo_id,
                user_id=state.user_id,
            ),
            current_summary=_dedupe(
                [
                    "Repo path: `%s`." % state.repo_path,
                    "Branch: `%s`." % state.branch_name if state.branch_name else "",
                ],
                max_items=8,
            ),
            active_conventions=list(DEFAULT_CONVENTIONS),
            useful_commands=list(self.default_useful_commands),
        )
        self.save_memory(memory)
        return memory

    def delete_agent_memory(self, state: RepositoryAgentState) -> None:
        path = self.path_for_agent(state.repo_agent_id)
        if path.exists():
            archive_path = self.archive_dir / ("%s_%s.md" % (
                state.repo_agent_id,
                datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            ))
            archive_path.parent.mkdir(parents=True, exist_ok=True)
            path.rename(archive_path)

    def load_memory(self, repo_agent_id: str) -> RepositoryMemory:
        path = self.path_for_agent(repo_agent_id)
        if not path.exists():
            raise FileNotFoundError("Memory file does not exist: %s" % path)
        content = path.read_text(encoding="utf-8")
        front_matter, body = self._parse_front_matter(content)
        return RepositoryMemory(
            front_matter=front_matter,
            current_summary=self._parse_bullets(body, "Current Summary"),
            user_preferences=self._parse_bullets(body, "User Preferences"),
            active_conventions=self._parse_bullets(body, "Active Conventions"),
            repository_learnings=self._parse_bullets(body, "Repository Learnings"),
            useful_commands=self._parse_bullets(body, "Useful Commands"),
            active_decisions=self._parse_bullets(body, "Active Decisions"),
            known_risks=self._parse_bullets(body, "Known Risks"),
            completed_tasks=self._parse_completed_tasks(body),
        )

    def save_memory(self, memory: RepositoryMemory, compact: bool = True) -> None:
        sanitized = self._sanitize_memory(memory)
        sanitized.front_matter.last_updated = utc_now()
        path = self.path_for_agent(sanitized.front_matter.repo_agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self._render_markdown(sanitized), encoding="utf-8")
        if compact:
            self.compact_if_needed(sanitized.front_matter.repo_agent_id)

    def render_memory_for_llm(
        self,
        repo_agent_id: str,
        max_chars: Optional[int] = None,
    ) -> RenderedMemoryView:
        limit = max_chars or self.view_max_chars
        memory = self.load_memory(repo_agent_id)
        rendered = self._render_markdown(memory, completed_task_limit=3)
        original_len = len(rendered)
        truncated = False
        if original_len > limit:
            truncated = True
            marker = "\n\n<!-- memory truncated -->"
            rendered = rendered[: max(0, limit - len(marker))].rstrip() + marker
        return RenderedMemoryView(
            text=rendered,
            truncated=truncated,
            source_path=str(self.path_for_agent(repo_agent_id)),
            char_count=original_len,
        )

    def record_task_started(self, state: RepositoryAgentState) -> RepositoryMemory:
        memory = self.load_memory(state.repo_agent_id)
        memory.current_summary = _dedupe(
            memory.current_summary
            + [
                "Current goal: %s." % (state.task_goal or "Not recorded"),
                "Repo path: `%s`." % state.repo_path,
            ],
            max_items=8,
        )
        memory.user_preferences = _dedupe(
            memory.user_preferences
            + _extract_preferences([state.task_goal or ""] + state.acceptance_criteria),
            max_items=12,
        )
        self.save_memory(memory)
        return memory

    def record_plan_proposed(self, state: RepositoryAgentState) -> RepositoryMemory:
        memory = self.load_memory(state.repo_agent_id)
        memory.active_decisions = _dedupe(
            memory.active_decisions
            + _extract_decisions([state.plan or ""] + state.acceptance_criteria),
            max_items=20,
        )
        memory.user_preferences = _dedupe(
            memory.user_preferences + _extract_preferences(state.acceptance_criteria),
            max_items=12,
        )
        self.save_memory(memory)
        return memory

    def record_task_completed(
        self,
        repo_state: RepositoryAgentState,
        task_states: List[TaskAgentState],
    ) -> RepositoryMemory:
        memory = self.load_memory(repo_state.repo_agent_id)
        completed_task = CompletedTaskMemory(
            title=repo_state.task_goal or "Repository task",
            status="completed" if not repo_state.last_error else "failed",
            branch_name=repo_state.branch_name,
            goal=repo_state.task_goal or "Not recorded",
            acceptance_criteria=repo_state.acceptance_criteria,
            changed_files=_dedupe(repo_state.changed_files, max_items=40),
            validation=_dedupe(
                [_sanitize_validation(item) for item in repo_state.test_results],
                max_items=20,
            ),
            decisions=_dedupe(
                _extract_decisions([repo_state.plan or ""] + repo_state.acceptance_criteria),
                max_items=12,
            ),
            reusable_learnings=_dedupe(
                _extract_reusable_learnings(task_states, repo_state.changed_files),
                max_items=20,
            ),
            risks=_dedupe(_extract_risks(task_states, repo_state.final_report), max_items=12),
        )

        memory.completed_tasks.append(completed_task)
        prior_summary = [
            item for item in memory.current_summary if not item.lower().startswith("current goal:")
        ]
        memory.current_summary = _dedupe(
            [
                "Repo path: `%s`." % repo_state.repo_path,
                "Recent work: %s." % (repo_state.task_goal or "Repository task completed"),
            ]
            + prior_summary,
            max_items=8,
        )
        memory.repository_learnings = _dedupe(
            memory.repository_learnings + completed_task.reusable_learnings,
            max_items=40,
        )
        memory.useful_commands = _dedupe(
            memory.useful_commands
            + self.default_useful_commands
            + _extract_commands(completed_task.validation),
            max_items=12,
        )
        memory.active_decisions = _dedupe(
            memory.active_decisions + completed_task.decisions,
            max_items=20,
        )
        memory.known_risks = _dedupe(memory.known_risks + completed_task.risks, max_items=20)
        self.save_memory(memory)
        return memory

    def compact_if_needed(self, repo_agent_id: str) -> bool:
        memory = self.load_memory(repo_agent_id)
        rendered = self._render_markdown(memory)
        needs_task_compaction = len(memory.completed_tasks) > self.max_completed_tasks
        needs_size_compaction = len(rendered) > self.max_chars
        if not needs_task_compaction and not needs_size_compaction:
            return False

        old_tasks = memory.completed_tasks[: -self.max_completed_tasks]
        if old_tasks:
            self._archive_tasks(memory.front_matter.repo_agent_id, old_tasks)
            memory.completed_tasks = memory.completed_tasks[-self.max_completed_tasks :]

        memory.current_summary = memory.current_summary[:8]
        memory.user_preferences = memory.user_preferences[:12]
        memory.active_conventions = memory.active_conventions[:12]
        memory.repository_learnings = memory.repository_learnings[-40:]
        memory.useful_commands = memory.useful_commands[:12]
        memory.active_decisions = memory.active_decisions[-20:]
        memory.known_risks = memory.known_risks[-20:]
        self.save_memory(memory, compact=False)
        return True

    def _render_markdown(
        self,
        memory: RepositoryMemory,
        completed_task_limit: Optional[int] = None,
    ) -> str:
        tasks = memory.completed_tasks
        if completed_task_limit is not None:
            tasks = tasks[-completed_task_limit:]
        parts = [
            "---",
            "repo_agent_id: %s" % memory.front_matter.repo_agent_id,
            "repo_id: %s" % memory.front_matter.repo_id,
            "user_id: %s" % memory.front_matter.user_id,
            "memory_version: %s" % memory.front_matter.memory_version,
            "last_updated: %s" % _format_dt(memory.front_matter.last_updated),
            "---",
            "",
            "# Repository Memory",
            "",
            self._render_list_section("Current Summary", memory.current_summary),
            self._render_list_section("User Preferences", memory.user_preferences),
            self._render_list_section("Active Conventions", memory.active_conventions),
            self._render_list_section("Repository Learnings", memory.repository_learnings),
            self._render_list_section("Useful Commands", _format_commands(memory.useful_commands)),
            self._render_list_section("Active Decisions", memory.active_decisions),
            self._render_list_section("Known Risks", memory.known_risks),
            self._render_completed_tasks(tasks),
        ]
        return "\n".join(parts).rstrip() + "\n"

    def _render_list_section(self, title: str, items: List[str]) -> str:
        lines = ["## %s" % title, ""]
        if items:
            lines.extend("- %s" % item for item in items)
        else:
            lines.append("- None recorded.")
        lines.append("")
        return "\n".join(lines)

    def _render_completed_tasks(self, tasks: List[CompletedTaskMemory]) -> str:
        lines = ["## Completed Tasks", ""]
        if not tasks:
            lines.append("- None recorded.")
            lines.append("")
            return "\n".join(lines)

        for task in tasks:
            lines.extend(
                [
                    "### %s - %s" % (_format_dt(task.completed_at), task.title),
                    "",
                    "Status: %s" % task.status,
                    "Branch: %s" % (task.branch_name or "not set"),
                    "",
                    "Goal:",
                    task.goal or "Not recorded.",
                    "",
                    "Acceptance Criteria:",
                ]
            )
            lines.extend(_render_inline_list(task.acceptance_criteria))
            lines.extend(["", "Changed Files:"])
            lines.extend(_render_inline_list(_format_paths(task.changed_files)))
            lines.extend(["", "Validation:"])
            lines.extend(_render_inline_list(task.validation))
            lines.extend(["", "Decisions:"])
            lines.extend(_render_inline_list(task.decisions))
            lines.extend(["", "Reusable Learnings:"])
            lines.extend(_render_inline_list(task.reusable_learnings))
            lines.extend(["", "Risks:"])
            lines.extend(_render_inline_list(task.risks))
            lines.append("")
        return "\n".join(lines)

    def _parse_front_matter(self, content: str) -> Tuple[MemoryFrontMatter, str]:
        if not content.startswith("---\n"):
            raise ValueError("Memory file is not structured front matter Markdown.")
        end = content.find("\n---", 4)
        if end == -1:
            raise ValueError("Memory file front matter is not closed.")
        raw_front_matter = content[4:end].strip()
        body = content[end + len("\n---") :].lstrip()
        payload: Dict[str, object] = {}
        for line in raw_front_matter.splitlines():
            if ":" not in line:
                continue
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "memory_version":
                payload[key] = int(value)
            elif key == "last_updated":
                payload[key] = _parse_dt(value)
            else:
                payload[key] = value
        return MemoryFrontMatter(**payload), body

    def _parse_bullets(self, body: str, section_title: str) -> List[str]:
        content = _section_content(body, section_title)
        items = []
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped.startswith("- "):
                continue
            value = stripped[2:].strip()
            if value.lower() == "none recorded.":
                continue
            items.append(value)
        return _dedupe(items)

    def _parse_completed_tasks(self, body: str) -> List[CompletedTaskMemory]:
        content = _section_content(body, "Completed Tasks")
        tasks: List[CompletedTaskMemory] = []
        blocks = re.split(r"^### ", content, flags=re.MULTILINE)
        for block in blocks:
            block = block.strip()
            if not block or block.startswith("- None recorded."):
                continue
            lines = block.splitlines()
            heading = lines[0].strip()
            completed_at, title = _parse_task_heading(heading)
            block_text = "\n".join(lines[1:])
            tasks.append(
                CompletedTaskMemory(
                    completed_at=completed_at,
                    title=title,
                    status=_parse_scalar(block_text, "Status") or "completed",
                    branch_name=_none_if_unset(_parse_scalar(block_text, "Branch")),
                    goal=_parse_multiline(block_text, "Goal") or "Not recorded",
                    acceptance_criteria=_parse_named_list(block_text, "Acceptance Criteria"),
                    changed_files=[_strip_backticks(item) for item in _parse_named_list(block_text, "Changed Files")],
                    validation=_parse_named_list(block_text, "Validation"),
                    decisions=_parse_named_list(block_text, "Decisions"),
                    reusable_learnings=_parse_named_list(block_text, "Reusable Learnings"),
                    risks=_parse_named_list(block_text, "Risks"),
                )
            )
        return tasks

    def _sanitize_memory(self, memory: RepositoryMemory) -> RepositoryMemory:
        memory.current_summary = _dedupe(memory.current_summary, max_items=8)
        memory.user_preferences = _dedupe(memory.user_preferences, max_items=12)
        memory.active_conventions = _dedupe(memory.active_conventions, max_items=12)
        memory.repository_learnings = _dedupe(memory.repository_learnings, max_items=40)
        memory.useful_commands = _dedupe(memory.useful_commands, max_items=12)
        memory.active_decisions = _dedupe(memory.active_decisions, max_items=20)
        memory.known_risks = _dedupe(memory.known_risks, max_items=20)
        sanitized_tasks = []
        for task in memory.completed_tasks:
            task.title = _safe_text(task.title, max_chars=160) or "Repository task"
            task.goal = _safe_text(task.goal, max_chars=500) or "Not recorded"
            task.acceptance_criteria = _dedupe(task.acceptance_criteria, max_items=20)
            task.changed_files = _dedupe(task.changed_files, max_items=40)
            task.validation = _dedupe([_sanitize_validation(item) for item in task.validation], max_items=20)
            task.decisions = _dedupe(task.decisions, max_items=12)
            task.reusable_learnings = _dedupe(task.reusable_learnings, max_items=20)
            task.risks = _dedupe(task.risks, max_items=12)
            sanitized_tasks.append(task)
        memory.completed_tasks = sanitized_tasks
        return memory

    def _is_structured_memory(self, path: Path) -> bool:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception:
            return False
        return content.startswith("---\n") and "# Repository Memory" in content

    def _archive_legacy_memory(self, path: Path, repo_agent_id: str) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        archive_path = self.archive_dir / ("%s-legacy-%s.md" % (repo_agent_id, _archive_timestamp()))
        path.replace(archive_path)

    def _archive_tasks(self, repo_agent_id: str, tasks: List[CompletedTaskMemory]) -> None:
        self.archive_dir.mkdir(parents=True, exist_ok=True)
        archive_memory = RepositoryMemory(
            front_matter=MemoryFrontMatter(
                repo_agent_id=repo_agent_id,
                repo_id="archive",
                user_id="demo",
            ),
            completed_tasks=tasks,
        )
        archive_path = self.archive_dir / ("%s-%s.md" % (repo_agent_id, _archive_timestamp()))
        archive_path.write_text(self._render_markdown(archive_memory), encoding="utf-8")


def _section_content(body: str, section_title: str) -> str:
    pattern = r"^## %s\s*\n(.*?)(?=^## |\Z)" % re.escape(section_title)
    match = re.search(pattern, body, flags=re.MULTILINE | re.DOTALL)
    return match.group(1).strip() if match else ""


def _parse_task_heading(heading: str) -> Tuple[datetime, str]:
    if " - " in heading:
        raw_dt, title = heading.split(" - ", 1)
    else:
        raw_dt, title = heading, "Repository task"
    return _parse_dt(raw_dt.strip()), title.strip()


def _parse_scalar(block_text: str, label: str) -> Optional[str]:
    match = re.search(r"^%s:\s*(.*)$" % re.escape(label), block_text, flags=re.MULTILINE)
    if not match:
        return None
    return match.group(1).strip()


def _parse_multiline(block_text: str, label: str) -> str:
    match = re.search(
        r"^%s:\s*\n(.*?)(?=^[A-Z][A-Za-z ]+:\s*$|^[A-Z][A-Za-z ]+:\s*|\Z)"
        % re.escape(label),
        block_text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def _parse_named_list(block_text: str, label: str) -> List[str]:
    content = _parse_multiline(block_text, label)
    items = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        value = stripped[2:].strip()
        if value.lower() == "none recorded.":
            continue
        items.append(value)
    return _dedupe(items)


def _render_inline_list(items: List[str]) -> List[str]:
    if not items:
        return ["- None recorded."]
    return ["- %s" % item for item in items]


def _format_commands(commands: List[str]) -> List[str]:
    return ["`%s`" % _strip_backticks(item) for item in commands]


def _format_paths(paths: List[str]) -> List[str]:
    return ["`%s`" % _strip_backticks(item) for item in paths]


def _dedupe(items: Iterable[Optional[str]], max_items: Optional[int] = None) -> List[str]:
    seen = set()
    result = []
    for item in items:
        cleaned = _safe_text(item)
        if not cleaned:
            continue
        key = _dedupe_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if max_items is not None and len(result) >= max_items:
            break
    return result


def _safe_text(value: Optional[str], max_chars: int = 500) -> Optional[str]:
    if value is None:
        return None
    cleaned = " ".join(str(value).replace("\x00", "").split())
    if not cleaned:
        return None
    if _looks_sensitive(cleaned) or _looks_like_patch(cleaned):
        return None
    if len(cleaned) > 2000:
        return None
    if len(cleaned) > max_chars:
        cleaned = cleaned[: max_chars - 3].rstrip() + "..."
    return cleaned


def _looks_sensitive(value: str) -> bool:
    return any(pattern.search(value) for pattern in SECRET_PATTERNS)


def _looks_like_patch(value: str) -> bool:
    stripped = value.strip()
    return stripped.startswith(PATCH_PREFIXES)


def _dedupe_key(value: str) -> str:
    lowered = _strip_backticks(value).lower()
    lowered = re.sub(r"\s+", " ", lowered)
    return lowered.strip(" .")


def _strip_backticks(value: str) -> str:
    return value.strip().strip("`")


def _sanitize_validation(value: Optional[str]) -> Optional[str]:
    cleaned = _safe_text(value, max_chars=240)
    if cleaned is None:
        return None
    command = _extract_command_from_validation(cleaned)
    exit_code = _extract_exit_code(cleaned)
    if command and exit_code is not None:
        return "command=%s exit_code=%s" % (command, exit_code)
    if command:
        return "command=%s" % command
    return cleaned


def _extract_command_from_validation(value: str) -> Optional[str]:
    match = re.search(r"command=([^=]+?)(?:\s+exit_code=|\s+stdout=|\s+stderr=|$)", value)
    if match:
        return _strip_backticks(match.group(1).strip())
    if ":" in value:
        candidate = value.split(":", 1)[0].strip()
        if candidate:
            return _strip_backticks(candidate)
    return None


def _extract_exit_code(value: str) -> Optional[str]:
    match = re.search(r"exit_code=([0-9]+)", value)
    return match.group(1) if match else None


def _extract_preferences(values: Iterable[str]) -> List[str]:
    preferences = []
    for value in values:
        for line in str(value).splitlines():
            stripped = line.strip("- ").strip()
            lowered = stripped.lower()
            if "prefer" in lowered or "ask before" in lowered or "approval" in lowered:
                preferences.append(stripped)
    return _dedupe(preferences, max_items=12)


def _extract_decisions(values: Iterable[str]) -> List[str]:
    decisions = []
    for value in values:
        for line in str(value).splitlines():
            stripped = line.strip("-0123456789. ").strip()
            lowered = stripped.lower()
            if lowered.startswith(("use ", "do not ", "don't ", "prefer ", "keep ", "no ")):
                decisions.append(stripped)
            if lowered.startswith(("decision:", "decisions:")):
                after = stripped.split(":", 1)[1].strip()
                if after:
                    decisions.append(after)
    return _dedupe(decisions, max_items=20)


def _extract_reusable_learnings(
    task_states: List[TaskAgentState],
    changed_files: Iterable[str],
) -> List[str]:
    learnings = []
    for task in task_states:
        learnings.extend(_extract_tagged_items(task.result_summary or "", "reusable learning"))
        learnings.extend(_extract_tagged_items(task.result_summary or "", "repository learning"))
    for path in changed_files:
        learnings.append("Recent implementation touched `%s`." % path)
    return _dedupe(learnings, max_items=20)


def _extract_risks(
    task_states: List[TaskAgentState],
    final_report: Optional[str],
) -> List[str]:
    risks = []
    for task in task_states:
        risks.extend(_extract_tagged_items(task.result_summary or "", "risk"))
        if task.last_error:
            risks.append(task.last_error)
    risks.extend(_extract_tagged_items(final_report or "", "risk"))
    return _dedupe(risks, max_items=12)


def _extract_tagged_items(text: str, label: str) -> List[str]:
    items = []
    active = False
    label_re = re.compile(r"^%ss?:\s*(.*)$" % re.escape(label), flags=re.IGNORECASE)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            active = False
            continue
        match = label_re.match(line)
        if match:
            active = True
            inline = match.group(1).strip()
            if inline:
                items.append(inline.strip("- "))
            continue
        if active and line.startswith("- "):
            items.append(line[2:].strip())
        elif ":" in line and line.split(":", 1)[0].strip().lower() != label:
            active = False
    return _dedupe(items)


def _extract_commands(validation_items: Iterable[str]) -> List[str]:
    commands = []
    for item in validation_items:
        command = _extract_command_from_validation(item)
        if command:
            commands.append(command)
    return _dedupe(commands, max_items=12)


def _format_dt(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_dt(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    return datetime.fromisoformat(raw)


def _archive_timestamp() -> str:
    return _format_dt(utc_now()).replace(":", "").replace("-", "")


def _none_if_unset(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return None if value.lower() in {"not set", "none", ""} else value
