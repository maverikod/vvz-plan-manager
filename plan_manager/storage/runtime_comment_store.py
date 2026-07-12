"""Runtime comment persistence: append-oriented add/supersede/resolve over runtime_comment with audit + soft delete (C-014)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from plan_manager.domain.runtime_comment import (
    RuntimeComment, COMMENT_KINDS, validate_comment_kind,
    COMMENT_ANCHOR_TYPES, validate_comment_anchor_type,
)
from plan_manager.domain.comment_visibility import VISIBILITY_MODES, validate_visibility
from plan_manager.domain.primary_anchor import PrimaryAnchor, validate_anchor, anchor_to_columns, anchor_from_columns
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: tuple | list) -> RuntimeComment:
    """Convert a database row tuple to RuntimeComment dataclass."""
    (uuid_val, primary_anchor_type, anchor_project_id, anchor_file_path,
     anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
     anchor_ref_id, kind, visibility, author, body, resolved,
     supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at) = row

    return RuntimeComment(
        comment_uuid=uuid_val,
        primary_anchor_type=primary_anchor_type,
        anchor_project_id=anchor_project_id,
        anchor_file_path=anchor_file_path,
        anchor_plan_uuid=anchor_plan_uuid,
        anchor_revision_uuid=anchor_revision_uuid,
        anchor_step_uuid=anchor_step_uuid,
        anchor_step_path=anchor_step_path,
        anchor_ref_id=anchor_ref_id,
        kind=kind,
        visibility=visibility,
        author=author,
        body=body,
        resolved=resolved,
        supersedes_comment_uuid=supersedes_comment_uuid,
        created_by=created_by,
        created_at=created_at.isoformat() if created_at else None,
        updated_at=updated_at.isoformat() if updated_at else None,
        deleted_at=deleted_at.isoformat() if deleted_at else None,
    )


def add_comment(
    conn: psycopg.Connection,
    *,
    anchor: PrimaryAnchor,
    kind: str,
    visibility: str,
    author: str,
    body: str,
    created_by: str,
    resolved: bool | None = None,
    supersedes_comment_uuid: uuid.UUID | None = None,
) -> RuntimeComment:
    """Create a new runtime comment, optionally superseding a prior comment."""
    # Validate inputs
    validate_comment_kind(kind)
    validate_visibility(visibility)
    validate_comment_anchor_type(anchor.anchor_type)

    # Anchor-type-specific validation
    if anchor.anchor_type == "escalation":
        # Escalation requires a ref_id
        if anchor.ref_id is None:
            raise RuntimeValidationError("escalation anchor requires ref_id")
        # Check escalation row exists
        check_row_exists(conn, "escalation", anchor.ref_id, frozenset({"escalation"}))
    else:
        # All other 10 types use standard anchor validation
        validate_anchor(conn, anchor)

    # If superseding, check old comment exists
    if supersedes_comment_uuid is not None:
        check_row_exists(conn, "runtime_comment", supersedes_comment_uuid, frozenset({"runtime_comment"}))

    # Generate new comment UUID and timestamp
    comment_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Flatten anchor to columns
    anchor_cols = anchor_to_columns(anchor)

    # Insert the comment
    sql = """
    INSERT INTO runtime_comment
    (uuid, primary_anchor_type, anchor_project_id, anchor_file_path,
     anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
     anchor_ref_id, kind, visibility, author, body, resolved,
     supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at)
    VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING uuid, primary_anchor_type, anchor_project_id, anchor_file_path,
              anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
              anchor_ref_id, kind, visibility, author, body, resolved,
              supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at
    """

    params = (
        comment_uuid,
        anchor_cols["primary_anchor_type"],
        anchor_cols["anchor_project_id"],
        anchor_cols["anchor_file_path"],
        anchor_cols["anchor_plan_uuid"],
        anchor_cols["anchor_revision_uuid"],
        anchor_cols["anchor_step_uuid"],
        anchor_cols["anchor_step_path"],
        anchor_cols["anchor_ref_id"],
        kind,
        visibility,
        author,
        body,
        resolved,
        supersedes_comment_uuid,
        created_by,
        now,
        now,
        None,
    )

    row = conn.execute(sql, params).fetchone()

    # Record audit
    record_runtime_change(
        conn,
        plan_uuid=anchor_cols["anchor_plan_uuid"],
        entity_type="runtime_comment",
        entity_id=comment_uuid,
        action="create",
        changed_by=created_by,
    )

    return _row_to_record(row)


def get_comment(conn: psycopg.Connection, comment_uuid: uuid.UUID) -> RuntimeComment | None:
    """Retrieve a comment by UUID, or None if not found or soft-deleted."""
    sql = """
    SELECT uuid, primary_anchor_type, anchor_project_id, anchor_file_path,
           anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
           anchor_ref_id, kind, visibility, author, body, resolved,
           supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at
    FROM runtime_comment
    WHERE uuid = %s AND deleted_at IS NULL
    """

    row = conn.execute(sql, (comment_uuid,)).fetchone()
    return _row_to_record(row) if row else None


def list_comments(
    conn: psycopg.Connection,
    *,
    anchor_plan_uuid: uuid.UUID | None = None,
    anchor_step_uuid: uuid.UUID | None = None,
    anchor_ref_id: uuid.UUID | None = None,
    visibility: str | None = None,
    include_deleted: bool = False,
) -> list[RuntimeComment]:
    """List comments matching the given filters, ordered by creation time."""
    conditions = []
    params = []

    if anchor_plan_uuid is not None:
        conditions.append("anchor_plan_uuid = %s")
        params.append(anchor_plan_uuid)

    if anchor_step_uuid is not None:
        conditions.append("anchor_step_uuid = %s")
        params.append(anchor_step_uuid)

    if anchor_ref_id is not None:
        conditions.append("anchor_ref_id = %s")
        params.append(anchor_ref_id)

    if visibility is not None:
        conditions.append("visibility = %s")
        params.append(visibility)

    if not include_deleted:
        conditions.append("deleted_at IS NULL")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    sql = f"""
    SELECT uuid, primary_anchor_type, anchor_project_id, anchor_file_path,
           anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
           anchor_ref_id, kind, visibility, author, body, resolved,
           supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at
    FROM runtime_comment
    WHERE {where_clause}
    ORDER BY created_at ASC
    """

    rows = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in rows]


def supersede_comment(
    conn: psycopg.Connection,
    comment_uuid: uuid.UUID,
    *,
    new_body: str,
    changed_by: str,
) -> RuntimeComment:
    """Create a new comment superseding an existing one (append-oriented history)."""
    # Load the existing comment
    existing = get_comment(conn, comment_uuid)
    if existing is None:
        raise RuntimeValidationError(f"Cannot supersede: comment {comment_uuid} not found or is soft-deleted")

    # Create new UUID and timestamp
    new_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)

    # Insert new comment row, copying all fields except body and uuid
    sql = """
    INSERT INTO runtime_comment
    (uuid, primary_anchor_type, anchor_project_id, anchor_file_path,
     anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
     anchor_ref_id, kind, visibility, author, body, resolved,
     supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at)
    VALUES
    (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    RETURNING uuid, primary_anchor_type, anchor_project_id, anchor_file_path,
              anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
              anchor_ref_id, kind, visibility, author, body, resolved,
              supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at
    """

    params = (
        new_uuid,
        existing.primary_anchor_type,
        existing.anchor_project_id,
        existing.anchor_file_path,
        existing.anchor_plan_uuid,
        existing.anchor_revision_uuid,
        existing.anchor_step_uuid,
        existing.anchor_step_path,
        existing.anchor_ref_id,
        existing.kind,
        existing.visibility,
        existing.author,
        new_body,
        existing.resolved,
        existing.comment_uuid,  # New comment supersedes the old one
        changed_by,
        now,
        now,
        None,
    )

    row = conn.execute(sql, params).fetchone()

    # Record audit
    record_runtime_change(
        conn,
        plan_uuid=existing.anchor_plan_uuid,
        entity_type="runtime_comment",
        entity_id=new_uuid,
        action="create",
        changed_by=changed_by,
    )

    return _row_to_record(row)


def resolve_comment(
    conn: psycopg.Connection,
    comment_uuid: uuid.UUID,
    *,
    changed_by: str,
) -> RuntimeComment:
    """Mark a comment as resolved."""
    # Load existing comment
    existing = get_comment(conn, comment_uuid)
    if existing is None:
        raise RuntimeValidationError(f"Cannot resolve: comment {comment_uuid} not found or is soft-deleted")

    now = datetime.now(timezone.utc)

    sql = """
    UPDATE runtime_comment
    SET resolved = true, updated_at = %s
    WHERE uuid = %s
    RETURNING uuid, primary_anchor_type, anchor_project_id, anchor_file_path,
              anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
              anchor_ref_id, kind, visibility, author, body, resolved,
              supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at
    """

    row = conn.execute(sql, (now, comment_uuid)).fetchone()

    # Record audit
    record_runtime_change(
        conn,
        plan_uuid=existing.anchor_plan_uuid,
        entity_type="runtime_comment",
        entity_id=comment_uuid,
        action="update",
        changed_by=changed_by,
    )

    return _row_to_record(row)


def soft_delete_comment(
    conn: psycopg.Connection,
    comment_uuid: uuid.UUID,
    *,
    changed_by: str,
) -> RuntimeComment:
    """Soft-delete a comment by setting deleted_at timestamp."""
    # Load existing comment
    existing = get_comment(conn, comment_uuid)
    if existing is None:
        raise RuntimeValidationError(f"Cannot delete: comment {comment_uuid} not found or is already soft-deleted")

    now = datetime.now(timezone.utc)

    sql = """
    UPDATE runtime_comment
    SET deleted_at = %s, updated_at = %s
    WHERE uuid = %s
    RETURNING uuid, primary_anchor_type, anchor_project_id, anchor_file_path,
              anchor_plan_uuid, anchor_revision_uuid, anchor_step_uuid, anchor_step_path,
              anchor_ref_id, kind, visibility, author, body, resolved,
              supersedes_comment_uuid, created_by, created_at, updated_at, deleted_at
    """

    row = conn.execute(sql, (now, now, comment_uuid)).fetchone()

    # Record audit
    record_runtime_change(
        conn,
        plan_uuid=existing.anchor_plan_uuid,
        entity_type="runtime_comment",
        entity_id=comment_uuid,
        action="soft_delete",
        changed_by=changed_by,
    )

    return _row_to_record(row)
