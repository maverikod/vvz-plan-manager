"""Toolset persistence store: CRUD, audit, soft-delete, and ordered tool membership for the toolset entity (C-002)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.toolset import Toolset, ToolsetMembership
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_toolset(
    conn: psycopg.Connection,
    *,
    name: str,
    created_by: str,
    description: str | None = None,
) -> Toolset:
    """Create a new toolset record; records a "create" audit entry; returns the Toolset."""
    toolset_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc).isoformat()

    sql = (
        "INSERT INTO toolset (uuid, name, description, created_by, created_at, "
        "updated_at, deleted_at) VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    conn.execute(sql, (toolset_uuid, name, description, created_by, now, now, None))

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="toolset",
        entity_id=toolset_uuid,
        action="create",
        changed_by=created_by,
    )

    return Toolset(
        toolset_uuid=toolset_uuid,
        name=name,
        description=description,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def get_toolset(conn: psycopg.Connection, toolset_uuid: uuid.UUID) -> Toolset | None:
    """Fetch one toolset by UUID (includes soft-deleted rows); None if no row exists."""
    sql = (
        "SELECT uuid, name, description, created_by, created_at, updated_at, "
        "deleted_at FROM toolset WHERE uuid = %s"
    )
    row = conn.execute(sql, (toolset_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_toolset(row)


def list_toolsets(
    conn: psycopg.Connection,
    *,
    name: str | None = None,
    include_deleted: bool = False,
) -> list[Toolset]:
    """List toolsets, optionally filtered by exact name; excludes soft-deleted rows unless include_deleted."""
    conditions: list[str] = []
    params: list[Any] = []

    if name is not None:
        conditions.append("name = %s")
        params.append(name)

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = (
        "SELECT uuid, name, description, created_by, created_at, updated_at, "
        "deleted_at FROM toolset " + where_clause + " ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_toolset(row) for row in rows]


def update_toolset(
    conn: psycopg.Connection,
    toolset_uuid: uuid.UUID,
    *,
    changed_by: str,
    description: str | None = None,
) -> Toolset:
    """Update the mutable description field; records an "update" audit entry; raises RuntimeValidationError if not found."""
    set_clauses: list[str] = []
    params: list[Any] = []

    if description is not None:
        set_clauses.append("description = %s")
        params.append(description)

    now = datetime.now(timezone.utc).isoformat()
    set_clauses.append("updated_at = %s")
    params.append(now)
    params.append(toolset_uuid)

    sql = "UPDATE toolset SET " + ", ".join(set_clauses) + " WHERE uuid = %s"
    result = conn.execute(sql, params)

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no toolset with uuid={toolset_uuid}")

    updated = get_toolset(conn, toolset_uuid)
    if updated is None:
        raise RuntimeValidationError(f"toolset with uuid={toolset_uuid} not found after update")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="toolset",
        entity_id=toolset_uuid,
        action="update",
        changed_by=changed_by,
    )

    return updated


def remove_toolset(conn: psycopg.Connection, toolset_uuid: uuid.UUID, *, changed_by: str) -> Toolset:
    """Soft-delete a toolset (sets deleted_at + updated_at); records a "soft_delete" audit entry."""
    toolset = get_toolset(conn, toolset_uuid)
    if toolset is None:
        raise RuntimeValidationError(f"no toolset with uuid={toolset_uuid}")

    now = datetime.now(timezone.utc).isoformat()
    sql = "UPDATE toolset SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (now, now, toolset_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no toolset with uuid={toolset_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="toolset",
        entity_id=toolset_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return Toolset(
        toolset_uuid=toolset.toolset_uuid,
        name=toolset.name,
        description=toolset.description,
        created_by=toolset.created_by,
        created_at=toolset.created_at,
        updated_at=now,
        deleted_at=now,
    )


def add_toolset_member(
    conn: psycopg.Connection,
    *,
    toolset_uuid: uuid.UUID,
    tool_uuid: uuid.UUID,
    position: int,
    created_by: str,
) -> ToolsetMembership:
    """Add a tool reference to a toolset at an ordered position; never embeds the Tool, only its UUID; records a "create" audit entry."""
    membership_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc).isoformat()

    sql = (
        "INSERT INTO toolset_membership (uuid, toolset_uuid, tool_uuid, position, "
        "created_by, created_at, updated_at, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
    )
    conn.execute(
        sql,
        (membership_uuid, toolset_uuid, tool_uuid, position, created_by, now, now, None),
    )

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="toolset_membership",
        entity_id=membership_uuid,
        action="create",
        changed_by=created_by,
    )

    return ToolsetMembership(
        membership_uuid=membership_uuid,
        toolset_uuid=toolset_uuid,
        tool_uuid=tool_uuid,
        position=position,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def remove_toolset_member(
    conn: psycopg.Connection, membership_uuid: uuid.UUID, *, changed_by: str
) -> ToolsetMembership:
    """Soft-delete a toolset membership; records a "soft_delete" audit entry; raises RuntimeValidationError if not found."""
    sql = (
        "SELECT uuid, toolset_uuid, tool_uuid, position, created_by, created_at, "
        "updated_at, deleted_at FROM toolset_membership WHERE uuid = %s"
    )
    row = conn.execute(sql, (membership_uuid,)).fetchone()
    if row is None:
        raise RuntimeValidationError(f"no toolset membership with uuid={membership_uuid}")
    membership = _row_to_membership(row)

    now = datetime.now(timezone.utc).isoformat()
    update_sql = "UPDATE toolset_membership SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(update_sql, (now, now, membership_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no toolset membership with uuid={membership_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="toolset_membership",
        entity_id=membership_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return ToolsetMembership(
        membership_uuid=membership.membership_uuid,
        toolset_uuid=membership.toolset_uuid,
        tool_uuid=membership.tool_uuid,
        position=membership.position,
        created_by=membership.created_by,
        created_at=membership.created_at,
        updated_at=now,
        deleted_at=now,
    )


def list_toolset_members(conn: psycopg.Connection, toolset_uuid: uuid.UUID) -> list[ToolsetMembership]:
    """List the live (non-deleted) memberships of a toolset, ordered by position ascending."""
    sql = (
        "SELECT uuid, toolset_uuid, tool_uuid, position, created_by, created_at, "
        "updated_at, deleted_at FROM toolset_membership "
        "WHERE toolset_uuid = %s AND deleted_at IS NULL ORDER BY position ASC"
    )
    rows = conn.execute(sql, (toolset_uuid,)).fetchall()
    return [_row_to_membership(row) for row in rows]


def _row_to_toolset(row: tuple[Any, ...]) -> Toolset:
    """Map a DB row (uuid, name, description, created_by, created_at, updated_at, deleted_at) to a Toolset."""
    toolset_uuid, name, description, created_by, created_at, updated_at, deleted_at = row

    if created_at is not None and hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    if updated_at is not None and hasattr(updated_at, "isoformat"):
        updated_at = updated_at.isoformat()
    if deleted_at is not None and hasattr(deleted_at, "isoformat"):
        deleted_at = deleted_at.isoformat()

    return Toolset(
        toolset_uuid=toolset_uuid,
        name=name,
        description=description,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


def _row_to_membership(row: tuple[Any, ...]) -> ToolsetMembership:
    """Map a DB row (uuid, toolset_uuid, tool_uuid, position, created_by, created_at, updated_at, deleted_at) to a ToolsetMembership."""
    (
        membership_uuid,
        toolset_uuid,
        tool_uuid,
        position,
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

    return ToolsetMembership(
        membership_uuid=membership_uuid,
        toolset_uuid=toolset_uuid,
        tool_uuid=tool_uuid,
        position=position,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
