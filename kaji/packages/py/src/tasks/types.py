"""Public task projection types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from kaji.artifacts import ArtifactRef


class TaskState(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_FOR_APPROVAL = "waiting_for_approval"
    SUSPENDED = "suspended"
    RECONCILIATION_REQUIRED = "reconciliation_required"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class PendingApprovalSummary:
    id: str
    capability: str
    risk: str


@dataclass(frozen=True, slots=True)
class PendingApproval(PendingApprovalSummary):
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    task_id: str
    state: TaskState
    sequence_cursor: int
    created_at: str
    updated_at: str
    artifacts: tuple[ArtifactRef, ...]
    terminal_error_code: str | None
    pending_approvals: tuple[PendingApprovalSummary, ...]
