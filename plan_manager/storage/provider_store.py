"""Provider persistence store: CRUD, validation, single-call status switch, audit, and soft-delete for the provider entity (C-004)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.provider import (
    Provider,
    validate_provider_status,
    validate_provider_type,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_provider(
    conn: psycopg.Connection,
    *,
    name: str,
    type: str,
    rented_hardware: bool,
    status: str,
    created_by: str,
    billing_notes: str | None = None,
    quota_notes: str | None = None,
) -> Provider:
    """Create a new provider record with validation and audit recording.

    Parameters:
        conn: Open psycopg 3 connection.
        name: Provider name.
        type: Provider type; validated via validate_provider_type
            (cloud_api or self_hosted_hardware).
        rented_hardware: Distinguishes owned from rented self-hosted hardware.
        status: Activity status; validated via validate_provider_status
            (active or suspended).
        created_by: Actor performing the creation, recorded in the audit trail.
        billing_notes: Optional free-text billing notes.
        quota_notes: Optional free-text quota notes.

    Returns:
        Provider: The newly created provider record.

    Raises:
        RuntimeValidationError: If type fails validate_provider_type or status
            fails validate_provider_status.
    """
    validate_provider_type(type)
    validate_provider_status(status)

    provider_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc).isoformat()

    sql = (
        "INSERT INTO provider "
        "(uuid, name, type, rented_hardware, status, billing_notes, quota_notes, "
        "created_by, created_at, updated_at, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    params = (
        provider_uuid,
        name,
        type,
        rented_hardware,
        status,
        billing_notes,
        quota_notes,
        created_by,
        now,
        now,
        None,
    )
    conn.execute(sql, params)

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="provider",
        entity_id=provider_uuid,
        action="create",
        changed_by=created_by,
    )

    return Provider(
        provider_uuid=provider_uuid,
        name=name,
        type=type,
        rented_hardware=rented_hardware,
        status=status,
        billing_notes=billing_notes,
        quota_notes=quota_notes,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def get_provider(conn: psycopg.Connection, provider_uuid: uuid.UUID) -> Provider | None:
    """Retrieve a single provider by UUID (includes soft-deleted rows).

    Parameters:
        conn: Open psycopg 3 connection.
        provider_uuid: Identity of the provider to fetch.

    Returns:
        Provider | None: The provider record, or None if no row exists.
    """
    sql = (
        "SELECT uuid, name, type, rented_hardware, status, billing_notes, "
        "quota_notes, created_by, created_at, updated_at, deleted_at "
        "FROM provider WHERE uuid = %s"
    )
    row = conn.execute(sql, (provider_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_providers(
    conn: psycopg.Connection,
    *,
    type: str | None = None,
    status: str | None = None,
    include_deleted: bool = False,
) -> list[Provider]:
    """List providers with optional type/status filtering and soft-delete handling.

    Parameters:
        conn: Open psycopg 3 connection.
        type: When given, restrict to providers with this exact type.
        status: When given, restrict to providers with this exact status.
        include_deleted: When False (default), exclude soft-deleted rows.

    Returns:
        list[Provider]: Matching provider records ordered by created_at ascending.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if type is not None:
        conditions.append("type = %s")
        params.append(type)

    if status is not None:
        conditions.append("status = %s")
        params.append(status)

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = (
        "SELECT uuid, name, type, rented_hardware, status, billing_notes, "
        "quota_notes, created_by, created_at, updated_at, deleted_at "
        "FROM provider " + where_clause + " ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def update_provider(
    conn: psycopg.Connection,
    provider_uuid: uuid.UUID,
    *,
    changed_by: str,
    type: str | None = None,
    rented_hardware: bool | None = None,
    status: str | None = None,
    billing_notes: str | None = None,
    quota_notes: str | None = None,
) -> Provider:
    """Update mutable fields of a provider with audit recording.

    Parameters:
        conn: Open psycopg 3 connection.
        provider_uuid: Identity of the provider to update.
        changed_by: Actor performing the update, recorded in the audit trail.
        type: New provider type, when given; validated via validate_provider_type.
        rented_hardware: New rented_hardware flag, when given.
        status: New activity status, when given; validated via
            validate_provider_status.
        billing_notes: New billing notes, when given.
        quota_notes: New quota notes, when given.

    Returns:
        Provider: The updated provider record, re-read from storage.

    Raises:
        RuntimeValidationError: If type or status is given and fails its
            validator, or if no provider exists with provider_uuid.
    """
    if type is not None:
        validate_provider_type(type)
    if status is not None:
        validate_provider_status(status)

    set_clauses: list[str] = []
    params: list[Any] = []

    if type is not None:
        set_clauses.append("type = %s")
        params.append(type)

    if rented_hardware is not None:
        set_clauses.append("rented_hardware = %s")
        params.append(rented_hardware)

    if status is not None:
        set_clauses.append("status = %s")
        params.append(status)

    if billing_notes is not None:
        set_clauses.append("billing_notes = %s")
        params.append(billing_notes)

    if quota_notes is not None:
        set_clauses.append("quota_notes = %s")
        params.append(quota_notes)

    now = datetime.now(timezone.utc).isoformat()
    set_clauses.append("updated_at = %s")
    params.append(now)
    params.append(provider_uuid)

    sql = "UPDATE provider SET " + ", ".join(set_clauses) + " WHERE uuid = %s"
    result = conn.execute(sql, params)

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no provider with uuid={provider_uuid}")

    updated = get_provider(conn, provider_uuid)
    if updated is None:
        raise RuntimeValidationError(f"provider with uuid={provider_uuid} not found after update")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="provider",
        entity_id=provider_uuid,
        action="update",
        changed_by=changed_by,
    )

    return updated


