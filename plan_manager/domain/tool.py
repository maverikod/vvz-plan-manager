"""Tool domain model: a stored, callable instrument description (C-001)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from plan_manager.domain.entity import DataclassEntity
from plan_manager.domain.runtime_validation import RuntimeValidationError


@dataclass(frozen=True)
class Tool(DataclassEntity):
    """Immutable domain record for one callable tool instrument (C-001): a server
    reference, a command name, and a pinned option set of declarative constraints
    fixed at authoring time. At execution time, caller-supplied arguments merge
    UNDER the pinned options so the tool record fixes both call routing and the
    sandbox bounds callers cannot exceed."""

    ENTITY_TYPE = "tool"
    ENTITY_ID_FIELD = "tool_uuid"
    TABLE_NAME = "tool"
    ID_COLUMN = "uuid"
    # Column order follows the tool CREATE TABLE in migration 0018_agent_config_entities.sql.
    COLUMNS = (
        "uuid",
        "name",
        "server_id",
        "command",
        "pinned_options",
        "description",
        "created_by",
        "created_at",
        "updated_at",
        "deleted_at",
    )
    # Every column except deleted_at. uuid, created_at and updated_at ARE
    # insertable and must stay here: none of them carries a DB default, and
    # create_tool supplies all three explicitly in Python. Omitting them would
    # make crud_create reject the store's own payload, because INSERT_COLUMNS is
    # the whitelist it validates against. deleted_at is excluded so a create
    # cannot mark a row deleted at birth.
    INSERT_COLUMNS = (
        "uuid",
        "name",
        "server_id",
        "command",
        "pinned_options",
        "description",
        "created_by",
        "created_at",
        "updated_at",
    )
    # Immutable after creation: uuid, created_by, name. deleted_at is absent on
    # purpose — soft deletion runs through crud_soft_delete, which writes the
    # soft-delete column directly and never consults this tuple.
    UPDATE_COLUMNS = ("server_id", "command", "pinned_options", "description", "updated_at")
    SEARCH_COLUMNS = ("name",)
    # Compact view=summary projection (bug 8a13977d): drops pinned_options and description.
    SUMMARY_FIELDS = ("uuid", "name", "server_id", "command", "updated_at")

    tool_uuid: uuid.UUID
    name: str
    server_id: str
    command: str
    pinned_options: dict[str, Any]
    description: str | None
    created_by: str
    created_at: str
    updated_at: str
    deleted_at: str | None

    def to_payload(self) -> dict[str, Any]:
        """Render the Tool as a JSON-safe payload dictionary with tool_uuid as str."""
        return {
            "uuid": str(self.tool_uuid),
            "name": self.name,
            "server_id": self.server_id,
            "command": self.command,
            "pinned_options": self.pinned_options,
            "description": self.description,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "deleted_at": self.deleted_at,
        }


def validate_pinned_options(value: Any) -> dict[str, Any]:
    """Validate a candidate pinned-options value for a Tool record (C-001).

    Pinned options are a declarative constraint mapping fixed at authoring time
    (for example project id, path prefix, result limits); this validator only
    checks the mapping shape here — merge-time enforcement happens in consuming
    runtimes, not in this module.

    Parameters:
        value: Candidate pinned-options value.

    Returns:
        The validated pinned options, unchanged, as a dict.

    Raises:
        RuntimeValidationError: If value is not a dict.
    """
    if isinstance(value, dict):
        return value
    raise RuntimeValidationError(f"pinned_options must be a mapping (dict), got {type(value).__name__}")
