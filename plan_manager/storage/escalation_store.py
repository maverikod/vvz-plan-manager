"""Escalation persistence: create/resolve/list escalations over escalation with audit + soft delete (C-037)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from plan_manager.domain.escalation import Escalation, ESCALATION_STATUSES, validate_escalation_status
from plan_manager.domain.primary_anchor import PrimaryAnchor, validate_anchor, anchor_to_columns, anchor_from_columns
from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.storage.escalation_routing_store import routing_from_row
from plan_manager.storage.runtime_audit_store import record_runtime_change


# Explicit read projection for every escalation SELECT in this module (bug
# 0798c162 sweep): these reads used SELECT * with positional row indexing, so
# any change to the table's column order -- and, for the fixed slices, any
# inserted column -- would silently misread rows (migration 0029 appended
# `owner`, which the fixed indexes below would otherwise drift onto). Selecting
# exactly these columns pins the row shape to the names, immune to future
# additive columns.
_ESCALATION_SELECT_COLUMN_NAMES = (
    "uuid", "primary_anchor_type", "anchor_project_id", "anchor_file_path",
    "anchor_plan_uuid", "anchor_revision_uuid", "anchor_step_uuid",
    "anchor_step_path", "anchor_ref_id", "reason", "from_level", "to_level",
    "status", "resolution", "resolved_by", "resolved_at", "created_by",
    "created_at", "updated_at", "deleted_at", "addressee_level",
    "addressee_role", "forwarded_from_uuid", "chain_root_uuid",
    "sweep_priority", "blocks_subtree",
)
_ESCALATION_SELECT_COLUMNS = ", ".join(_ESCALATION_SELECT_COLUMN_NAMES)


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    """Zip a row fetched via _ESCALATION_SELECT_COLUMNS into a column dict."""
    return dict(zip(_ESCALATION_SELECT_COLUMN_NAMES, row))


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
    routing = routing_from_row(row)

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
        **routing,
    )


def create_escalation(conn: psycopg.Connection, *, anchor: PrimaryAnchor, reason: str, created_by: str,
                      from_level: str | None = None, to_level: str | None = None,
                      addressee_level: str | None = None, addressee_role: str | None = None,
                      forwarded_from_uuid: uuid.UUID | None = None, chain_root_uuid: uuid.UUID | None = None,
                      sweep_priority: int | None = None, blocks_subtree: bool = False) -> Escalation:
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

    # CR-7 G-004 (C-005, C-012): the write is delegated to the unified
    # engine's creation path; this module no longer composes INSERT SQL.
    Escalation.crud_create(
        conn,
        {
            "uuid": escalation_uuid,
            "primary_anchor_type": anchor_columns["primary_anchor_type"],
            "anchor_project_id": anchor_columns["anchor_project_id"],
            "anchor_file_path": anchor_columns["anchor_file_path"],
            "anchor_plan_uuid": anchor_columns["anchor_plan_uuid"],
            "anchor_revision_uuid": anchor_columns["anchor_revision_uuid"],
            "anchor_step_uuid": anchor_columns["anchor_step_uuid"],
            "anchor_step_path": anchor_columns["anchor_step_path"],
            "anchor_ref_id": anchor_columns["anchor_ref_id"],
            "reason": reason,
            "from_level": from_level,
            "to_level": to_level,
            "status": status,
            "resolution": resolution,
            "resolved_by": resolved_by,
            "resolved_at": resolved_at,
            "created_by": created_by,
            "created_at": created_at,
            "updated_at": updated_at,
            "deleted_at": deleted_at,
            "addressee_level": addressee_level,
            "addressee_role": addressee_role,
            "forwarded_from_uuid": forwarded_from_uuid,
            "chain_root_uuid": chain_root_uuid,
            "sweep_priority": sweep_priority,
            "blocks_subtree": blocks_subtree,
        },
        returning=False,
    )

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
        addressee_level=addressee_level,
        addressee_role=addressee_role,
        forwarded_from_uuid=forwarded_from_uuid,
        chain_root_uuid=chain_root_uuid,
        sweep_priority=sweep_priority,
        blocks_subtree=blocks_subtree,
    )


def resolve_escalation(conn: psycopg.Connection, escalation_uuid: uuid.UUID, *, resolved_by: str,
                       resolution: str) -> Escalation:
    """Resolve an open escalation."""
    # Load the existing escalation
    sql_select = f"SELECT {_ESCALATION_SELECT_COLUMNS} FROM escalation WHERE uuid = %s"
    cursor = conn.execute(sql_select, (escalation_uuid,))
    row = cursor.fetchone()

    if row is None:
        raise RuntimeValidationError(f"Escalation {escalation_uuid} not found")
    row_dict = _row_to_dict(row)

    # Check if soft-deleted
    if row_dict["deleted_at"] is not None:
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
    record_runtime_change(
        conn,
        plan_uuid=row_dict["anchor_plan_uuid"],
        entity_type="escalation",
        entity_id=escalation_uuid,
        action="update",
        changed_by=resolved_by,
    )

    # Reconstruct and return the updated escalation
    # Rebuild the row dict for _row_to_record
    # Using the updated values
    anchor_columns = {
        "primary_anchor_type": row_dict["primary_anchor_type"],
        "anchor_project_id": row_dict["anchor_project_id"],
        "anchor_file_path": row_dict["anchor_file_path"],
        "anchor_plan_uuid": row_dict["anchor_plan_uuid"],
        "anchor_revision_uuid": row_dict["anchor_revision_uuid"],
        "anchor_step_uuid": row_dict["anchor_step_uuid"],
        "anchor_step_path": row_dict["anchor_step_path"],
        "anchor_ref_id": row_dict["anchor_ref_id"],
    }
    anchor = anchor_from_columns(anchor_columns)
    routing = routing_from_row(row_dict)

    created_at_val = row_dict["created_at"]
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
        reason=row_dict["reason"],
        from_level=row_dict["from_level"],
        to_level=row_dict["to_level"],
        status="resolved",
        resolution=resolution,
        resolved_by=resolved_by,
        resolved_at=now.isoformat(),
        created_by=row_dict["created_by"],
        created_at=created_at_val.isoformat() if isinstance(created_at_val, datetime) else created_at_val,
        updated_at=now.isoformat(),
        deleted_at=None,
        **routing,
    )


def get_escalation(conn: psycopg.Connection, escalation_uuid: uuid.UUID) -> Escalation | None:
    """Get an escalation by UUID."""
    sql = f"SELECT {_ESCALATION_SELECT_COLUMNS} FROM escalation WHERE uuid = %s"
    cursor = conn.execute(sql, (escalation_uuid,))
    row = cursor.fetchone()

    if row is None:
        return None

    return _row_to_record(_row_to_dict(row))


def list_escalations(conn: psycopg.Connection, *, status: str | None = None,
                     anchor_ref_id: uuid.UUID | None = None,
                     anchor_plan_uuid: uuid.UUID | None = None,
                     anchor_project_id: uuid.UUID | None = None,
                     project_bound_plan_uuids: list[uuid.UUID] | None = None,
                     include_deleted: bool = False) -> list[Escalation]:
    """List escalations with optional filters.

    When anchor_plan_uuid is given, only rows whose anchor_plan_uuid equals it match
    (NULL and foreign plan anchors are excluded; direct equality, no transitivity).

    When anchor_project_id is given, matching is transitive: a row whose own
    anchor_project_id equals it matches directly, OR (when project_bound_plan_uuids is
    a non-empty list of plan uuids bound to that project via plan.project_ids) a row
    whose anchor_plan_uuid is one of those plan uuids also matches, even when the row's
    own anchor_project_id is NULL. project_bound_plan_uuids is ignored when
    anchor_project_id is None.
    """
    # Build the query
    sql_parts = [f"SELECT {_ESCALATION_SELECT_COLUMNS} FROM escalation WHERE 1=1"]
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

    if anchor_project_id is not None:
        if project_bound_plan_uuids:
            sql_parts.append("AND (anchor_project_id = %s OR anchor_plan_uuid = ANY(%s))")
            params.append(anchor_project_id)
            params.append(project_bound_plan_uuids)
        else:
            sql_parts.append("AND anchor_project_id = %s")
            params.append(anchor_project_id)

    if not include_deleted:
        sql_parts.append("AND deleted_at IS NULL")

    sql_parts.append("ORDER BY created_at ASC")

    sql = " ".join(sql_parts)

    cursor = conn.execute(sql, params)
    rows = cursor.fetchall()

    return [_row_to_record(_row_to_dict(row)) for row in rows]
