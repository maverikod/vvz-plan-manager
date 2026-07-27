"""Calendar-entry persistence: CRUD, filtering, audit, and soft-delete."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.calendar_entry import (
    ACTIVE_CALENDAR_ENTRY_STATUSES,
    CALENDAR_ENTRY_STATUSES,
    CalendarEntry,
    validate_calendar_date,
    validate_calendar_range,
    validate_calendar_status,
)
from plan_manager.domain.primary_anchor import PrimaryAnchor, anchor_to_columns, validate_anchor
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: tuple[Any, ...]) -> CalendarEntry:
    (
        row_uuid,
        title,
        description,
        status,
        start_date,
        end_date,
        created_by,
        assigned_to,
        wish_uuid,
        created_at,
        updated_at,
        primary_anchor_type,
        anchor_project_id,
        anchor_file_path,
        anchor_plan_uuid,
        anchor_revision_uuid,
        anchor_step_uuid,
        anchor_step_path,
        anchor_ref_id,
        deleted_at,
    ) = row
    return CalendarEntry(
        calendar_entry_uuid=row_uuid if isinstance(row_uuid, uuid.UUID) else uuid.UUID(row_uuid),
        title=title,
        description=description,
        status=status,
        start_date=start_date.isoformat() if hasattr(start_date, "isoformat") else str(start_date),
        end_date=end_date.isoformat() if hasattr(end_date, "isoformat") else str(end_date),
        created_by=created_by,
        assigned_to=assigned_to,
        wish_uuid=wish_uuid if isinstance(wish_uuid, uuid.UUID) else (uuid.UUID(wish_uuid) if wish_uuid else None),
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
        primary_anchor_type=primary_anchor_type,
        anchor_project_id=anchor_project_id if isinstance(anchor_project_id, uuid.UUID) else (uuid.UUID(anchor_project_id) if anchor_project_id else None),
        anchor_file_path=anchor_file_path,
        anchor_plan_uuid=anchor_plan_uuid if isinstance(anchor_plan_uuid, uuid.UUID) else (uuid.UUID(anchor_plan_uuid) if anchor_plan_uuid else None),
        anchor_revision_uuid=anchor_revision_uuid if isinstance(anchor_revision_uuid, uuid.UUID) else (uuid.UUID(anchor_revision_uuid) if anchor_revision_uuid else None),
        anchor_step_uuid=anchor_step_uuid if isinstance(anchor_step_uuid, uuid.UUID) else (uuid.UUID(anchor_step_uuid) if anchor_step_uuid else None),
        anchor_step_path=anchor_step_path,
        anchor_ref_id=anchor_ref_id if isinstance(anchor_ref_id, uuid.UUID) else (uuid.UUID(anchor_ref_id) if anchor_ref_id else None),
        deleted_at=deleted_at.isoformat() if deleted_at else None,
    )


def _get_row(conn: psycopg.Connection, calendar_entry_uuid: uuid.UUID) -> CalendarEntry | None:
    row = conn.execute(
        """
        SELECT
            uuid, title, description, status, start_date, end_date, created_by,
            assigned_to, wish_uuid, created_at, updated_at, primary_anchor_type,
            anchor_project_id, anchor_file_path, anchor_plan_uuid,
            anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
            anchor_ref_id, deleted_at
        FROM calendar_entry
        WHERE uuid = %s
        """,
        (calendar_entry_uuid,),
    ).fetchone()
    return _row_to_record(row) if row else None


def create_calendar_entry(
    conn: psycopg.Connection,
    *,
    title: str,
    description: str,
    status: str,
    start_date: str,
    end_date: str,
    created_by: str,
    anchor: PrimaryAnchor,
    assigned_to: str | None = None,
    wish_uuid: uuid.UUID | None = None,
) -> CalendarEntry:
    validate_calendar_status(status)
    validate_calendar_range(start_date, end_date)
    validate_anchor(conn, anchor)
    if wish_uuid is not None:
        check_row_exists(conn, "wish_item", wish_uuid, frozenset({"wish_item"}))

    entry_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    columns = anchor_to_columns(anchor)
    conn.execute(
        """
        INSERT INTO calendar_entry (
            uuid, title, description, status, start_date, end_date, created_by,
            assigned_to, wish_uuid, created_at, updated_at, primary_anchor_type,
            anchor_project_id, anchor_file_path, anchor_plan_uuid,
            anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
            anchor_ref_id, deleted_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s,
            %s, %s
        )
        """,
        (
            entry_uuid,
            title,
            description,
            status,
            validate_calendar_date(start_date),
            validate_calendar_date(end_date),
            created_by,
            assigned_to,
            wish_uuid,
            now,
            now,
            columns["primary_anchor_type"],
            columns["anchor_project_id"],
            columns["anchor_file_path"],
            columns["anchor_plan_uuid"],
            columns["anchor_revision_uuid"],
            columns["anchor_step_uuid"],
            columns["anchor_step_path"],
            columns["anchor_ref_id"],
            None,
        ),
    )
    record_runtime_change(
        conn,
        plan_uuid=anchor.plan_uuid,
        entity_type="calendar_entry",
        entity_id=entry_uuid,
        action="create",
        changed_by=created_by,
    )
    record = _get_row(conn, entry_uuid)
    if record is None:
        raise RuntimeValidationError(f"calendar_entry {entry_uuid} not found after create")
    return record


def get_calendar_entry(conn: psycopg.Connection, calendar_entry_uuid: uuid.UUID) -> CalendarEntry | None:
    record = _get_row(conn, calendar_entry_uuid)
    if record is None or record.deleted_at is not None:
        return None
    return record


def list_calendar_entries_page(
    conn: psycopg.Connection,
    *,
    status: str | None = None,
    anchor_file_path: str | None = None,
    anchor_plan_uuid: uuid.UUID | None = None,
    anchor_revision_uuid: uuid.UUID | None = None,
    anchor_step_uuid: uuid.UUID | None = None,
    owner: str | None = None,
    assignee: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    active_only: bool = False,
    unanchored_only: bool = False,
    project_id: uuid.UUID | None = None,
    day_from: str | None = None,
    day_to: str | None = None,
    wish_uuid: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
) -> tuple[list[CalendarEntry], int]:
    where_clauses: list[str] = []
    params: list[Any] = []

    if status is not None:
        where_clauses.append("status = %s")
        params.append(status)
    if anchor_file_path is not None:
        where_clauses.append("anchor_file_path = %s")
        params.append(anchor_file_path)
    if anchor_plan_uuid is not None:
        where_clauses.append("anchor_plan_uuid = %s")
        params.append(anchor_plan_uuid)
    if anchor_revision_uuid is not None:
        where_clauses.append("anchor_revision_uuid = %s")
        params.append(anchor_revision_uuid)
    if anchor_step_uuid is not None:
        where_clauses.append("anchor_step_uuid = %s")
        params.append(anchor_step_uuid)
    if owner is not None:
        where_clauses.append("created_by = %s")
        params.append(owner)
    if assignee is not None:
        where_clauses.append("assigned_to = %s")
        params.append(assignee)
    if created_after is not None:
        where_clauses.append("created_at >= %s")
        params.append(created_after)
    if created_before is not None:
        where_clauses.append("created_at <= %s")
        params.append(created_before)
    if active_only:
        where_clauses.append("status = ANY(%s)")
        params.append(sorted(ACTIVE_CALENDAR_ENTRY_STATUSES))
    if unanchored_only:
        where_clauses.append("primary_anchor_type = %s")
        params.append("none")
    if project_id is not None:
        where_clauses.append(
            "(anchor_project_id = %s OR anchor_plan_uuid IN (SELECT uuid FROM plan WHERE %s = ANY(project_ids)))"
        )
        params.append(project_id)
        params.append(str(project_id))
    if day_from is not None:
        where_clauses.append("end_date >= %s")
        params.append(validate_calendar_date(day_from))
    if day_to is not None:
        where_clauses.append("start_date <= %s")
        params.append(validate_calendar_date(day_to))
    if wish_uuid is not None:
        where_clauses.append("wish_uuid = %s")
        params.append(wish_uuid)
    if not include_deleted:
        where_clauses.append("deleted_at IS NULL")

    where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
    sql = (
        "SELECT uuid, title, description, status, start_date, end_date, created_by, "
        "assigned_to, wish_uuid, created_at, updated_at, primary_anchor_type, anchor_project_id, "
        "anchor_file_path, anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path, "
        "anchor_ref_id, deleted_at, count(*) OVER() AS total "
        f"FROM calendar_entry WHERE {where_clause} ORDER BY start_date ASC, created_at ASC LIMIT %s OFFSET %s"
    )
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    if rows:
        total = rows[0][-1]
        return [_row_to_record(row[:-1]) for row in rows], total
    count_row = conn.execute(f"SELECT count(*) FROM calendar_entry WHERE {where_clause}", params).fetchone()
    return [], (count_row[0] if count_row else 0)


def update_calendar_entry(
    conn: psycopg.Connection,
    calendar_entry_uuid: uuid.UUID,
    *,
    changed_by: str,
    title: str | None = None,
    description: str | None = None,
    status: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    assigned_to: str | None = None,
    wish_uuid: uuid.UUID | None = None,
) -> CalendarEntry:
    current = _get_row(conn, calendar_entry_uuid)
    if current is None:
        raise RuntimeValidationError(f"calendar_entry not found: {calendar_entry_uuid}")

    next_start = start_date or current.start_date
    next_end = end_date or current.end_date
    validate_calendar_range(next_start, next_end)

    updates: list[str] = []
    params: list[Any] = []
    if title is not None:
        updates.append("title = %s")
        params.append(title)
    if description is not None:
        updates.append("description = %s")
        params.append(description)
    if status is not None:
        validate_calendar_status(status)
        updates.append("status = %s")
        params.append(status)
    if start_date is not None:
        updates.append("start_date = %s")
        params.append(validate_calendar_date(start_date))
    if end_date is not None:
        updates.append("end_date = %s")
        params.append(validate_calendar_date(end_date))
    if assigned_to is not None:
        updates.append("assigned_to = %s")
        params.append(assigned_to)
    if wish_uuid is not None:
        check_row_exists(conn, "wish_item", wish_uuid, frozenset({"wish_item"}))
        updates.append("wish_uuid = %s")
        params.append(wish_uuid)

    now = datetime.now(timezone.utc)
    updates.append("updated_at = %s")
    params.append(now)
    params.append(calendar_entry_uuid)
    conn.execute(f"UPDATE calendar_entry SET {', '.join(updates)} WHERE uuid = %s", params)
    record = _get_row(conn, calendar_entry_uuid)
    if record is None:
        raise RuntimeValidationError(f"calendar_entry not found after update: {calendar_entry_uuid}")
    record_runtime_change(
        conn,
        plan_uuid=record.anchor_plan_uuid,
        entity_type="calendar_entry",
        entity_id=calendar_entry_uuid,
        action="update",
        changed_by=changed_by,
    )
    return record


def soft_delete_calendar_entry(
    conn: psycopg.Connection,
    calendar_entry_uuid: uuid.UUID,
    *,
    changed_by: str,
) -> CalendarEntry:
    now = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE calendar_entry SET deleted_at = %s, updated_at = %s WHERE uuid = %s",
        (now, now, calendar_entry_uuid),
    )
    record = _get_row(conn, calendar_entry_uuid)
    if record is None:
        raise RuntimeValidationError(f"calendar_entry not found after soft delete: {calendar_entry_uuid}")
    record_runtime_change(
        conn,
        plan_uuid=record.anchor_plan_uuid,
        entity_type="calendar_entry",
        entity_id=calendar_entry_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )
    return record

