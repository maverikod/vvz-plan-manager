"""Generic runtime link domain: typed links between runtime records whose endpoints are each a bug or a todo, with self-reference, duplicate, and blocking-cycle guards (C-012)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.runtime_integrity import detect_cycle, ensure_no_duplicate

class RuntimeLinkEntityType(str, Enum):
    BUG = "bug"
    TODO = "todo"

RUNTIME_LINK_ENTITY_TYPES: frozenset[str] = frozenset(t.value for t in RuntimeLinkEntityType)

class RuntimeLinkType(str, Enum):
    RELATES_TO = "relates_to"
    BLOCKS = "blocks"
    BLOCKED_BY = "blocked_by"
    DUPLICATES = "duplicates"
    CAUSED_BY = "caused_by"
    CREATED_FROM = "created_from"
    REQUIRES = "requires"
    FOLLOWUP_FOR = "followup_for"

RUNTIME_LINK_TYPES: frozenset[str] = frozenset(t.value for t in RuntimeLinkType)
RUNTIME_BLOCKING_LINK_TYPES: frozenset[str] = frozenset({"blocks", "blocked_by"})

@dataclass(frozen=True)
class RuntimeLink(DataclassEntity):
    ENTITY_TYPE = "runtime_link"
    ENTITY_ID_FIELD = "link_uuid"
    TABLE_NAME = "runtime_link"

    link_uuid: uuid.UUID
    from_entity_type: str
    from_entity_uuid: uuid.UUID
    to_entity_type: str
    to_entity_uuid: uuid.UUID
    link_type: str
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render this RuntimeLink as a JSON-serializable dict, with every uuid.UUID field rendered as str and all other fields passed through unchanged."""
        return {
            "uuid": str(self.link_uuid),
            "link_uuid": str(self.link_uuid),
            "from_entity_type": self.from_entity_type,
            "from_entity_uuid": str(self.from_entity_uuid),
            "to_entity_type": self.to_entity_type,
            "to_entity_uuid": str(self.to_entity_uuid),
            "link_type": self.link_type,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }

def validate_entity_type(value: str) -> str:
    """Validate a candidate runtime link endpoint entity_type. Returns value if it is a member of RUNTIME_LINK_ENTITY_TYPES ("bug" or "todo"), else raises RuntimeValidationError."""
    if value not in RUNTIME_LINK_ENTITY_TYPES:
        raise RuntimeValidationError(f"invalid runtime link entity_type: {value!r}; must be one of {sorted(RUNTIME_LINK_ENTITY_TYPES)}")
    return value

def validate_link_type(value: str) -> str:
    """Validate a candidate runtime link_type. Returns value if it is a member of RUNTIME_LINK_TYPES, else raises RuntimeValidationError."""
    if value not in RUNTIME_LINK_TYPES:
        raise RuntimeValidationError(f"invalid runtime link_type: {value!r}; must be one of {sorted(RUNTIME_LINK_TYPES)}")
    return value

def guard_self_reference(
    from_entity_type: str, from_entity_uuid: uuid.UUID, to_entity_type: str, to_entity_uuid: uuid.UUID
) -> None:
    """Raise RuntimeValidationError if the two endpoints denote the same runtime record (from_entity_type == to_entity_type AND from_entity_uuid == to_entity_uuid); a runtime link may not reference the same record as both source and target. Return None otherwise."""
    if from_entity_type == to_entity_type and from_entity_uuid == to_entity_uuid:
        raise RuntimeValidationError("a runtime link may not reference the same record as both source and target")

def guard_no_duplicate(existing: set[tuple], candidate: tuple) -> None:
    """Thin wrapper delegating to ensure_no_duplicate(existing, candidate). Each tuple has the shape (from_entity_type, str(from_entity_uuid), to_entity_type, str(to_entity_uuid), link_type). Raises RuntimeValidationError if candidate is already present in existing."""
    ensure_no_duplicate(existing, candidate)

def guard_no_blocking_cycle(blocking_edges: list[tuple[str, str]]) -> None:
    """Thin wrapper delegating to detect_cycle(blocking_edges). The caller passes ALL active blocking edges, INCLUDING the candidate edge being validated, with each endpoint normalized to the node identifier f"{entity_type}:{entity_uuid}" (e.g. "bug:11111111-1111-1111-1111-111111111111" or "todo:22222222-2222-2222-2222-222222222222"), and each edge already normalized to the "blocks" direction: a BLOCKS link from A to B contributes edge (node(A), node(B)); a BLOCKED_BY link from A to B contributes edge (node(B), node(A)). Raises RuntimeValidationError if the resulting directed graph contains a cycle."""
    detect_cycle(blocking_edges)

def entity_node(entity_type: str, entity_uuid: uuid.UUID) -> str:
    """Build the cycle-graph node identifier for one runtime link endpoint as f"{entity_type}:{entity_uuid}", e.g. entity_node("bug", some_uuid) -> "bug:<uuid>". Used to give detect_cycle a single flat string-keyed graph across both bug and todo endpoints."""
    return f"{entity_type}:{entity_uuid}"
