from __future__ import annotations

from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.state import RepositoryAgentPhase
from app.models.turns import utc_now


class RepositoryRecord(BaseModel):
    repo_id: str = Field(default_factory=lambda: "repo_" + uuid4().hex)
    user_id: str = "demo"
    repo_path: str
    display_name: str
    created_at: datetime = Field(default_factory=utc_now)


class RepositoryAgentState(BaseModel):
    repo_agent_id: str = Field(default_factory=lambda: "repo_agent_" + uuid4().hex)
    user_id: str = "demo"
    repo_id: str
    repo_path: str
    branch_name: Optional[str] = None
    phase: RepositoryAgentPhase = RepositoryAgentPhase.INTAKE
    thread_id: str
    task_goal: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    plan: Optional[str] = None
    task_agents: List[str] = Field(default_factory=list)
    changed_files: List[str] = Field(default_factory=list)
    test_results: List[str] = Field(default_factory=list)
    final_report: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()

