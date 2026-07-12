"""Model binding persistence store: CRUD, validation, audit, and soft-delete for runtime model bindings (C-009)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.model_binding import (
    ModelBinding,
    validate_binding_scope,
    validate_scope_fields,
)
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import (
    RuntimeValidationError,
    check_row_exists,
    validate_step_in_plan_revision,
)
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_model_binding(
    conn: psycopg.Connection,
    *,
    scope: str,
    provider: str,
    model: str,
    max_retries: int,
    timeout: int,
    created_by: str,
    role: str | None = None,
    plan_uuid: uuid.UUID | None = None,
    spec_level: str | None = None,
    branch_step_uuid: uuid.UUID | None = None,
    revision_uuid: uuid.UUID | None = None,
    step_uuid: uuid.UUID | None = None,
    step_path: str | None = None,
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
    context_budget: int | None = None,
    active: bool = True,
) -> ModelBinding:
    """Create a new model binding with validation, existence checks, and audit recording."""
    # Validation step 1: validate scope
    validate_binding_scope(scope)

    # Validation step 2: validate role if provided
    if role is not None:
        validate_runtime_role(role)

    # Validation step 3: validate scope-field consistency
    validate_scope_fields(
        scope,
        role=role,
        plan_uuid=plan_uuid,
        spec_level=spec_level,
        branch_step_uuid=branch_step_uuid,
        step_uuid=step_uuid,
    )

    # Validation step 4: perform existence checks
    if plan_uuid is not None:
        check_row_exists(conn, "plan", plan_uuid, frozenset({"plan"}))

    if scope == "step":
        validate_step_in_plan_revision(conn, plan_uuid, revision_uuid, step_uuid)

    if scope == "branch":
        check_row_exists(conn, "step", branch_step_uuid, frozenset({"step"}))

    # Generate UUIDs and timestamps
    binding_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    updated_at = now.isoformat()
    deleted_at = None

    # Insert into database with exact column order
    sql = (
        "INSERT INTO model_binding "
        "(uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
        "step_uuid, step_path, provider, model, fallback_provider, fallback_model, "
        "max_retries, timeout, context_budget, active, created_by, created_at, "
        "updated_at, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s)"
    )
    params = (
        binding_uuid,
        scope,
        role,
        plan_uuid,
        spec_level,
        branch_step_uuid,
        revision_uuid,
        step_uuid,
        step_path,
        provider,
        model,
        fallback_provider,
        fallback_model,
        max_retries,
        timeout,
        context_budget,
        active,
        created_by,
        created_at,
        updated_at,
        deleted_at,
    )
    conn.execute(sql, params)

    # Record audit trail
    record_runtime_change(
        conn,
        plan_uuid=plan_uuid,
        entity_type="model_binding",
        entity_id=binding_uuid,
        action="create",
        changed_by=created_by,
    )

    # Build and return the ModelBinding instance
    return ModelBinding(
        binding_uuid=binding_uuid,
        scope=scope,
        role=role,
        plan_uuid=plan_uuid,
        spec_level=spec_level,
        branch_step_uuid=branch_step_uuid,
        revision_uuid=revision_uuid,
        step_uuid=step_uuid,
        step_path=step_path,
        provider=provider,
        model=model,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
        max_retries=max_retries,
        timeout=timeout,
        context_budget=context_budget,
        active=active,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


def get_model_binding(conn: psycopg.Connection, binding_uuid: uuid.UUID) -> ModelBinding | None:
    """Retrieve a single model binding by UUID (includes soft-deleted rows)."""
    sql = (
        "SELECT uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
        "step_uuid, step_path, provider, model, fallback_provider, fallback_model, "
        "max_retries, timeout, context_budget, active, created_by, created_at, "
        "updated_at, deleted_at FROM model_binding WHERE uuid = %s"
    )
    row = conn.execute(sql, (binding_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_model_bindings(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None = None,
    scope: str | None = None,
    role: str | None = None,
    include_deleted: bool = False,
) -> list[ModelBinding]:
    """List model bindings with optional filtering and soft-delete handling."""
    conditions = []
    params = []

    if plan_uuid is not None:
        conditions.append("plan_uuid = %s")
        params.append(plan_uuid)

    if scope is not None:
        conditions.append("scope = %s")
        params.append(scope)

    if role is not None:
        conditions.append("role = %s")
        params.append(role)

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    sql = (
        "SELECT uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
        "step_uuid, step_path, provider, model, fallback_provider, fallback_model, "
        "max_retries, timeout, context_budget, active, created_by, created_at, "
        "updated_at, deleted_at FROM model_binding "
        + where_clause
        + " ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def list_bindings_for_resolution(conn: psycopg.Connection, *, plan_uuid: uuid.UUID) -> list[ModelBinding]:
    """List active, non-deleted model bindings matching the plan or system-wide."""
    sql = (
        "SELECT uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
        "step_uuid, step_path, provider, model, fallback_provider, fallback_model, "
        "max_retries, timeout, context_budget, active, created_by, created_at, "
        "updated_at, deleted_at FROM model_binding "
        "WHERE active = true AND deleted_at IS NULL AND (plan_uuid = %s OR plan_uuid IS NULL) "
        "ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, (plan_uuid,)).fetchall()
    return [_row_to_record(row) for row in rows]


def update_model_binding(
    conn: psycopg.Connection,
    binding_uuid: uuid.UUID,
    *,
    changed_by: str,
    provider: str | None = None,
    model: str | None = None,
    fallback_provider: str | None = None,
    fallback_model: str | None = None,
    max_retries: int | None = None,
    timeout: int | None = None,
    context_budget: int | None = None,
    active: bool | None = None,
) -> ModelBinding:
    """Update mutable fields of a model binding with audit recording."""
    # Build the UPDATE statement dynamically for non-None fields
    set_clauses = []
    params = []

    if provider is not None:
        set_clauses.append("provider = %s")
        params.append(provider)

    if model is not None:
        set_clauses.append("model = %s")
        params.append(model)

    if fallback_provider is not None:
        set_clauses.append("fallback_provider = %s")
        params.append(fallback_provider)

    if fallback_model is not None:
        set_clauses.append("fallback_model = %s")
        params.append(fallback_model)

    if max_retries is not None:
        set_clauses.append("max_retries = %s")
        params.append(max_retries)

    if timeout is not None:
        set_clauses.append("timeout = %s")
        params.append(timeout)

    if context_budget is not None:
        set_clauses.append("context_budget = %s")
        params.append(context_budget)

    if active is not None:
        set_clauses.append("active = %s")
        params.append(active)

    # Always update updated_at
    now = datetime.now(timezone.utc)
    updated_at = now.isoformat()
    set_clauses.append("updated_at = %s")
    params.append(updated_at)

    # Add binding_uuid to params for the WHERE clause
    params.append(binding_uuid)

    sql = "UPDATE model_binding SET " + ", ".join(set_clauses) + " WHERE uuid = %s"
    result = conn.execute(sql, params)

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no model binding with uuid={binding_uuid}")

    # Re-read the updated row to get the current plan_uuid and other fields
    updated_binding = get_model_binding(conn, binding_uuid)
    if updated_binding is None:
        raise RuntimeValidationError(f"model binding with uuid={binding_uuid} not found after update")

    # Record audit trail
    record_runtime_change(
        conn,
        plan_uuid=updated_binding.plan_uuid,
        entity_type="model_binding",
        entity_id=binding_uuid,
        action="update",
        changed_by=changed_by,
    )

    return updated_binding


def remove_model_binding(conn: psycopg.Connection, binding_uuid: uuid.UUID, *, changed_by: str) -> ModelBinding:
    """Soft-delete a model binding by setting deleted_at and recording audit trail."""
    # First, fetch the binding to get its plan_uuid for audit recording
    binding = get_model_binding(conn, binding_uuid)
    if binding is None:
        raise RuntimeValidationError(f"no model binding with uuid={binding_uuid}")

    # Perform soft delete
    now = datetime.now(timezone.utc)
    deleted_at = now.isoformat()
    updated_at = now.isoformat()

    sql = "UPDATE model_binding SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (deleted_at, updated_at, binding_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no model binding with uuid={binding_uuid}")

    # Record audit trail
    record_runtime_change(
        conn,
        plan_uuid=binding.plan_uuid,
        entity_type="model_binding",
        entity_id=binding_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    # Return the soft-deleted binding with updated timestamps
    return ModelBinding(
        binding_uuid=binding.binding_uuid,
        scope=binding.scope,
        role=binding.role,
        plan_uuid=binding.plan_uuid,
        spec_level=binding.spec_level,
        branch_step_uuid=binding.branch_step_uuid,
        revision_uuid=binding.revision_uuid,
        step_uuid=binding.step_uuid,
        step_path=binding.step_path,
        provider=binding.provider,
        model=binding.model,
        fallback_provider=binding.fallback_provider,
        fallback_model=binding.fallback_model,
        max_retries=binding.max_retries,
        timeout=binding.timeout,
        context_budget=binding.context_budget,
        active=binding.active,
        created_by=binding.created_by,
        created_at=binding.created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


def _row_to_record(row: tuple[Any, ...]) -> ModelBinding:
    """Map a database row to a ModelBinding dataclass instance."""
    # Column order: uuid, scope, role, plan_uuid, spec_level, branch_step_uuid,
    # revision_uuid, step_uuid, step_path, provider, model, fallback_provider,
    # fallback_model, max_retries, timeout, context_budget, active, created_by,
    # created_at, updated_at, deleted_at
    binding_uuid = row[0]
    scope = row[1]
    role = row[2]
    plan_uuid = row[3]
    spec_level = row[4]
    branch_step_uuid = row[5]
    revision_uuid = row[6]
    step_uuid = row[7]
    step_path = row[8]
    provider = row[9]
    model = row[10]
    fallback_provider = row[11]
    fallback_model = row[12]
    max_retries = row[13]
    timeout = row[14]
    context_budget = row[15]
    active = row[16]
    created_by = row[17]
    created_at = row[18]
    updated_at = row[19]
    deleted_at = row[20]

    # Convert datetime objects to ISO format strings if needed
    if created_at is not None and hasattr(created_at, 'isoformat'):
        created_at = created_at.isoformat()
    if updated_at is not None and hasattr(updated_at, 'isoformat'):
        updated_at = updated_at.isoformat()
    if deleted_at is not None and hasattr(deleted_at, 'isoformat'):
        deleted_at = deleted_at.isoformat()

    return ModelBinding(
        binding_uuid=binding_uuid,
        scope=scope,
        role=role,
        plan_uuid=plan_uuid,
        spec_level=spec_level,
        branch_step_uuid=branch_step_uuid,
        revision_uuid=revision_uuid,
        step_uuid=step_uuid,
        step_path=step_path,
        provider=provider,
        model=model,
        fallback_provider=fallback_provider,
        fallback_model=fallback_model,
        max_retries=max_retries,
        timeout=timeout,
        context_budget=context_budget,
        active=active,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
