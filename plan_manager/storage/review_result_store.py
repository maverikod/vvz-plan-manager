"""Review result persistence: create/list review outcomes over review_result with audit + soft delete (C-018)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from psycopg.types.json import Jsonb
from plan_manager.domain.review_result import (
    ReviewResult, REVIEW_OBJECT_TYPES, REVIEW_STATUSES,
    validate_review_object_type, validate_review_status,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


def create_review_result(
    conn: psycopg.Connection, *, object_type: str, reviewer: str, status: str, created_by: str,
    reviewed_attempt_uuid: uuid.UUID | None = None, reviewed_revision_uuid: uuid.UUID | None = None,
    findings: str | None = None, evidence: dict[str, Any] | None = None,
    verification_commands: list[Any] | None = None, escalation_target_uuid: uuid.UUID | None = None,
) -> ReviewResult:
    """Create a review result record with validation, persistence, and audit logging."""
    # Validate object_type and status
    validate_review_object_type(object_type)
    validate_review_status(status)

    # Validate and check reviewed object UUID based on object_type
    if object_type == "execution_attempt":
        if reviewed_attempt_uuid is None:
            raise RuntimeValidationError("reviewed_attempt_uuid is required when object_type is execution_attempt")
        check_row_exists(conn, "execution_attempt", reviewed_attempt_uuid, frozenset({"execution_attempt"}))
    elif object_type == "revision":
        if reviewed_revision_uuid is None:
            raise RuntimeValidationError("reviewed_revision_uuid is required when object_type is revision")
        check_row_exists(conn, "revision", reviewed_revision_uuid, frozenset({"revision"}))

    # Validate escalation target if provided
    if escalation_target_uuid is not None:
        check_row_exists(conn, "escalation", escalation_target_uuid, frozenset({"escalation"}))

    # Generate UUID and timestamps
    new_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    created_at = updated_at = now
    deleted_at = None

    # Wrap jsonb fields
    evidence_wrapped = Jsonb(evidence) if evidence is not None else None
    verification_commands_wrapped = Jsonb(verification_commands) if verification_commands is not None else None

    # INSERT into review_result table
    sql = """
    INSERT INTO review_result (
        uuid, object_type, reviewed_attempt_uuid, reviewed_revision_uuid,
        reviewer, status, findings, evidence, verification_commands,
        escalation_target_uuid, created_by, created_at, updated_at, deleted_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
    )
    """
    params = (
        new_uuid, object_type, reviewed_attempt_uuid, reviewed_revision_uuid,
        reviewer, status, findings, evidence_wrapped, verification_commands_wrapped,
        escalation_target_uuid, created_by, created_at, updated_at, deleted_at
    )
    conn.execute(sql, params)

    # Record audit change
    record_runtime_change(
        conn,
        plan_uuid=None,
        entity_type="review_result",
        entity_id=new_uuid,
        action="create",
        changed_by=created_by,
        linked_attempt_id=reviewed_attempt_uuid,
        linked_review_id=new_uuid,
    )

    # Return ReviewResult with unwrapped jsonb values and ISO-formatted timestamps
    return ReviewResult(
        review_uuid=new_uuid,
        object_type=object_type,
        reviewed_attempt_uuid=reviewed_attempt_uuid,
        reviewed_revision_uuid=reviewed_revision_uuid,
        reviewer=reviewer,
        status=status,
        findings=findings,
        evidence=evidence,
        verification_commands=verification_commands,
        escalation_target_uuid=escalation_target_uuid,
        created_by=created_by,
        created_at=created_at.isoformat(),
        updated_at=updated_at.isoformat(),
        deleted_at=None,
    )


def get_review_result(conn: psycopg.Connection, review_uuid: uuid.UUID) -> ReviewResult | None:
    """Fetch a single review result by UUID, or None if not found."""
    sql = "SELECT * FROM review_result WHERE uuid = %s"
    row = conn.execute(sql, (review_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_review_results(
    conn: psycopg.Connection, *, reviewed_attempt_uuid: uuid.UUID | None = None,
    status: str | None = None, include_deleted: bool = False,
) -> list[ReviewResult]:
    """List review results with optional filtering by reviewed_attempt_uuid and/or status.

    Excludes soft-deleted rows (deleted_at IS NOT NULL) unless include_deleted=True.
    Results ordered by created_at ASC.
    """
    conditions = []
    params = []

    if reviewed_attempt_uuid is not None:
        conditions.append("reviewed_attempt_uuid = %s")
        params.append(reviewed_attempt_uuid)

    if status is not None:
        conditions.append("status = %s")
        params.append(status)

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"SELECT * FROM review_result WHERE {where_clause} ORDER BY created_at ASC"

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def _row_to_record(row: Any) -> ReviewResult:
    """Convert a database row tuple to a ReviewResult dataclass instance.

    Row columns (in table order):
    0: uuid, 1: object_type, 2: reviewed_attempt_uuid, 3: reviewed_revision_uuid,
    4: reviewer, 5: status, 6: findings, 7: evidence, 8: verification_commands,
    9: escalation_target_uuid, 10: created_by, 11: created_at, 12: updated_at, 13: deleted_at

    Converts:
    - UUID columns (0,2,3,9): uuid.UUID or None (psycopg3 returns these natively)
    - Timestamp columns (11,12,13): ISO format strings (or None for deleted_at if NULL)
    - JSONB columns (7,8): Python dict/list or None (already deserialized by psycopg3)
    """
    return ReviewResult(
        review_uuid=row[0],
        object_type=row[1],
        reviewed_attempt_uuid=row[2],
        reviewed_revision_uuid=row[3],
        reviewer=row[4],
        status=row[5],
        findings=row[6],
        evidence=row[7],
        verification_commands=row[8],
        escalation_target_uuid=row[9],
        created_by=row[10],
        created_at=row[11].isoformat(),
        updated_at=row[12].isoformat(),
        deleted_at=row[13].isoformat() if row[13] is not None else None,
    )
