from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.todo import TodoItem, TODO_KINDS, TODO_STATUSES
from plan_manager.domain.primary_anchor import PrimaryAnchor, validate_anchor, anchor_to_columns
from plan_manager.domain.nice_priority import validate_nice_priority
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: tuple[Any, ...] | dict[str, Any]) -> TodoItem:
    """Convert a database row (tuple or dict) to a TodoItem instance.

    Row order matches todo_item table column order when tuple:
    uuid, title, description, kind, status, priority_nice, created_by,
    assigned_to, created_at, updated_at, started_at, resolved_at, due_at,
    primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
    anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
    blocking_reason, execution_result, deleted_at
    """
    # Handle dict rows from crud_* methods
    if isinstance(row, dict):
        row_uuid = row["uuid"]
        title = row["title"]
        description = row["description"]
        kind = row["kind"]
        status = row["status"]
        priority_nice = row["priority_nice"]
        created_by = row["created_by"]
        assigned_to = row["assigned_to"]
        created_at = row["created_at"]
        updated_at = row["updated_at"]
        started_at = row["started_at"]
        resolved_at = row["resolved_at"]
        due_at = row["due_at"]
        primary_anchor_type = row["primary_anchor_type"]
        anchor_project_id = row["anchor_project_id"]
        anchor_file_path = row["anchor_file_path"]
        anchor_plan_uuid = row["anchor_plan_uuid"]
        anchor_revision_uuid = row["anchor_revision_uuid"]
        anchor_step_uuid = row["anchor_step_uuid"]
        anchor_step_path = row["anchor_step_path"]
        anchor_ref_id = row["anchor_ref_id"]
        blocking_reason = row["blocking_reason"]
        execution_result = row["execution_result"]
        deleted_at = row["deleted_at"]
    else:
        # Handle tuple rows (legacy path for queries using _get_row)
        (
            row_uuid,
            title,
            description,
            kind,
            status,
            priority_nice,
            created_by,
            assigned_to,
            created_at,
            updated_at,
            started_at,
            resolved_at,
            due_at,
            primary_anchor_type,
            anchor_project_id,
            anchor_file_path,
            anchor_plan_uuid,
            anchor_revision_uuid,
            anchor_step_uuid,
            anchor_step_path,
            anchor_ref_id,
            blocking_reason,
            execution_result,
            deleted_at,
        ) = row

    return TodoItem(
        todo_uuid=row_uuid if isinstance(row_uuid, uuid.UUID) else uuid.UUID(row_uuid),
        title=title,
        description=description,
        kind=kind,
        status=status,
        priority_nice=priority_nice,
        created_by=created_by,
        assigned_to=assigned_to,
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
        started_at=started_at.isoformat() if started_at else None,
        resolved_at=resolved_at.isoformat() if resolved_at else None,
        due_at=due_at.isoformat() if due_at else None,
        primary_anchor_type=primary_anchor_type,
        anchor_project_id=anchor_project_id if isinstance(anchor_project_id, uuid.UUID) else (uuid.UUID(anchor_project_id) if anchor_project_id else None),
        anchor_file_path=anchor_file_path,
        anchor_plan_uuid=anchor_plan_uuid if isinstance(anchor_plan_uuid, uuid.UUID) else (uuid.UUID(anchor_plan_uuid) if anchor_plan_uuid else None),
        anchor_revision_uuid=anchor_revision_uuid if isinstance(anchor_revision_uuid, uuid.UUID) else (uuid.UUID(anchor_revision_uuid) if anchor_revision_uuid else None),
        anchor_step_uuid=anchor_step_uuid if isinstance(anchor_step_uuid, uuid.UUID) else (uuid.UUID(anchor_step_uuid) if anchor_step_uuid else None),
        anchor_step_path=anchor_step_path,
        anchor_ref_id=anchor_ref_id if isinstance(anchor_ref_id, uuid.UUID) else (uuid.UUID(anchor_ref_id) if anchor_ref_id else None),
        blocking_reason=blocking_reason,
        execution_result=execution_result,
        deleted_at=deleted_at.isoformat() if deleted_at else None,
    )


def _get_row(conn: psycopg.Connection, todo_uuid: uuid.UUID) -> TodoItem | None:
    """Select a single row by uuid, regardless of deleted_at status.

    Returns the row if it exists (including soft-deleted rows), else None.
    This is the internal fetch path for mutating functions.
    """
    sql = """
    SELECT
        uuid, title, description, kind, status, priority_nice, created_by,
        assigned_to, created_at, updated_at, started_at, resolved_at, due_at,
        primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
        anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
        blocking_reason, execution_result, deleted_at
    FROM todo_item
    WHERE uuid = %s
    """
    result = conn.execute(sql, (todo_uuid,))
    row = result.fetchone()
    return _row_to_record(row) if row else None


