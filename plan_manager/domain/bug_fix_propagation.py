"""Bug fix propagation domain: the required downstream action for one impact target after a source fix (C-025)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


class PropagationAction(str, Enum):
    PULL_DEPENDENCY = "pull_dependency"
    UPDATE_DEPENDENCY_VERSION = "update_dependency_version"
    BUMP_VERSION = "bump_version"
    REBUILD_PACKAGE = "rebuild_package"
    REBUILD_IMAGE = "rebuild_image"
    REDEPLOY = "redeploy"
    RERUN_TESTS = "rerun_tests"
    UPDATE_GENERATED_CODE = "update_generated_code"
    UPDATE_CONFIGURATION = "update_configuration"
    RUN_MIGRATION = "run_migration"
    UPDATE_DOCUMENTATION = "update_documentation"
    CREATE_PLAN_CASCADE = "create_plan_cascade"
    NO_ACTION_REQUIRED = "no_action_required"


class PropagationStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"
    VERIFIED = "verified"


PROPAGATION_ACTIONS: frozenset[str] = frozenset(a.value for a in PropagationAction)
PROPAGATION_STATUSES: frozenset[str] = frozenset(s.value for s in PropagationStatus)


@dataclass(frozen=True)
class BugFixPropagation(DataclassEntity):
    ENTITY_TYPE = "bug_fix_propagation"
    ENTITY_ID_FIELD = "propagation_uuid"
    TABLE_NAME = "bug_fix_propagation"

    propagation_uuid: uuid.UUID
    bug_fix_uuid: uuid.UUID
    impact_uuid: uuid.UUID
    target_type: str | None
    target_identifier: str | None
    action: str
    status: str
    assigned_to: str | None
    linked_todo_uuid: uuid.UUID | None
    linked_plan_uuid: uuid.UUID | None
    linked_cascade_uuid: uuid.UUID | None
    started_at: str | None
    finished_at: str | None
    evidence: dict[str, Any] | None
    verification_result: str | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Convert dataclass to a dictionary payload for serialization."""
        return {
            "uuid": str(self.propagation_uuid),
            "bug_fix_uuid": str(self.bug_fix_uuid),
            "impact_uuid": str(self.impact_uuid),
            "target_type": self.target_type,
            "target_identifier": self.target_identifier,
            "action": self.action,
            "status": self.status,
            "assigned_to": self.assigned_to,
            "linked_todo_uuid": str(self.linked_todo_uuid) if self.linked_todo_uuid is not None else None,
            "linked_plan_uuid": str(self.linked_plan_uuid) if self.linked_plan_uuid is not None else None,
            "linked_cascade_uuid": str(self.linked_cascade_uuid) if self.linked_cascade_uuid is not None else None,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "evidence": self.evidence,
            "verification_result": self.verification_result,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_propagation_action(value: str) -> str:
    """Validate that value is a known propagation action.

    Args:
        value: The action string to validate.

    Returns:
        The value unchanged if valid.

    Raises:
        RuntimeValidationError: If value is not in PROPAGATION_ACTIONS.
    """
    if value in PROPAGATION_ACTIONS:
        return value
    raise RuntimeValidationError(f"unknown propagation action: {value!r}")


def validate_propagation_status(value: str) -> str:
    """Validate that value is a known propagation status.

    Args:
        value: The status string to validate.

    Returns:
        The value unchanged if valid.

    Raises:
        RuntimeValidationError: If value is not in PROPAGATION_STATUSES.
    """
    if value in PROPAGATION_STATUSES:
        return value
    raise RuntimeValidationError(f"unknown propagation status: {value!r}")
