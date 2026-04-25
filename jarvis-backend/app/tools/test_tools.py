from __future__ import annotations

from typing import Iterable


def command_is_allowed(command: str, allowed_commands: Iterable[str]) -> bool:
    stripped = " ".join(command.strip().split())
    if not stripped:
        return False
    for allowed in allowed_commands:
        allowed_clean = " ".join(allowed.strip().split())
        if stripped == allowed_clean or stripped.startswith(allowed_clean + " "):
            return True
    return False

