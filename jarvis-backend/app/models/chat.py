from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.turns import utc_now


class ChatSessionStatus(str, Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class ChatMessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatSession(BaseModel):
    chat_id: str = Field(default_factory=lambda: "chat_" + uuid4().hex)
    repo_agent_id: str
    user_id: str = "demo"
    status: ChatSessionStatus = ChatSessionStatus.ACTIVE
    title: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    closed_at: Optional[datetime] = None

    def touch(self) -> None:
        self.updated_at = utc_now()

    def close(self) -> None:
        self.status = ChatSessionStatus.CLOSED
        self.closed_at = utc_now()
        self.touch()


class ChatMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: "chatmsg_" + uuid4().hex)
    chat_id: str
    repo_agent_id: str
    user_id: str = "demo"
    role: ChatMessageRole
    content: str
    turn_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)
