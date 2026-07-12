"""Runtime audit trail persistence: append-only recorder for runtime changes, kept separate from versioned plan truth."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


ALLOWED_ACTIONS: frozenset[str] = frozenset({"create", "update", "soft_delete", "archive", "restore"})


@dataclass(frozen=True)
class RuntimeAuditRecord:
    audit_uuid: uuid.UUID
    plan_uuid: uuid.UUID | None
    entity_type: str
    entity_id: uuid.UUID
    action: str
    changed_by: str
    change_reason: str | None
    changed_fields: dict[str, Any] | None
    linked_attempt_id: uuid.UUID | None
    linked_review_id: uuid.UUID | None
    created_at: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.audit_uuid),
            "plan_uuid": str(self.plan_uuid) if self.plan_uuid is not None else None,
            "entity_type": self.entity_type,
            "entity_id": str(self.entity_id),
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
        entity_type=row[2],
        entity_id=row[3],
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
        entity_type=entity_type,
        entity_id=entity_id,
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
