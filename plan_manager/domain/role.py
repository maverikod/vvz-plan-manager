"""Role domain model: a first-class stored entity naming who the agent is (C-003)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_role import RUNTIME_ROLES
from plan_manager.domain.runtime_validation import RuntimeValidationError


@dataclass(frozen=True)
class Role(DataclassEntity):
    """Immutable domain record for one role (C-003): who the agent is. Upgrades the
    closed 12-value RuntimeRole enum to a first-class stored entity with unique,
    free-form names. The 12 existing enum values are seeded as rows, but role names
    are NOT restricted to that closed set — future roles must be addable without a
    code change. Runtime references that carry role strings stay string-compatible."""

    ENTITY_TYPE = "role"
    ENTITY_ID_FIELD = "role_uuid"
    TABLE_NAME = "role"

    role_uuid: uuid.UUID
    name: str
    description: str | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the Role as a JSON-safe payload dictionary with role_uuid as str."""
        return {
            "uuid": str(self.role_uuid),
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_role_name(value: str) -> str:
    """Validate a candidate role name for a Role record (C-003).

    Role names are unique, free-form strings; this validator only rejects an
    empty or blank (whitespace-only) string. It does NOT restrict names to the
    12 seeded RuntimeRole values — future roles must be addable without a code
    change. Uniqueness is enforced by storage, not here.

    Parameters:
        value: Candidate role name.

    Returns:
        The validated role name, unchanged.

    Raises:
        RuntimeValidationError: If value is not a str, or is empty or blank after stripping whitespace.
    """
    if not isinstance(value, str) or not value.strip():
        raise RuntimeValidationError(f"role name must be a non-empty, non-blank string, got {value!r}")
    return value


def is_seed_role_name(value: str) -> bool:
    """Return True if value equals one of the 12 seeded RuntimeRole values (C-003).

    This is a documented convenience predicate only — it is NOT a validation gate.
    Role names are free-form and unique; a role name that is not a seed name is
    still a fully valid Role (future roles beyond the 12 seed values are valid).

    Parameters:
        value: Candidate role name.

    Returns:
        True if value is a member of RUNTIME_ROLES, False otherwise.
    """
    return value in RUNTIME_ROLES
