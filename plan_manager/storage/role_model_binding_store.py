"""Role-model level binding persistence store: CRUD and audit for the manual role-to-model-level relation (C-006)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.role_model_binding import RoleModelBinding, validate_required_level
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_role_model_binding(
    conn: psycopg.Connection,
    *,
    role: str,
    required_level: str,
    created_by: str,
    phase: str | None = None,
    active: bool = True,
) -> RoleModelBinding:
    """Create a new role-model level binding with validation and audit recording."""
    validate_runtime_role(role)
    validate_required_level(required_level)

    binding_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    updated_at = now.isoformat()
    deleted_at = None

    sql = (
        "INSERT INTO role_model_binding "
        "(uuid, role, phase, required_level, active, created_by, created_at, updated_at, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    params = (
        binding_uuid,
        role,
        phase,
        required_level,
        active,
        created_by,
        created_at,
        updated_at,
        deleted_at,
    )
    conn.execute(sql, params)

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="role_model_binding",
        entity_id=binding_uuid,
        action="create",
        changed_by=created_by,
    )

    return RoleModelBinding(
        binding_uuid=binding_uuid,
        role=role,
        phase=phase,
        required_level=required_level,
        active=active,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


def get_role_model_binding(conn: psycopg.Connection, binding_uuid: uuid.UUID) -> RoleModelBinding | None:
    """Retrieve a single role-model binding by UUID (includes soft-deleted rows)."""
    sql = (
        "SELECT uuid, role, phase, required_level, active, created_by, created_at, updated_at, deleted_at "
        "FROM role_model_binding WHERE uuid = %s"
    )
    row = conn.execute(sql, (binding_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_role_model_bindings(
    conn: psycopg.Connection,
    *,
    role: str | None = None,
    include_deleted: bool = False,
) -> list[RoleModelBinding]:
    """List role-model bindings with optional role filtering and soft-delete handling."""
    conditions = []
    params: list[Any] = []

    if role is not None:
        conditions.append("role = %s")
        params.append(role)

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    sql = (
        "SELECT uuid, role, phase, required_level, active, created_by, created_at, updated_at, deleted_at "
        "FROM role_model_binding " + where_clause + " ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def list_for_resolution(conn: psycopg.Connection, role: str) -> list[RoleModelBinding]:
    """Return active, non-deleted role-model bindings for one role, for use by the resolver's caller."""
    sql = (
        "SELECT uuid, role, phase, required_level, active, created_by, created_at, updated_at, deleted_at "
        "FROM role_model_binding WHERE role = %s AND active = true AND deleted_at IS NULL "
        "ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, (role,)).fetchall()
    return [_row_to_record(row) for row in rows]


def update_role_model_binding(
    conn: psycopg.Connection,
    binding_uuid: uuid.UUID,
    *,
    changed_by: str,
    phase: str | None = None,
    required_level: str | None = None,
    active: bool | None = None,
) -> RoleModelBinding:
    """Update mutable fields of a role-model binding with audit recording.

    phase, required_level, and active are updated only when given a non-None
    value; None means "leave this field unchanged" (mirrors
    plan_manager.storage.model_binding_store's update_model_binding
    convention for optional fields, including its limitation that a field
    cannot be reset back to None through this function).
    """
    set_clauses = []
    params: list[Any] = []

    if phase is not None:
        set_clauses.append("phase = %s")
        params.append(phase)

    if required_level is not None:
        validate_required_level(required_level)
        set_clauses.append("required_level = %s")
        params.append(required_level)

    if active is not None:
        set_clauses.append("active = %s")
        params.append(active)

    now = datetime.now(timezone.utc)
    updated_at = now.isoformat()
    set_clauses.append("updated_at = %s")
    params.append(updated_at)

    params.append(binding_uuid)

    sql = "UPDATE role_model_binding SET " + ", ".join(set_clauses) + " WHERE uuid = %s"
    result = conn.execute(sql, params)

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no role_model_binding with uuid={binding_uuid}")

    updated_binding = get_role_model_binding(conn, binding_uuid)
    if updated_binding is None:
        raise RuntimeValidationError(f"role_model_binding with uuid={binding_uuid} not found after update")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="role_model_binding",
        entity_id=binding_uuid,
        action="update",
        changed_by=changed_by,
    )

    return updated_binding


def remove_role_model_binding(conn: psycopg.Connection, binding_uuid: uuid.UUID, *, changed_by: str) -> RoleModelBinding:
    """Soft-delete a role-model binding by setting deleted_at and recording audit trail."""
    binding = get_role_model_binding(conn, binding_uuid)
    if binding is None:
        raise RuntimeValidationError(f"no role_model_binding with uuid={binding_uuid}")

    now = datetime.now(timezone.utc)
    deleted_at = now.isoformat()
    updated_at = now.isoformat()

    sql = "UPDATE role_model_binding SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (deleted_at, updated_at, binding_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no role_model_binding with uuid={binding_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="role_model_binding",
        entity_id=binding_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return RoleModelBinding(
        binding_uuid=binding.binding_uuid,
        role=binding.role,
        phase=binding.phase,
        required_level=binding.required_level,
        active=binding.active,
        created_by=binding.created_by,
        created_at=binding.created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


def _row_to_record(row: tuple[Any, ...]) -> RoleModelBinding:
    """Map a database row to a RoleModelBinding dataclass instance.

    Column order: uuid, role, phase, required_level, active, created_by,
    created_at, updated_at, deleted_at.
    """
    binding_uuid = row[0]
    role = row[1]
    phase = row[2]
    required_level = row[3]
    active = row[4]
    created_by = row[5]
    created_at = row[6]
    updated_at = row[7]
    deleted_at = row[8]

    if created_at is not None and hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    if updated_at is not None and hasattr(updated_at, "isoformat"):
        updated_at = updated_at.isoformat()
    if deleted_at is not None and hasattr(deleted_at, "isoformat"):
        deleted_at = deleted_at.isoformat()

    return RoleModelBinding(
        binding_uuid=binding_uuid,
        role=role,
        phase=phase,
        required_level=required_level,
        active=active,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
