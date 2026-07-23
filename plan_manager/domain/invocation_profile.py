"""Invocation profile domain: the informational call-characteristics record and its scope vocabulary (C-008)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.model_binding import BINDING_SCOPES, SPEC_LEVELS
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError


class InvalidProfileScopeError(RuntimeValidationError):
    """Raised when a candidate invocation profile scope value, or the companion fields required by
    that scope, are inconsistent with the six-level specificity scope vocabulary (C-010) reused
    unchanged from model bindings; maps to INVALID_PROFILE_SCOPE."""


class InvalidExecutionModeError(RuntimeValidationError):
    """Raised when a candidate execution_mode value is not one of the recognized values
    ("interactive", "batch"); maps to INVALID_EXECUTION_MODE."""


EXECUTION_MODES: frozenset[str] = frozenset({"interactive", "batch"})


@dataclass(frozen=True)
class InvocationProfile(DataclassEntity):
    ENTITY_TYPE = "invocation_profile"
    ENTITY_ID_FIELD = "profile_uuid"
    TABLE_NAME = "invocation_profile"

    profile_uuid: uuid.UUID
    scope: str
    role: str | None
    plan_uuid: uuid.UUID | None
    spec_level: str | None
    branch_step_uuid: uuid.UUID | None
    revision_uuid: uuid.UUID | None
    step_uuid: uuid.UUID | None
    step_path: str | None
    temperature: float | None
    top_p: float | None
    max_output_tokens: int | None
    reasoning_effort: str | None
    context_window_budget: int | None
    timeout: int | None
    retry_policy: dict[str, Any] | None
    concurrency: int | None
    rate_hint: dict[str, Any] | None
    response_format: str | None
    response_schema: dict[str, Any] | None
    max_tool_iterations: int | None
    per_call_timeout: int | None
    execution_mode: str | None
    token_budget: int | None
    cost_budget: float | None
    dialogue_chain_ref: uuid.UUID | None
    active: bool
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the InvocationProfile as a payload dictionary with UUIDs as strings."""
        return {
            "uuid": str(self.profile_uuid),
            "scope": self.scope,
            "role": self.role,
            "plan_uuid": str(self.plan_uuid) if self.plan_uuid is not None else None,
            "spec_level": self.spec_level,
            "branch_step_uuid": str(self.branch_step_uuid) if self.branch_step_uuid is not None else None,
            "revision_uuid": str(self.revision_uuid) if self.revision_uuid is not None else None,
            "step_uuid": str(self.step_uuid) if self.step_uuid is not None else None,
            "step_path": self.step_path,
            "temperature": self.temperature,
            "top_p": self.top_p,
            "max_output_tokens": self.max_output_tokens,
            "reasoning_effort": self.reasoning_effort,
            "context_window_budget": self.context_window_budget,
            "timeout": self.timeout,
            "retry_policy": self.retry_policy,
            "concurrency": self.concurrency,
            "rate_hint": self.rate_hint,
            "response_format": self.response_format,
            "response_schema": self.response_schema,
            "max_tool_iterations": self.max_tool_iterations,
            "per_call_timeout": self.per_call_timeout,
            "execution_mode": self.execution_mode,
            "token_budget": self.token_budget,
            "cost_budget": self.cost_budget,
            "dialogue_chain_ref": str(self.dialogue_chain_ref) if self.dialogue_chain_ref is not None else None,
            "active": self.active,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_profile_scope(value: str) -> str:
    """Validate and return an invocation profile scope value."""
    if value in BINDING_SCOPES:
        return value
    raise InvalidProfileScopeError(f"Invalid invocation profile scope: {value}; expected one of {sorted(BINDING_SCOPES)}")


def validate_profile_scope_fields(
    scope: str,
    *,
    role: str | None,
    plan_uuid: uuid.UUID | None,
    spec_level: str | None,
    branch_step_uuid: uuid.UUID | None,
    step_uuid: uuid.UUID | None,
) -> None:
    """Validate scope-field combinations for consistency, mirroring model_binding.validate_scope_fields."""
    if scope == "system":
        if plan_uuid is not None or spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidProfileScopeError("scope='system' requires plan_uuid, spec_level, branch_step_uuid, step_uuid to be None")
    elif scope == "plan":
        if plan_uuid is None:
            raise InvalidProfileScopeError("scope='plan' requires plan_uuid")
        if spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidProfileScopeError("scope='plan' requires spec_level, branch_step_uuid, step_uuid to be None")
    elif scope == "level":
        if plan_uuid is None:
            raise InvalidProfileScopeError("scope='level' requires plan_uuid")
        if spec_level is None:
            raise InvalidProfileScopeError("scope='level' requires spec_level")
        if spec_level not in SPEC_LEVELS:
            raise InvalidProfileScopeError(f"spec_level '{spec_level}' must be in {SPEC_LEVELS}; expected one of {sorted(SPEC_LEVELS)}")
        if branch_step_uuid is not None or step_uuid is not None:
            raise InvalidProfileScopeError("scope='level' requires branch_step_uuid, step_uuid to be None")
    elif scope == "branch":
        if plan_uuid is None or branch_step_uuid is None:
            raise InvalidProfileScopeError("scope='branch' requires plan_uuid and branch_step_uuid")
        if spec_level is not None or step_uuid is not None:
            raise InvalidProfileScopeError("scope='branch' requires spec_level, step_uuid to be None")
    elif scope == "step":
        if plan_uuid is None or step_uuid is None:
            raise InvalidProfileScopeError("scope='step' requires plan_uuid and step_uuid")
        if spec_level is not None or branch_step_uuid is not None:
            raise InvalidProfileScopeError("scope='step' requires spec_level, branch_step_uuid to be None")
    elif scope == "role":
        if role is None:
            raise InvalidProfileScopeError("scope='role' requires role")
        if spec_level is not None or branch_step_uuid is not None or step_uuid is not None:
            raise InvalidProfileScopeError("scope='role' requires spec_level, branch_step_uuid, step_uuid to be None")
    else:
        raise InvalidProfileScopeError(f"Invalid scope: {scope}; expected one of {sorted(BINDING_SCOPES)}")


def validate_profile_role(value: str) -> str:
    """Validate a candidate role selector via the shared runtime role vocabulary (C-011)."""
    try:
        return validate_runtime_role(value)
    except RuntimeValidationError as exc:
        raise InvalidProfileScopeError(str(exc)) from exc


def validate_execution_mode(value: str) -> str:
    """Validate a candidate execution_mode value against the fixed {'interactive', 'batch'} set."""
    if value in EXECUTION_MODES:
        return value
    raise InvalidExecutionModeError(f"Invalid execution_mode: {value}; expected one of {sorted(EXECUTION_MODES)}")
