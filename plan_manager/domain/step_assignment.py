"""Step assignment domain: the per-step role and toolset assignment record reusing the six-scope binding specificity ladder (C-007)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.model_binding import BINDING_SCOPES, SPEC_LEVELS, BindingScope
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError


class InvalidAssignmentScopeError(RuntimeValidationError):
    """Raised when a candidate step_assignment scope value, or the companion fields required by
    that scope, are inconsistent with the six-level model-binding inheritance scope vocabulary
    (C-010) reused unchanged for step assignment (C-007); maps to INVALID_ASSIGNMENT_SCOPE."""


class InvalidAssignmentPayloadError(RuntimeValidationError):
    """Raised when a candidate step_assignment record carries neither assigned_role nor
    toolset_uuid; maps to INVALID_ASSIGNMENT_PAYLOAD. A step assignment must assign at least
    one of the two payload fields to have any resolution effect."""


@dataclass(frozen=True)
class StepAssignment(DataclassEntity):
    """A record attaching, at one of the six scopes (system, plan, level, branch, step, role),
    an assigned role and/or an assigned toolset for the matching steps (C-007). References the
    Role and Toolset entities by identity only (role as a plain str, toolset_uuid as a plain
    uuid.UUID); it carries no database foreign key to either entity table."""

    ENTITY_TYPE = "step_assignment"
    ENTITY_ID_FIELD = "assignment_uuid"
    TABLE_NAME = "step_assignment"

    assignment_uuid: uuid.UUID
    scope: str
    role: str | None
    plan_uuid: uuid.UUID | None
    spec_level: str | None
    branch_step_uuid: uuid.UUID | None
    revision_uuid: uuid.UUID | None
    step_uuid: uuid.UUID | None
    step_path: str | None
    assigned_role: str | None
    toolset_uuid: uuid.UUID | None
    active: bool
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the StepAssignment as a payload dictionary with UUIDs as strings."""
        return {
            "uuid": str(self.assignment_uuid),
            "scope": self.scope,
            "role": self.role,
            "plan_uuid": str(self.plan_uuid) if self.plan_uuid is not None else None,
            "spec_level": self.spec_level,
            "branch_step_uuid": str(self.branch_step_uuid) if self.branch_step_uuid is not None else None,
            "revision_uuid": str(self.revision_uuid) if self.revision_uuid is not None else None,
            "step_uuid": str(self.step_uuid) if self.step_uuid is not None else None,
            "step_path": self.step_path,
            "assigned_role": self.assigned_role,
            "toolset_uuid": str(self.toolset_uuid) if self.toolset_uuid is not None else None,
            "active": self.active,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_assignment_scope_fields(
    scope: str,
    *,
    role: str | None,
    plan_uuid: uuid.UUID | None,
    spec_level: str | None,
    branch_step_uuid: uuid.UUID | None,
    step_uuid: uuid.UUID | None,
) -> None:
    """Validate scope-field combinations for a step_assignment candidate.

    Mirrors plan_manager.domain.model_binding.validate_scope_fields's six-branch
    scope-field consistency rule (C-010), applied to the step_assignment anchor
    fields (scope, role, plan_uuid, spec_level, branch_step_uuid, step_uuid).

    Args:
        scope: One of BindingScope's six values.
        role: The scope selector / optional role filter.
        plan_uuid: The plan anchor, required from scope='plan' upward.
        spec_level: The spec-level anchor, required only for scope='level'.
        branch_step_uuid: The branch anchor, required only for scope='branch'.
        step_uuid: The step anchor, required only for scope='step'.

    Raises:
        InvalidAssignmentScopeError: If scope is not a recognized BindingScope value, or if the
            companion fields present do not match what that scope requires/forbids.
    """
    if scope == BindingScope.SYSTEM.value:
        if plan_uuid is not None or spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidAssignmentScopeError("scope='system' requires plan_uuid, spec_level, branch_step_uuid, step_uuid to be None")
    elif scope == BindingScope.PLAN.value:
        if plan_uuid is None:
            raise InvalidAssignmentScopeError("scope='plan' requires plan_uuid")
        if spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidAssignmentScopeError("scope='plan' requires spec_level, branch_step_uuid, step_uuid to be None")
    elif scope == BindingScope.LEVEL.value:
        if plan_uuid is None:
            raise InvalidAssignmentScopeError("scope='level' requires plan_uuid")
        if spec_level is None:
            raise InvalidAssignmentScopeError("scope='level' requires spec_level")
        if spec_level not in SPEC_LEVELS:
            raise InvalidAssignmentScopeError(f"spec_level '{spec_level}' must be in {SPEC_LEVELS}; expected one of {sorted(SPEC_LEVELS)}")
        if branch_step_uuid is not None or step_uuid is not None:
            raise InvalidAssignmentScopeError("scope='level' requires branch_step_uuid, step_uuid to be None")
    elif scope == BindingScope.BRANCH.value:
        if plan_uuid is None or branch_step_uuid is None:
            raise InvalidAssignmentScopeError("scope='branch' requires plan_uuid and branch_step_uuid")
        if spec_level is not None or step_uuid is not None:
            raise InvalidAssignmentScopeError("scope='branch' requires spec_level, step_uuid to be None")
    elif scope == BindingScope.STEP.value:
        if plan_uuid is None or step_uuid is None:
            raise InvalidAssignmentScopeError("scope='step' requires plan_uuid and step_uuid")
        if spec_level is not None or branch_step_uuid is not None:
            raise InvalidAssignmentScopeError("scope='step' requires spec_level, branch_step_uuid to be None")
    elif scope == BindingScope.ROLE.value:
        if role is None:
            raise InvalidAssignmentScopeError("scope='role' requires role")
        if spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidAssignmentScopeError("scope='role' requires spec_level, branch_step_uuid, step_uuid to be None")
    else:
        raise InvalidAssignmentScopeError(f"Invalid scope: {scope}; expected one of {sorted(BINDING_SCOPES)}")


def validate_assignment_selectors(role: str | None, assigned_role: str | None) -> None:
    """Validate the two runtime-role-typed fields of a step_assignment candidate.

    Args:
        role: The scope selector / optional role filter; validated via validate_runtime_role
            when not None.
        assigned_role: The assigned-role payload field; validated via validate_runtime_role
            when not None.

    Raises:
        RuntimeValidationError: If role or assigned_role is not None and not a recognized
            runtime role (raised by validate_runtime_role).
    """
    if role is not None:
        validate_runtime_role(role)
    if assigned_role is not None:
        validate_runtime_role(assigned_role)


def validate_assignment_payload(assigned_role: str | None, toolset_uuid: uuid.UUID | None) -> None:
    """Require at least one of assigned_role/toolset_uuid to be non-null.

    Args:
        assigned_role: The assigned-role payload field.
        toolset_uuid: The assigned-toolset payload field; a plain uuid.UUID reference with no
            cross-entity existence check (toolset validity is deferred to command/runtime, per
            HRS).

    Raises:
        InvalidAssignmentPayloadError: If both assigned_role and toolset_uuid are None.
    """
    if assigned_role is None and toolset_uuid is None:
        raise InvalidAssignmentPayloadError("step_assignment requires at least one of assigned_role, toolset_uuid to be non-null")
