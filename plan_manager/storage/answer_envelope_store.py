"""Answer-envelope persistence: create/get/list stored answer envelopes with audit + soft delete (C-010)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from psycopg.types.json import Jsonb
from plan_manager.domain.answer_envelope import AnswerEnvelope, validate_answer_envelope
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: dict[str, Any]) -> AnswerEnvelope:
    """Convert a database row dict to an AnswerEnvelope instance."""
    created_at_str = row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"]
    updated_at_str = row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"]
    deleted_at_str = (
        row["deleted_at"].isoformat() if isinstance(row["deleted_at"], datetime) and row["deleted_at"] else row["deleted_at"]
    )
    return AnswerEnvelope(
        envelope_uuid=row["uuid"],
        kind=row["kind"],
        schema_version=row["schema_version"],
        payload=row["payload"],
        anchor_plan_uuid=row["anchor_plan_uuid"],
        anchor_step_uuid=row["anchor_step_uuid"],
        attempt_uuid=row["attempt_uuid"],
        created_by=row["created_by"],
        created_at=created_at_str,
        updated_at=updated_at_str,
        deleted_at=deleted_at_str,
    )


def create_answer_envelope(
    conn: psycopg.Connection,
    *,
    kind: str,
    schema_version: int,
    payload: dict[str, Any],
    created_by: str,
    anchor_plan_uuid: uuid.UUID | None = None,
    anchor_step_uuid: uuid.UUID | None = None,
    attempt_uuid: uuid.UUID | None = None,
) -> AnswerEnvelope:
    """Create a new answer envelope record."""
    validate_answer_envelope(kind, schema_version, payload)
    envelope_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    created_at = updated_at = now

    sql = """
    INSERT INTO answer_envelope (
        uuid, kind, schema_version, payload, anchor_plan_uuid, anchor_step_uuid,
        attempt_uuid, created_by, created_at, updated_at, deleted_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s
    )
    """

    params = (
        envelope_uuid,
        kind,
        schema_version,
        Jsonb(payload),
        anchor_plan_uuid,
        anchor_step_uuid,
        attempt_uuid,
        created_by,
        created_at,
        updated_at,
        None,
    )

    conn.execute(sql, params)

    record_runtime_change(
        conn,
        plan_uuid=anchor_plan_uuid,
        entity_type="answer_envelope",
        entity_id=envelope_uuid,
        action="create",
        changed_by=created_by,
    )

    return AnswerEnvelope(
        envelope_uuid=envelope_uuid,
        kind=kind,
        schema_version=schema_version,
        payload=payload,
        anchor_plan_uuid=anchor_plan_uuid,
        anchor_step_uuid=anchor_step_uuid,
        attempt_uuid=attempt_uuid,
        created_by=created_by,
        created_at=created_at.isoformat(),
        updated_at=updated_at.isoformat(),
        deleted_at=None,
    )


def get_answer_envelope(conn: psycopg.Connection, envelope_uuid: uuid.UUID) -> AnswerEnvelope | None:
    """Get an answer envelope by its UUID."""
    sql = "SELECT * FROM answer_envelope WHERE uuid = %s"
    cursor = conn.execute(sql, (envelope_uuid,))
    row = cursor.fetchone()

    if row is None:
        return None

    row_dict = {
        "uuid": row[0],
        "kind": row[1],
        "schema_version": row[2],
        "payload": row[3],
        "anchor_plan_uuid": row[4],
        "anchor_step_uuid": row[5],
        "attempt_uuid": row[6],
        "created_by": row[7],
        "created_at": row[8],
        "updated_at": row[9],
        "deleted_at": row[10],
    }

    return _row_to_record(row_dict)


def list_answer_envelopes(
    conn: psycopg.Connection,
    *,
    kind: str | None = None,
    attempt_uuid: uuid.UUID | None = None,
    anchor_plan_uuid: uuid.UUID | None = None,
    include_deleted: bool = False,
) -> list[AnswerEnvelope]:
    """List answer envelopes with optional filters."""
    sql_parts = ["SELECT * FROM answer_envelope WHERE 1=1"]
    params: list[Any] = []

    if kind is not None:
        sql_parts.append("AND kind = %s")
        params.append(kind)

    if attempt_uuid is not None:
        sql_parts.append("AND attempt_uuid = %s")
        params.append(attempt_uuid)

    if anchor_plan_uuid is not None:
        sql_parts.append("AND anchor_plan_uuid = %s")
        params.append(anchor_plan_uuid)

    if not include_deleted:
        sql_parts.append("AND deleted_at IS NULL")

    sql_parts.append("ORDER BY created_at ASC")

    sql = " ".join(sql_parts)

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    envelopes = []
    for row in rows:
        row_dict = {
            "uuid": row[0],
            "kind": row[1],
            "schema_version": row[2],
            "payload": row[3],
            "anchor_plan_uuid": row[4],
            "anchor_step_uuid": row[5],
            "attempt_uuid": row[6],
            "created_by": row[7],
            "created_at": row[8],
            "updated_at": row[9],
            "deleted_at": row[10],
        }
        envelopes.append(_row_to_record(row_dict))

    return envelopes
