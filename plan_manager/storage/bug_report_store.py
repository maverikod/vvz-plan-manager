"""Bug report persistence: CRUD and mechanical lifecycle status transitions over bug_report with audit + soft delete (C-020)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from psycopg.types.json import Jsonb
from plan_manager.domain.bug_report import (
    BugReport, BUG_KINDS, BUG_SEVERITIES, BUG_STATUSES,
    validate_bug_kind, validate_bug_severity, validate_bug_status,
)
from plan_manager.domain.bug_source import BugSource, validate_bug_source, bug_source_to_columns, bug_source_from_columns
from plan_manager.domain.nice_priority import validate_nice_priority
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: tuple[Any, ...]) -> BugReport:
    """Convert a raw database row tuple to a BugReport object."""
    (uuid_val, title, short_description, detailed_description, expected_behavior, actual_behavior,
     reproduction, evidence, environment, kind, severity, priority_nice, status, reporter, owner,
     duplicate_of_uuid, parent_bug_uuid, source_anchor_type, source_project_id, source_file_path,
     source_plan_uuid, source_revision_uuid, source_step_uuid, source_step_path, source_ref_id,
     source_command, source_service, confirmed_at, closed_at, reopened_at, created_by, created_at,
     updated_at, deleted_at) = row
    return BugReport(
        bug_uuid=uuid_val, title=title, short_description=short_description,
        detailed_description=detailed_description, expected_behavior=expected_behavior,
        actual_behavior=actual_behavior, reproduction=reproduction, evidence=evidence,
        environment=environment, kind=kind, severity=severity, priority_nice=priority_nice,
        status=status, reporter=reporter, owner=owner, duplicate_of_uuid=duplicate_of_uuid,
        parent_bug_uuid=parent_bug_uuid, source_anchor_type=source_anchor_type,
        source_project_id=source_project_id, source_file_path=source_file_path,
        source_plan_uuid=source_plan_uuid, source_revision_uuid=source_revision_uuid,
        source_step_uuid=source_step_uuid, source_step_path=source_step_path,
        source_ref_id=source_ref_id, source_command=source_command, source_service=source_service,
        confirmed_at=(confirmed_at.isoformat() if confirmed_at else None),
        closed_at=(closed_at.isoformat() if closed_at else None),
        reopened_at=(reopened_at.isoformat() if reopened_at else None),
        created_by=created_by, created_at=created_at.isoformat(),
        updated_at=updated_at.isoformat(), deleted_at=(deleted_at.isoformat() if deleted_at else None),
    )


def create_bug(
    conn: psycopg.Connection,
    *,
    title: str,
    short_description: str,
    detailed_description: str,
    kind: str,
    severity: str,
    priority_nice: int,
    reporter: str,
    created_by: str,
    source: BugSource,
    status: str = "reported",
    owner: str | None = None,
    expected_behavior: str | None = None,
    actual_behavior: str | None = None,
    reproduction: str | None = None,
    evidence: dict[str, Any] | None = None,
    environment: str | None = None,
    duplicate_of_uuid: uuid.UUID | None = None,
    parent_bug_uuid: uuid.UUID | None = None,
) -> BugReport:
    """Create a new bug report with audit logging."""
    validate_bug_kind(kind)
    validate_bug_severity(severity)
    validate_bug_status(status)
    validate_nice_priority(priority_nice)
    validate_bug_source(conn, source)
    if duplicate_of_uuid:
        check_row_exists(conn, "bug_report", duplicate_of_uuid, frozenset({"bug_report"}))
    if parent_bug_uuid:
        check_row_exists(conn, "bug_report", parent_bug_uuid, frozenset({"bug_report"}))
    source_cols = bug_source_to_columns(source)
    new_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    evidence_val = Jsonb(evidence) if evidence is not None else None
    sql = "INSERT INTO bug_report (uuid, title, short_description, detailed_description, expected_behavior, actual_behavior, reproduction, evidence, environment, kind, severity, priority_nice, status, reporter, owner, duplicate_of_uuid, parent_bug_uuid, source_anchor_type, source_project_id, source_file_path, source_plan_uuid, source_revision_uuid, source_step_uuid, source_step_path, source_ref_id, source_command, source_service, confirmed_at, closed_at, reopened_at, created_by, created_at, updated_at, deleted_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    params = (new_uuid, title, short_description, detailed_description, expected_behavior, actual_behavior,
        reproduction, evidence_val, environment, kind, severity, priority_nice, status, reporter, owner,
        duplicate_of_uuid, parent_bug_uuid, source_cols['source_anchor_type'], source_cols['source_project_id'],
        source_cols['source_file_path'], source_cols['source_plan_uuid'], source_cols['source_revision_uuid'],
        source_cols['source_step_uuid'], source_cols['source_step_path'], source_cols['source_ref_id'],
        source_cols['source_command'], source_cols['source_service'], None, None, None, created_by, now, now, None)
    conn.execute(sql, params)
    record_runtime_change(conn, plan_uuid=source.plan_uuid, entity_type="bug_report", entity_id=new_uuid,
        action="create", changed_by=created_by)
    return BugReport(bug_uuid=new_uuid, title=title, short_description=short_description,
        detailed_description=detailed_description, expected_behavior=expected_behavior,
        actual_behavior=actual_behavior, reproduction=reproduction, evidence=evidence,
        environment=environment, kind=kind, severity=severity, priority_nice=priority_nice,
        status=status, reporter=reporter, owner=owner, duplicate_of_uuid=duplicate_of_uuid,
        parent_bug_uuid=parent_bug_uuid, source_anchor_type=source_cols['source_anchor_type'],
        source_project_id=source_cols['source_project_id'], source_file_path=source_cols['source_file_path'],
        source_plan_uuid=source_cols['source_plan_uuid'], source_revision_uuid=source_cols['source_revision_uuid'],
        source_step_uuid=source_cols['source_step_uuid'], source_step_path=source_cols['source_step_path'],
        source_ref_id=source_cols['source_ref_id'], source_command=source_cols['source_command'],
        source_service=source_cols['source_service'], confirmed_at=None, closed_at=None, reopened_at=None,
        created_by=created_by, created_at=now.isoformat(), updated_at=now.isoformat(), deleted_at=None)


def get_bug(conn: psycopg.Connection, bug_uuid: uuid.UUID) -> BugReport | None:
    """Retrieve a bug report by UUID; return None if not found."""
    sql = "SELECT * FROM bug_report WHERE uuid = %s"
    result = conn.execute(sql, (bug_uuid,))
    row = result.fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_bugs(
    conn: psycopg.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    severity: str | None = None,
    owner: str | None = None,
    source_project_id: uuid.UUID | None = None,
    include_deleted: bool = False,
) -> list[BugReport]:
    """List bug reports with optional filtering; exclude soft-deleted rows unless include_deleted is True."""
    where_clauses = []
    params = []

    if status is not None:
        where_clauses.append("status = %s")
        params.append(status)
    if kind is not None:
        where_clauses.append("kind = %s")
        params.append(kind)
    if severity is not None:
        where_clauses.append("severity = %s")
        params.append(severity)
    if owner is not None:
        where_clauses.append("owner = %s")
        params.append(owner)
    if source_project_id is not None:
        where_clauses.append("source_project_id = %s")
        params.append(source_project_id)

    if not include_deleted:
        where_clauses.append("deleted_at IS NULL")

    where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
    sql = f"SELECT * FROM bug_report WHERE {where_clause} ORDER BY created_at ASC"

    result = conn.execute(sql, params)
    rows = result.fetchall()
    return [_row_to_record(row) for row in rows]


def update_bug(
    conn: psycopg.Connection,
    bug_uuid: uuid.UUID,
    *,
    changed_by: str,
    title: str | None = None,
    short_description: str | None = None,
    detailed_description: str | None = None,
    expected_behavior: str | None = None,
    actual_behavior: str | None = None,
    reproduction: str | None = None,
    evidence: dict[str, Any] | None = None,
    environment: str | None = None,
    severity: str | None = None,
    priority_nice: int | None = None,
    owner: str | None = None,
) -> BugReport:
    """Update mutable fields of a bug report."""
    now = datetime.now(timezone.utc)

    if severity is not None:
        validate_bug_severity(severity)
    if priority_nice is not None:
        validate_nice_priority(priority_nice)

    updates = []
    params = []

    if title is not None:
        updates.append("title = %s")
        params.append(title)
    if short_description is not None:
        updates.append("short_description = %s")
        params.append(short_description)
    if detailed_description is not None:
        updates.append("detailed_description = %s")
        params.append(detailed_description)
    if expected_behavior is not None:
        updates.append("expected_behavior = %s")
        params.append(expected_behavior)
    if actual_behavior is not None:
        updates.append("actual_behavior = %s")
        params.append(actual_behavior)
    if reproduction is not None:
        updates.append("reproduction = %s")
        params.append(reproduction)
    if evidence is not None:
        updates.append("evidence = %s")
        params.append(Jsonb(evidence))
    if environment is not None:
        updates.append("environment = %s")
        params.append(environment)
    if severity is not None:
        updates.append("severity = %s")
        params.append(severity)
    if priority_nice is not None:
        updates.append("priority_nice = %s")
        params.append(priority_nice)
    if owner is not None:
        updates.append("owner = %s")
        params.append(owner)

    updates.append("updated_at = %s")
    params.append(now)
    params.append(bug_uuid)

    update_clause = ", ".join(updates)
    sql = f"UPDATE bug_report SET {update_clause} WHERE uuid = %s"

    conn.execute(sql, params)
    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="bug_report",
        entity_id=bug_uuid,
        action="update",
        changed_by=changed_by,
    )

    return get_bug(conn, bug_uuid)  # type: ignore


def set_bug_status(
    conn: psycopg.Connection,
    bug_uuid: uuid.UUID,
    *,
    changed_by: str,
    status: str,
) -> BugReport:
    """Set bug status with mechanical timestamp updates."""
    validate_bug_status(status)
    now = datetime.now(timezone.utc)

    updates = ["status = %s", "updated_at = %s"]
    params = [status, now]

    if status == "confirmed":
        updates.append("confirmed_at = %s")
        params.append(now)
    elif status == "closed":
        updates.append("closed_at = %s")
        params.append(now)
    elif status == "reopened":
        updates.append("reopened_at = %s")
        params.append(now)

    params.append(bug_uuid)

    update_clause = ", ".join(updates)
    sql = f"UPDATE bug_report SET {update_clause} WHERE uuid = %s"

    conn.execute(sql, params)
    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="bug_report",
        entity_id=bug_uuid,
        action="update",
        changed_by=changed_by,
    )

    return get_bug(conn, bug_uuid)  # type: ignore


def mark_bug_duplicate(
    conn: psycopg.Connection,
    bug_uuid: uuid.UUID,
    *,
    changed_by: str,
    duplicate_of_uuid: uuid.UUID,
) -> BugReport:
    """Mark a bug as a duplicate of another bug."""
    check_row_exists(conn, "bug_report", duplicate_of_uuid, frozenset({"bug_report"}))

    now = datetime.now(timezone.utc)
    sql = "UPDATE bug_report SET status = %s, duplicate_of_uuid = %s, updated_at = %s WHERE uuid = %s"
    params = ("duplicate", duplicate_of_uuid, now, bug_uuid)

    conn.execute(sql, params)
    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="bug_report",
        entity_id=bug_uuid,
        action="update",
        changed_by=changed_by,
    )

    return get_bug(conn, bug_uuid)  # type: ignore


def soft_delete_bug(
    conn: psycopg.Connection,
    bug_uuid: uuid.UUID,
    *,
    changed_by: str,
) -> BugReport:
    """Soft-delete a bug (mark as deleted without physical removal)."""
    now = datetime.now(timezone.utc)
    sql = "UPDATE bug_report SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    params = (now, now, bug_uuid)

    conn.execute(sql, params)
    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="bug_report",
        entity_id=bug_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return get_bug(conn, bug_uuid)  # type: ignore
