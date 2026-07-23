"""Role-model level binding domain record: manual role-to-model-level relation (C-006)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError


class InvalidRequiredLevelError(RuntimeValidationError):
    """Raised when a candidate required_level value is not a non-empty string; maps to INVALID_REQUIRED_LEVEL."""


@dataclass(frozen=True)
class RoleModelBinding(DataclassEntity):
    ENTITY_TYPE = "role_model_binding"
    ENTITY_ID_FIELD = "binding_uuid"
    TABLE_NAME = "role_model_binding"

    binding_uuid: uuid.UUID
    role: str
    phase: str | None
    required_level: str
    active: bool
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the RoleModelBinding as a payload dictionary with the UUID as a string."""
        return {
            "uuid": str(self.binding_uuid),
            "role": self.role,
            "phase": self.phase,
            "required_level": self.required_level,
            "active": self.active,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_required_level(value: str) -> str:
    """Validate and return a required_level value.

    The value set for required_level is intentionally NOT a fixed enum in
    this plan; any non-empty string is accepted (the caller decides which
    level identifiers are meaningful).

    Args:
        value: A candidate required_level string.

    Returns:
        The input value unchanged, if it is a non-empty string.

    Raises:
        InvalidRequiredLevelError: If value is not a str, or is an empty string.
    """
    if not isinstance(value, str) or not value:
        raise InvalidRequiredLevelError(f"required_level must be a non-empty str, got {value!r}")
    return value
