"""Escalation domain: a decision raised to the next-level owner; anchorable and command-managed (C-037)."""
from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


class EscalationStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"


ESCALATION_STATUSES: frozenset[str] = frozenset(s.value for s in EscalationStatus)

ADDRESSEE_LEVELS: frozenset[str] = frozenset({"tactical", "global", "plan", "user"})


@dataclass(frozen=True)
class Escalation(DataclassEntity):
    ENTITY_TYPE = "escalation"
    ENTITY_ID_FIELD = "escalation_uuid"
    TABLE_NAME = "escalation"
    # Compact view=summary projection (bug 8a13977d): drops reason and resolution.
    SUMMARY_FIELDS = (
        "uuid", "primary_anchor_type", "anchor_ref_id", "status",
        "addressee_level", "addressee_role", "updated_at",
    )

    escalation_uuid: uuid.UUID
    primary_anchor_type: str
    anchor_project_id: uuid.UUID | None
    anchor_file_path: str | None
    anchor_plan_uuid: uuid.UUID | None
    anchor_revision_uuid: uuid.UUID | None
    anchor_step_uuid: uuid.UUID | None
    anchor_step_path: str | None
    anchor_ref_id: uuid.UUID | None
    reason: str
    from_level: str | None
    to_level: str | None
    status: str
    resolution: str | None
    resolved_by: str | None
    resolved_at: str | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None
    addressee_level: str | None
    addressee_role: str | None
    forwarded_from_uuid: uuid.UUID | None
    chain_root_uuid: uuid.UUID | None
    sweep_priority: int | None
    blocks_subtree: bool

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.escalation_uuid),
            "escalation_uuid": str(self.escalation_uuid),
            "primary_anchor_type": self.primary_anchor_type,
            "anchor_project_id": str(self.anchor_project_id) if self.anchor_project_id else None,
            "anchor_file_path": self.anchor_file_path,
            "anchor_plan_uuid": str(self.anchor_plan_uuid) if self.anchor_plan_uuid else None,
            "anchor_revision_uuid": str(self.anchor_revision_uuid) if self.anchor_revision_uuid else None,
            "anchor_step_uuid": str(self.anchor_step_uuid) if self.anchor_step_uuid else None,
            "anchor_step_path": self.anchor_step_path,
            "anchor_ref_id": str(self.anchor_ref_id) if self.anchor_ref_id else None,
            "reason": self.reason,
            "from_level": self.from_level,
            "to_level": self.to_level,
            "status": self.status,
            "resolution": self.resolution,
            "resolved_by": self.resolved_by,
            "resolved_at": self.resolved_at,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
            "addressee_level": self.addressee_level,
            "addressee_role": self.addressee_role,
            "forwarded_from_uuid": str(self.forwarded_from_uuid) if self.forwarded_from_uuid else None,
            "chain_root_uuid": str(self.chain_root_uuid) if self.chain_root_uuid else None,
            "sweep_priority": self.sweep_priority,
            "blocks_subtree": self.blocks_subtree,
        }


def validate_escalation_status(value: str) -> str:
    if value in ESCALATION_STATUSES:
        return value
    raise RuntimeValidationError(f"invalid escalation status: {value!r}")


def validate_sweep_priority(value: int | None) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int):
        raise RuntimeValidationError(f"sweep_priority must be an int or None, got {type(value).__name__}")
    return value


def validate_addressee_level(value: str | None) -> str | None:
    if value is None:
        return None
    if value not in ADDRESSEE_LEVELS:
        raise RuntimeValidationError(f"invalid addressee_level: {value!r}")
    return value
