from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings
from app.services.local_executor import LocalExecutor


def test_executor_rejects_path_traversal_and_absolute_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "safe.txt").write_text("safe", encoding="utf-8")
    executor = LocalExecutor(_settings(tmp_path))

    assert executor.read_file(str(repo), "safe.txt") == "safe"

    try:
        executor.read_file(str(repo), "../secret.txt")
        raise AssertionError("path traversal should fail")
    except ValueError as exc:
        assert "escapes repository" in str(exc)

    try:
        executor.read_file(str(repo), str(repo / "safe.txt"))
        raise AssertionError("absolute path should fail")
    except ValueError as exc:
        assert "Absolute paths" in str(exc)


def test_executor_rejects_disallowed_commands(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    executor = LocalExecutor(_settings(tmp_path))

    async def scenario():
        try:
            await executor.run_allowed_command(str(repo), "rm -rf .")
            raise AssertionError("disallowed command should fail")
        except ValueError as exc:
            assert "not allowed" in str(exc)

    asyncio.run(scenario())


def test_executor_skips_large_generated_directories(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('ok')", encoding="utf-8")
    (repo / "node_modules").mkdir()
    (repo / "node_modules" / "dep.js").write_text("bad", encoding="utf-8")

    executor = LocalExecutor(_settings(tmp_path))

    assert executor.list_files(str(repo)) == ["src/app.py"]


def _settings(tmp_path):
    return Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
    )