def set_provider_status(
    conn: psycopg.Connection, provider_uuid: uuid.UUID, *, status: str, changed_by: str
) -> Provider:
    """Switch a provider's activity status in a single call (the C-004 switching axis).

    Parameters:
        conn: Open psycopg 3 connection.
        provider_uuid: Identity of the provider whose status changes.
        status: New activity status; validated via validate_provider_status
            (active or suspended).
        changed_by: Actor performing the switch, recorded in the audit trail.

    Returns:
        Provider: The updated provider record, re-read from storage.

    Raises:
        RuntimeValidationError: If status fails validate_provider_status, or if
            no provider exists with provider_uuid.
    """
    validate_provider_status(status)

    now = datetime.now(timezone.utc).isoformat()
    sql = "UPDATE provider SET status = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (status, now, provider_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no provider with uuid={provider_uuid}")

    updated = get_provider(conn, provider_uuid)
    if updated is None:
        raise RuntimeValidationError(f"provider with uuid={provider_uuid} not found after update")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="provider",
        entity_id=provider_uuid,
        action="update",
        changed_by=changed_by,
    )

    return updated


def remove_provider(conn: psycopg.Connection, provider_uuid: uuid.UUID, *, changed_by: str) -> Provider:
    """Soft-delete a provider by setting deleted_at and recording the audit trail.

    Parameters:
        conn: Open psycopg 3 connection.
        provider_uuid: Identity of the provider to soft-delete.
        changed_by: Actor performing the deletion, recorded in the audit trail.

    Returns:
        Provider: The soft-deleted provider record with updated timestamps.

    Raises:
        RuntimeValidationError: If no provider exists with provider_uuid.
    """
    provider = get_provider(conn, provider_uuid)
    if provider is None:
        raise RuntimeValidationError(f"no provider with uuid={provider_uuid}")

    now = datetime.now(timezone.utc).isoformat()
    sql = "UPDATE provider SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (now, now, provider_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no provider with uuid={provider_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="provider",
        entity_id=provider_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return Provider(
        provider_uuid=provider.provider_uuid,
        name=provider.name,
        type=provider.type,
        rented_hardware=provider.rented_hardware,
        status=provider.status,
        billing_notes=provider.billing_notes,
        quota_notes=provider.quota_notes,
        created_by=provider.created_by,
        created_at=provider.created_at,
        updated_at=now,
        deleted_at=now,
    )


def _row_to_record(row: tuple[Any, ...]) -> Provider:
    """Map a database row to a Provider dataclass instance.

    Column order: uuid, name, type, rented_hardware, status, billing_notes,
    quota_notes, created_by, created_at, updated_at, deleted_at.
    """
    (
        provider_uuid,
        name,
        type_,
        rented_hardware,
        status,
        billing_notes,
        quota_notes,
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

    return Provider(
        provider_uuid=provider_uuid,
        name=name,
        type=type_,
        rented_hardware=rented_hardware,
        status=status,
        billing_notes=billing_notes,
        quota_notes=quota_notes,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
