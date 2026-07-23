"""Model domain model: one invocable model, provider reference and level indirection (C-005)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


class ExecutionMode(str, Enum):
    INTERACTIVE = "interactive"
    BATCH = "batch"


EXECUTION_MODES: frozenset[str] = frozenset(m.value for m in ExecutionMode)


@dataclass(frozen=True)
class Model(DataclassEntity):
    """Immutable domain record for one invocable model (C-005): name, provider
    reference (model-depends-on-provider), capability level, operational
    attributes, and execution mode. The level is the key indirection: roles
    request a level, not a concrete model, so equivalent-level models of
    different providers are interchangeable. Execution mode is interactive or
    batch; batch carries discounted asynchronous economics with no tool-use loop
    inside a single item."""

    ENTITY_TYPE = "model"
    ENTITY_ID_FIELD = "model_uuid"
    TABLE_NAME = "model"

    model_uuid: uuid.UUID
    name: str
    provider_uuid: uuid.UUID
    level: str
    context_window: int | None
    cost_class: str | None
    availability: str | None
    execution_mode: str
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the Model as a JSON-safe payload dictionary with model_uuid and provider_uuid as str."""
        return {
            "uuid": str(self.model_uuid),
            "name": self.name,
            "provider_uuid": str(self.provider_uuid),
            "level": self.level,
            "context_window": self.context_window,
            "cost_class": self.cost_class,
            "availability": self.availability,
            "execution_mode": self.execution_mode,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_execution_mode(value: str) -> str:
    """Validate a candidate execution mode value for a Model record (C-005).

    Parameters:
        value: Candidate execution mode string.

    Returns:
        The validated execution mode value, unchanged.

    Raises:
        RuntimeValidationError: If value is not a member of EXECUTION_MODES.
    """
    if value in EXECUTION_MODES:
        return value
    raise RuntimeValidationError(f"Invalid execution mode: {value}; expected one of {sorted(EXECUTION_MODES)}")
