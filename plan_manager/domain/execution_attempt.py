"""Execution attempt domain: per-run record of a real execution; never a correctness certificate (C-016)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.runtime_validation import RuntimeValidationError


class ExecutionAttemptStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    NEEDS_REVIEW = "needs_review"
    NEEDS_ESCALATION = "needs_escalation"


ATTEMPT_STATUSES: frozenset[str] = frozenset(s.value for s in ExecutionAttemptStatus)
TERMINAL_ATTEMPT_STATUSES: frozenset[str] = frozenset({"succeeded", "failed", "cancelled", "timed_out"})


@dataclass(frozen=True)
class ExecutionAttempt:
    attempt_uuid: uuid.UUID
    plan_uuid: uuid.UUID
    revision_uuid: uuid.UUID | None
    step_uuid: uuid.UUID
    step_path: str | None
    todo_uuid: uuid.UUID | None
    bug_fix_uuid: uuid.UUID | None
    assigned_binding_uuid: uuid.UUID | None
    assigned_provider: str | None
    assigned_model: str | None
    used_provider: str | None
    used_model: str | None
    runtime: str | None
    vast_instance_id: str | None
    started_at: str | None
    finished_at: str | None
    status: str
    input_context_hash: str | None
    result_summary: str | None
    changed_files: list[Any] | None
    command_test_results: dict[str, Any] | None
    resource_accounting: dict[str, Any] | None
    error: str | None
    escalation_reason: str | None
    parent_attempt_uuid: uuid.UUID | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render this record as a JSON-safe dict: uuid fields become str or None,
        jsonb-backed fields (changed_files, command_test_results, resource_accounting)
        pass through unchanged, and timestamp fields are already ISO strings."""
        return {
            "attempt_uuid": str(self.attempt_uuid),
            "plan_uuid": str(self.plan_uuid),
            "revision_uuid": str(self.revision_uuid) if self.revision_uuid is not None else None,
            "step_uuid": str(self.step_uuid),
            "step_path": self.step_path,
            "todo_uuid": str(self.todo_uuid) if self.todo_uuid is not None else None,
            "bug_fix_uuid": str(self.bug_fix_uuid) if self.bug_fix_uuid is not None else None,
            "assigned_binding_uuid": str(self.assigned_binding_uuid) if self.assigned_binding_uuid is not None else None,
            "assigned_provider": self.assigned_provider,
            "assigned_model": self.assigned_model,
            "used_provider": self.used_provider,
            "used_model": self.used_model,
            "runtime": self.runtime,
            "vast_instance_id": self.vast_instance_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "input_context_hash": self.input_context_hash,
            "result_summary": self.result_summary,
            "changed_files": self.changed_files,
            "command_test_results": self.command_test_results,
            "resource_accounting": self.resource_accounting,
            "error": self.error,
            "escalation_reason": self.escalation_reason,
            "parent_attempt_uuid": str(self.parent_attempt_uuid) if self.parent_attempt_uuid is not None else None,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_attempt_status(value: str) -> str:
    """Return value if it is a member of ATTEMPT_STATUSES, else raise RuntimeValidationError."""
    if value not in ATTEMPT_STATUSES:
        raise RuntimeValidationError(f"invalid execution attempt status: {value!r}")
    return value


def is_terminal_status(status: str) -> bool:
    """Validate status, then return True only if it is one of the four terminal statuses
    (succeeded, failed, cancelled, timed_out)."""
    validate_attempt_status(status)
    return status in TERMINAL_ATTEMPT_STATUSES
