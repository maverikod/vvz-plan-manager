"""Provider domain model: the source that serves a model, the switching axis (C-004)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


class ProviderType(str, Enum):
    CLOUD_API = "cloud_api"
    SELF_HOSTED_HARDWARE = "self_hosted_hardware"


class ProviderStatus(str, Enum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


PROVIDER_TYPES: frozenset[str] = frozenset(t.value for t in ProviderType)
PROVIDER_STATUSES: frozenset[str] = frozenset(s.value for s in ProviderStatus)


@dataclass(frozen=True)
class Provider(DataclassEntity):
    """Immutable domain record for one provider (C-004): the source that serves a
    model. Carries its type (cloud API or self-hosted hardware, with an
    owned-versus-rented flag), an activity status that makes provider switching a
    single field change (the switching axis), and billing/quota notes."""

    ENTITY_TYPE = "provider"
    ENTITY_ID_FIELD = "provider_uuid"
    TABLE_NAME = "provider"
    # Compact view=summary projection (bug 8a13977d): drops billing_notes and quota_notes.
    SUMMARY_FIELDS = ("uuid", "name", "type", "status", "updated_at")

    provider_uuid: uuid.UUID
    name: str
    type: str
    rented_hardware: bool
    status: str
    billing_notes: str | None
    quota_notes: str | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the Provider as a JSON-safe payload dictionary with provider_uuid as str."""
        return {
            "uuid": str(self.provider_uuid),
            "name": self.name,
            "type": self.type,
            "rented_hardware": self.rented_hardware,
            "status": self.status,
            "billing_notes": self.billing_notes,
            "quota_notes": self.quota_notes,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_provider_type(value: str) -> str:
    """Validate a candidate provider type value for a Provider record (C-004).

    Parameters:
        value: Candidate provider type string.

    Returns:
        The validated provider type value, unchanged.

    Raises:
        RuntimeValidationError: If value is not a member of PROVIDER_TYPES.
    """
    if value in PROVIDER_TYPES:
        return value
    raise RuntimeValidationError(f"Invalid provider type: {value}; expected one of {sorted(PROVIDER_TYPES)}")


def validate_provider_status(value: str) -> str:
    """Validate a candidate provider status value for a Provider record (C-004).

    Parameters:
        value: Candidate provider status string.

    Returns:
        The validated provider status value, unchanged.

    Raises:
        RuntimeValidationError: If value is not a member of PROVIDER_STATUSES.
    """
    if value in PROVIDER_STATUSES:
        return value
    raise RuntimeValidationError(f"Invalid provider status: {value}; expected one of {sorted(PROVIDER_STATUSES)}")