def create_todo(
    conn: psycopg.Connection,
    *,
    title: str,
    description: str,
    kind: str,
    priority_nice: int,
    created_by: str,
    anchor: PrimaryAnchor,
    status: str = "open",
    assigned_to: str | None = None,
    due_at: str | None = None,
    blocking_reason: str | None = None,
    execution_result: str | None = None,
) -> TodoItem:
    """Create a new TODO item with validation and audit recording."""
    if kind not in TODO_KINDS:
        raise RuntimeValidationError(f"Invalid kind: {kind}")

    if status not in TODO_STATUSES:
        raise RuntimeValidationError(f"Invalid status: {status}")

    validate_nice_priority(priority_nice)
    validate_anchor(conn, anchor)

    new_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    columns = anchor_to_columns(anchor)

    values = {
        "uuid": new_uuid,
        "title": title,
        "description": description,
        "kind": kind,
        "status": status,
        "priority_nice": priority_nice,
        "created_by": created_by,
        "assigned_to": assigned_to,
        "created_at": now,
        "updated_at": now,
        "started_at": None,
        "resolved_at": None,
        "due_at": due_at,
        "primary_anchor_type": columns["primary_anchor_type"],
        "anchor_project_id": columns["anchor_project_id"],
        "anchor_file_path": columns["anchor_file_path"],
        "anchor_plan_uuid": columns["anchor_plan_uuid"],
        "anchor_revision_uuid": columns["anchor_revision_uuid"],
        "anchor_step_uuid": columns["anchor_step_uuid"],
        "anchor_step_path": columns["anchor_step_path"],
        "anchor_ref_id": columns["anchor_ref_id"],
        "blocking_reason": blocking_reason,
        "execution_result": execution_result,
    }

    row_dict = TodoItem.crud_create(conn, values)

    record_runtime_change(
        conn,
        plan_uuid=anchor.plan_uuid,
        entity_type="todo",
        entity_id=new_uuid,
        action="create",
        changed_by=created_by,
    )

    return _row_to_record(row_dict)


def get_todo(conn: psycopg.Connection, todo_uuid: uuid.UUID) -> TodoItem | None:
    """Retrieve a live TODO item by uuid.

    Returns None if the item does not exist or is soft-deleted.
    """
    row_dict = TodoItem.crud_get(conn, todo_uuid, include_deleted=False)
    return _row_to_record(row_dict) if row_dict else None


def list_todos(
    conn: psycopg.Connection,
    *,
    status: str | None = None,
    kind: str | None = None,
    include_deleted: bool = False,
) -> list[TodoItem]:
    """List TODO items, optionally filtered by status and/or kind.

    Excludes soft-deleted items unless include_deleted=True.
    Returns results ordered by created_at ASC.
    """
    filters = {}
    if kind is not None:
        filters["kind"] = kind
    if status is not None:
        filters["status"] = status

    rows = TodoItem.crud_list(
        conn,
        filters=filters if filters else None,
        include_deleted=include_deleted,
        order_by=("created_at",),
    )
    return [_row_to_record(row) for row in rows]


# The set of statuses treated as "active" for the active_only filter (todo_list's
# equivalent of _ACTIVE_STATUSES, owned here now that the filter is SQL-side).
_ACTIVE_TODO_STATUSES = frozenset({"open", "in_progress", "blocked"})


_TODO_SELECT_COLUMNS = """
    uuid, title, description, kind, status, priority_nice, created_by,
    assigned_to, created_at, updated_at, started_at, resolved_at, due_at,
    primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
    anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
    blocking_reason, execution_result, deleted_at
"""


