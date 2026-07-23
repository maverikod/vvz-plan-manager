"""Toolset domain model: a named, ordered set of tool references (C-002), and its toolset-uses-tool membership record."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.entity import DataclassEntity


@dataclass(frozen=True)
class Toolset(DataclassEntity):
    """Immutable domain record for one toolset (C-002): a named, ordered set of tool
    references — the equipment list of one kind of work. A toolset references tool
    entities only and never embeds their definitions, so a tool contract change is
    visible to every toolset that carries it. Membership (the ordered tool references)
    is realized by the separate ToolsetMembership record, not by fields on this class."""

    ENTITY_TYPE = "toolset"
    ENTITY_ID_FIELD = "toolset_uuid"
    TABLE_NAME = "toolset"
    # Compact view=summary projection (bug 8a13977d): drops description.
    SUMMARY_FIELDS = ("uuid", "name", "updated_at")

    toolset_uuid: uuid.UUID
    name: str
    description: str | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the Toolset as a JSON-safe payload dictionary with toolset_uuid as str."""
        return {
            "uuid": str(self.toolset_uuid),
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


@dataclass(frozen=True)
class ToolsetMembership(DataclassEntity):
    """Immutable domain record for one toolset-uses-tool membership (C-002 uses C-001):
    one ordered tool reference within one toolset. References the tool by uuid only;
    never embeds a Tool object inline, so a tool contract change is visible to every
    toolset that carries it without denormalized copies."""

    ENTITY_TYPE = "toolset_membership"
    ENTITY_ID_FIELD = "membership_uuid"
    TABLE_NAME = "toolset_membership"

    membership_uuid: uuid.UUID
    toolset_uuid: uuid.UUID
    tool_uuid: uuid.UUID
    position: int
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the ToolsetMembership as a JSON-safe payload dictionary with membership_uuid, toolset_uuid, and tool_uuid as str."""
        return {
            "uuid": str(self.membership_uuid),
            "toolset_uuid": str(self.toolset_uuid),
            "tool_uuid": str(self.tool_uuid),
            "position": self.position,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }
