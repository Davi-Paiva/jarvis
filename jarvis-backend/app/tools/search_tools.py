from __future__ import annotations

from pathlib import Path


SKIPPED_PARTS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    "node_modules",
    ".next",
    ".turbo",
    ".cache",
}


def should_skip_path(path: Path) -> bool:
    return any(part in SKIPPED_PARTS for part in path.parts)

