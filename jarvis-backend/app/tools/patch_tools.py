from __future__ import annotations

from typing import Iterable, List


def path_is_in_scope(path: str, scope: Iterable[str]) -> bool:
    scope_list = [item.strip().strip("/") for item in scope if item.strip()]
    if not scope_list:
        return True
    normalized = path.strip().strip("/")
    return any(normalized == item or normalized.startswith(item + "/") for item in scope_list)


def paths_outside_scope(paths: Iterable[str], scope: Iterable[str]) -> List[str]:
    return [path for path in paths if not path_is_in_scope(path, scope)]

