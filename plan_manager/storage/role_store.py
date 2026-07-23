"""Role persistence store: CRUD, unique-name validation, audit, and soft-delete for the role entity (C-003)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.role import Role, validate_role_name
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_role(
    conn: psycopg.Connection,
    *,
    name: str,
    created_by: str,
    description: str | None = None,
) -> Role:
    """Create a new role record with name validation, uniqueness pre-check, and audit recording.

    Parameters:
        conn: Open psycopg 3 connection.
        name: Role name; validated via validate_role_name and required unique
            among live (non-soft-deleted) role rows.
        created_by: Actor performing the creation, recorded in the audit trail.
        description: Optional free-text description.

    Returns:
        Role: The newly created role record.

    Raises:
        RuntimeValidationError: If name fails validate_role_name, or if a live
            role with this name already exists.
    """
    validate_role_name(name)

    existing = get_role_by_name(conn, name)
    if existing is not None:
        raise RuntimeValidationError(f"role name already in use: {name!r}")

    role_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc).isoformat()

    sql = (
        "INSERT INTO role (uuid, name, description, created_by, created_at, "
        "updated_at, deleted_at) VALUES (%s, %s, %s, %s, %s, %s, %s)"
    )
    conn.execute(sql, (role_uuid, name, description, created_by, now, now, None))

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="role",
        entity_id=role_uuid,
        action="create",
        changed_by=created_by,
    )

    return Role(
        role_uuid=role_uuid,
        name=name,
        description=description,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def get_role(conn: psycopg.Connection, role_uuid: uuid.UUID) -> Role | None:
    """Retrieve a single role by UUID (includes soft-deleted rows).

    Parameters:
        conn: Open psycopg 3 connection.
        role_uuid: Identity of the role to fetch.

    Returns:
        Role | None: The role record, or None if no row exists with that UUID.
    """
    sql = (
        "SELECT uuid, name, description, created_by, created_at, updated_at, "
        "deleted_at FROM role WHERE uuid = %s"
    )
    row = conn.execute(sql, (role_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def get_role_by_name(conn: psycopg.Connection, name: str) -> Role | None:
    """Retrieve a single live (non-soft-deleted) role by exact name.

    Parameters:
        conn: Open psycopg 3 connection.
        name: Exact role name to look up.

    Returns:
        Role | None: The live role record with this name, or None if none exists.
    """
    sql = (
        "SELECT uuid, name, description, created_by, created_at, updated_at, "
        "deleted_at FROM role WHERE name = %s AND deleted_at IS NULL"
    )
    row = conn.execute(sql, (name,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_roles(conn: psycopg.Connection, *, include_deleted: bool = False) -> list[Role]:
    """List roles with soft-delete handling.

    Parameters:
        conn: Open psycopg 3 connection.
        include_deleted: When False (default), exclude soft-deleted rows.

    Returns:
        list[Role]: Matching role records ordered by created_at ascending.
    """
    where_clause = "" if include_deleted else "WHERE deleted_at IS NULL"
    sql = (
        "SELECT uuid, name, description, created_by, created_at, updated_at, "
        "deleted_at FROM role " + where_clause + " ORDER BY created_at ASC"
    )
    rows = conn.execute(sql).fetchall()
    return [_row_to_record(row) for row in rows]


def update_role(
    conn: psycopg.Connection,
    role_uuid: uuid.UUID,
    *,
    changed_by: str,
    description: str | None = None,
) -> Role:
    """Update the mutable description field of a role with audit recording.

    Parameters:
        conn: Open psycopg 3 connection.
        role_uuid: Identity of the role to update.
        changed_by: Actor performing the update, recorded in the audit trail.
        description: New description, when given.

    Returns:
        Role: The updated role record, re-read from storage.

    Raises:
        RuntimeValidationError: If no role exists with role_uuid.
    """
    set_clauses: list[str] = []
    params: list[Any] = []

    if description is not None:
        set_clauses.append("description = %s")
        params.append(description)

    now = datetime.now(timezone.utc).isoformat()
    set_clauses.append("updated_at = %s")
    params.append(now)
    params.append(role_uuid)

    sql = "UPDATE role SET " + ", ".join(set_clauses) + " WHERE uuid = %s"
    result = conn.execute(sql, params)

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no role with uuid={role_uuid}")

    updated = get_role(conn, role_uuid)
    if updated is None:
        raise RuntimeValidationError(f"role with uuid={role_uuid} not found after update")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="role",
        entity_id=role_uuid,
        action="update",
        changed_by=changed_by,
    )

    return updated


def remove_role(conn: psycopg.Connection, role_uuid: uuid.UUID, *, changed_by: str) -> Role:
    """Soft-delete a role by setting deleted_at and recording the audit trail.

    Parameters:
        conn: Open psycopg 3 connection.
        role_uuid: Identity of the role to soft-delete.
        changed_by: Actor performing the deletion, recorded in the audit trail.

    Returns:
        Role: The soft-deleted role record with updated timestamps.

    Raises:
        RuntimeValidationError: If no role exists with role_uuid.
    """
    role = get_role(conn, role_uuid)
    if role is None:
        raise RuntimeValidationError(f"no role with uuid={role_uuid}")

    now = datetime.now(timezone.utc).isoformat()
    sql = "UPDATE role SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (now, now, role_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no role with uuid={role_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="role",
        entity_id=role_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return Role(
        role_uuid=role.role_uuid,
        name=role.name,
        description=role.description,
        created_by=role.created_by,
        created_at=role.created_at,
        updated_at=now,
        deleted_at=now,
    )


def _row_to_record(row: tuple[Any, ...]) -> Role:
    """Map a database row to a Role dataclass instance.

    Column order: uuid, name, description, created_by, created_at, updated_at,
    deleted_at.
    """
    role_uuid, name, description, created_by, created_at, updated_at, deleted_at = row

    if created_at is not None and hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    if updated_at is not None and hasattr(updated_at, "isoformat"):
        updated_at = updated_at.isoformat()
    if deleted_at is not None and hasattr(deleted_at, "isoformat"):
        deleted_at = deleted_at.isoformat()

    return Role(
        role_uuid=role_uuid,
        name=name,
        description=description,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
