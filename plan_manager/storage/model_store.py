"""Model persistence store: CRUD, validation, provider-reference enforcement, audit, and soft-delete for the model entity (C-005)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.model import Model, validate_execution_mode
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_model(
    conn: psycopg.Connection,
    *,
    name: str,
    provider_uuid: uuid.UUID,
    level: str,
    execution_mode: str,
    created_by: str,
    context_window: int | None = None,
    cost_class: str | None = None,
    availability: str | None = None,
) -> Model:
    """Create a new model record, enforcing model-depends-on-provider, with audit recording.

    Parameters:
        conn: Open psycopg 3 connection.
        name: Model name.
        provider_uuid: The provider this model runs on; validated to reference
            a live (non-soft-deleted) provider row before insert.
        level: Capability level (the indirection roles request against).
        execution_mode: Interactive or batch; validated via
            validate_execution_mode.
        created_by: Actor performing the creation, recorded in the audit trail.
        context_window: Optional context window size.
        cost_class: Optional cost classification.
        availability: Optional availability descriptor.

    Returns:
        Model: The newly created model record.

    Raises:
        RuntimeValidationError: If execution_mode fails validate_execution_mode,
            or if no live provider exists with provider_uuid.
    """
    validate_execution_mode(execution_mode)

    provider_row = conn.execute(
        "SELECT 1 FROM provider WHERE uuid = %s AND deleted_at IS NULL",
        (provider_uuid,),
    ).fetchone()
    if provider_row is None:
        raise RuntimeValidationError(f"no live provider with uuid={provider_uuid}")

    model_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc).isoformat()

    sql = (
        "INSERT INTO model "
        "(uuid, name, provider_uuid, level, context_window, cost_class, "
        "availability, execution_mode, created_by, created_at, updated_at, "
        "deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    params = (
        model_uuid,
        name,
        provider_uuid,
        level,
        context_window,
        cost_class,
        availability,
        execution_mode,
        created_by,
        now,
        now,
        None,
    )
    conn.execute(sql, params)

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="model",
        entity_id=model_uuid,
        action="create",
        changed_by=created_by,
    )

    return Model(
        model_uuid=model_uuid,
        name=name,
        provider_uuid=provider_uuid,
        level=level,
        context_window=context_window,
        cost_class=cost_class,
        availability=availability,
        execution_mode=execution_mode,
        created_by=created_by,
        created_at=now,
        updated_at=now,
        deleted_at=None,
    )


def get_model(conn: psycopg.Connection, model_uuid: uuid.UUID) -> Model | None:
    """Retrieve a single model by UUID (includes soft-deleted rows).

    Parameters:
        conn: Open psycopg 3 connection.
        model_uuid: Identity of the model to fetch.

    Returns:
        Model | None: The model record, or None if no row exists.
    """
    sql = (
        "SELECT uuid, name, provider_uuid, level, context_window, cost_class, "
        "availability, execution_mode, created_by, created_at, updated_at, "
        "deleted_at FROM model WHERE uuid = %s"
    )
    row = conn.execute(sql, (model_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_models(
    conn: psycopg.Connection,
    *,
    provider_uuid: uuid.UUID | None = None,
    level: str | None = None,
    execution_mode: str | None = None,
    include_deleted: bool = False,
) -> list[Model]:
    """List models with optional provider/level/execution_mode filtering and soft-delete handling.

    Parameters:
        conn: Open psycopg 3 connection.
        provider_uuid: When given, restrict to models with this provider_uuid.
        level: When given, restrict to models with this exact level.
        execution_mode: When given, restrict to models with this exact
            execution_mode.
        include_deleted: When False (default), exclude soft-deleted rows.

    Returns:
        list[Model]: Matching model records ordered by created_at ascending.
    """
    conditions: list[str] = []
    params: list[Any] = []

    if provider_uuid is not None:
        conditions.append("provider_uuid = %s")
        params.append(provider_uuid)

    if level is not None:
        conditions.append("level = %s")
        params.append(level)

    if execution_mode is not None:
        conditions.append("execution_mode = %s")
        params.append(execution_mode)

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    sql = (
        "SELECT uuid, name, provider_uuid, level, context_window, cost_class, "
        "availability, execution_mode, created_by, created_at, updated_at, "
        "deleted_at FROM model " + where_clause + " ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def update_model(
    conn: psycopg.Connection,
    model_uuid: uuid.UUID,
    *,
    changed_by: str,
    level: str | None = None,
    context_window: int | None = None,
    cost_class: str | None = None,
    availability: str | None = None,
    execution_mode: str | None = None,
) -> Model:
    """Update mutable fields of a model with audit recording. name and provider_uuid are set at create and not updated here.

    Parameters:
        conn: Open psycopg 3 connection.
        model_uuid: Identity of the model to update.
        changed_by: Actor performing the update, recorded in the audit trail.
        level: New capability level, when given.
        context_window: New context window size, when given.
        cost_class: New cost classification, when given.
        availability: New availability descriptor, when given.
        execution_mode: New execution mode, when given; validated via
            validate_execution_mode.

    Returns:
        Model: The updated model record, re-read from storage.

    Raises:
        RuntimeValidationError: If execution_mode is given and fails
            validate_execution_mode, or if no model exists with model_uuid.
    """
    if execution_mode is not None:
        validate_execution_mode(execution_mode)

    set_clauses: list[str] = []
    params: list[Any] = []

    if level is not None:
        set_clauses.append("level = %s")
        params.append(level)

    if context_window is not None:
        set_clauses.append("context_window = %s")
        params.append(context_window)

    if cost_class is not None:
        set_clauses.append("cost_class = %s")
        params.append(cost_class)

    if availability is not None:
        set_clauses.append("availability = %s")
        params.append(availability)

    if execution_mode is not None:
        set_clauses.append("execution_mode = %s")
        params.append(execution_mode)

    now = datetime.now(timezone.utc).isoformat()
    set_clauses.append("updated_at = %s")
    params.append(now)
    params.append(model_uuid)

    sql = "UPDATE model SET " + ", ".join(set_clauses) + " WHERE uuid = %s"
    result = conn.execute(sql, params)

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no model with uuid={model_uuid}")

    updated = get_model(conn, model_uuid)
    if updated is None:
        raise RuntimeValidationError(f"model with uuid={model_uuid} not found after update")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="model",
        entity_id=model_uuid,
        action="update",
        changed_by=changed_by,
    )

    return updated


def remove_model(conn: psycopg.Connection, model_uuid: uuid.UUID, *, changed_by: str) -> Model:
    """Soft-delete a model by setting deleted_at and recording the audit trail.

    Parameters:
        conn: Open psycopg 3 connection.
        model_uuid: Identity of the model to soft-delete.
        changed_by: Actor performing the deletion, recorded in the audit trail.

    Returns:
        Model: The soft-deleted model record with updated timestamps.

    Raises:
        RuntimeValidationError: If no model exists with model_uuid.
    """
    model = get_model(conn, model_uuid)
    if model is None:
        raise RuntimeValidationError(f"no model with uuid={model_uuid}")

    now = datetime.now(timezone.utc).isoformat()
    sql = "UPDATE model SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (now, now, model_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no model with uuid={model_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="model",
        entity_id=model_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return Model(
        model_uuid=model.model_uuid,
        name=model.name,
        provider_uuid=model.provider_uuid,
        level=model.level,
        context_window=model.context_window,
        cost_class=model.cost_class,
        availability=model.availability,
        execution_mode=model.execution_mode,
        created_by=model.created_by,
        created_at=model.created_at,
        updated_at=now,
        deleted_at=now,
    )


def _row_to_record(row: tuple[Any, ...]) -> Model:
    """Map a database row to a Model dataclass instance.

    Column order: uuid, name, provider_uuid, level, context_window, cost_class,
    availability, execution_mode, created_by, created_at, updated_at, deleted_at.
    """
    (
        model_uuid,
        name,
        provider_uuid,
        level,
        context_window,
        cost_class,
        availability,
        execution_mode,
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

    return Model(
        model_uuid=model_uuid,
        name=name,
        provider_uuid=provider_uuid,
        level=level,
        context_window=context_window,
        cost_class=cost_class,
        availability=availability,
        execution_mode=execution_mode,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
