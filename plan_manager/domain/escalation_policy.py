"""Escalation policy domain: the standing, versioned record fixing summoned-owner authority typology, escalation-round guard, and overnight parking rules (C-012)."""

from __future__ import annotations
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


class AuthorityAction(str, Enum):
    """The closed authority typology available to a summoned owner (C-012); a summoned owner never alters frozen truth."""

    INTERPRET_MANDATE = "interpret_mandate"
    SUPPLEMENT_CONTEXT = "supplement_context"
    DECLARE_NEEDS_PLAN_CHANGE = "declare_needs_plan_change"
    ABORT_STEP = "abort_step"


AUTHORITY_TYPOLOGY: frozenset[str] = frozenset(a.value for a in AuthorityAction)

MAX_OWNER_ROUNDS = 2


@dataclass(frozen=True)
class EscalationPolicy(DataclassEntity):
    """The standing, versioned escalation-policy record (C-012): fixes the closed authority typology of a summoned owner, the ping-pong guard of at most `max_owner_rounds` owner-answer rounds per (step, issue) before forced escalation one level up, and the overnight rule where a terminal user-addressed escalation parks the whole wave (`terminal_parks_wave`) while an owner-call timeout parks rather than aborts (`owner_timeout_parks`). `schema_version` versions the payload shape. `active` marks the current standing policy; `deleted_at` is the soft-delete marker (ISO-8601 string or None)."""

    ENTITY_TYPE = "escalation_policy"
    ENTITY_ID_FIELD = "policy_uuid"
    TABLE_NAME = "escalation_policy"

    policy_uuid: uuid.UUID
    schema_version: int
    authority_typology: list[str]
    max_owner_rounds: int
    terminal_parks_wave: bool
    owner_timeout_parks: bool
    active: bool
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render this policy record as a JSON-safe API payload."""
        return {
            "uuid": str(self.policy_uuid),
            "policy_uuid": str(self.policy_uuid),
            "schema_version": self.schema_version,
            "authority_typology": list(self.authority_typology),
            "max_owner_rounds": self.max_owner_rounds,
            "terminal_parks_wave": self.terminal_parks_wave,
            "owner_timeout_parks": self.owner_timeout_parks,
            "active": self.active,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_escalation_policy(policy: EscalationPolicy) -> None:
    """Validate an EscalationPolicy instance.

    Args:
        policy: The EscalationPolicy instance to validate.

    Raises:
        RuntimeValidationError: If any entry of policy.authority_typology is not a member of AUTHORITY_TYPOLOGY, or if policy.max_owner_rounds is not an int >= 1.
    """
    for action in policy.authority_typology:
        if action not in AUTHORITY_TYPOLOGY:
            raise RuntimeValidationError(f"invalid authority action: {action!r}")
    if not isinstance(policy.max_owner_rounds, int) or policy.max_owner_rounds < 1:
        raise RuntimeValidationError(f"max_owner_rounds must be an int >= 1, got {policy.max_owner_rounds!r}")


def standing_escalation_policy_defaults() -> dict[str, Any]:
    """Return the standing escalation-policy default values (user decision 2026-07-20) as a plain dict, ready to be merged with a freshly generated policy_uuid, created_by, and timestamps by the storage layer. Does not include policy_uuid, created_by, created_at, updated_at, or deleted_at — only the policy content fields."""
    return {
        "schema_version": 1,
        "authority_typology": [a.value for a in AuthorityAction],
        "max_owner_rounds": MAX_OWNER_ROUNDS,
        "terminal_parks_wave": True,
        "owner_timeout_parks": True,
        "active": True,
    }