def list_todos_page(
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
) -> tuple[list[TodoItem], int]:
    """List one paginated page of TODO items plus the total filtered count, entirely in SQL.

    Every todo_list filter (status, kind, file, anchor_plan, revision, step, priority,
    owner, assignee, created_after/before, active_only, unanchored_only, and the
    transitive project scope) is a WHERE clause here; none is applied by post-fetch
    Python filtering. `owner` maps to the created_by column and `assignee` to
    assigned_to, matching TodoItem's field names (the entity has no separate
    "owner" column). The `model` filter parameter accepted by todo_list has no
    backing column and is therefore, as before, not applied here either.

    `project_id`, when given, is a TRANSITIVE OR match expressed as a single
    correlated subquery (one round trip, no precomputed plan-uuid list passed from
    Python): a TODO matches when its own anchor_project_id equals project_id
    directly, OR its anchor_plan_uuid is one of the plans whose plan.project_ids
    contains project_id.

    Returns (page_rows, total); see list_bugs_page's docstring for the count(*)
    OVER() / fallback-COUNT(*) total-computation strategy this mirrors exactly.
    """
    where_clauses: list[str] = []
    params: list[Any] = []

    if kind is not None:
        where_clauses.append("kind = %s")
        params.append(kind)
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
        where_clauses.append("status IN (%s, %s, %s)")
        params.extend(sorted(_ACTIVE_TODO_STATUSES))
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
        f"SELECT {_TODO_SELECT_COLUMNS}, count(*) OVER() AS total FROM todo_item "
        f"WHERE {where_clause} ORDER BY created_at ASC LIMIT %s OFFSET %s"
    )
    rows = conn.execute(sql, params + [limit, offset]).fetchall()

    if rows:
        total = rows[0][-1]
        return [_row_to_record(row[:-1]) for row in rows], total

    count_row = conn.execute(f"SELECT count(*) FROM todo_item WHERE {where_clause}", params).fetchone()
    return [], (count_row[0] if count_row else 0)


def update_todo(
    conn: psycopg.Connection,
    todo_uuid: uuid.UUID,
    *,
    changed_by: str,
    title: str | None = None,
    description: str | None = None,
    priority_nice: int | None = None,
    assigned_to: str | None = None,
    blocking_reason: str | None = None,
    execution_result: str | None = None,
) -> TodoItem:
    """Update mutable fields of a TODO item and record the change.

    Only non-None fields are updated. Anchor columns are never modified.
    """
    values: dict[str, Any] = {}

    if title is not None:
        values["title"] = title

    if description is not None:
        values["description"] = description

    if priority_nice is not None:
        validate_nice_priority(priority_nice)
        values["priority_nice"] = priority_nice

    if assigned_to is not None:
        values["assigned_to"] = assigned_to

    if blocking_reason is not None:
        values["blocking_reason"] = blocking_reason

    if execution_result is not None:
        values["execution_result"] = execution_result

    now = datetime.now(timezone.utc)
    values["updated_at"] = now

    row_dict = TodoItem.crud_update(conn, todo_uuid, values)
    if row_dict is None:
        from plan_manager.commands.errors import DomainCommandError
        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")

    record_obj = _row_to_record(row_dict)

    record_runtime_change(
        conn,
        plan_uuid=record_obj.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="update",
        changed_by=changed_by,
    )

    return record_obj


def resolve_todo(
    conn: psycopg.Connection, todo_uuid: uuid.UUID, *, changed_by: str
) -> TodoItem:
    """Transition a TODO item to 'resolved' status."""
    now = datetime.now(timezone.utc)

    values = {
        "status": "resolved",
        "resolved_at": now,
        "updated_at": now,
    }

    row_dict = TodoItem.crud_update(conn, todo_uuid, values)
    if row_dict is None:
        from plan_manager.commands.errors import DomainCommandError
        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")

    record_obj = _row_to_record(row_dict)

    record_runtime_change(
        conn,
        plan_uuid=record_obj.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="update",
        changed_by=changed_by,
    )

    return record_obj


def close_todo(
    conn: psycopg.Connection, todo_uuid: uuid.UUID, *, changed_by: str
) -> TodoItem:
    """Transition a TODO item to 'closed' status."""
    now = datetime.now(timezone.utc)

    values = {
        "status": "closed",
        "updated_at": now,
    }

    row_dict = TodoItem.crud_update(conn, todo_uuid, values)
    if row_dict is None:
        from plan_manager.commands.errors import DomainCommandError
        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")

    record_obj = _row_to_record(row_dict)

    record_runtime_change(
        conn,
        plan_uuid=record_obj.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="update",
        changed_by=changed_by,
    )

    return record_obj


def soft_delete_todo(
    conn: psycopg.Connection, todo_uuid: uuid.UUID, *, changed_by: str
) -> TodoItem:
    """Soft-delete a TODO item by setting deleted_at."""
    now = datetime.now(timezone.utc)

    row_dict = TodoItem.crud_soft_delete(
        conn,
        todo_uuid,
        deleted_at=now,
        updated_at=now,
    )

    record_obj = _row_to_record(row_dict)

    record_runtime_change(
        conn,
        plan_uuid=record_obj.anchor_plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return record_obj
