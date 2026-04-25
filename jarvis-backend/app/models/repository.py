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
    intent_type: Optional[str] = None
    original_user_prompt: Optional[str] = None
    requirements: List[str] = Field(default_factory=list)
    acceptance_criteria: List[str] = Field(default_factory=list)
    plan: Optional[str] = None
    planning_context: Optional[str] = None
    # Conversational flow v2 keeps branch intent separate from the active branch_name.
    branch_decision: Optional[str] = None
    requested_branch_name: Optional[str] = None
    confirmed_branch_name: Optional[str] = None
    branch_created: bool = False
    # Conversational flow v2 stores step-by-step review state independently from plan.
    plan_steps: List[dict] = Field(default_factory=list)
    current_plan_step_index: int = 0
    execution_approved: bool = False
    task_agents: List[str] = Field(default_factory=list)
    changed_files: List[str] = Field(default_factory=list)
    test_results: List[str] = Field(default_factory=list)
    last_explanation: Optional[str] = None
    final_report: Optional[str] = None
    last_error: Optional[str] = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    def touch(self) -> None:
        self.updated_at = utc_now()
