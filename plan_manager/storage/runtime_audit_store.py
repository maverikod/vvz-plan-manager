"""Runtime audit trail persistence: append-only recorder for runtime changes, kept separate from versioned plan truth."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.domain.actor_identity import validate_actor_identity
from plan_manager.domain.entity import DataclassEntity


ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {
        "create",
        "update",
        "soft_delete",
        "hard_delete",
        "archive",
        "restore",
        "plan_unfreeze",
        "subtree_unfreeze",
        "plan_completed_set",
        "plan_comment_set",
    }
)


@dataclass(frozen=True)
class RuntimeAuditRecord(DataclassEntity):
    """One append-only runtime audit-log row, seated on the shared entity base.

    The DataclassEntity base contributes the ``entity_type()`` classmethod and
    the ``entity_id()`` instance method (the identity of THIS audit record,
    i.e. ``audit_uuid``). To avoid colliding with those methods, the two data
    fields that describe WHICH entity a mutation targeted are named
    ``target_type``/``target_id`` in this class; they map back to the unchanged
    DB columns ``entity_type``/``entity_id`` and to the unchanged outward
    payload keys ``entity_type``/``entity_id`` at the boundaries below.

    Append-only: the table has no soft-delete/updated-at columns, so
    ``SOFT_DELETE_COLUMN``/``UPDATED_AT_COLUMN`` are ``None`` (which makes the
    base's soft_delete/delete/hard_delete/purge helpers raise instead of
    mutating), and ``crud_update`` is overridden to refuse. Records are created
    only through ``record_runtime_change`` (a raw INSERT); identity is
    registered by a DB trigger.
    """

    ENTITY_TYPE: ClassVar[str] = "runtime_audit"
    ENTITY_ID_FIELD: ClassVar[str] = "audit_uuid"
    TABLE_NAME: ClassVar[str] = "runtime_audit_log"
    COLUMNS: ClassVar[tuple[str, ...]] = (
        "uuid",
        "plan_uuid",
        "entity_type",
        "entity_id",
        "action",
        "changed_by",
        "change_reason",
        "changed_fields",
        "linked_attempt_id",
        "linked_review_id",
        "created_at",
    )
    SOFT_DELETE_COLUMN: ClassVar[str | None] = None
    UPDATED_AT_COLUMN: ClassVar[str | None] = None

    audit_uuid: uuid.UUID
    plan_uuid: uuid.UUID | None
    target_type: str
    target_id: uuid.UUID
    action: str
    changed_by: str
    change_reason: str | None
    changed_fields: dict[str, Any] | None
    linked_attempt_id: uuid.UUID | None
    linked_review_id: uuid.UUID | None
    created_at: str

    @classmethod
    def crud_update(cls, *args: Any, **kwargs: Any) -> None:
        raise NotImplementedError("runtime_audit_log is append-only; records cannot be updated")

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.audit_uuid),
            "plan_uuid": str(self.plan_uuid) if self.plan_uuid is not None else None,
            "entity_type": self.target_type,
            "entity_id": str(self.target_id),
            "action": self.action,
            "changed_by": self.changed_by,
            "change_reason": self.change_reason,
            "changed_fields": self.changed_fields,
            "linked_attempt_id": str(self.linked_attempt_id) if self.linked_attempt_id is not None else None,
            "linked_review_id": str(self.linked_review_id) if self.linked_review_id is not None else None,
            "created_at": self.created_at,
        }


def _row_to_record(row: tuple[Any, ...]) -> RuntimeAuditRecord:
    return RuntimeAuditRecord(
        audit_uuid=row[0],
        plan_uuid=row[1],
        target_type=row[2],
        target_id=row[3],
        action=row[4],
        changed_by=row[5],
        change_reason=row[6],
        changed_fields=row[7],
        linked_attempt_id=row[8],
        linked_review_id=row[9],
        created_at=row[10].isoformat(),
    )


def record_runtime_change(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    changed_by: str,
    change_reason: str | None = None,
    changed_fields: dict[str, Any] | None = None,
    linked_attempt_id: uuid.UUID | None = None,
    linked_review_id: uuid.UUID | None = None,
) -> RuntimeAuditRecord:
    """Append one immutable audit record for a runtime change.

    Parameters:
        conn: psycopg.Connection
            Open connection used to execute the INSERT.
        plan_uuid: uuid.UUID | None
            The plan the runtime change is anchored to, or None for an
            unanchored runtime change.
        entity_type: str
            The runtime entity kind changed.
        entity_id: uuid.UUID
            The runtime record changed.
        action: str
            One of "create", "update", "soft_delete", "hard_delete", "archive",
            "restore", "plan_unfreeze", "subtree_unfreeze".
        changed_by: str
            Who performed the change.
        change_reason: str | None
            Why the change was made.
        changed_fields: dict[str, Any] | None
            What changed, as a JSON-serializable mapping.
        linked_attempt_id: uuid.UUID | None
            The linked execution attempt, if any.
        linked_review_id: uuid.UUID | None
            The linked review, if any.

    Returns:
        RuntimeAuditRecord
            The persisted audit record.

    Raises:
        ValueError
            If action is not one of the ALLOWED_ACTIONS values.

    This function only INSERTs into runtime_audit_log. It never issues
    UPDATE or DELETE against runtime_audit_log.
    """
    if action not in ALLOWED_ACTIONS:
        raise ValueError(f"invalid action: {action}")
    changed_by = validate_actor_identity(changed_by)

    audit_uuid = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO runtime_audit_log "
        "(uuid, plan_uuid, entity_type, entity_id, action, changed_by, change_reason, "
        "changed_fields, linked_attempt_id, linked_review_id, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            audit_uuid,
            plan_uuid,
            entity_type,
            entity_id,
            action,
            changed_by,
            change_reason,
            Jsonb(changed_fields) if changed_fields is not None else None,
            linked_attempt_id,
            linked_review_id,
            created_at,
        ),
    )
    return RuntimeAuditRecord(
        audit_uuid=audit_uuid,
        plan_uuid=plan_uuid,
        target_type=entity_type,
        target_id=entity_id,
        action=action,
        changed_by=changed_by,
        change_reason=change_reason,
        changed_fields=changed_fields,
        linked_attempt_id=linked_attempt_id,
        linked_review_id=linked_review_id,
        created_at=created_at.isoformat(),
    )


def _filter_clause(
    *,
    plan_uuid: uuid.UUID | None,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    changed_by: str | None,
    action: str | None,
    created_after: str | None,
    created_before: str | None,
) -> tuple[str, list[Any]]:
    """Build the shared WHERE clause and parameter list for list_runtime_audit and count_runtime_audit.

    Parameters:
        plan_uuid: uuid.UUID | None
            When given, restrict to audit records with this plan_uuid.
        entity_type: str | None
            When given, restrict to audit records with this entity_type.
        entity_id: uuid.UUID | None
            When given, restrict to audit records with this entity_id.
        changed_by: str | None
            When given, restrict to audit records with this changed_by actor.
        action: str | None
            When given, restrict to audit records with this action.
        created_after: str | None
            When given, restrict to audit records with created_at >= this value.
        created_before: str | None
            When given, restrict to audit records with created_at <= this value.

    Returns:
        tuple[str, list[Any]]
            A (where_clause, params) pair. where_clause is either the empty
            string or a string starting with " WHERE " ready to append to a
            base SQL statement; params is the ordered list of bind values
            matching the clause's placeholders.
    """
    conditions: list[str] = []
    params: list[Any] = []
    if plan_uuid is not None:
        conditions.append("plan_uuid = %s")
        params.append(plan_uuid)
    if entity_type is not None:
        conditions.append("entity_type = %s")
        params.append(entity_type)
    if entity_id is not None:
        conditions.append("entity_id = %s")
        params.append(entity_id)
    if changed_by is not None:
        conditions.append("changed_by = %s")
        params.append(changed_by)
    if action is not None:
        conditions.append("action = %s")
        params.append(action)
    if created_after is not None:
        conditions.append("created_at >= %s")
        params.append(created_after)
    if created_before is not None:
        conditions.append("created_at <= %s")
        params.append(created_before)
    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    return where_clause, params


def list_runtime_audit(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    changed_by: str | None = None,
    action: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> list[RuntimeAuditRecord]:
    """Return a newest-first page of the retained audit chain, optionally filtered.

    Parameters:
        conn: psycopg.Connection
            Open connection used to execute the SELECT.
        plan_uuid: uuid.UUID | None
            When given, restrict to audit records with this plan_uuid.
        entity_type: str | None
            When given, restrict to audit records with this entity_type.
        entity_id: uuid.UUID | None
            When given, restrict to audit records with this entity_id.
        changed_by: str | None
            When given, restrict to audit records with this changed_by actor.
        action: str | None
            When given, restrict to audit records with this action. The
            caller is responsible for validating the value against
            ALLOWED_ACTIONS before calling; this function does not validate it.
        created_after: str | None
            When given, restrict to audit records with created_at >= this value.
        created_before: str | None
            When given, restrict to audit records with created_at <= this value.
        limit: int | None
            When given, caps the number of returned rows via SQL LIMIT. None
            means no LIMIT clause is applied.
        offset: int
            Number of matching rows, in the newest-first order, to skip
            before the returned page starts. Defaults to 0.

    Returns:
        list[RuntimeAuditRecord]
            The matching audit records within [offset, offset+limit) (or all
            matching records from offset onward when limit is None), ordered
            by created_at descending (newest first; no record is ever
            excluded by soft deletion since deletion is itself an appended
            action, not a removal).
    """
    where_clause, params = _filter_clause(
        plan_uuid=plan_uuid,
        entity_type=entity_type,
        entity_id=entity_id,
        changed_by=changed_by,
        action=action,
        created_after=created_after,
        created_before=created_before,
    )
    sql = (
        "SELECT uuid, plan_uuid, entity_type, entity_id, action, changed_by, change_reason, "
        "changed_fields, linked_attempt_id, linked_review_id, created_at FROM runtime_audit_log"
        + where_clause
        + " ORDER BY created_at DESC"
    )
    if limit is not None:
        sql += " LIMIT %s"
        params.append(limit)
    sql += " OFFSET %s"
    params.append(offset)
    rows = conn.execute(sql, tuple(params)).fetchall()
    return [_row_to_record(row) for row in rows]


def count_runtime_audit(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    changed_by: str | None = None,
    action: str | None = None,
    created_after: str | None = None,
    created_before: str | None = None,
) -> int:
    """Return the count of audit records matching the same filter set as list_runtime_audit, independent of limit/offset.

    Parameters:
        conn: psycopg.Connection
            Open connection used to execute the SELECT COUNT(*).
        plan_uuid: uuid.UUID | None
            When given, restrict to audit records with this plan_uuid.
        entity_type: str | None
            When given, restrict to audit records with this entity_type.
        entity_id: uuid.UUID | None
            When given, restrict to audit records with this entity_id.
        changed_by: str | None
            When given, restrict to audit records with this changed_by actor.
        action: str | None
            When given, restrict to audit records with this action.
        created_after: str | None
            When given, restrict to audit records with created_at >= this value.
        created_before: str | None
            When given, restrict to audit records with created_at <= this value.

    Returns:
        int
            The total number of audit records matching the given filter set,
            independent of any limit/offset paging.
    """
    where_clause, params = _filter_clause(
        plan_uuid=plan_uuid,
        entity_type=entity_type,
        entity_id=entity_id,
        changed_by=changed_by,
        action=action,
        created_after=created_after,
        created_before=created_before,
    )
    row = conn.execute(
        "SELECT COUNT(*) FROM runtime_audit_log" + where_clause,
        tuple(params),
    ).fetchone()
    return row[0] if row is not None else 0
