"""Bug report domain: the discovered-defect entity, distinct from TODOs and fix attempts (C-020)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity, ReferenceCheck
from plan_manager.domain.runtime_validation import RuntimeValidationError


class BugKind(str, Enum):
    FUNCTIONAL = "functional"
    WRONG_OUTPUT = "wrong_output"
    DATA_LOSS = "data_loss"
    REGRESSION = "regression"
    COMPATIBILITY = "compatibility"
    STALE_CONTEXT = "stale_context"
    PLANNING = "planning"
    PERFORMANCE = "performance"
    SECURITY = "security"
    INFRASTRUCTURE = "infrastructure"
    DEPLOYMENT = "deployment"
    CONFIGURATION = "configuration"
    DOCUMENTATION = "documentation"
    USER_EXPERIENCE = "user_experience"


class BugSeverity(str, Enum):
    BLOCKER = "blocker"
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    TRIVIAL = "trivial"


class BugStatus(str, Enum):
    REPORTED = "reported"
    TRIAGED = "triaged"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    DUPLICATE = "duplicate"
    FIXING = "fixing"
    FIXED_SOURCE = "fixed_source"
    PROPAGATING = "propagating"
    VERIFIED = "verified"
    CLOSED = "closed"
    REOPENED = "reopened"


BUG_KINDS: frozenset[str] = frozenset(k.value for k in BugKind)
BUG_SEVERITIES: frozenset[str] = frozenset(s.value for s in BugSeverity)
BUG_STATUSES: frozenset[str] = frozenset(s.value for s in BugStatus)


@dataclass(frozen=True)
class BugReport(DataclassEntity):
    ENTITY_TYPE = "bug"
    ENTITY_ID_FIELD = "bug_uuid"
    TABLE_NAME = "bug_report"
    # Compact view=summary projection (bug 8a13977d): drops short/detailed_description,
    # expected/actual_behavior, reproduction, evidence, and environment -- the
    # free-text fields that dominate a bug row's size.
    SUMMARY_FIELDS = (
        "uuid",
        "bug_uuid",
        "title",
        "kind",
        "severity",
        "status",
        "priority_nice",
        "source_anchor_type",
        "source_ref_id",
        "updated_at",
    )
    HARD_DELETE_REFERENCE_CHECKS = (
        # source_column is "uuid", not the dataclass field "bug_uuid": find_entity_reference_counts
        # (plan_manager/domain/entity.py) builds id_values from DataclassEntity.get_by_id's row, whose
        # keys are the raw bug_report DB columns (PK column is literally "uuid") — not the dataclass's
        # ENTITY_ID_FIELD name. A source_column of "bug_uuid" here is a KeyError (bug e52daeab).
        ReferenceCheck("runtime_comment", "anchor_ref_id", "uuid", live_column="deleted_at"),
        ReferenceCheck("bug_report", "duplicate_of_uuid", "uuid", live_column="deleted_at"),
        ReferenceCheck("bug_report", "parent_bug_uuid", "uuid", live_column="deleted_at"),
        ReferenceCheck("bug_impact", "bug_uuid", "uuid", live_column="deleted_at"),
        ReferenceCheck("bug_fix", "bug_uuid", "uuid", live_column="deleted_at"),
    )

    bug_uuid: uuid.UUID
    title: str
    short_description: str
    detailed_description: str
    expected_behavior: str | None
    actual_behavior: str | None
    reproduction: str | None
    evidence: dict[str, Any] | None
    environment: str | None
    kind: str
    severity: str
    priority_nice: int
    status: str
    reporter: str
    owner: str | None
    duplicate_of_uuid: uuid.UUID | None
    parent_bug_uuid: uuid.UUID | None
    source_anchor_type: str
    source_project_id: uuid.UUID | None
    source_file_path: str | None
    source_plan_uuid: uuid.UUID | None
    source_revision_uuid: uuid.UUID | None
    source_step_uuid: uuid.UUID | None
    source_step_path: str | None
    source_ref_id: uuid.UUID | None
    source_command: str | None
    source_service: str | None
    confirmed_at: str | None
    closed_at: str | None
    reopened_at: str | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Convert BugReport to a dictionary payload with UUIDs as strings."""
        return {
            "uuid": str(self.bug_uuid),
            "bug_uuid": str(self.bug_uuid),
            "title": self.title,
            "short_description": self.short_description,
            "detailed_description": self.detailed_description,
            "expected_behavior": self.expected_behavior,
            "actual_behavior": self.actual_behavior,
            "reproduction": self.reproduction,
            "evidence": self.evidence,
            "environment": self.environment,
            "kind": self.kind,
            "severity": self.severity,
            "priority_nice": self.priority_nice,
            "status": self.status,
            "reporter": self.reporter,
            "owner": self.owner,
            "duplicate_of_uuid": str(self.duplicate_of_uuid) if self.duplicate_of_uuid is not None else None,
            "parent_bug_uuid": str(self.parent_bug_uuid) if self.parent_bug_uuid is not None else None,
            "source_anchor_type": self.source_anchor_type,
            "source_project_id": str(self.source_project_id) if self.source_project_id is not None else None,
            "source_file_path": self.source_file_path,
            "source_plan_uuid": str(self.source_plan_uuid) if self.source_plan_uuid is not None else None,
            "source_revision_uuid": str(self.source_revision_uuid) if self.source_revision_uuid is not None else None,
            "source_step_uuid": str(self.source_step_uuid) if self.source_step_uuid is not None else None,
            "source_step_path": self.source_step_path,
            "source_ref_id": str(self.source_ref_id) if self.source_ref_id is not None else None,
            "source_command": self.source_command,
            "source_service": self.source_service,
            "confirmed_at": self.confirmed_at,
            "closed_at": self.closed_at,
            "reopened_at": self.reopened_at,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_bug_kind(value: str) -> str:
    """Validate that a bug kind is in BUG_KINDS. Returns value if valid, else raises RuntimeValidationError."""
    if value not in BUG_KINDS:
        raise RuntimeValidationError(f"Invalid bug kind: {value!r}. Must be one of {sorted(BUG_KINDS)}")
    return value


def validate_bug_severity(value: str) -> str:
    """Validate that a bug severity is in BUG_SEVERITIES. Returns value if valid, else raises RuntimeValidationError."""
    if value not in BUG_SEVERITIES:
        raise RuntimeValidationError(f"Invalid bug severity: {value!r}. Must be one of {sorted(BUG_SEVERITIES)}")
    return value


def validate_bug_status(value: str) -> str:
    """Validate that a bug status is in BUG_STATUSES. Returns value if valid, else raises RuntimeValidationError."""
    if value not in BUG_STATUSES:
        raise RuntimeValidationError(f"Invalid bug status: {value!r}. Must be one of {sorted(BUG_STATUSES)}")
    return value
