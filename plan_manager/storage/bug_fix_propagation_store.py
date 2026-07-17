"""Bug fix propagation persistence: per-impact downstream action records over bug_fix_propagation with audit + soft delete (C-025)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from psycopg.types.json import Jsonb
from plan_manager.domain.bug_fix_propagation import (
    BugFixPropagation, PROPAGATION_ACTIONS, PROPAGATION_STATUSES,
    validate_propagation_action, validate_propagation_status,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: tuple[Any, ...]) -> BugFixPropagation:
    """Build a BugFixPropagation from a full-row tuple."""
    (uuid_val, bug_fix_uuid_val, impact_uuid_val, target_type_val, target_identifier_val,
     action_val, status_val, assigned_to_val, linked_todo_uuid_val, linked_plan_uuid_val,
     linked_cascade_uuid_val, started_at_val, finished_at_val, evidence_val,
     verification_result_val, created_by_val, created_at_val, updated_at_val, deleted_at_val) = row

    return BugFixPropagation(
        propagation_uuid=uuid_val,
        bug_fix_uuid=bug_fix_uuid_val,
        impact_uuid=impact_uuid_val,
        target_type=target_type_val,
        target_identifier=target_identifier_val,
        action=action_val,
        status=status_val,
        assigned_to=assigned_to_val,
        linked_todo_uuid=linked_todo_uuid_val,
        linked_plan_uuid=linked_plan_uuid_val,
        linked_cascade_uuid=linked_cascade_uuid_val,
        started_at=started_at_val.isoformat() if started_at_val is not None else None,
        finished_at=finished_at_val.isoformat() if finished_at_val is not None else None,
        evidence=evidence_val,
        verification_result=verification_result_val,
        created_by=created_by_val,
        created_at=created_at_val.isoformat(),
        updated_at=updated_at_val.isoformat(),
        deleted_at=deleted_at_val.isoformat() if deleted_at_val is not None else None,
    )


def create_bug_fix_propagation(conn: psycopg.Connection, *, bug_fix_uuid: uuid.UUID, impact_uuid: uuid.UUID,
                               action: str, created_by: str, status: str = "pending", target_type: str | None = None,
                               target_identifier: str | None = None, assigned_to: str | None = None,
                               linked_todo_uuid: uuid.UUID | None = None, linked_plan_uuid: uuid.UUID | None = None,
                               linked_cascade_uuid: uuid.UUID | None = None) -> BugFixPropagation:
    """Create a new bug fix propagation record."""
    validate_propagation_action(action)
    validate_propagation_status(status)
    check_row_exists(conn, "bug_fix", bug_fix_uuid, frozenset({"bug_fix"}))
    check_row_exists(conn, "bug_impact", impact_uuid, frozenset({"bug_impact"}))

    propagation_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    sql = (
        "INSERT INTO bug_fix_propagation "
        "(uuid, bug_fix_uuid, impact_uuid, target_type, target_identifier, "
        "action, status, assigned_to, linked_todo_uuid, linked_plan_uuid, "
        "linked_cascade_uuid, started_at, finished_at, evidence, verification_result, "
        "created_by, created_at, updated_at, deleted_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    )
    params = (
        propagation_uuid, bug_fix_uuid, impact_uuid, target_type, target_identifier,
        action, status, assigned_to, linked_todo_uuid, linked_plan_uuid,
        linked_cascade_uuid, None, None, None, None,
        created_by, now, now, None
    )
    conn.execute(sql, params)

    record_runtime_change(
        conn,
        plan_uuid=linked_plan_uuid,
        entity_type="bug_fix_propagation",
        entity_id=propagation_uuid,
        action="create",
        changed_by=created_by
    )

    return BugFixPropagation(
        propagation_uuid=propagation_uuid,
        bug_fix_uuid=bug_fix_uuid,
        impact_uuid=impact_uuid,
        target_type=target_type,
        target_identifier=target_identifier,
        action=action,
        status=status,
        assigned_to=assigned_to,
        linked_todo_uuid=linked_todo_uuid,
        linked_plan_uuid=linked_plan_uuid,
        linked_cascade_uuid=linked_cascade_uuid,
        started_at=None,
        finished_at=None,
        evidence=None,
        verification_result=None,
        created_by=created_by,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        deleted_at=None,
    )


def get_bug_fix_propagation(conn: psycopg.Connection, propagation_uuid: uuid.UUID) -> BugFixPropagation | None:
    """Retrieve a bug fix propagation by UUID."""
    sql = (
        "SELECT uuid, bug_fix_uuid, impact_uuid, target_type, target_identifier, "
        "action, status, assigned_to, linked_todo_uuid, linked_plan_uuid, "
        "linked_cascade_uuid, started_at, finished_at, evidence, verification_result, "
        "created_by, created_at, updated_at, deleted_at "
        "FROM bug_fix_propagation WHERE uuid = %s"
    )
    cursor = conn.execute(sql, (propagation_uuid,))
    row = cursor.fetchone()
    return _row_to_record(row) if row is not None else None


def list_bug_fix_propagations(conn: psycopg.Connection, *, bug_fix_uuid: uuid.UUID | None = None,
                              impact_uuid: uuid.UUID | None = None, status: str | None = None,
                              include_deleted: bool = False,
                              source_plan_uuid: uuid.UUID | None = None,
                              source_project_id: uuid.UUID | None = None,
                              project_bound_plan_uuids: list[uuid.UUID] | None = None) -> list[BugFixPropagation]:
    """List bug fix propagations with optional filters.

    When source_plan_uuid is given, only propagations whose parent bug is anchored to
    that plan match (semi-join propagation -> bug_fix -> bug_report.source_plan_uuid);
    propagations of bugs with a NULL or foreign source_plan_uuid are excluded. The
    linked_plan_uuid column is the propagation TARGET, never this scope column.

    When source_project_id is given, matching is transitive: a propagation whose parent
    bug's source_project_id equals it matches directly, OR (when project_bound_plan_uuids
    is a non-empty list of plan uuids bound to that project via plan.project_ids) a
    propagation whose parent bug's source_plan_uuid is one of those plan uuids also
    matches, even when the parent bug's own source_project_id is NULL.
    project_bound_plan_uuids is ignored when source_project_id is None.
    """
    where_clauses = []
    params = []

    if bug_fix_uuid is not None:
        where_clauses.append("bug_fix_uuid = %s")
        params.append(bug_fix_uuid)

    if source_plan_uuid is not None:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM bug_fix f JOIN bug_report b ON b.uuid = f.bug_uuid "
            "WHERE f.uuid = bug_fix_propagation.bug_fix_uuid AND b.source_plan_uuid = %s)"
        )
        params.append(source_plan_uuid)

    if source_project_id is not None:
        if project_bound_plan_uuids:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM bug_fix f JOIN bug_report b ON b.uuid = f.bug_uuid "
                "WHERE f.uuid = bug_fix_propagation.bug_fix_uuid "
                "AND (b.source_project_id = %s OR b.source_plan_uuid = ANY(%s)))"
            )
            params.append(source_project_id)
            params.append(project_bound_plan_uuids)
        else:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM bug_fix f JOIN bug_report b ON b.uuid = f.bug_uuid "
                "WHERE f.uuid = bug_fix_propagation.bug_fix_uuid AND b.source_project_id = %s)"
            )
            params.append(source_project_id)

    if impact_uuid is not None:
        where_clauses.append("impact_uuid = %s")
        params.append(impact_uuid)

    if status is not None:
        where_clauses.append("status = %s")
        params.append(status)

    if not include_deleted:
        where_clauses.append("deleted_at IS NULL")

    where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"

    sql = (
        "SELECT uuid, bug_fix_uuid, impact_uuid, target_type, target_identifier, "
        "action, status, assigned_to, linked_todo_uuid, linked_plan_uuid, "
        "linked_cascade_uuid, started_at, finished_at, evidence, verification_result, "
        "created_by, created_at, updated_at, deleted_at "
        f"FROM bug_fix_propagation WHERE {where_clause} "
        "ORDER BY created_at ASC"
    )
    cursor = conn.execute(sql, params)
    return [_row_to_record(row) for row in cursor.fetchall()]


def update_bug_fix_propagation(conn: psycopg.Connection, propagation_uuid: uuid.UUID, *, changed_by: str,
                               status: str | None = None, assigned_to: str | None = None,
                               evidence: dict[str, Any] | None = None, verification_result: str | None = None,
                               linked_todo_uuid: uuid.UUID | None = None) -> BugFixPropagation:
    """Update a bug fix propagation record."""
    now = datetime.now(timezone.utc)

    set_clauses = []
    params = []

    if status is not None:
        validate_propagation_status(status)
        set_clauses.append("status = %s")
        params.append(status)

    if assigned_to is not None:
        set_clauses.append("assigned_to = %s")
        params.append(assigned_to)

    if evidence is not None:
        set_clauses.append("evidence = %s")
        params.append(Jsonb(evidence))

    if verification_result is not None:
        set_clauses.append("verification_result = %s")
        params.append(verification_result)

    if linked_todo_uuid is not None:
        set_clauses.append("linked_todo_uuid = %s")
        params.append(linked_todo_uuid)

    if status is not None and status == "in_progress":
        current_row_sql = (
            "SELECT started_at FROM bug_fix_propagation WHERE uuid = %s"
        )
        cursor = conn.execute(current_row_sql, (propagation_uuid,))
        current_row = cursor.fetchone()
        if current_row is not None and current_row[0] is None:
            set_clauses.append("started_at = %s")
            params.append(now)

    if status is not None and status in {"done", "verified", "skipped", "failed"}:
        set_clauses.append("finished_at = %s")
        params.append(now)

    set_clauses.append("updated_at = %s")
    params.append(now)

    set_clause = ", ".join(set_clauses)
    params.append(propagation_uuid)

    sql = (
        f"UPDATE bug_fix_propagation SET {set_clause} WHERE uuid = %s"
    )
    conn.execute(sql, params)

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="bug_fix_propagation",
        entity_id=propagation_uuid,
        action="update",
        changed_by=changed_by
    )

    fetched_row_sql = (
        "SELECT uuid, bug_fix_uuid, impact_uuid, target_type, target_identifier, "
        "action, status, assigned_to, linked_todo_uuid, linked_plan_uuid, "
        "linked_cascade_uuid, started_at, finished_at, evidence, verification_result, "
        "created_by, created_at, updated_at, deleted_at "
        "FROM bug_fix_propagation WHERE uuid = %s"
    )
    cursor = conn.execute(fetched_row_sql, (propagation_uuid,))
    row = cursor.fetchone()
    return _row_to_record(row)


def soft_delete_bug_fix_propagation(conn: psycopg.Connection, propagation_uuid: uuid.UUID, *, changed_by: str) -> BugFixPropagation:
    """Soft delete a bug fix propagation record."""
    now = datetime.now(timezone.utc)

    sql = (
        "UPDATE bug_fix_propagation SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    )
    conn.execute(sql, (now, now, propagation_uuid))

    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="bug_fix_propagation",
        entity_id=propagation_uuid,
        action="soft_delete",
        changed_by=changed_by
    )

    fetched_row_sql = (
        "SELECT uuid, bug_fix_uuid, impact_uuid, target_type, target_identifier, "
        "action, status, assigned_to, linked_todo_uuid, linked_plan_uuid, "
        "linked_cascade_uuid, started_at, finished_at, evidence, verification_result, "
        "created_by, created_at, updated_at, deleted_at "
        "FROM bug_fix_propagation WHERE uuid = %s"
    )
    cursor = conn.execute(fetched_row_sql, (propagation_uuid,))
    row = cursor.fetchone()
    return _row_to_record(row)
