from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.repository import RepositoryAgentState
from app.models.turns import TurnRequest


class CreateRepoAgentInput(BaseModel):
    repo_path: str
    display_name: Optional[str] = None
    branch_name: Optional[str] = None


class CreateRepoAgentOutput(BaseModel):
    repo_agent_id: str
    repo_id: str
    thread_id: str
    phase: str


class StartTaskInput(BaseModel):
    message: str
    acceptance_criteria: List[str] = Field(default_factory=list)


class UserResponseInput(BaseModel):
    response: str
    approved: Optional[bool] = None


class AgentStateOutput(BaseModel):
    agent: RepositoryAgentState
    next_turn: Optional[TurnRequest] = None

