from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.state import TaskAgentStatus
from app.models.turns import utc_now


class TaskPlanItem(BaseModel):
    title: str
    description: str
    scope: List[str] = Field(default_factory=list)


class TaskAgentState(BaseModel):
    task_agent_id: str = Field(default_factory=lambda: "task_agent_" + uuid4().hex)
    repo_agent_id: str
    title: str
    description: str
    scope: List[str] = Field(default_factory=list)
    status: TaskAgentStatus = TaskAgentStatus.CREATED
    proposed_patch: Optional[str] = None
    changed_files: List[str] = Field(default_factory=list)
    test_results: List[str] = Field(default_factory=list)
    blocking_question: Optional[str] = None
    result_summary: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()

