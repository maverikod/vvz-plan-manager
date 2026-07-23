"""Invocation profile persistence store: CRUD, validation, audit, and soft-delete for runtime invocation profiles (C-008)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.domain.invocation_profile import (
    InvocationProfile,
    validate_execution_mode,
    validate_profile_role,
    validate_profile_scope,
    validate_profile_scope_fields,
)
from plan_manager.domain.runtime_validation import (
    RuntimeValidationError,
    check_row_exists,
    validate_step_in_plan_revision,
)
from plan_manager.storage.runtime_audit_store import record_runtime_change


_SELECT_COLUMNS = (
    "SELECT uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
    "step_uuid, step_path, temperature, top_p, max_output_tokens, reasoning_effort, "
    "context_window_budget, timeout, retry_policy, concurrency, rate_hint, "
    "response_format, response_schema, max_tool_iterations, per_call_timeout, "
    "execution_mode, token_budget, cost_budget, dialogue_chain_ref, active, created_by, "
    "created_at, updated_at, deleted_at FROM invocation_profile "
)


def _row_to_record(row: tuple[Any, ...]) -> InvocationProfile:
    """Map a database row (column order matching _SELECT_COLUMNS) to an InvocationProfile."""
    (
        profile_uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid,
        step_uuid, step_path, temperature, top_p, max_output_tokens, reasoning_effort,
        context_window_budget, timeout, retry_policy, concurrency, rate_hint,
        response_format, response_schema, max_tool_iterations, per_call_timeout,
        execution_mode, token_budget, cost_budget, dialogue_chain_ref, active, created_by,
        created_at, updated_at, deleted_at,
    ) = row

    if created_at is not None and hasattr(created_at, "isoformat"):
        created_at = created_at.isoformat()
    if updated_at is not None and hasattr(updated_at, "isoformat"):
        updated_at = updated_at.isoformat()
    if deleted_at is not None and hasattr(deleted_at, "isoformat"):
        deleted_at = deleted_at.isoformat()

    return InvocationProfile(
        profile_uuid=profile_uuid, scope=scope, role=role, plan_uuid=plan_uuid,
        spec_level=spec_level, branch_step_uuid=branch_step_uuid, revision_uuid=revision_uuid,
        step_uuid=step_uuid, step_path=step_path, temperature=temperature, top_p=top_p,
        max_output_tokens=max_output_tokens, reasoning_effort=reasoning_effort,
        context_window_budget=context_window_budget, timeout=timeout, retry_policy=retry_policy,
        concurrency=concurrency, rate_hint=rate_hint, response_format=response_format,
        response_schema=response_schema, max_tool_iterations=max_tool_iterations,
        per_call_timeout=per_call_timeout, execution_mode=execution_mode,
        token_budget=token_budget, cost_budget=cost_budget, dialogue_chain_ref=dialogue_chain_ref,
        active=active, created_by=created_by, created_at=created_at, updated_at=updated_at,
        deleted_at=deleted_at,
    )


def _fetch_by_uuid(conn: psycopg.Connection, profile_uuid: uuid.UUID) -> InvocationProfile | None:
    """Re-select one invocation profile row by uuid and map it via _row_to_record."""
    row = conn.execute(_SELECT_COLUMNS + "WHERE uuid = %s", (profile_uuid,)).fetchone()
    return None if row is None else _row_to_record(row)


def create_invocation_profile(
    conn: psycopg.Connection,
    *,
    scope: str,
    created_by: str,
    role: str | None = None,
    plan_uuid: uuid.UUID | None = None,
    spec_level: str | None = None,
    branch_step_uuid: uuid.UUID | None = None,
    revision_uuid: uuid.UUID | None = None,
    step_uuid: uuid.UUID | None = None,
    step_path: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_output_tokens: int | None = None,
    reasoning_effort: str | None = None,
    context_window_budget: int | None = None,
    timeout: int | None = None,
    retry_policy: dict[str, Any] | None = None,
    concurrency: int | None = None,
    rate_hint: dict[str, Any] | None = None,
    response_format: str | None = None,
    response_schema: dict[str, Any] | None = None,
    max_tool_iterations: int | None = None,
    per_call_timeout: int | None = None,
    execution_mode: str | None = None,
    token_budget: int | None = None,
    cost_budget: float | None = None,
    dialogue_chain_ref: uuid.UUID | None = None,
    active: bool = True,
) -> InvocationProfile:
    """Create a new invocation profile with validation, existence checks, and audit recording."""
    validate_profile_scope(scope)
    if role is not None:
        validate_profile_role(role)
    if execution_mode is not None:
        validate_execution_mode(execution_mode)
    validate_profile_scope_fields(
        scope, role=role, plan_uuid=plan_uuid, spec_level=spec_level,
        branch_step_uuid=branch_step_uuid, step_uuid=step_uuid,
    )

    if plan_uuid is not None:
        check_row_exists(conn, "plan", plan_uuid, frozenset({"plan"}))
    if scope == "step":
        validate_step_in_plan_revision(conn, plan_uuid, revision_uuid, step_uuid)
    if scope == "branch":
        check_row_exists(conn, "step", branch_step_uuid, frozenset({"step"}))

    profile_uuid = uuid.uuid4()
    now_iso = datetime.now(timezone.utc).isoformat()

    sql = (
        "INSERT INTO invocation_profile "
        "(uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
        "step_uuid, step_path, temperature, top_p, max_output_tokens, reasoning_effort, "
        "context_window_budget, timeout, retry_policy, concurrency, rate_hint, "
        "response_format, response_schema, max_tool_iterations, per_call_timeout, "
        "execution_mode, token_budget, cost_budget, dialogue_chain_ref, active, "
        "created_by, created_at, updated_at, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, "
        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    params = (
        profile_uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid,
        step_uuid, step_path, temperature, top_p, max_output_tokens, reasoning_effort,
        context_window_budget, timeout,
        Jsonb(retry_policy) if retry_policy is not None else None,
        concurrency,
        Jsonb(rate_hint) if rate_hint is not None else None,
        response_format,
        Jsonb(response_schema) if response_schema is not None else None,
        max_tool_iterations, per_call_timeout, execution_mode, token_budget, cost_budget,
        dialogue_chain_ref, active, created_by, now_iso, now_iso, None,
    )
    conn.execute(sql, params)

    record_runtime_change(
        conn, plan_uuid=plan_uuid, entity_type="invocation_profile", entity_id=profile_uuid,
        action="create", changed_by=created_by,
    )

    created = _fetch_by_uuid(conn, profile_uuid)
    if created is None:
        raise RuntimeValidationError(f"invocation profile with uuid={profile_uuid} not found after create")
    return created


def get_invocation_profile(conn: psycopg.Connection, profile_uuid: uuid.UUID) -> InvocationProfile | None:
    """Retrieve a single invocation profile by UUID (includes soft-deleted rows)."""
    return _fetch_by_uuid(conn, profile_uuid)


def list_invocation_profiles(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None = None,
    scope: str | None = None,
    role: str | None = None,
    include_deleted: bool = False,
) -> list[InvocationProfile]:
    """List invocation profiles with optional filtering and soft-delete handling."""
    conditions = []
    params: list[Any] = []

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

    sql = _SELECT_COLUMNS + where_clause + " ORDER BY created_at ASC"
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def list_profiles_for_resolution(conn: psycopg.Connection, *, plan_uuid: uuid.UUID) -> list[InvocationProfile]:
    """List active, non-deleted invocation profiles matching the plan or system-wide."""
    sql = (
        _SELECT_COLUMNS
        + "WHERE active = true AND deleted_at IS NULL AND (plan_uuid = %s OR plan_uuid IS NULL) "
        "ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, (plan_uuid,)).fetchall()
    return [_row_to_record(row) for row in rows]


_UPDATE_COLUMNS: tuple[str, ...] = (
    "step_path", "temperature", "top_p", "max_output_tokens", "reasoning_effort",
    "context_window_budget", "timeout", "retry_policy", "concurrency", "rate_hint",
    "response_format", "response_schema", "max_tool_iterations", "per_call_timeout",
    "execution_mode", "token_budget", "cost_budget", "dialogue_chain_ref", "active",
)
_JSONB_UPDATE_COLUMNS: frozenset[str] = frozenset({"retry_policy", "rate_hint", "response_schema"})


def update_invocation_profile(
    conn: psycopg.Connection,
    profile_uuid: uuid.UUID,
    *,
    changed_by: str,
    step_path: str | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_output_tokens: int | None = None,
    reasoning_effort: str | None = None,
    context_window_budget: int | None = None,
    timeout: int | None = None,
    retry_policy: dict[str, Any] | None = None,
    concurrency: int | None = None,
    rate_hint: dict[str, Any] | None = None,
    response_format: str | None = None,
    response_schema: dict[str, Any] | None = None,
    max_tool_iterations: int | None = None,
    per_call_timeout: int | None = None,
    execution_mode: str | None = None,
    token_budget: int | None = None,
    cost_budget: float | None = None,
    dialogue_chain_ref: uuid.UUID | None = None,
    active: bool | None = None,
) -> InvocationProfile:
    """Update mutable informational fields of an invocation profile with audit recording.

    Scope-anchor fields (scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid,
    step_uuid) are immutable after create and are not accepted here, mirroring
    update_model_binding's mutable-field-only surface. Only fields passed as non-None are
    written; every other column is left unchanged.
    """
    if execution_mode is not None:
        validate_execution_mode(execution_mode)

    candidate_values: dict[str, Any] = {
        "step_path": step_path, "temperature": temperature, "top_p": top_p,
        "max_output_tokens": max_output_tokens, "reasoning_effort": reasoning_effort,
        "context_window_budget": context_window_budget, "timeout": timeout,
        "retry_policy": retry_policy, "concurrency": concurrency, "rate_hint": rate_hint,
        "response_format": response_format, "response_schema": response_schema,
        "max_tool_iterations": max_tool_iterations, "per_call_timeout": per_call_timeout,
        "execution_mode": execution_mode, "token_budget": token_budget,
        "cost_budget": cost_budget, "dialogue_chain_ref": dialogue_chain_ref, "active": active,
    }

    set_clauses = []
    params: list[Any] = []
    for column in _UPDATE_COLUMNS:
        value = candidate_values[column]
        if value is None:
            continue
        set_clauses.append(f"{column} = %s")
        params.append(Jsonb(value) if column in _JSONB_UPDATE_COLUMNS else value)

    now_iso = datetime.now(timezone.utc).isoformat()
    set_clauses.append("updated_at = %s")
    params.append(now_iso)
    params.append(profile_uuid)

    sql = "UPDATE invocation_profile SET " + ", ".join(set_clauses) + " WHERE uuid = %s"
    result = conn.execute(sql, params)
    if result.rowcount == 0:
        raise RuntimeValidationError(f"no invocation profile with uuid={profile_uuid}")

    updated_profile = _fetch_by_uuid(conn, profile_uuid)
    if updated_profile is None:
        raise RuntimeValidationError(f"invocation profile with uuid={profile_uuid} not found after update")

    record_runtime_change(
        conn, plan_uuid=updated_profile.plan_uuid, entity_type="invocation_profile",
        entity_id=profile_uuid, action="update", changed_by=changed_by,
    )
    return updated_profile


def remove_invocation_profile(conn: psycopg.Connection, profile_uuid: uuid.UUID, *, changed_by: str) -> InvocationProfile:
    """Soft-delete an invocation profile by setting deleted_at and recording audit trail."""
    existing = _fetch_by_uuid(conn, profile_uuid)
    if existing is None:
        raise RuntimeValidationError(f"no invocation profile with uuid={profile_uuid}")

    now_iso = datetime.now(timezone.utc).isoformat()
    sql = "UPDATE invocation_profile SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (now_iso, now_iso, profile_uuid))
    if result.rowcount == 0:
        raise RuntimeValidationError(f"no invocation profile with uuid={profile_uuid}")

    record_runtime_change(
        conn, plan_uuid=existing.plan_uuid, entity_type="invocation_profile",
        entity_id=profile_uuid, action="soft_delete", changed_by=changed_by,
    )

    deleted = _fetch_by_uuid(conn, profile_uuid)
    if deleted is None:
        raise RuntimeValidationError(f"invocation profile with uuid={profile_uuid} not found after soft-delete")
    return deleted
