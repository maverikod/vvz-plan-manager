"""Step assignment persistence store: CRUD, validation, audit, and soft-delete for per-step role/toolset assignment records (C-007)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.runtime_validation import (
    RuntimeValidationError,
    check_row_exists,
    validate_step_in_plan_revision,
)
from plan_manager.domain.step_assignment import (
    StepAssignment,
    validate_assignment_payload,
    validate_assignment_scope_fields,
    validate_assignment_selectors,
)
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_step_assignment(
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
    assigned_role: str | None = None,
    toolset_uuid: uuid.UUID | None = None,
    active: bool = True,
) -> StepAssignment:
    """Create a new step assignment with validation, existence checks, and audit recording."""
    # Validation step 1: validate scope value and scope-field consistency
    validate_assignment_scope_fields(
        scope,
        role=role,
        plan_uuid=plan_uuid,
        spec_level=spec_level,
        branch_step_uuid=branch_step_uuid,
        step_uuid=step_uuid,
    )

    # Validation step 2: validate the two runtime-role-typed fields
    validate_assignment_selectors(role, assigned_role)

    # Validation step 3: require at least one non-null payload field
    validate_assignment_payload(assigned_role, toolset_uuid)

    # Validation step 4: perform existence checks against core tables only (plan, step)
    if plan_uuid is not None:
        check_row_exists(conn, "plan", plan_uuid, frozenset({"plan"}))

    if scope == "step":
        validate_step_in_plan_revision(conn, plan_uuid, revision_uuid, step_uuid)

    if scope == "branch":
        check_row_exists(conn, "step", branch_step_uuid, frozenset({"step"}))

    # Generate UUID and timestamps
    assignment_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    created_at = now.isoformat()
    updated_at = now.isoformat()
    deleted_at = None

    # Insert into database with exact column order
    sql = (
        "INSERT INTO step_assignment "
        "(uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
        "step_uuid, step_path, assigned_role, toolset_uuid, active, created_by, created_at, "
        "updated_at, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    params = (
        assignment_uuid,
        scope,
        role,
        plan_uuid,
        spec_level,
        branch_step_uuid,
        revision_uuid,
        step_uuid,
        step_path,
        assigned_role,
        toolset_uuid,
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
        entity_type="step_assignment",
        entity_id=assignment_uuid,
        action="create",
        changed_by=created_by,
    )

    # Build and return the StepAssignment instance
    return StepAssignment(
        assignment_uuid=assignment_uuid,
        scope=scope,
        role=role,
        plan_uuid=plan_uuid,
        spec_level=spec_level,
        branch_step_uuid=branch_step_uuid,
        revision_uuid=revision_uuid,
        step_uuid=step_uuid,
        step_path=step_path,
        assigned_role=assigned_role,
        toolset_uuid=toolset_uuid,
        active=active,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


def get_step_assignment(conn: psycopg.Connection, assignment_uuid: uuid.UUID) -> StepAssignment | None:
    """Retrieve a single step assignment by UUID (includes soft-deleted rows)."""
    sql = (
        "SELECT uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
        "step_uuid, step_path, assigned_role, toolset_uuid, active, created_by, created_at, "
        "updated_at, deleted_at FROM step_assignment WHERE uuid = %s"
    )
    row = conn.execute(sql, (assignment_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_step_assignments(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None = None,
    scope: str | None = None,
    role: str | None = None,
    include_deleted: bool = False,
) -> list[StepAssignment]:
    """List step assignments with optional filtering and soft-delete handling."""
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
        "step_uuid, step_path, assigned_role, toolset_uuid, active, created_by, created_at, "
        "updated_at, deleted_at FROM step_assignment "
        + where_clause
        + " ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def list_for_resolution(conn: psycopg.Connection, *, plan_uuid: uuid.UUID) -> list[StepAssignment]:
    """List active, non-deleted step assignments matching the plan or system-wide."""
    sql = (
        "SELECT uuid, scope, role, plan_uuid, spec_level, branch_step_uuid, revision_uuid, "
        "step_uuid, step_path, assigned_role, toolset_uuid, active, created_by, created_at, "
        "updated_at, deleted_at FROM step_assignment "
        "WHERE active = true AND deleted_at IS NULL AND (plan_uuid = %s OR plan_uuid IS NULL) "
        "ORDER BY created_at ASC"
    )
    rows = conn.execute(sql, (plan_uuid,)).fetchall()
    return [_row_to_record(row) for row in rows]


def update_step_assignment(
    conn: psycopg.Connection,
    assignment_uuid: uuid.UUID,
    *,
    changed_by: str,
    assigned_role: str | None = None,
    toolset_uuid: uuid.UUID | None = None,
    active: bool | None = None,
) -> StepAssignment:
    """Update mutable payload fields of a step assignment with audit recording."""
    # Build the UPDATE statement dynamically for non-None fields
    set_clauses = []
    params = []

    if assigned_role is not None:
        validate_assignment_selectors(None, assigned_role)
        set_clauses.append("assigned_role = %s")
        params.append(assigned_role)

    if toolset_uuid is not None:
        set_clauses.append("toolset_uuid = %s")
        params.append(toolset_uuid)

    if active is not None:
        set_clauses.append("active = %s")
        params.append(active)

    # Always update updated_at
    now = datetime.now(timezone.utc)
    updated_at = now.isoformat()
    set_clauses.append("updated_at = %s")
    params.append(updated_at)

    # Add assignment_uuid to params for the WHERE clause
    params.append(assignment_uuid)

    sql = "UPDATE step_assignment SET " + ", ".join(set_clauses) + " WHERE uuid = %s"
    result = conn.execute(sql, params)

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no step assignment with uuid={assignment_uuid}")

    # Re-read the updated row to get the current plan_uuid and other fields
    updated_assignment = get_step_assignment(conn, assignment_uuid)
    if updated_assignment is None:
        raise RuntimeValidationError(f"step assignment with uuid={assignment_uuid} not found after update")

    # Record audit trail
    record_runtime_change(
        conn,
        plan_uuid=updated_assignment.plan_uuid,
        entity_type="step_assignment",
        entity_id=assignment_uuid,
        action="update",
        changed_by=changed_by,
    )

    return updated_assignment


def remove_step_assignment(conn: psycopg.Connection, assignment_uuid: uuid.UUID, *, changed_by: str) -> StepAssignment:
    """Soft-delete a step assignment by setting deleted_at and recording audit trail."""
    # First, fetch the assignment to get its plan_uuid for audit recording
    assignment = get_step_assignment(conn, assignment_uuid)
    if assignment is None:
        raise RuntimeValidationError(f"no step assignment with uuid={assignment_uuid}")

    # Perform soft delete
    now = datetime.now(timezone.utc)
    deleted_at = now.isoformat()
    updated_at = now.isoformat()

    sql = "UPDATE step_assignment SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (deleted_at, updated_at, assignment_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"no step assignment with uuid={assignment_uuid}")

    # Record audit trail
    record_runtime_change(
        conn,
        plan_uuid=assignment.plan_uuid,
        entity_type="step_assignment",
        entity_id=assignment_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    # Return the soft-deleted assignment with updated timestamps
    return StepAssignment(
        assignment_uuid=assignment.assignment_uuid,
        scope=assignment.scope,
        role=assignment.role,
        plan_uuid=assignment.plan_uuid,
        spec_level=assignment.spec_level,
        branch_step_uuid=assignment.branch_step_uuid,
        revision_uuid=assignment.revision_uuid,
        step_uuid=assignment.step_uuid,
        step_path=assignment.step_path,
        assigned_role=assignment.assigned_role,
        toolset_uuid=assignment.toolset_uuid,
        active=assignment.active,
        created_by=assignment.created_by,
        created_at=assignment.created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )


def _row_to_record(row: tuple[Any, ...]) -> StepAssignment:
    """Map a database row to a StepAssignment dataclass instance."""
    # Column order: uuid, scope, role, plan_uuid, spec_level, branch_step_uuid,
    # revision_uuid, step_uuid, step_path, assigned_role, toolset_uuid, active,
    # created_by, created_at, updated_at, deleted_at
    assignment_uuid = row[0]
    scope = row[1]
    role = row[2]
    plan_uuid = row[3]
    spec_level = row[4]
    branch_step_uuid = row[5]
    revision_uuid = row[6]
    step_uuid = row[7]
    step_path = row[8]
    assigned_role = row[9]
    toolset_uuid = row[10]
    active = row[11]
    created_by = row[12]
    created_at = row[13]
    updated_at = row[14]
    deleted_at = row[15]

    # Convert datetime objects to ISO format strings if needed
    if created_at is not None and hasattr(created_at, 'isoformat'):
        created_at = created_at.isoformat()
    if updated_at is not None and hasattr(updated_at, 'isoformat'):
        updated_at = updated_at.isoformat()
    if deleted_at is not None and hasattr(deleted_at, 'isoformat'):
        deleted_at = deleted_at.isoformat()

    return StepAssignment(
        assignment_uuid=assignment_uuid,
        scope=scope,
        role=role,
        plan_uuid=plan_uuid,
        spec_level=spec_level,
        branch_step_uuid=branch_step_uuid,
        revision_uuid=revision_uuid,
        step_uuid=step_uuid,
        step_path=step_path,
        assigned_role=assigned_role,
        toolset_uuid=toolset_uuid,
        active=active,
        created_by=created_by,
        created_at=created_at,
        updated_at=updated_at,
        deleted_at=deleted_at,
    )
