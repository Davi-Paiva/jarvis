from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TurnType(str, Enum):
    INTAKE = "INTAKE"
    BLOCKING_QUESTION = "BLOCKING_QUESTION"
    APPROVAL = "APPROVAL"
    COMPLETION = "COMPLETION"
    PROGRESS = "PROGRESS"


class TurnRequest(BaseModel):
    id: str = Field(default_factory=lambda: "turn_" + uuid4().hex)
    user_id: str = "demo"
    agent_id: str
    repo_agent_id: str
    type: TurnType
    priority: int
    message: str
    context: str = ""
    created_at: datetime = Field(default_factory=utc_now)
    requires_user_response: bool = False
    handled: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TurnResponse(BaseModel):
    turn_id: str
    response: str
    approved: Optional[bool] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

