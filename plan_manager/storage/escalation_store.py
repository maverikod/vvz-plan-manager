"""Escalation persistence: create/resolve/list escalations over escalation with audit + soft delete (C-037)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from plan_manager.domain.escalation import Escalation, ESCALATION_STATUSES, validate_escalation_status
from plan_manager.domain.primary_anchor import PrimaryAnchor, validate_anchor, anchor_to_columns, anchor_from_columns
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: dict[str, Any]) -> Escalation:
    """Convert a database row dict to an Escalation instance."""
    anchor_columns = {
        "primary_anchor_type": row["primary_anchor_type"],
        "anchor_project_id": row["anchor_project_id"],
        "anchor_file_path": row["anchor_file_path"],
        "anchor_plan_uuid": row["anchor_plan_uuid"],
        "anchor_revision_uuid": row["anchor_revision_uuid"],
        "anchor_step_uuid": row["anchor_step_uuid"],
        "anchor_step_path": row["anchor_step_path"],
        "anchor_ref_id": row["anchor_ref_id"],
    }
    anchor = anchor_from_columns(anchor_columns)

    # Convert datetime fields to isoformat strings if they are datetime objects
    created_at_str = row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"]
    updated_at_str = row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"]
    resolved_at_str = (
        row["resolved_at"].isoformat() if isinstance(row["resolved_at"], datetime) and row["resolved_at"] else row["resolved_at"]
    )
    deleted_at_str = (
        row["deleted_at"].isoformat() if isinstance(row["deleted_at"], datetime) and row["deleted_at"] else row["deleted_at"]
    )

    return Escalation(
        escalation_uuid=row["uuid"],
        primary_anchor_type=anchor.anchor_type,
        anchor_project_id=anchor.project_id,
        anchor_file_path=anchor.file_path,
        anchor_plan_uuid=anchor.plan_uuid,
        anchor_revision_uuid=anchor.revision_uuid,
        anchor_step_uuid=anchor.step_uuid,
        anchor_step_path=anchor.step_path,
        anchor_ref_id=anchor.ref_id,
        reason=row["reason"],
        from_level=row["from_level"],
        to_level=row["to_level"],
        status=row["status"],
        resolution=row["resolution"],
        resolved_by=row["resolved_by"],
        resolved_at=resolved_at_str,
        created_by=row["created_by"],
        created_at=created_at_str,
        updated_at=updated_at_str,
        deleted_at=deleted_at_str,
    )


def create_escalation(conn: psycopg.Connection, *, anchor: PrimaryAnchor, reason: str, created_by: str,
                      from_level: str | None = None, to_level: str | None = None) -> Escalation:
    """Create a new escalation record."""
    # Validate anchor
    validate_anchor(conn, anchor)

    # Generate UUID and timestamps
    escalation_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    created_at = updated_at = now

    # Set initial values
    status = "open"
    resolution = None
    resolved_by = None
    resolved_at = None
    deleted_at = None

    # Flatten anchor to column dict
    anchor_columns = anchor_to_columns(anchor)

    # INSERT into escalation table with exact column order
    sql = """
    INSERT INTO escalation (
        uuid, primary_anchor_type, anchor_project_id, anchor_file_path, anchor_plan_uuid,
        anchor_revision_uuid, anchor_step_uuid, anchor_step_path, anchor_ref_id,
        reason, from_level, to_level, status, resolution, resolved_by, resolved_at,
        created_by, created_at, updated_at, deleted_at
    ) VALUES (
        %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s
    )
    """

    params = (
        escalation_uuid,
        anchor_columns["primary_anchor_type"],
        anchor_columns["anchor_project_id"],
        anchor_columns["anchor_file_path"],
        anchor_columns["anchor_plan_uuid"],
        anchor_columns["anchor_revision_uuid"],
        anchor_columns["anchor_step_uuid"],
        anchor_columns["anchor_step_path"],
        anchor_columns["anchor_ref_id"],
        reason,
        from_level,
        to_level,
        status,
        resolution,
        resolved_by,
        resolved_at,
        created_by,
        created_at,
        updated_at,
        deleted_at,
    )

    conn.execute(sql, params)

    # Record runtime change
    record_runtime_change(
        conn,
        plan_uuid=anchor.plan_uuid,
        entity_type="escalation",
        entity_id=escalation_uuid,
        action="create",
        changed_by=created_by,
    )

    # Return the created escalation
    return Escalation(
        escalation_uuid=escalation_uuid,
        primary_anchor_type=anchor_columns["primary_anchor_type"],
        anchor_project_id=anchor_columns["anchor_project_id"],
        anchor_file_path=anchor_columns["anchor_file_path"],
        anchor_plan_uuid=anchor_columns["anchor_plan_uuid"],
        anchor_revision_uuid=anchor_columns["anchor_revision_uuid"],
        anchor_step_uuid=anchor_columns["anchor_step_uuid"],
        anchor_step_path=anchor_columns["anchor_step_path"],
        anchor_ref_id=anchor_columns["anchor_ref_id"],
        reason=reason,
        from_level=from_level,
        to_level=to_level,
        status=status,
        resolution=resolution,
        resolved_by=resolved_by,
        resolved_at=resolved_at,
        created_by=created_by,
        created_at=created_at.isoformat(),
        updated_at=updated_at.isoformat(),
        deleted_at=deleted_at,
    )


def resolve_escalation(conn: psycopg.Connection, escalation_uuid: uuid.UUID, *, resolved_by: str,
                       resolution: str) -> Escalation:
    """Resolve an open escalation."""
    # Load the existing escalation
    sql_select = "SELECT * FROM escalation WHERE uuid = %s"
    cursor = conn.execute(sql_select, (escalation_uuid,))
    row = cursor.fetchone()

    if row is None:
        raise RuntimeValidationError(f"Escalation {escalation_uuid} not found")

    # Check if soft-deleted
    if row[19] is not None:  # deleted_at column (20th column, 0-indexed as 19)
        raise RuntimeValidationError(f"Escalation {escalation_uuid} is deleted")

    # Get current timestamp
    now = datetime.now(timezone.utc)

    # UPDATE the row
    sql_update = """
    UPDATE escalation
    SET status = %s, resolution = %s, resolved_by = %s, resolved_at = %s, updated_at = %s
    WHERE uuid = %s
    """

    params = (
        "resolved",
        resolution,
        resolved_by,
        now,
        now,
        escalation_uuid,
    )

    conn.execute(sql_update, params)

    # Record runtime change
    # row[4] is anchor_plan_uuid (5th column, 0-indexed as 4)
    record_runtime_change(
        conn,
        plan_uuid=row[4],
        entity_type="escalation",
        entity_id=escalation_uuid,
        action="update",
        changed_by=resolved_by,
    )

    # Reconstruct and return the updated escalation
    # Rebuild the row dict for _row_to_record
    # Using the updated values
    anchor_columns = {
        "primary_anchor_type": row[1],
        "anchor_project_id": row[2],
        "anchor_file_path": row[3],
        "anchor_plan_uuid": row[4],
        "anchor_revision_uuid": row[5],
        "anchor_step_uuid": row[6],
        "anchor_step_path": row[7],
        "anchor_ref_id": row[8],
    }
    anchor = anchor_from_columns(anchor_columns)

    return Escalation(
        escalation_uuid=escalation_uuid,
        primary_anchor_type=anchor.anchor_type,
        anchor_project_id=anchor.project_id,
        anchor_file_path=anchor.file_path,
        anchor_plan_uuid=anchor.plan_uuid,
        anchor_revision_uuid=anchor.revision_uuid,
        anchor_step_uuid=anchor.step_uuid,
        anchor_step_path=anchor.step_path,
        anchor_ref_id=anchor.ref_id,
        reason=row[9],
        from_level=row[10],
        to_level=row[11],
        status="resolved",
        resolution=resolution,
        resolved_by=resolved_by,
        resolved_at=now.isoformat(),
        created_by=row[16],
        created_at=row[17].isoformat() if isinstance(row[17], datetime) else row[17],
        updated_at=now.isoformat(),
        deleted_at=None,
    )


def get_escalation(conn: psycopg.Connection, escalation_uuid: uuid.UUID) -> Escalation | None:
    """Get an escalation by UUID."""
    sql = "SELECT * FROM escalation WHERE uuid = %s"
    cursor = conn.execute(sql, (escalation_uuid,))
    row = cursor.fetchone()

    if row is None:
        return None

    # Convert tuple to dict for reconstruction
    row_dict = {
        "uuid": row[0],
        "primary_anchor_type": row[1],
        "anchor_project_id": row[2],
        "anchor_file_path": row[3],
        "anchor_plan_uuid": row[4],
        "anchor_revision_uuid": row[5],
        "anchor_step_uuid": row[6],
        "anchor_step_path": row[7],
        "anchor_ref_id": row[8],
        "reason": row[9],
        "from_level": row[10],
        "to_level": row[11],
        "status": row[12],
        "resolution": row[13],
        "resolved_by": row[14],
        "resolved_at": row[15],
        "created_by": row[16],
        "created_at": row[17],
        "updated_at": row[18],
        "deleted_at": row[19],
    }

    return _row_to_record(row_dict)


def list_escalations(conn: psycopg.Connection, *, status: str | None = None,
                     anchor_ref_id: uuid.UUID | None = None,
                     anchor_plan_uuid: uuid.UUID | None = None,
                     include_deleted: bool = False) -> list[Escalation]:
    """List escalations with optional filters. When anchor_plan_uuid is given, only rows whose anchor_plan_uuid equals it match (NULL and foreign plan anchors are excluded)."""
    # Build the query
    sql_parts = ["SELECT * FROM escalation WHERE 1=1"]
    params: list[Any] = []

    if status is not None:
        sql_parts.append("AND status = %s")
        params.append(status)

    if anchor_ref_id is not None:
        sql_parts.append("AND anchor_ref_id = %s")
        params.append(anchor_ref_id)

    if anchor_plan_uuid is not None:
        sql_parts.append("AND anchor_plan_uuid = %s")
        params.append(anchor_plan_uuid)

    if not include_deleted:
        sql_parts.append("AND deleted_at IS NULL")

    sql_parts.append("ORDER BY created_at ASC")

    sql = " ".join(sql_parts)

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    escalations = []
    for row in rows:
        row_dict = {
            "uuid": row[0],
            "primary_anchor_type": row[1],
            "anchor_project_id": row[2],
            "anchor_file_path": row[3],
            "anchor_plan_uuid": row[4],
            "anchor_revision_uuid": row[5],
            "anchor_step_uuid": row[6],
            "anchor_step_path": row[7],
            "anchor_ref_id": row[8],
            "reason": row[9],
            "from_level": row[10],
            "to_level": row[11],
            "status": row[12],
            "resolution": row[13],
            "resolved_by": row[14],
            "resolved_at": row[15],
            "created_by": row[16],
            "created_at": row[17],
            "updated_at": row[18],
            "deleted_at": row[19],
        }
        escalations.append(_row_to_record(row_dict))

    return escalations
