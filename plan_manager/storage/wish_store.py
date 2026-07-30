"""Wish persistence: CRUD, filtering, audit, and soft-delete."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.nice_priority import validate_nice_priority
from plan_manager.domain.primary_anchor import PrimaryAnchor, anchor_to_columns, validate_anchor
from plan_manager.domain.wish import (
    ACTIVE_WISH_STATUSES,
    WISH_KINDS,
    WISH_STATUSES,
    WishItem,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: tuple[Any, ...] | dict[str, Any]) -> WishItem:
    # Handle both tuple (from list_wishes_page) and dict (from crud_* methods)
    if isinstance(row, dict):
        row_uuid = row["uuid"]
        title = row["title"]
        description = row["description"]
        kind = row["kind"]
        status = row["status"]
        priority_nice = row["priority_nice"]
        created_by = row["created_by"]
        assigned_to = row["assigned_to"]
        target_release = row["target_release"]
        rationale = row["rationale"]
        created_at = row["created_at"]
        updated_at = row["updated_at"]
        decided_at = row["decided_at"]
        delivered_at = row["delivered_at"]
        primary_anchor_type = row["primary_anchor_type"]
        anchor_project_id = row["anchor_project_id"]
        anchor_file_path = row["anchor_file_path"]
        anchor_plan_uuid = row["anchor_plan_uuid"]
        anchor_revision_uuid = row["anchor_revision_uuid"]
        anchor_step_uuid = row["anchor_step_uuid"]
        anchor_step_path = row["anchor_step_path"]
        anchor_ref_id = row["anchor_ref_id"]
        deleted_at = row["deleted_at"]
    else:
        (
            row_uuid,
            title,
            description,
            kind,
            status,
            priority_nice,
            created_by,
            assigned_to,
            target_release,
            rationale,
            created_at,
            updated_at,
            decided_at,
            delivered_at,
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
    return WishItem(
        wish_uuid=row_uuid if isinstance(row_uuid, uuid.UUID) else uuid.UUID(row_uuid),
        title=title,
        description=description,
        kind=kind,
        status=status,
        priority_nice=priority_nice,
        created_by=created_by,
        assigned_to=assigned_to,
        target_release=target_release,
        rationale=rationale,
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
        decided_at=decided_at.isoformat() if decided_at else None,
        delivered_at=delivered_at.isoformat() if delivered_at else None,
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


def _get_row(conn: psycopg.Connection, wish_uuid: uuid.UUID) -> WishItem | None:
    sql = """
    SELECT
        uuid, title, description, kind, status, priority_nice, created_by,
        assigned_to, target_release, rationale, created_at, updated_at,
        decided_at, delivered_at, primary_anchor_type, anchor_project_id,
        anchor_file_path, anchor_plan_uuid, anchor_revision_uuid,
        anchor_step_uuid, anchor_step_path, anchor_ref_id, deleted_at
    FROM wish_item
    WHERE uuid = %s
    """
    row = conn.execute(sql, (wish_uuid,)).fetchone()
    return _row_to_record(row) if row else None


def create_wish(
    conn: psycopg.Connection,
    *,
    title: str,
    description: str,
    kind: str,
    priority_nice: int,
    created_by: str,
    anchor: PrimaryAnchor,
    status: str = "proposed",
    assigned_to: str | None = None,
    target_release: str | None = None,
    rationale: str | None = None,
) -> WishItem:
    if kind not in WISH_KINDS:
        raise RuntimeValidationError(f"invalid wish kind: {kind!r}")
    if status not in WISH_STATUSES:
        raise RuntimeValidationError(f"invalid wish status: {status!r}")
    validate_nice_priority(priority_nice)
    validate_anchor(conn, anchor)

    wish_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    decided_at = now if status in {"rejected", "cancelled"} else None
    delivered_at = now if status == "delivered" else None
    columns = anchor_to_columns(anchor)

    values = {
        "uuid": wish_uuid,
        "title": title,
        "description": description,
        "kind": kind,
        "status": status,
        "priority_nice": priority_nice,
        "created_by": created_by,
        "assigned_to": assigned_to,
        "target_release": target_release,
        "rationale": rationale,
        "created_at": now,
        "updated_at": now,
        "decided_at": decided_at,
        "delivered_at": delivered_at,
        "primary_anchor_type": columns["primary_anchor_type"],
        "anchor_project_id": columns["anchor_project_id"],
        "anchor_file_path": columns["anchor_file_path"],
        "anchor_plan_uuid": columns["anchor_plan_uuid"],
        "anchor_revision_uuid": columns["anchor_revision_uuid"],
        "anchor_step_uuid": columns["anchor_step_uuid"],
        "anchor_step_path": columns["anchor_step_path"],
        "anchor_ref_id": columns["anchor_ref_id"],
    }

    row = WishItem.crud_create(conn, values)
    if row is None:
        raise RuntimeValidationError(f"wish {wish_uuid} not found after create")

    record_runtime_change(
        conn,
        plan_uuid=anchor.plan_uuid,
        entity_type="wish",
        entity_id=wish_uuid,
        action="create",
        changed_by=created_by,
    )

    return _row_to_record(row)


def get_wish(conn: psycopg.Connection, wish_uuid: uuid.UUID) -> WishItem | None:
    row = WishItem.crud_get(conn, wish_uuid, include_deleted=False)
    if row is None:
        return None
    return _row_to_record(row)


def list_wishes_page(
    conn: psycopg.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    anchor_file_path: str | None = None,
    anchor_plan_uuid: uuid.UUID | None = None,
    anchor_revision_uuid: uuid.UUID | None = None,
    anchor_step_uuid: uuid.UUID | None = None,
    priority_nice: int | None = None,
    owner: str | None = None,
    assignee: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    active_only: bool = False,
    unanchored_only: bool = False,
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    include_deleted: bool = False,
    search: str | None = None,
    search_regex: str | None = None,
) -> tuple[list[WishItem], int]:
    """List a page of wishes, optionally narrowed by content search.

    search and search_regex are additive keywords with None defaults, so every
    pre-existing caller is unaffected. They route to the declared
    WishItem.SEARCH_COLUMNS (title, description): search matches a substring
    case-insensitively, search_regex a POSIX regular expression. search wins
    when both are supplied. Either composes with every attribute filter by AND
    and with the existing pagination and ordering.
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if search is not None or search_regex is not None:
        if not WishItem.SEARCH_COLUMNS:
            raise ValueError(
                "WishItem does not declare SEARCH_COLUMNS; search not available"
            )
        if search is not None:
            operator, value = "ILIKE", f"%{search}%"
        else:
            operator, value = "~*", search_regex
        # One predicate per declared searchable column, OR-ed, then ANDed with
        # the attribute filters. Column names come from the class descriptor,
        # never from caller input; the value is always a bind parameter.
        group = " OR ".join(f"{column} {operator} %s" for column in WishItem.SEARCH_COLUMNS)
        where_clauses.append(f"({group})")
        params.extend([value] * len(WishItem.SEARCH_COLUMNS))

    if status is not None:
        where_clauses.append("status = %s")
        params.append(status)
    if kind is not None:
        where_clauses.append("kind = %s")
        params.append(kind)
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
    if priority_nice is not None:
        where_clauses.append("priority_nice = %s")
        params.append(priority_nice)
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
        params.append(sorted(ACTIVE_WISH_STATUSES))
    if unanchored_only:
        where_clauses.append("primary_anchor_type = %s")
        params.append("none")
    if project_id is not None:
        where_clauses.append(
            "(anchor_project_id = %s OR anchor_plan_uuid IN (SELECT uuid FROM plan WHERE %s = ANY(project_ids)))"
        )
        params.append(project_id)
        params.append(str(project_id))
    if not include_deleted:
        where_clauses.append("deleted_at IS NULL")

    where_clause = " AND ".join(where_clauses) if where_clauses else "1=1"
    sql = (
        "SELECT uuid, title, description, kind, status, priority_nice, created_by, "
        "assigned_to, target_release, rationale, created_at, updated_at, decided_at, delivered_at, "
        "primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid, anchor_revision_uuid, "
        "anchor_step_uuid, anchor_step_path, anchor_ref_id, deleted_at, count(*) OVER() AS total "
        f"FROM wish_item WHERE {where_clause} ORDER BY created_at ASC LIMIT %s OFFSET %s"
    )
    rows = conn.execute(sql, params + [limit, offset]).fetchall()
    if rows:
        total = rows[0][-1]
        return [_row_to_record(row[:-1]) for row in rows], total
    count_row = conn.execute(f"SELECT count(*) FROM wish_item WHERE {where_clause}", params).fetchone()
    return [], (count_row[0] if count_row else 0)


