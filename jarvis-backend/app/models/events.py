from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.turns import utc_now


class ManagerEventType(str, Enum):
    TURN_CREATED = "turn.created"
    USER_RESPONSE_RECEIVED = "user_response.received"
    AGENT_PROGRESS = "agent.progress"
    APPROVAL_REQUIRED = "approval.required"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"


class ManagerEvent(BaseModel):
    id: str = Field(default_factory=lambda: "evt_" + uuid4().hex)
    type: ManagerEventType
    repo_agent_id: Optional[str] = None
    task_agent_id: Optional[str] = None
    turn_id: Optional[str] = None
    message: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

