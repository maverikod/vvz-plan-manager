"""Tool persistence store: CRUD, validation, audit, and soft-delete for the tool entity (C-001)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.runtime_validation import RuntimeValidationError
from psycopg.types.json import Jsonb

from plan_manager.domain.tool import Tool, validate_pinned_options
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_tool(
    conn: psycopg.Connection,
    *,
    name: str,
    server_id: str,
    command: str,
    pinned_options: dict,
    created_by: str,
    description: str | None = None,
) -> Tool:
    """Create a new tool record with validation and audit recording.

    Parameters:
        conn: Open psycopg 3 connection.
        name: Tool name.
        server_id: Server reference the tool routes to.
        command: Command name the tool invokes on the server.
        pinned_options: Declarative constraints fixed at authoring time;
            validated via validate_pinned_options before insert.
        created_by: Actor performing the creation, recorded in the audit trail.
        description: Optional free-text description.

    Returns:
        Tool: The newly created tool record.

    Raises:
        RuntimeValidationError: If pinned_options fails validate_pinned_options.
    """
    validate_pinned_options(pinned_options)

    tool_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc).isoformat()

    values = {
        "uuid": tool_uuid,
        "name": name,
        "server_id": server_id,
        "command": command,
        # jsonb column: psycopg has no dumper for a bare dict, and crud_create
        # passes values straight through as bind parameters, so the wrapping
        # must happen here.
        "pinned_options": Jsonb(pinned_options),
        "description": description,
        "created_by": created_by,
        "created_at": now,
        "updated_at": now,
    }

    row = Tool.crud_create(conn, values, returning=True)
    if row is None:
        raise RuntimeValidationError(f"tool create failed to return row for uuid={tool_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="tool",
        entity_id=tool_uuid,
        action="create",
        changed_by=created_by,
    )

    return _row_to_record(row)


def get_tool(conn: psycopg.Connection, tool_uuid: uuid.UUID) -> Tool | None:
    """Retrieve a single tool by UUID (includes soft-deleted rows).

    Parameters:
        conn: Open psycopg 3 connection.
        tool_uuid: Identity of the tool to fetch.

    Returns:
        Tool | None: The tool record, or None if no row exists with that UUID.
    """
    row = Tool.crud_get(conn, tool_uuid, include_deleted=True)
    if row is None:
        return None
    return _row_to_record(row)


def list_tools(
    conn: psycopg.Connection,
    *,
    name: str | None = None,
    include_deleted: bool = False,
) -> list[Tool]:
    """List tools with optional name filtering and soft-delete handling.

    Parameters:
        conn: Open psycopg 3 connection.
        name: When given, restrict to tools with this exact name.
        include_deleted: When False (default), exclude soft-deleted rows.

    Returns:
        list[Tool]: Matching tool records ordered by created_at ascending.
    """
    filters = None
    if name is not None:
        filters = {"name": name}

    rows = Tool.crud_list(
        conn,
        filters=filters,
        include_deleted=include_deleted,
        order_by=("created_at",),
    )
    return [_row_to_record(row) for row in rows]


def update_tool(
    conn: psycopg.Connection,
    tool_uuid: uuid.UUID,
    *,
    changed_by: str,
    server_id: str | None = None,
    command: str | None = None,
    pinned_options: dict | None = None,
    description: str | None = None,
) -> Tool:
    """Update mutable fields of a tool with audit recording.

    Parameters:
        conn: Open psycopg 3 connection.
        tool_uuid: Identity of the tool to update.
        changed_by: Actor performing the update, recorded in the audit trail.
        server_id: New server reference, when given.
        command: New command name, when given.
        pinned_options: New pinned option set, when given; validated via
            validate_pinned_options before the UPDATE.
        description: New description, when given.

    Returns:
        Tool: The updated tool record, re-read from storage.

    Raises:
        RuntimeValidationError: If pinned_options is given and fails
            validate_pinned_options, or if no tool exists with tool_uuid.
    """
    if pinned_options is not None:
        validate_pinned_options(pinned_options)

    values: dict[str, Any] = {}

    if server_id is not None:
        values["server_id"] = server_id

    if command is not None:
        values["command"] = command

    if pinned_options is not None:
        values["pinned_options"] = Jsonb(pinned_options)

    if description is not None:
        values["description"] = description

    now = datetime.now(timezone.utc).isoformat()
    values["updated_at"] = now

    row = Tool.crud_update(conn, tool_uuid, values, returning=True)
    if row is None:
        raise RuntimeValidationError(f"no tool with uuid={tool_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="tool",
        entity_id=tool_uuid,
        action="update",
        changed_by=changed_by,
    )

    return _row_to_record(row)


def remove_tool(conn: psycopg.Connection, tool_uuid: uuid.UUID, *, changed_by: str) -> Tool:
    """Soft-delete a tool by setting deleted_at and recording the audit trail.

    Parameters:
        conn: Open psycopg 3 connection.
        tool_uuid: Identity of the tool to soft-delete.
        changed_by: Actor performing the deletion, recorded in the audit trail.

    Returns:
        Tool: The soft-deleted tool record with updated timestamps.

    Raises:
        RuntimeValidationError: If no tool exists with tool_uuid.
    """
    now = datetime.now(timezone.utc)

    row = Tool.crud_soft_delete(conn, tool_uuid, deleted_at=now, updated_at=now, returning=True)
    if row is None:
        raise RuntimeValidationError(f"no tool with uuid={tool_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="tool",
        entity_id=tool_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return _row_to_record(row)


def _row_to_record(row: tuple[Any, ...] | dict[str, Any]) -> Tool:
    """Map a database row to a Tool dataclass instance.

    Accepts either a tuple (from raw execute) or a dict (from crud_* methods).
    Column order: uuid, name, server_id, command, pinned_options, description,
    created_by, created_at, updated_at, deleted_at.
    """
    if isinstance(row, dict):
        # Handle dict rows from crud_* methods
        tool_uuid = row["uuid"]
        name = row["name"]
        server_id = row["server_id"]
        command = row["command"]
        pinned_options = row["pinned_options"]
        description = row["description"]
        created_by = row["created_by"]
        created_at = row["created_at"]
        updated_at = row["updated_at"]
        deleted_at = row["deleted_at"]
    else:
        # Handle tuple rows from raw execute
        (
            tool_uuid,
            name,
            server_id,
            command,
            pinned_options,
            description,
            created_by,
            created_at,
            updated_at,
            deleted_at,
        ) = row

    if created_at is not None and hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    if updated_at is not None and hasattr(updated_at, "isoformat"):
        updated_at = updated_at.isoformat()
    if deleted_at is not None and hasattr(deleted_at, "isoformat"):
        deleted_at = deleted_at.isoformat()

    return Tool(
        tool_uuid=tool_uuid,
        name=name,
        server_id=server_id,
        command=command,
        pinned_options=pinned_options,
        description=description,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
