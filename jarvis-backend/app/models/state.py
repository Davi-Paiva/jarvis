from __future__ import annotations

from enum import Enum


class RepositoryAgentPhase(str, Enum):
    INTAKE = "INTAKE"
    PLANNING = "PLANNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    FINALIZING = "FINALIZING"
    DONE = "DONE"
    FAILED = "FAILED"


class TaskAgentStatus(str, Enum):
    CREATED = "CREATED"
    INSPECTING = "INSPECTING"
    WORKING = "WORKING"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    VALIDATING = "VALIDATING"
    DONE = "DONE"
    FAILED = "FAILED"
    DEAD = "DEAD"

