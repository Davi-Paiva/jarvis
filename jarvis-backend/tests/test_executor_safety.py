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
    executor = LocalExecutor(_settings(tmp_path, allow_all_commands=False))

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


def test_executor_accepts_fenced_git_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    executor = LocalExecutor(_settings(tmp_path))

    patch_text = """```diff
diff --git a/hello.txt b/hello.txt
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+hola
```"""

    async def scenario():
        changed = await executor.apply_patch(str(repo), patch_text)
        assert changed == ["hello.txt"]
        assert (repo / "hello.txt").read_text(encoding="utf-8") == "hola\n"

    asyncio.run(scenario())


def test_executor_accepts_prose_before_git_diff(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    executor = LocalExecutor(_settings(tmp_path))

    patch_text = """Here is the requested patch:

diff --git a/hello.txt b/hello.txt
--- a/hello.txt
+++ b/hello.txt
@@ -1 +1 @@
-hello
+bonjour
"""

    async def scenario():
        changed = await executor.apply_patch(str(repo), patch_text)
        assert changed == ["hello.txt"]
        assert (repo / "hello.txt").read_text(encoding="utf-8") == "bonjour\n"

    asyncio.run(scenario())


def test_executor_rejects_non_diff_patch_text(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "hello.txt").write_text("hello\n", encoding="utf-8")
    executor = LocalExecutor(_settings(tmp_path))

    async def scenario():
        try:
            await executor.apply_patch(str(repo), "Please change hello.txt to say hola.")
            raise AssertionError("non-diff text should fail")
        except ValueError as exc:
            assert "valid git diff" in str(exc)

    asyncio.run(scenario())


def test_executor_allows_any_command_when_permissive_mode_is_on(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    executor = LocalExecutor(_settings(tmp_path, allow_all_commands=True))

    async def scenario():
        code, stdout, stderr = await executor.run_allowed_command(
            str(repo),
            "python3 -c \"print('ok')\"",
        )
        assert code == 0
        assert stdout.strip() == "ok"
        assert stderr.strip() == ""

    asyncio.run(scenario())


def test_executor_repairs_hunk_only_patch_for_single_scoped_file(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "training.py").write_text(
        "class TrainingRequest:\n"
        "    pass\n"
        "\n"
        "enabled = False\n",
        encoding="utf-8",
    )
    executor = LocalExecutor(_settings(tmp_path))

    patch_text = """@@ -1,4 +1,4 @@
-class TrainingRequest:
-    pass
+class TrainingRequest:
+    retries = 3
 
 enabled = False
"""

    async def scenario():
        changed = await executor.apply_patch(
            str(repo),
            patch_text,
            scope=["training.py"],
        )
        assert changed == ["training.py"]
        assert "retries = 3" in (repo / "training.py").read_text(encoding="utf-8")

    asyncio.run(scenario())


def test_executor_rejects_hunk_only_patch_without_single_file_scope(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "one.py").write_text("value = 1\n", encoding="utf-8")
    (repo / "two.py").write_text("value = 2\n", encoding="utf-8")
    executor = LocalExecutor(_settings(tmp_path))

    async def scenario():
        try:
            await executor.apply_patch(
                str(repo),
                "@@ -1 +1 @@\n-value = 1\n+value = 3\n",
                scope=["one.py", "two.py"],
            )
            raise AssertionError("ambiguous hunk-only patch should fail")
        except ValueError as exc:
            assert "without file headers" in str(exc)

    asyncio.run(scenario())


def _settings(tmp_path, allow_all_commands=True):
    return Settings(
        jarvis_data_dir=str(tmp_path / "data"),
        jarvis_db_path=str(tmp_path / "jarvis.db"),
        jarvis_memory_dir=str(tmp_path / "memory"),
        jarvis_allowed_repo_roots=[str(tmp_path)],
        jarvis_allow_all_commands=allow_all_commands,
    )
