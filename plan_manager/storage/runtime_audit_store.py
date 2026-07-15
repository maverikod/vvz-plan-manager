"""Runtime audit trail persistence: append-only recorder for runtime changes, kept separate from versioned plan truth."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.domain.entity import DataclassEntity


ALLOWED_ACTIONS: frozenset[str] = frozenset(
    {"create", "update", "soft_delete", "archive", "restore", "plan_unfreeze"}
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
            One of "create", "update", "soft_delete", "archive", "restore".
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


def list_runtime_audit(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None = None,
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
) -> list[RuntimeAuditRecord]:
    """Return the retained audit chain, optionally filtered, oldest first.

    Parameters:
        conn: psycopg.Connection
            Open connection used to execute the SELECT.
        plan_uuid: uuid.UUID | None
            When given, restrict to audit records with this plan_uuid.
        entity_type: str | None
            When given, restrict to audit records with this entity_type.
        entity_id: uuid.UUID | None
            When given, restrict to audit records with this entity_id.

    Returns:
        list[RuntimeAuditRecord]
            The matching audit records ordered by created_at ascending
            (the full retained chain of events; no record is ever
            excluded by soft deletion since deletion is itself an
            appended action, not a removal).
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

    where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""
    rows = conn.execute(
        "SELECT uuid, plan_uuid, entity_type, entity_id, action, changed_by, change_reason, "
        "changed_fields, linked_attempt_id, linked_review_id, created_at FROM runtime_audit_log"
        + where_clause
        + " ORDER BY created_at ASC",
        tuple(params),
    ).fetchall()
    return [_row_to_record(row) for row in rows]
