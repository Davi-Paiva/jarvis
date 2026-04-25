from __future__ import annotations

import re
import unicodedata
from enum import Enum
from typing import Optional

from pydantic import BaseModel


class VoiceCommandType(str, Enum):
    OPEN_REPO = "open_repo"
    SWITCH_REPO = "switch_repo"
    NEW_CHAT = "new_chat"
    END_CHAT = "end_chat"
    LIST_PENDING = "list_pending"
    APPROVE = "approve"
    REJECT = "reject"
    NONE = "none"


class VoiceCommand(BaseModel):
    type: VoiceCommandType = VoiceCommandType.NONE
    repo_query: Optional[str] = None
    raw_text: str = ""


OPEN_PATTERNS = [
    re.compile(r"^(?:abre|abrir|activa|activar|open|activate)\s+(?:el\s+)?(?:repo|repositorio|repository)\s+(.+)$"),
]

SWITCH_PATTERNS = [
    re.compile(r"^(?:cambia|cambiar|ve|ir|switch|go)\s+(?:al|a|to)?\s*(?:repo|repositorio|repository)?\s+(.+)$"),
]

NEW_CHAT_PATTERNS = [
    re.compile(r"^(?:nuevo|nueva|new)\s+(?:chat|conversation|conversacion|conversación)$"),
    re.compile(r"^(?:empieza|empezar|inicia|iniciar|start)\s+(?:un\s+)?(?:nuevo\s+)?(?:chat|conversation|conversacion|conversación)$"),
]

END_CHAT_PATTERNS = [
    re.compile(r"^(?:termina|terminar|finaliza|finalizar|cierra|close|end)\s+(?:el\s+)?(?:chat|conversation|conversacion|conversación)$"),
]

LIST_PENDING_PATTERNS = [
    re.compile(r"^(?:que|qué|show|list|what)\s+(?:pendientes?|pending|pending tasks|pending approvals)(?:\s+hay)?$"),
    re.compile(r"^(?:que|qué)\s+(?:hay\s+)?pendiente$"),
]

APPROVAL_WORDS = {"yes", "y", "si", "sí", "vale", "ok", "okay", "approve", "approved", "dale"}
REJECTION_WORDS = {"no", "cancel", "cancela", "rechaza", "reject", "deniega", "stop"}


class VoiceCommandRouter:
    def parse(self, text: str) -> VoiceCommand:
        normalized = _normalize_text(text)
        if not normalized:
            return VoiceCommand(raw_text=text)

        if normalized in APPROVAL_WORDS:
            return VoiceCommand(type=VoiceCommandType.APPROVE, raw_text=text)
        if normalized in REJECTION_WORDS:
            return VoiceCommand(type=VoiceCommandType.REJECT, raw_text=text)

        for pattern in OPEN_PATTERNS:
            match = pattern.match(normalized)
            if match:
                return VoiceCommand(
                    type=VoiceCommandType.OPEN_REPO,
                    repo_query=match.group(1).strip(),
                    raw_text=text,
                )

        for pattern in SWITCH_PATTERNS:
            match = pattern.match(normalized)
            if match:
                return VoiceCommand(
                    type=VoiceCommandType.SWITCH_REPO,
                    repo_query=match.group(1).strip(),
                    raw_text=text,
                )

        if any(pattern.match(normalized) for pattern in NEW_CHAT_PATTERNS):
            return VoiceCommand(type=VoiceCommandType.NEW_CHAT, raw_text=text)

        if any(pattern.match(normalized) for pattern in END_CHAT_PATTERNS):
            return VoiceCommand(type=VoiceCommandType.END_CHAT, raw_text=text)

        if any(pattern.match(normalized) for pattern in LIST_PENDING_PATTERNS):
            return VoiceCommand(type=VoiceCommandType.LIST_PENDING, raw_text=text)

        return VoiceCommand(raw_text=text)


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower().strip()
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized
