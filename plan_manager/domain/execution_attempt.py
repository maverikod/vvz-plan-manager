"""Execution attempt domain: per-run record of a real execution; never a correctness certificate (C-016)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity, ReferenceCheck
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
class ExecutionAttempt(DataclassEntity):
    ENTITY_TYPE = "execution_attempt"
    ENTITY_ID_FIELD = "attempt_uuid"
    TABLE_NAME = "execution_attempt"
    HARD_DELETE_REFERENCE_CHECKS = (
        # source_column is "uuid", not the dataclass field "attempt_uuid": find_entity_reference_counts
        # (plan_manager/domain/entity.py) builds id_values from DataclassEntity.get_by_id's row, whose
        # keys are the raw execution_attempt DB columns (PK column is literally "uuid") — not the
        # dataclass's ENTITY_ID_FIELD name. A source_column of "attempt_uuid" here is a KeyError (bug e52daeab).
        ReferenceCheck("runtime_comment", "anchor_ref_id", "uuid", live_column="deleted_at"),
        ReferenceCheck("review_result", "reviewed_attempt_uuid", "uuid", live_column="deleted_at"),
        ReferenceCheck("execution_attempt", "parent_attempt_uuid", "uuid", live_column="deleted_at"),
    )

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
    acct_tokens_in: int | None
    acct_tokens_out: int | None
    acct_provider: str | None
    acct_model: str | None
    acct_wall_ms: int | None
    acct_cost_estimate: float | None
    transcript_ref: str | None
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
        pass through unchanged, the typed accounting columns and transcript_ref pass
        through unchanged (already JSON-safe scalars), and timestamp fields are already
        ISO strings."""
        return {
            "uuid": str(self.attempt_uuid),
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
            "acct_tokens_in": self.acct_tokens_in,
            "acct_tokens_out": self.acct_tokens_out,
            "acct_provider": self.acct_provider,
            "acct_model": self.acct_model,
            "acct_wall_ms": self.acct_wall_ms,
            "acct_cost_estimate": self.acct_cost_estimate,
            "transcript_ref": self.transcript_ref,
            "error": self.error,
            "escalation_reason": self.escalation_reason,
            "parent_attempt_uuid": str(self.parent_attempt_uuid) if self.parent_attempt_uuid is not None else None,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


RESOURCE_ACCOUNTING_KEYS: frozenset[str] = frozenset(
    {"tokens_in", "tokens_out", "provider", "model", "wall_ms", "cost_estimate"}
)


@dataclass(frozen=True)
class ResourceAccounting:
    """Typed execution-accounting value object (C-013): validated token counts, provider,
    model, wall-clock milliseconds, and an optional cost estimate for one execution attempt."""
    tokens_in: int
    tokens_out: int
    provider: str
    model: str
    wall_ms: int
    cost_estimate: float | None


def validate_resource_accounting(value: dict[str, Any]) -> dict[str, Any]:
    """Validate a candidate execution-accounting dict against the typed ResourceAccounting
    schema (C-013).

    Parameters:
        value: Candidate dict; must have exactly the six keys tokens_in, tokens_out,
            provider, model, wall_ms, cost_estimate.

    Returns:
        The validated dict, unchanged.

    Raises:
        RuntimeValidationError: If value is not a dict; if its keys are not exactly
            {tokens_in, tokens_out, provider, model, wall_ms, cost_estimate}; if
            tokens_in, tokens_out, or wall_ms is not a non-negative int; if provider
            or model is not a non-empty str; or if cost_estimate is neither None nor
            a real number (int or float, not bool).
    """
    if not isinstance(value, dict):
        raise RuntimeValidationError(f"resource_accounting must be a dict, got {type(value).__name__}")
    actual_keys = set(value.keys())
    if actual_keys != RESOURCE_ACCOUNTING_KEYS:
        missing = RESOURCE_ACCOUNTING_KEYS - actual_keys
        unknown = actual_keys - RESOURCE_ACCOUNTING_KEYS
        raise RuntimeValidationError(
            f"resource_accounting must have exactly the keys {sorted(RESOURCE_ACCOUNTING_KEYS)}; "
            f"missing={sorted(missing)} unknown={sorted(unknown)}"
        )
    for int_key in ("tokens_in", "tokens_out", "wall_ms"):
        candidate = value[int_key]
        if isinstance(candidate, bool) or not isinstance(candidate, int) or candidate < 0:
            raise RuntimeValidationError(
                f"resource_accounting.{int_key} must be a non-negative int, got {candidate!r}"
            )
    for str_key in ("provider", "model"):
        candidate = value[str_key]
        if not isinstance(candidate, str) or candidate == "":
            raise RuntimeValidationError(
                f"resource_accounting.{str_key} must be a non-empty str, got {candidate!r}"
            )
    cost_estimate = value["cost_estimate"]
    if cost_estimate is not None:
        if isinstance(cost_estimate, bool) or not isinstance(cost_estimate, (int, float)):
            raise RuntimeValidationError(
                f"resource_accounting.cost_estimate must be None or a real number, got {cost_estimate!r}"
            )
    return value


def validate_transcript_ref(value: str) -> str:
    """Validate a candidate transcript reference (C-013 dialogue-chain id).

    Parameters:
        value: Candidate transcript reference string.

    Returns:
        The validated value, unchanged.

    Raises:
        RuntimeValidationError: If value is not a non-empty str.
    """
    if not isinstance(value, str) or value == "":
        raise RuntimeValidationError(f"transcript_ref must be a non-empty str, got {value!r}")
    return value


def validate_attempt_status(value: str) -> str:
    """Return value if it is a member of ATTEMPT_STATUSES, else raise RuntimeValidationError."""
    if value not in ATTEMPT_STATUSES:
        raise RuntimeValidationError(f"invalid execution attempt status: {value!r}; expected one of {sorted(ATTEMPT_STATUSES)}")
    return value


def is_terminal_status(status: str) -> bool:
    """Validate status, then return True only if it is one of the four terminal statuses
    (succeeded, failed, cancelled, timed_out)."""
    validate_attempt_status(status)
    return status in TERMINAL_ATTEMPT_STATUSES
