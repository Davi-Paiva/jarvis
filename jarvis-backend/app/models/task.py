from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from app.models.state import TaskAgentStatus
from app.models.turns import utc_now


class TaskPlanItem(BaseModel):
    title: str
    description: str
    scope: List[str] = Field(default_factory=list)

    @field_validator("title", "description", mode="before")
    @classmethod
    def _normalize_text_field(cls, value):
        if value is None:
            return ""
        if isinstance(value, str):
            return value.strip()
        return str(value).strip()

    @field_validator("scope", mode="before")
    @classmethod
    def _normalize_scope(cls, value):
        return _coerce_scope_list(value)


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


def _coerce_scope_list(value) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return []
        if "\n" in normalized or "," in normalized:
            parts = re.split(r"[\n,]+", normalized)
            return _coerce_scope_list(parts)
        if not _looks_like_scope_path(normalized):
            return []
        return [normalized.strip("/\\")]
    if isinstance(value, dict):
        for key in ("scope", "scopes", "paths", "files", "modules"):
            if key in value:
                return _coerce_scope_list(value[key])
        return []
    if isinstance(value, (list, tuple, set)):
        items: List[str] = []
        for item in value:
            items.extend(_coerce_scope_list(item))
        deduped: List[str] = []
        seen = set()
        for item in items:
            if item and item not in seen:
                seen.add(item)
                deduped.append(item)
        return deduped
    return []


def _looks_like_scope_path(value: str) -> bool:
    return (
        "/" in value
        or "\\" in value
        or "." in value
        or value.startswith(("src", "app", "tests", "api", "services", "components"))
    )
