from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.turns import utc_now


class MemoryFrontMatter(BaseModel):
    repo_agent_id: str
    repo_id: str
    user_id: str = "demo"
    memory_version: int = 1
    last_updated: datetime = Field(default_factory=utc_now)


class CompletedTaskMemory(BaseModel):
    completed_at: datetime = Field(default_factory=utc_now)
    title: str
    status: str = "completed"
    branch_name: Optional[str] = None
    goal: str
    acceptance_criteria: List[str] = Field(default_factory=list)
    changed_files: List[str] = Field(default_factory=list)
    validation: List[str] = Field(default_factory=list)
    decisions: List[str] = Field(default_factory=list)
    reusable_learnings: List[str] = Field(default_factory=list)
    risks: List[str] = Field(default_factory=list)


class RepositoryMemory(BaseModel):
    front_matter: MemoryFrontMatter
    current_summary: List[str] = Field(default_factory=list)
    user_preferences: List[str] = Field(default_factory=list)
    active_conventions: List[str] = Field(default_factory=list)
    repository_learnings: List[str] = Field(default_factory=list)
    useful_commands: List[str] = Field(default_factory=list)
    active_decisions: List[str] = Field(default_factory=list)
    known_risks: List[str] = Field(default_factory=list)
    completed_tasks: List[CompletedTaskMemory] = Field(default_factory=list)


class RenderedMemoryView(BaseModel):
    text: str
    truncated: bool = False
    source_path: str
    char_count: int

