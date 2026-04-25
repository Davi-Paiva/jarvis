from __future__ import annotations

import asyncio
import os
import shlex
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from app.config import Settings
from app.tools.git_tools import changed_paths_from_patch, is_safe_branch_name
from app.tools.patch_tools import paths_outside_scope
from app.tools.search_tools import should_skip_path
from app.tools.test_tools import command_is_allowed


class LocalExecutor:
    """Safe-ish local executor for repository-scoped filesystem operations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._repo_locks: Dict[str, asyncio.Lock] = {}

    def list_files(self, repo_path: str, max_files: int = 300) -> List[str]:
        root = self._assert_repo_allowed(repo_path)
        files: List[str] = []
        for path in root.rglob("*"):
            if path.is_symlink():
                continue
            if should_skip_path(path.relative_to(root)):
                continue
            if path.is_file():
                files.append(str(path.relative_to(root)))
            if len(files) >= max_files:
                break
        return sorted(files)

    def read_file(self, repo_path: str, relative_path: str, max_chars: int = 20000) -> str:
        path = self._resolve_inside_repo(repo_path, relative_path)
        if not path.is_file():
            raise ValueError("Path is not a file: %s" % relative_path)
        content = path.read_text(encoding="utf-8", errors="replace")
        return content[:max_chars]

    def search_code(self, repo_path: str, query: str, max_matches: int = 50) -> List[str]:
        root = self._assert_repo_allowed(repo_path)
        matches: List[str] = []
        for relative in self.list_files(repo_path):
            try:
                content = self.read_file(str(root), relative)
            except Exception:
                continue
            if query in content:
                matches.append(relative)
            if len(matches) >= max_matches:
                break
        return matches

    async def apply_patch(
        self,
        repo_path: str,
        patch_text: str,
        scope: Optional[Iterable[str]] = None,
    ) -> List[str]:
        root = self._assert_repo_allowed(repo_path)
        normalized_patch = _normalize_patch_text(patch_text)
        changed_paths = changed_paths_from_patch(normalized_patch)
        if not changed_paths:
            raise ValueError(
                "Generated patch did not contain a valid git diff. "
                "Expected unified diff content with file headers."
            )
        outside_scope = paths_outside_scope(changed_paths, scope or [])
        if outside_scope:
            raise ValueError("Patch touches files outside task scope: %s" % outside_scope)
        for changed_path in changed_paths:
            self._resolve_inside_repo(repo_path, changed_path)

        async with self._lock_for_repo(root):
            check = await self._run_process(
                ["git", "apply", "--check", "-"],
                cwd=str(root),
                stdin=normalized_patch,
            )
            if check[0] != 0:
                raise RuntimeError("Patch check failed: %s" % check[2])
            result = await self._run_process(
                ["git", "apply", "-"],
                cwd=str(root),
                stdin=normalized_patch,
            )
            if result[0] != 0:
                raise RuntimeError("Patch apply failed: %s" % result[2])
        return changed_paths

    async def run_allowed_command(
        self,
        repo_path: str,
        command: str,
        timeout_seconds: int = 120,
    ) -> Tuple[int, str, str]:
        root = self._assert_repo_allowed(repo_path)
        if (
            not self.settings.jarvis_allow_all_commands
            and not command_is_allowed(command, self.settings.jarvis_allowed_commands)
        ):
            raise ValueError("Command is not allowed: %s" % command)
        args = shlex.split(command)
        return await asyncio.wait_for(
            self._run_process(args, cwd=str(root)),
            timeout=timeout_seconds,
        )

    async def create_branch(self, repo_path: str, branch_name: str) -> Tuple[int, str, str]:
        root = self._assert_repo_allowed(repo_path)
        if not is_safe_branch_name(branch_name):
            raise ValueError("Unsafe branch name: %s" % branch_name)
        async with self._lock_for_repo(root):
            return await self._run_process(["git", "checkout", "-b", branch_name], cwd=str(root))

    async def git_status(self, repo_path: str) -> Tuple[int, str, str]:
        root = self._assert_repo_allowed(repo_path)
        return await self._run_process(["git", "status", "--short"], cwd=str(root))

    async def git_diff(self, repo_path: str) -> Tuple[int, str, str]:
        root = self._assert_repo_allowed(repo_path)
        return await self._run_process(["git", "diff"], cwd=str(root))

    def _assert_repo_allowed(self, repo_path: str) -> Path:
        root = Path(repo_path).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise ValueError("Repository path does not exist or is not a directory: %s" % repo_path)
        allowed_roots = self._allowed_roots()
        if allowed_roots and not any(_is_relative_to(root, allowed) for allowed in allowed_roots):
            raise ValueError("Repository path is outside allowed roots: %s" % repo_path)
        return root

    def _resolve_inside_repo(self, repo_path: str, relative_path: str) -> Path:
        if Path(relative_path).is_absolute():
            raise ValueError("Absolute paths are not allowed: %s" % relative_path)
        root = self._assert_repo_allowed(repo_path)
        path = (root / relative_path).resolve()
        if not _is_relative_to(path, root):
            raise ValueError("Path escapes repository: %s" % relative_path)
        return path

    def _allowed_roots(self) -> List[Path]:
        roots = []
        for raw_root in self.settings.jarvis_allowed_repo_roots:
            path = Path(raw_root).expanduser()
            if path.exists():
                roots.append(path.resolve())
        return roots

    def _lock_for_repo(self, root: Path) -> asyncio.Lock:
        key = str(root)
        if key not in self._repo_locks:
            self._repo_locks[key] = asyncio.Lock()
        return self._repo_locks[key]

    async def _run_process(
        self,
        args: List[str],
        cwd: str,
        stdin: Optional[str] = None,
    ) -> Tuple[int, str, str]:
        process = await asyncio.create_subprocess_exec(
            *args,
            cwd=cwd,
            stdin=asyncio.subprocess.PIPE if stdin is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await process.communicate(
            stdin.encode("utf-8") if stdin is not None else None
        )
        return (
            process.returncode or 0,
            stdout_bytes.decode("utf-8", errors="replace"),
            stderr_bytes.decode("utf-8", errors="replace"),
        )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        common = os.path.commonpath([str(path), str(root)])
    except ValueError:
        return False
    return common == str(root)


def _normalize_patch_text(patch_text: str) -> str:
    text = patch_text.strip()
    if not text:
        return ""

    lines = text.splitlines()

    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
        while lines and lines[-1].strip() == "":
            lines.pop()
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]

    start_index = None
    for index, line in enumerate(lines):
        if line.startswith("diff --git ") or line.startswith("--- "):
            start_index = index
            break
    if start_index is not None:
        lines = lines[start_index:]

    while lines and lines[-1].strip() in {"", "```"}:
        lines.pop()

    normalized = "\n".join(lines).strip()
    if not normalized:
        return ""
    return normalized + "\n"
