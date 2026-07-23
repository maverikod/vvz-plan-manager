"""Step assignment resolution: pick the most specific applicable step_assignment for a target step and report provenance (C-007)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.model_binding_inheritance import scope_rank
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.step_assignment import StepAssignment


class StepAssignmentResolutionError(RuntimeValidationError):
    """Raised when no candidate step_assignment record applies to the resolution target (C-007);
    maps to NO_APPLICABLE_ASSIGNMENT."""


@dataclass(frozen=True)
class AssignmentTarget:
    """The (role, plan, level, branch, step) coordinates a step_assignment resolution is performed against."""

    role: str
    plan_uuid: uuid.UUID | None = None
    spec_level: str | None = None
    branch_step_uuid: uuid.UUID | None = None
    step_uuid: uuid.UUID | None = None


@dataclass(frozen=True)
class StepAssignmentResolution:
    """The resolved role/toolset for a target step together with the inheritance path considered."""

    resolved_assigned_role: str | None
    resolved_toolset_uuid: uuid.UUID | None
    source: str
    source_assignment_uuid: uuid.UUID
    inheritance_path: list[dict[str, Any]]

    def to_payload(self) -> dict[str, Any]:
        """Render the StepAssignmentResolution as a payload dictionary with UUIDs as strings."""
        return {
            "resolved_assigned_role": self.resolved_assigned_role,
            "resolved_toolset_uuid": str(self.resolved_toolset_uuid) if self.resolved_toolset_uuid is not None else None,
            "source": self.source,
            "source_assignment_uuid": str(self.source_assignment_uuid),
            "inheritance_path": self.inheritance_path,
        }


def assignment_applies(record: StepAssignment, target: AssignmentTarget) -> bool:
    """Return whether a candidate step_assignment record applies to the given resolution target.

    Mirrors plan_manager.domain.model_resolution.binding_applies exactly, applied to StepAssignment
    fields instead of ModelBinding fields.

    Args:
        record: The candidate step_assignment record.
        target: The resolution target coordinates.

    Returns:
        True if record is active, not soft-deleted, its optional role filter matches target.role
        (or is None), and its scope-specific anchor fields match target; False otherwise.

    Raises:
        RuntimeValidationError: If record.scope is not one of the six recognized scope values.
    """
    if not record.active or record.deleted_at is not None:
        return False

    if not (record.role is None or record.role == target.role):
        return False

    if record.scope == "system":
        return True
    elif record.scope == "plan":
        return record.plan_uuid == target.plan_uuid
    elif record.scope == "level":
        return (record.plan_uuid == target.plan_uuid) and (record.spec_level == target.spec_level)
    elif record.scope == "branch":
        return (record.plan_uuid == target.plan_uuid) and (record.branch_step_uuid == target.branch_step_uuid)
    elif record.scope == "step":
        return (record.plan_uuid == target.plan_uuid) and (record.step_uuid == target.step_uuid)
    elif record.scope == "role":
        return (record.role == target.role) and (record.plan_uuid is None or record.plan_uuid == target.plan_uuid)
    else:
        raise RuntimeValidationError(f"unknown scope: {record.scope}")


def step_assignment_resolve(candidates: list[StepAssignment], target: AssignmentTarget) -> StepAssignmentResolution:
    """Pure resolution: select the most specific applicable step_assignment record for target.

    Mirrors plan_manager.domain.model_resolution.resolve_effective_binding exactly: same
    ordering keys (scope_rank ascending, role-specificity, plan-specificity, created_at,
    uuid tiebreaker) and same inheritance_path shape, applied to StepAssignment candidates.
    This function performs no I/O; candidates must already be loaded by the caller (the
    storage layer's list_for_resolution).

    Args:
        candidates: The full candidate set of step_assignment records to consider (typically
            pre-filtered to active, non-deleted, plan-or-system-wide rows by the storage layer).
        target: The resolution target coordinates.

    Returns:
        The StepAssignmentResolution for the winning (most specific) applicable record, with
        inheritance_path listing every applicable candidate in ascending specificity order and
        "selected": True on the last (winning) entry.

    Raises:
        StepAssignmentResolutionError: If no candidate in candidates applies to target.
    """
    applicable = [r for r in candidates if assignment_applies(r, target)]

    if not applicable:
        raise StepAssignmentResolutionError("no applicable step assignment for target")

    sorted_applicable = sorted(
        applicable,
        key=lambda r: (
            scope_rank(r.scope),
            1 if r.role is not None else 0,
            1 if (r.plan_uuid is not None and r.plan_uuid == target.plan_uuid) else 0,
            r.created_at,
            str(r.assignment_uuid),
        ),
    )

    inheritance_path = []
    for r in sorted_applicable:
        inheritance_path.append(
            {
                "scope": r.scope,
                "role": r.role,
                "assignment_uuid": str(r.assignment_uuid),
                "assigned_role": r.assigned_role,
                "toolset_uuid": str(r.toolset_uuid) if r.toolset_uuid is not None else None,
                "plan_specific": (r.plan_uuid is not None and r.plan_uuid == target.plan_uuid),
                "selected": False,
            }
        )

    inheritance_path[-1]["selected"] = True

    winner = sorted_applicable[-1]

    return StepAssignmentResolution(
        resolved_assigned_role=winner.assigned_role,
        resolved_toolset_uuid=winner.toolset_uuid,
        source=winner.scope,
        source_assignment_uuid=winner.assignment_uuid,
        inheritance_path=inheritance_path,
    )
