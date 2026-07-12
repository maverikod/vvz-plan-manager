"""Cascade request persistence: runtime-raised requests for normative changes to frozen plan truth."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.storage.runtime_audit_store import record_runtime_change


@dataclass(frozen=True)
class CascadeRequestRecord:
    request_uuid: uuid.UUID
    plan_uuid: uuid.UUID
    revision_uuid: uuid.UUID | None
    target_artifact: str
    target_step_path: str | None
    origin_kind: str
    origin_id: uuid.UUID | None
    reason: str
    status: str
    created_by: str
    created_at: str
    updated_at: str

    def to_payload(self) -> dict[str, Any]:
        """Serialize this record to a JSON-safe dict.

        Returns:
            dict[str, Any]
                A dict with every UUID field (request_uuid, plan_uuid,
                revision_uuid, origin_id) rendered as str (None stays
                None for the nullable UUID fields), and every other
                field passed through unchanged. Keyed as: "uuid",
                "plan_uuid", "revision_uuid", "target_artifact",
                "target_step_path", "origin_kind", "origin_id",
                "reason", "status", "created_by", "created_at",
                "updated_at".
        """
        return {
            "uuid": str(self.request_uuid),
            "plan_uuid": str(self.plan_uuid),
            "revision_uuid": str(self.revision_uuid) if self.revision_uuid is not None else None,
            "target_artifact": self.target_artifact,
            "target_step_path": self.target_step_path,
            "origin_kind": self.origin_kind,
            "origin_id": str(self.origin_id) if self.origin_id is not None else None,
            "reason": self.reason,
            "status": self.status,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _row_to_record(row: tuple[Any, ...]) -> CascadeRequestRecord:
    return CascadeRequestRecord(
        request_uuid=row[0],
        plan_uuid=row[1],
        revision_uuid=row[2],
        target_artifact=row[3],
        target_step_path=row[4],
        origin_kind=row[5],
        origin_id=row[6],
        reason=row[7],
        status=row[8],
        created_by=row[9],
        created_at=row[10].isoformat(),
        updated_at=row[11].isoformat(),
    )


def create_cascade_request(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID,
    revision_uuid: uuid.UUID | None,
    target_artifact: str,
    target_step_path: str | None,
    origin_kind: str,
    origin_id: uuid.UUID | None,
    reason: str,
    created_by: str,
) -> CascadeRequestRecord:
    """Create and persist one cascade request raised from runtime work.

    Parameters:
        conn: psycopg.Connection
            Open connection; this function issues one INSERT against
            cascade_request and then appends one runtime audit record
            via record_runtime_change (an INSERT into runtime_audit_log).
            It never writes to plan, revision, step, concept, relation,
            or paragraph tables, and never performs the normative change
            itself.
        plan_uuid: uuid.UUID
            The FrozenPlanTruth plan this request refers to.
        revision_uuid: uuid.UUID | None
            The FrozenPlanTruth revision this request refers to, or
            None when not applicable.
        target_artifact: str
            The frozen-truth artifact level the discovered need
            targets. Must be one of "HRS", "MRS", "GS", "TS", "AS".
        target_step_path: str | None
            The canonical step path of the targeted GS/TS/AS step, or
            None when target_artifact is "HRS" or "MRS".
        origin_kind: str
            The kind of runtime record that raised this request. Must
            be one of "todo", "comment", "bug", "verification_result".
        origin_id: uuid.UUID | None
            The identifier of the originating runtime record, or None
            when no runtime record identifier is available.
        reason: str
            Prose explaining why a normative change is discovered to
            be necessary.
        created_by: str
            The identity of the author raising the cascade request.

    Returns:
        CascadeRequestRecord
            The newly created record, with a fresh uuid.uuid4()
            identifier, status "open", and created_at/updated_at both
            set to the same datetime.now(timezone.utc) instant.

    Raises:
        ValueError
            If target_artifact is not one of HRS, MRS, GS, TS, AS, or
            if origin_kind is not one of todo, comment, bug,
            verification_result.
    """
    if target_artifact not in ("HRS", "MRS", "GS", "TS", "AS"):
        raise ValueError(
            f"target_artifact must be one of HRS, MRS, GS, TS, AS; got {target_artifact!r}"
        )
    if origin_kind not in ("todo", "comment", "bug", "verification_result"):
        raise ValueError(
            f"origin_kind must be one of todo, comment, bug, verification_result; got {origin_kind!r}"
        )
    request_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO cascade_request "
        "(uuid, plan_uuid, revision_uuid, target_artifact, target_step_path, "
        "origin_kind, origin_id, reason, status, created_by, created_at, updated_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            request_uuid,
            plan_uuid,
            revision_uuid,
            target_artifact,
            target_step_path,
            origin_kind,
            origin_id,
            reason,
            "open",
            created_by,
            now,
            now,
        ),
    )
    record_runtime_change(
        conn,
        plan_uuid=plan_uuid,
        entity_type="cascade_request",
        entity_id=request_uuid,
        action="create",
        changed_by=created_by,
        change_reason=reason,
    )
    return CascadeRequestRecord(
        request_uuid=request_uuid,
        plan_uuid=plan_uuid,
        revision_uuid=revision_uuid,
        target_artifact=target_artifact,
        target_step_path=target_step_path,
        origin_kind=origin_kind,
        origin_id=origin_id,
        reason=reason,
        status="open",
        created_by=created_by,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
    )


def get_cascade_request(conn: psycopg.Connection, request_uuid: uuid.UUID) -> CascadeRequestRecord | None:
    """Fetch one cascade request by its identifier.

    Parameters:
        conn: psycopg.Connection
            Open connection; this function issues one SELECT against
            cascade_request and nothing else.
        request_uuid: uuid.UUID
            The primary key of the cascade_request row to fetch.

    Returns:
        CascadeRequestRecord | None
            The matching record, or None when no row has this uuid.
    """
    row = conn.execute(
        "SELECT uuid, plan_uuid, revision_uuid, target_artifact, target_step_path, "
        "origin_kind, origin_id, reason, status, created_by, created_at, updated_at "
        "FROM cascade_request WHERE uuid = %s",
        (request_uuid,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_cascade_requests(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID,
    status: str | None = None,
) -> list[CascadeRequestRecord]:
    """List cascade requests for one plan, optionally filtered by status.

    Parameters:
        conn: psycopg.Connection
            Open connection; this function issues one SELECT against
            cascade_request and nothing else.
        plan_uuid: uuid.UUID
            The FrozenPlanTruth plan to list cascade requests for.
        status: str | None
            When given, restricts the result to rows with this exact
            status value (e.g. "open", "promoted", "closed"). When
            None, all statuses are returned.

    Returns:
        list[CascadeRequestRecord]
            Every matching row, ordered by created_at ascending
            (oldest first).
    """
    if status is None:
        rows = conn.execute(
            "SELECT uuid, plan_uuid, revision_uuid, target_artifact, target_step_path, "
            "origin_kind, origin_id, reason, status, created_by, created_at, updated_at "
            "FROM cascade_request WHERE plan_uuid = %s ORDER BY created_at ASC",
            (plan_uuid,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT uuid, plan_uuid, revision_uuid, target_artifact, target_step_path, "
            "origin_kind, origin_id, reason, status, created_by, created_at, updated_at "
            "FROM cascade_request WHERE plan_uuid = %s AND status = %s ORDER BY created_at ASC",
            (plan_uuid, status),
        ).fetchall()
    return [_row_to_record(row) for row in rows]
