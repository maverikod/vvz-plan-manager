"""Model binding domain: the runtime model-configuration record and its scope vocabulary (C-009)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


class InvalidBindingScopeError(RuntimeValidationError):
    """Raised when a candidate binding scope value, or the companion fields required by that
    scope, are inconsistent with the six-level model-binding inheritance scope vocabulary
    (C-010); maps to INVALID_BINDING_SCOPE."""


class InvalidRuntimeRoleError(RuntimeValidationError):
    """Raised when a candidate runtime role value is not one of the recognized RuntimeRole
    values (C-011); maps to INVALID_RUNTIME_ROLE. Defined here (rather than in
    domain/runtime_role.py, which owns the role vocabulary itself) so model-binding write
    commands can translate that module's generic RuntimeValidationError into this specific
    subclass at the command boundary."""


class BindingScope(str, Enum):
    SYSTEM = "system"
    PLAN = "plan"
    LEVEL = "level"
    BRANCH = "branch"
    STEP = "step"
    ROLE = "role"


BINDING_SCOPES: frozenset[str] = frozenset(s.value for s in BindingScope)
SPEC_LEVELS: frozenset[str] = frozenset({"HRS", "MRS", "GS", "TS", "AS"})


@dataclass(frozen=True)
class ModelBinding(DataclassEntity):
    ENTITY_TYPE = "model_binding"
    ENTITY_ID_FIELD = "binding_uuid"
    TABLE_NAME = "model_binding"
    # Compact view=summary projection (bug 8a13977d): drops fallback_provider/
    # fallback_model, max_retries, timeout, context_budget.
    SUMMARY_FIELDS = ("uuid", "scope", "role", "plan_uuid", "provider", "model", "active", "updated_at")

    binding_uuid: uuid.UUID
    scope: str
    role: str | None
    plan_uuid: uuid.UUID | None
    spec_level: str | None
    branch_step_uuid: uuid.UUID | None
    revision_uuid: uuid.UUID | None
    step_uuid: uuid.UUID | None
    step_path: str | None
    provider: str
    model: str
    fallback_provider: str | None
    fallback_model: str | None
    max_retries: int
    timeout: int
    context_budget: int | None
    active: bool
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the ModelBinding as a payload dictionary with UUIDs as strings."""
        return {
            "uuid": str(self.binding_uuid),
            "scope": self.scope,
            "role": self.role,
            "plan_uuid": str(self.plan_uuid) if self.plan_uuid is not None else None,
            "spec_level": self.spec_level,
            "branch_step_uuid": str(self.branch_step_uuid) if self.branch_step_uuid is not None else None,
            "revision_uuid": str(self.revision_uuid) if self.revision_uuid is not None else None,
            "step_uuid": str(self.step_uuid) if self.step_uuid is not None else None,
            "step_path": self.step_path,
            "provider": self.provider,
            "model": self.model,
            "fallback_provider": self.fallback_provider,
            "fallback_model": self.fallback_model,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
            "context_budget": self.context_budget,
            "active": self.active,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_binding_scope(value: str) -> str:
    """Validate and return a binding scope value."""
    if value in BINDING_SCOPES:
        return value
    raise InvalidBindingScopeError(f"Invalid binding scope: {value}; expected one of {sorted(BINDING_SCOPES)}")


def validate_scope_fields(
    scope: str,
    *,
    role: str | None,
    plan_uuid: uuid.UUID | None,
    spec_level: str | None,
    branch_step_uuid: uuid.UUID | None,
    step_uuid: uuid.UUID | None,
) -> None:
    """Validate scope-field combinations for consistency."""
    if scope == "system":
        if plan_uuid is not None or spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidBindingScopeError("scope='system' requires plan_uuid, spec_level, branch_step_uuid, step_uuid to be None")
    elif scope == "plan":
        if plan_uuid is None:
            raise InvalidBindingScopeError("scope='plan' requires plan_uuid")
        if spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidBindingScopeError("scope='plan' requires spec_level, branch_step_uuid, step_uuid to be None")
    elif scope == "level":
        if plan_uuid is None:
            raise InvalidBindingScopeError("scope='level' requires plan_uuid")
        if spec_level is None:
            raise InvalidBindingScopeError("scope='level' requires spec_level")
        if spec_level not in SPEC_LEVELS:
            raise InvalidBindingScopeError(f"spec_level '{spec_level}' must be in {SPEC_LEVELS}; expected one of {sorted(SPEC_LEVELS)}")
        if branch_step_uuid is not None or step_uuid is not None:
            raise InvalidBindingScopeError("scope='level' requires branch_step_uuid, step_uuid to be None")
    elif scope == "branch":
        if plan_uuid is None or branch_step_uuid is None:
            raise InvalidBindingScopeError("scope='branch' requires plan_uuid and branch_step_uuid")
        if spec_level is not None or step_uuid is not None:
            raise InvalidBindingScopeError("scope='branch' requires spec_level, step_uuid to be None")
    elif scope == "step":
        if plan_uuid is None or step_uuid is None:
            raise InvalidBindingScopeError("scope='step' requires plan_uuid and step_uuid")
        if spec_level is not None or branch_step_uuid is not None:
            raise InvalidBindingScopeError("scope='step' requires spec_level, branch_step_uuid to be None")
    elif scope == "role":
        if role is None:
            raise InvalidBindingScopeError("scope='role' requires role")
        if spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidBindingScopeError("scope='role' requires spec_level, branch_step_uuid, step_uuid to be None")
    else:
        raise InvalidBindingScopeError(f"Invalid scope: {scope}; expected one of {sorted(BINDING_SCOPES)}")
