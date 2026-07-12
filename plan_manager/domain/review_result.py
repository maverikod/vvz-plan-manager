"""Review result domain: recorded outcome of reviewing an execution attempt or artifact revision (C-018)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.runtime_validation import RuntimeValidationError


class ReviewObjectType(str, Enum):
    EXECUTION_ATTEMPT = "execution_attempt"
    REVISION = "revision"


class ReviewStatus(str, Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    CHANGES_REQUESTED = "changes_requested"
    ESCALATED = "escalated"
    NEEDS_OWNER_DECISION = "needs_owner_decision"


REVIEW_OBJECT_TYPES: frozenset[str] = frozenset(t.value for t in ReviewObjectType)
REVIEW_STATUSES: frozenset[str] = frozenset(s.value for s in ReviewStatus)


@dataclass(frozen=True)
class ReviewResult:
    review_uuid: uuid.UUID
    object_type: str
    reviewed_attempt_uuid: uuid.UUID | None
    reviewed_revision_uuid: uuid.UUID | None
    reviewer: str
    status: str
    findings: str | None
    evidence: dict[str, Any] | None
    verification_commands: list[Any] | None
    escalation_target_uuid: uuid.UUID | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render this record as a JSON-serializable dict. UUID fields become str or None;
        evidence and verification_commands are passed through unchanged (already JSON-compatible);
        timestamp fields are already ISO-format strings and are passed through unchanged."""
        return {
            "review_uuid": str(self.review_uuid),
            "object_type": self.object_type,
            "reviewed_attempt_uuid": str(self.reviewed_attempt_uuid) if self.reviewed_attempt_uuid is not None else None,
            "reviewed_revision_uuid": str(self.reviewed_revision_uuid) if self.reviewed_revision_uuid is not None else None,
            "reviewer": self.reviewer,
            "status": self.status,
            "findings": self.findings,
            "evidence": self.evidence,
            "verification_commands": self.verification_commands,
            "escalation_target_uuid": str(self.escalation_target_uuid) if self.escalation_target_uuid is not None else None,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_review_object_type(value: str) -> str:
    """Return value if it is a member of REVIEW_OBJECT_TYPES, else raise RuntimeValidationError."""
    if value not in REVIEW_OBJECT_TYPES:
        raise RuntimeValidationError(f"invalid review object_type: {value!r}; expected one of {sorted(REVIEW_OBJECT_TYPES)}")
    return value


def validate_review_status(value: str) -> str:
    """Return value if it is a member of REVIEW_STATUSES, else raise RuntimeValidationError."""
    if value not in REVIEW_STATUSES:
        raise RuntimeValidationError(f"invalid review status: {value!r}; expected one of {sorted(REVIEW_STATUSES)}")
    return value
