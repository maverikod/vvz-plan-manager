"""Runtime link persistence: create/list/remove typed links over runtime_link with guard enforcement, audit, and soft delete."""

from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from plan_manager.domain.runtime_link import (
    RuntimeLink, RUNTIME_LINK_TYPES, RUNTIME_BLOCKING_LINK_TYPES,
    validate_entity_type, validate_link_type, guard_self_reference,
    guard_no_duplicate, guard_no_blocking_cycle, entity_node,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


_ENTITY_TABLE: dict[str, str] = {'bug': 'bug_report', 'todo': 'todo_item'}


def _row_to_record(row: Any) -> RuntimeLink:
    return RuntimeLink(
        link_uuid=row[0], from_entity_type=row[1], from_entity_uuid=row[2],
        to_entity_type=row[3], to_entity_uuid=row[4], link_type=row[5],
        created_by=row[6], created_at=row[7].isoformat(), updated_at=row[8].isoformat(),
        deleted_at=row[9].isoformat() if row[9] is not None else None,
    )


def create_runtime_link(
    conn: psycopg.Connection,
    *,
    from_entity_type: str,
    from_entity_uuid: uuid.UUID,
    to_entity_type: str,
    to_entity_uuid: uuid.UUID,
    link_type: str,
    created_by: str,
) -> RuntimeLink:
    validate_entity_type(from_entity_type)
    validate_entity_type(to_entity_type)
    validate_link_type(link_type)
    guard_self_reference(from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid)
    check_row_exists(conn, _ENTITY_TABLE[from_entity_type], from_entity_uuid, frozenset(_ENTITY_TABLE.values()))
    check_row_exists(conn, _ENTITY_TABLE[to_entity_type], to_entity_uuid, frozenset(_ENTITY_TABLE.values()))
    sql = "SELECT from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid, link_type FROM runtime_link WHERE deleted_at IS NULL"
    result = conn.execute(sql)
    existing = set()
    for row in result:
        existing.add((row[0], str(row[1]), row[2], str(row[3]), row[4]))
    guard_no_duplicate(existing, (from_entity_type, str(from_entity_uuid), to_entity_type, str(to_entity_uuid), link_type))
    if link_type in RUNTIME_BLOCKING_LINK_TYPES:
        sql = "SELECT from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid, link_type FROM runtime_link WHERE deleted_at IS NULL AND link_type IN (%s, %s)"
        result = conn.execute(sql, ('blocks', 'blocked_by'))
        edges = []
        for row in result:
            from_node = entity_node(row[0], row[1])
            to_node = entity_node(row[2], row[3])
            if row[4] == 'blocks':
                edges.append((from_node, to_node))
            else:
                edges.append((to_node, from_node))
        if link_type == 'blocks':
            candidate_edge = (entity_node(from_entity_type, from_entity_uuid), entity_node(to_entity_type, to_entity_uuid))
        else:
            candidate_edge = (entity_node(to_entity_type, to_entity_uuid), entity_node(from_entity_type, from_entity_uuid))
        edges.append(candidate_edge)
        guard_no_blocking_cycle(edges)
    new_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    sql = "INSERT INTO runtime_link (uuid, from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid, link_type, created_by, created_at, updated_at, deleted_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"
    conn.execute(sql, (new_uuid, from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid, link_type, created_by, now, now, None))
    record_runtime_change(conn, plan_uuid=None, entity_type="runtime_link", entity_id=new_uuid, action="create", changed_by=created_by)
    return RuntimeLink(
        link_uuid=new_uuid, from_entity_type=from_entity_type, from_entity_uuid=from_entity_uuid,
        to_entity_type=to_entity_type, to_entity_uuid=to_entity_uuid, link_type=link_type,
        created_by=created_by, created_at=now.isoformat(), updated_at=now.isoformat(), deleted_at=None,
    )


def get_runtime_link(conn: psycopg.Connection, link_uuid: uuid.UUID) -> RuntimeLink | None:
    sql = "SELECT uuid, from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid, link_type, created_by, created_at, updated_at, deleted_at FROM runtime_link WHERE uuid = %s"
    result = conn.execute(sql, (link_uuid,))
    row = result.fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_runtime_links(
    conn: psycopg.Connection,
    *,
    entity_type: str | None = None,
    entity_uuid: uuid.UUID | None = None,
    include_deleted: bool = False,
) -> list[RuntimeLink]:
    if (entity_type is None) != (entity_uuid is None):
        raise RuntimeValidationError("entity_type and entity_uuid must be supplied together")
    sql = "SELECT uuid, from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid, link_type, created_by, created_at, updated_at, deleted_at FROM runtime_link"
    params = []
    conditions = []
    if entity_type is not None and entity_uuid is not None:
        conditions.append("((from_entity_type = %s AND from_entity_uuid = %s) OR (to_entity_type = %s AND to_entity_uuid = %s))")
        params.extend([entity_type, entity_uuid, entity_type, entity_uuid])
    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY created_at ASC"
    result = conn.execute(sql, params) if params else conn.execute(sql)
    return [_row_to_record(row) for row in result]


def remove_runtime_link(conn: psycopg.Connection, link_uuid: uuid.UUID, *, changed_by: str) -> RuntimeLink:
    now = datetime.now(timezone.utc)
    sql = "UPDATE runtime_link SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    conn.execute(sql, (now, now, link_uuid))
    record_runtime_change(conn, plan_uuid=None, entity_type="runtime_link", entity_id=link_uuid, action="soft_delete", changed_by=changed_by)
    sql = "SELECT uuid, from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid, link_type, created_by, created_at, updated_at, deleted_at FROM runtime_link WHERE uuid = %s"
    result = conn.execute(sql, (link_uuid,))
    row = result.fetchone()
    return _row_to_record(row)
