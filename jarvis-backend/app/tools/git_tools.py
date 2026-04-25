from __future__ import annotations

import re
from typing import List, Set


BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,120}$")


def is_safe_branch_name(branch_name: str) -> bool:
    if not BRANCH_RE.match(branch_name):
        return False
    blocked = ["..", "@{", "\\", " ", "~", "^", ":", "?", "*", "["]
    return not any(part in branch_name for part in blocked)


def changed_paths_from_patch(patch_text: str) -> List[str]:
    paths: Set[str] = set()
    for line in patch_text.splitlines():
        if line.startswith("diff --git "):
            pieces = line.split()
            for piece in pieces[2:4]:
                cleaned = _clean_patch_path(piece)
                if cleaned:
                    paths.add(cleaned)
        elif line.startswith("+++ ") or line.startswith("--- "):
            cleaned = _clean_patch_path(line[4:].strip())
            if cleaned:
                paths.add(cleaned)
    return sorted(paths)


def _clean_patch_path(raw_path: str) -> str:
    if raw_path == "/dev/null":
        return ""
    if raw_path.startswith("a/") or raw_path.startswith("b/"):
        raw_path = raw_path[2:]
    return raw_path.strip()

