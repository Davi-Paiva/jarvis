from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.repository import RepositoryAgentState
from app.models.turns import TurnRequest


class ChatMessageRole(str, Enum):
    """Role of the message sender."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessage(BaseModel):
    """Represents a chat message."""
    role: ChatMessageRole
    content: str
    timestamp: Optional[str] = None
    message_id: Optional[str] = None


class CreateRepoAgentInput(BaseModel):
    repo_path: str
    display_name: Optional[str] = None
    branch_name: Optional[str] = None


class CreateRepoAgentOutput(BaseModel):
    repo_agent_id: str
    repo_id: str
    thread_id: str
    phase: str


class AnalyzeInput(BaseModel):
    fileName: Optional[str] = None
    content: Optional[str] = None
    diff: Optional[str] = None


class AnalyzeOutput(BaseModel):
    summary: str
    steps: List[str] = Field(default_factory=list)


class StartTaskInput(BaseModel):
    message: str
    acceptance_criteria: List[str] = Field(default_factory=list)


class UserResponseInput(BaseModel):
    response: str
    approved: Optional[bool] = None


class AgentStateOutput(BaseModel):
    agent: RepositoryAgentState
    next_turn: Optional[TurnRequest] = None

