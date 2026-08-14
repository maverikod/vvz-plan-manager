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


# Explicit read projection for every review_result SELECT in this module. Bug
# 0798c162: SELECT * rows are fragile when tables add columns; selecting
# exactly the columns _row_to_record consumes keeps the row shape pinned to
# the unpack below, immune to future additive columns. _row_to_record itself
# maps this tuple onto ReviewResult by COLUMN NAME (dict(zip(...))), not by
# position, so appending a column here (as migration 0031 did for
# superseded_by_uuid) never requires renumbering existing indices -- the same
# unpack-safety technique plan_manager.storage.execution_attempt_store uses.
_REVIEW_RESULT_SELECT_COLUMNS = """
    uuid, object_type, reviewed_attempt_uuid, reviewed_revision_uuid, reviewer,
    status, findings, evidence, verification_commands, escalation_target_uuid,
    created_by, created_at, updated_at, deleted_at, superseded_by_uuid
"""


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
    # CR-7 G-004 (C-005, C-012): the write is delegated to the unified
    # engine's creation path; this module no longer composes INSERT SQL.
    ReviewResult.crud_create(
        conn,
        {
            "uuid": new_uuid,
            "object_type": object_type,
            "reviewed_attempt_uuid": reviewed_attempt_uuid,
            "reviewed_revision_uuid": reviewed_revision_uuid,
            "reviewer": reviewer,
            "status": status,
            "findings": findings,
            "evidence": evidence_wrapped,
            "verification_commands": verification_commands_wrapped,
            "escalation_target_uuid": escalation_target_uuid,
            "created_by": created_by,
            "created_at": created_at,
            "updated_at": updated_at,
            "deleted_at": deleted_at,
        },
        returning=False,
    )

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
        superseded_by_uuid=None,
    )


def get_review_result(conn: psycopg.Connection, review_uuid: uuid.UUID) -> ReviewResult | None:
    """Fetch a single review result by UUID, or None if not found."""
    sql = f"SELECT {_REVIEW_RESULT_SELECT_COLUMNS} FROM review_result WHERE uuid = %s"
    row = conn.execute(sql, (review_uuid,)).fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_review_results(
    conn: psycopg.Connection, *, reviewed_attempt_uuid: uuid.UUID | None = None,
    status: str | None = None, include_deleted: bool = False,
    plan_uuid: uuid.UUID | None = None,
    project_bound_plan_uuids: list[uuid.UUID] | None = None,
) -> list[ReviewResult]:
    """List review results with optional filtering by reviewed_attempt_uuid and/or status.

    When plan_uuid is given, only review results whose reviewed execution attempt
    belongs to that plan match (semi-join on execution_attempt.plan_uuid); rows with
    reviewed_attempt_uuid NULL (e.g. revision reviews) and rows whose attempt belongs
    to another plan are excluded.

    project_bound_plan_uuids implements the project scope: review_result carries no
    project column of its own (nor does execution_attempt), so project matching is
    purely transitive via execution_attempt.plan_uuid being one of the given plan
    uuids (plans bound to the project via plan.project_ids). Pass None (the default)
    to skip project scoping entirely; pass an empty list to scope by project when
    zero plans are bound to it (yields no matches, since there is no direct project
    column to fall back on).

    Excludes soft-deleted rows (deleted_at IS NOT NULL) unless include_deleted=True.
    Results ordered by created_at ASC.
    """
    conditions = []
    params = []

    if reviewed_attempt_uuid is not None:
        conditions.append("reviewed_attempt_uuid = %s")
        params.append(reviewed_attempt_uuid)

    if plan_uuid is not None:
        conditions.append(
            "EXISTS (SELECT 1 FROM execution_attempt ea "
            "WHERE ea.uuid = review_result.reviewed_attempt_uuid AND ea.plan_uuid = %s)"
        )
        params.append(plan_uuid)

    if project_bound_plan_uuids is not None:
        if project_bound_plan_uuids:
            conditions.append(
                "EXISTS (SELECT 1 FROM execution_attempt ea "
                "WHERE ea.uuid = review_result.reviewed_attempt_uuid AND ea.plan_uuid = ANY(%s))"
            )
            params.append(project_bound_plan_uuids)
        else:
            # project filter active but zero plans are bound to it, and there is no
            # direct project column to match against: no row can possibly match.
            conditions.append("1 = 0")

    if status is not None:
        conditions.append("status = %s")
        params.append(status)

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"SELECT {_REVIEW_RESULT_SELECT_COLUMNS} FROM review_result WHERE {where_clause} ORDER BY created_at ASC"

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


_REVIEW_RESULT_COLUMN_NAMES: tuple[str, ...] = (
    "uuid", "object_type", "reviewed_attempt_uuid", "reviewed_revision_uuid", "reviewer",
    "status", "findings", "evidence", "verification_commands", "escalation_target_uuid",
    "created_by", "created_at", "updated_at", "deleted_at", "superseded_by_uuid",
)


def _row_to_record(row: tuple[Any, ...]) -> ReviewResult:
    """Convert a database row (in _REVIEW_RESULT_SELECT_COLUMNS order) to a ReviewResult dataclass instance.

    Bug 0798c162 unpack-safety: the row is first zipped into a dict keyed by
    _REVIEW_RESULT_COLUMN_NAMES (the exact same order the SELECT above uses),
    then read back out BY NAME below -- never by positional index -- so a
    future migration that appends another column here (as 0031 already did
    for superseded_by_uuid) cannot silently shift every field one slot to the
    right. Mirrors plan_manager.storage.execution_attempt_store._row_to_record.

    Converts:
    - UUID columns (uuid, reviewed_attempt_uuid, reviewed_revision_uuid,
      escalation_target_uuid, superseded_by_uuid): uuid.UUID or None (psycopg3
      returns these natively)
    - Timestamp columns (created_at, updated_at, deleted_at): ISO format
      strings (or None for deleted_at if NULL)
    - JSONB columns (evidence, verification_commands): Python dict/list or
      None (already deserialized by psycopg3)
    """
    data = dict(zip(_REVIEW_RESULT_COLUMN_NAMES, row))
    return ReviewResult(
        review_uuid=data["uuid"],
        object_type=data["object_type"],
        reviewed_attempt_uuid=data["reviewed_attempt_uuid"],
        reviewed_revision_uuid=data["reviewed_revision_uuid"],
        reviewer=data["reviewer"],
        status=data["status"],
        findings=data["findings"],
        evidence=data["evidence"],
        verification_commands=data["verification_commands"],
        escalation_target_uuid=data["escalation_target_uuid"],
        created_by=data["created_by"],
        created_at=data["created_at"].isoformat(),
        updated_at=data["updated_at"].isoformat(),
        deleted_at=data["deleted_at"].isoformat() if data["deleted_at"] is not None else None,
        superseded_by_uuid=data["superseded_by_uuid"],
    )
