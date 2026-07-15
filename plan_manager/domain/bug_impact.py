"""Bug impact domain: one object affected by a bug — the many-sided counterpart of the single source (C-022)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity, ReferenceCheck
from plan_manager.domain.runtime_validation import RuntimeValidationError

class BugImpactTargetType(str, Enum):
    PROJECT="project"; FILE="file"; PLAN="plan"; REVISION="revision"; STEP="step"; COMMAND="command"
    RUNTIME_SERVICE="runtime_service"; CONTAINER_IMAGE="container_image"; DEPLOYMENT="deployment"
    DEPENDENCY="dependency"; DOCUMENTATION="documentation"

class BugImpactType(str, Enum):
    USES_BROKEN_API="uses_broken_api"; USES_BROKEN_CONTRACT="uses_broken_contract"
    NEEDS_DEPENDENCY_UPDATE="needs_dependency_update"; NEEDS_VERSION_BUMP="needs_version_bump"
    NEEDS_PULL="needs_pull"; NEEDS_REBUILD="needs_rebuild"; NEEDS_REDEPLOY="needs_redeploy"
    NEEDS_TEST_RERUN="needs_test_rerun"; NEEDS_PLAN_UPDATE="needs_plan_update"; NEEDS_CASCADE="needs_cascade"
    NEEDS_DOCUMENTATION_UPDATE="needs_documentation_update"; RUNTIME_REGRESSION_RISK="runtime_regression_risk"
    DATA_MIGRATION_REQUIRED="data_migration_required"; SECURITY_REVIEW_REQUIRED="security_review_required"; UNKNOWN="unknown"

class BugImpactStatus(str, Enum):
    SUSPECTED="suspected"; CONFIRMED="confirmed"; UNAFFECTED="unaffected"; PENDING_RESOLUTION="pending_resolution"
    RESOLVED="resolved"; VERIFIED="verified"; SKIPPED="skipped"

BUG_IMPACT_TARGET_TYPES: frozenset[str] = frozenset(t.value for t in BugImpactTargetType)
BUG_IMPACT_TYPES: frozenset[str] = frozenset(t.value for t in BugImpactType)
BUG_IMPACT_STATUSES: frozenset[str] = frozenset(s.value for s in BugImpactStatus)

@dataclass(frozen=True)
class BugImpact(DataclassEntity):
    ENTITY_TYPE = "bug_impact"
    ENTITY_ID_FIELD = "impact_uuid"
    TABLE_NAME = "bug_impact"
    HARD_DELETE_REFERENCE_CHECKS = (
        ReferenceCheck("bug_fix_propagation", "impact_uuid", "impact_uuid", live_column="deleted_at"),
    )

    impact_uuid: uuid.UUID
    bug_uuid: uuid.UUID
    target_type: str
    target_project_id: uuid.UUID | None
    target_file_path: str | None
    target_plan_uuid: uuid.UUID | None
    target_revision_uuid: uuid.UUID | None
    target_step_uuid: uuid.UUID | None
    target_step_path: str | None
    target_ref_id: uuid.UUID | None
    target_identifier: str | None
    impact_type: str
    status: str
    reason: str | None
    skip_decided_by: str | None
    discovery_method: str | None
    resolution_evidence: dict[str, Any] | None
    created_by: str
    created_at: str
    updated_at: str
    resolved_at: str | None
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.impact_uuid),
            "bug_uuid": str(self.bug_uuid),
            "target_type": self.target_type,
            "target_project_id": str(self.target_project_id) if self.target_project_id is not None else None,
            "target_file_path": self.target_file_path,
            "target_plan_uuid": str(self.target_plan_uuid) if self.target_plan_uuid is not None else None,
            "target_revision_uuid": str(self.target_revision_uuid) if self.target_revision_uuid is not None else None,
            "target_step_uuid": str(self.target_step_uuid) if self.target_step_uuid is not None else None,
            "target_step_path": self.target_step_path,
            "target_ref_id": str(self.target_ref_id) if self.target_ref_id is not None else None,
            "target_identifier": self.target_identifier,
            "impact_type": self.impact_type,
            "status": self.status,
            "reason": self.reason,
            "skip_decided_by": self.skip_decided_by,
            "discovery_method": self.discovery_method,
            "resolution_evidence": self.resolution_evidence,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
            "deleted_at": self.deleted_at,
        }


def validate_impact_target_type(value: str) -> str:
    if value not in BUG_IMPACT_TARGET_TYPES:
        raise RuntimeValidationError(f"invalid bug impact target_type: {value!r}")
    return value


def validate_impact_type(value: str) -> str:
    if value not in BUG_IMPACT_TYPES:
        raise RuntimeValidationError(f"invalid bug impact impact_type: {value!r}")
    return value


def validate_impact_status(value: str) -> str:
    if value not in BUG_IMPACT_STATUSES:
        raise RuntimeValidationError(f"invalid bug impact status: {value!r}")
    return value


def validate_impact_skip_decision(status: str, reason: str | None, skip_decided_by: str | None) -> None:
    if status == "skipped" and not (
        isinstance(reason, str) and reason.strip()
        and isinstance(skip_decided_by, str) and skip_decided_by.strip()
    ):
        raise RuntimeValidationError(
            "skipped bug impact requires a non-empty reason and skip_decided_by (owner decision)"
        )
