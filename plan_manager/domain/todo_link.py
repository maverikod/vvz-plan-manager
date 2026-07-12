"""TODO link domain: typed links between TODOs with self-reference, duplicate, and blocking-cycle guards (C-008)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any

from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.runtime_integrity import detect_cycle, ensure_no_duplicate


class TodoLinkType(str, Enum):
    RELATES_TO = "relates_to"
    BLOCKS = "blocks"
    BLOCKED_BY = "blocked_by"
    DUPLICATES = "duplicates"
    CAUSED_BY = "caused_by"
    CREATED_FROM = "created_from"
    REQUIRES = "requires"
    FOLLOWUP_FOR = "followup_for"


TODO_LINK_TYPES: frozenset[str] = frozenset(t.value for t in TodoLinkType)
BLOCKING_LINK_TYPES: frozenset[str] = frozenset({"blocks", "blocked_by"})


@dataclass(frozen=True)
class TodoLink:
    link_uuid: uuid.UUID
    from_todo_uuid: uuid.UUID
    to_todo_uuid: uuid.UUID
    link_type: str
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render this TodoLink as a JSON-serializable dict, with every uuid.UUID field rendered as str and all other fields passed through unchanged."""
        return {
            "link_uuid": str(self.link_uuid),
            "from_todo_uuid": str(self.from_todo_uuid),
            "to_todo_uuid": str(self.to_todo_uuid),
            "link_type": self.link_type,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def guard_self_reference(from_todo_uuid: uuid.UUID, to_todo_uuid: uuid.UUID) -> None:
    """Raise RuntimeValidationError if from_todo_uuid equals to_todo_uuid (a TODO may not be linked to itself). Return None otherwise."""
    if from_todo_uuid == to_todo_uuid:
        raise RuntimeValidationError("a TODO link may not reference the same TODO as both source and target")


def guard_no_duplicate(existing: set[tuple], candidate: tuple) -> None:
    """Thin wrapper delegating to ensure_no_duplicate(existing, candidate). Each tuple has the shape (str(from_todo_uuid), str(to_todo_uuid), link_type). Raises RuntimeValidationError if candidate is already present in existing."""
    ensure_no_duplicate(existing, candidate)


def guard_no_blocking_cycle(blocking_edges: list[tuple[str, str]]) -> None:
    """Thin wrapper delegating to detect_cycle(blocking_edges). The caller passes ALL active blocking edges, INCLUDING the candidate edge being validated, already normalized to the "blocks" direction: a BLOCKS link from A to B contributes edge (str(A), str(B)); a BLOCKED_BY link from A to B contributes edge (str(B), str(A)). Raises RuntimeValidationError if the resulting directed graph contains a cycle."""
    detect_cycle(blocking_edges)