def update_wish(
    conn: psycopg.Connection,
    wish_uuid: uuid.UUID,
    *,
    changed_by: str,
    title: str | None = None,
    description: str | None = None,
    kind: str | None = None,
    status: str | None = None,
    priority_nice: int | None = None,
    assigned_to: str | None = None,
    target_release: str | None = None,
    rationale: str | None = None,
) -> WishItem:
    values: dict[str, Any] = {}

    if title is not None:
        values["title"] = title
    if description is not None:
        values["description"] = description
    if kind is not None:
        if kind not in WISH_KINDS:
            raise RuntimeValidationError(f"invalid wish kind: {kind!r}")
        values["kind"] = kind
    if status is not None:
        if status not in WISH_STATUSES:
            raise RuntimeValidationError(f"invalid wish status: {status!r}")
        values["status"] = status
        if status in {"rejected", "cancelled"}:
            values["decided_at"] = datetime.now(timezone.utc)
        if status == "delivered":
            values["delivered_at"] = datetime.now(timezone.utc)
    if priority_nice is not None:
        validate_nice_priority(priority_nice)
        values["priority_nice"] = priority_nice
    if assigned_to is not None:
        values["assigned_to"] = assigned_to
    if target_release is not None:
        values["target_release"] = target_release
    if rationale is not None:
        values["rationale"] = rationale

    now = datetime.now(timezone.utc)
    values["updated_at"] = now

    row = WishItem.crud_update(conn, wish_uuid, values)
    if row is None:
        raise RuntimeValidationError(f"wish not found after update: {wish_uuid}")

    record = _row_to_record(row)
    record_runtime_change(
        conn,
        plan_uuid=record.anchor_plan_uuid,
        entity_type="wish",
        entity_id=wish_uuid,
        action="update",
        changed_by=changed_by,
    )
    return record


def soft_delete_wish(conn: psycopg.Connection, wish_uuid: uuid.UUID, *, changed_by: str) -> WishItem:
    now = datetime.now(timezone.utc)
    row = WishItem.crud_soft_delete(conn, wish_uuid, deleted_at=now, updated_at=now)
    if row is None:
        raise RuntimeValidationError(f"wish not found after soft delete: {wish_uuid}")

    record = _row_to_record(row)
    record_runtime_change(
        conn,
        plan_uuid=record.anchor_plan_uuid,
        entity_type="wish",
        entity_id=wish_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )
    return record


def resolve_wish_uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    """Parse an optional wish UUID parameter."""
    if value is None:
        return None
    return validate_uuid(value)

