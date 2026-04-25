from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.models.repository import RepositoryAgentState
from app.models.task import TaskAgentState


class MarkdownMemoryStore:
    """Human-readable memory files for local demo sessions."""

    def __init__(self, memory_dir: str) -> None:
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

    def path_for_agent(self, repo_agent_id: str) -> Path:
        return self.memory_dir / ("%s.md" % repo_agent_id)

    def initialize_agent(self, state: RepositoryAgentState) -> None:
        path = self.path_for_agent(state.repo_agent_id)
        if path.exists():
            return
        content = [
            "# Jarvis Repository Agent Memory",
            "",
            "## Repository",
            "- repo_agent_id: `%s`" % state.repo_agent_id,
            "- repo_id: `%s`" % state.repo_id,
            "- repo_path: `%s`" % state.repo_path,
            "- thread_id: `%s`" % state.thread_id,
            "",
        ]
        path.write_text("\n".join(content), encoding="utf-8")

    def append_section(self, repo_agent_id: str, title: str, body: str) -> None:
        path = self.path_for_agent(repo_agent_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n## %s\n%s\n" % (title, body.strip()))

    def append_task_result(self, task: TaskAgentState) -> None:
        body = [
            "- task_agent_id: `%s`" % task.task_agent_id,
            "- status: `%s`" % task.status.value,
            "- changed_files: `%s`" % ", ".join(task.changed_files),
            "",
            task.result_summary or "No summary generated.",
        ]
        self.append_section(task.repo_agent_id, "Task: %s" % task.title, "\n".join(body))

    def read_summary(self, repo_agent_id: str, max_chars: Optional[int] = 12000) -> str:
        path = self.path_for_agent(repo_agent_id)
        if not path.exists():
            return ""
        content = path.read_text(encoding="utf-8")
        if max_chars is None or len(content) <= max_chars:
            return content
        return content[-max_chars:]

