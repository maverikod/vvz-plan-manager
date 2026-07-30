"""Bug fix persistence: create/update/verify/revert fix attempts over bug_fix with audit + soft delete (C-024)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from psycopg.types.json import Jsonb
from plan_manager.domain.bug_fix import (
    BugFix, BUG_FIX_TYPES, BUG_FIX_STATUSES, validate_fix_type, validate_fix_status,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: dict[str, Any] | tuple[Any, ...]) -> BugFix:
    """Build a BugFix from a DB row dict or tuple in bug_fix table column order.

    crud_* methods return dicts with column names as keys; legacy tuple-based
    callers (if any) are still supported by dict-conversion.
    """
    if isinstance(row, dict):
        return BugFix(
            fix_uuid=row["uuid"],
            bug_uuid=row["bug_uuid"],
            status=row["status"],
            fix_type=row["fix_type"],
            summary=row["summary"],
            implementation_notes=row["implementation_notes"],
            source_project_id=row["source_project_id"],
            branch=row["branch"],
            commit_hash=row["commit_hash"],
            pull_request=row["pull_request"],
            changed_files=row["changed_files"],
            tests=row["tests"],
            author=row["author"],
            reviewer=row["reviewer"],
            started_at=row["started_at"].isoformat() if row["started_at"] is not None else None,
            implemented_at=row["implemented_at"].isoformat() if row["implemented_at"] is not None else None,
            verified_at=row["verified_at"].isoformat() if row["verified_at"] is not None else None,
            verification_method=row["verification_method"],
            expected_result=row["expected_result"],
            actual_result=row["actual_result"],
            passed=row["passed"],
            revert_info=row["revert_info"],
            created_by=row["created_by"],
            # Bug 4375c341: the guard used to test for `str`, so a real psycopg
            # datetime fell through unconverted into a field annotated `str`, and
            # order_queue later compared it against every other source's ISO
            # string. Test for `datetime` — the shape every other store here uses.
            created_at=row["created_at"].isoformat() if isinstance(row["created_at"], datetime) else row["created_at"],
            updated_at=row["updated_at"].isoformat() if isinstance(row["updated_at"], datetime) else row["updated_at"],
            deleted_at=row["deleted_at"].isoformat() if row["deleted_at"] is not None else None,
        )
    else:
        # Legacy tuple support
        (uuid_val, bug_uuid_val, status_val, fix_type_val, summary_val, implementation_notes_val,
         source_project_id_val, branch_val, commit_hash_val, pull_request_val, changed_files_val,
         tests_val, author_val, reviewer_val, started_at_val, implemented_at_val, verified_at_val,
         verification_method_val, expected_result_val, actual_result_val, passed_val, revert_info_val,
         created_by_val, created_at_val, updated_at_val, deleted_at_val) = row
        return BugFix(
            fix_uuid=uuid_val,
            bug_uuid=bug_uuid_val,
            status=status_val,
            fix_type=fix_type_val,
            summary=summary_val,
            implementation_notes=implementation_notes_val,
            source_project_id=source_project_id_val,
            branch=branch_val,
            commit_hash=commit_hash_val,
            pull_request=pull_request_val,
            changed_files=changed_files_val,
            tests=tests_val,
            author=author_val,
            reviewer=reviewer_val,
            started_at=started_at_val.isoformat() if started_at_val is not None else None,
            implemented_at=implemented_at_val.isoformat() if implemented_at_val is not None else None,
            verified_at=verified_at_val.isoformat() if verified_at_val is not None else None,
            verification_method=verification_method_val,
            expected_result=expected_result_val,
            actual_result=actual_result_val,
            passed=passed_val,
            revert_info=revert_info_val,
            created_by=created_by_val,
            created_at=created_at_val.isoformat(),
            updated_at=updated_at_val.isoformat(),
            deleted_at=deleted_at_val.isoformat() if deleted_at_val is not None else None,
        )


def create_bug_fix(conn: psycopg.Connection, *, bug_uuid: uuid.UUID, fix_type: str, summary: str, author: str,
                   created_by: str, status: str = "proposed", implementation_notes: str | None = None,
                   source_project_id: uuid.UUID | None = None, branch: str | None = None,
                   commit_hash: str | None = None, pull_request: str | None = None,
                   changed_files: list[Any] | None = None, tests: list[Any] | None = None,
                   reviewer: str | None = None, verification_method: str | None = None,
                   expected_result: str | None = None) -> BugFix:
    """Create a new bug fix record."""
    validate_fix_type(fix_type)
    validate_fix_status(status)
    check_row_exists(conn, "bug_report", bug_uuid, frozenset({"bug_report"}))
    fix_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    started_at = now if status == "in_progress" else None
    # Stamp implemented_at at creation when a fix is created already in the
    # implemented state, mirroring update_bug_fix which stamps it on the
    # transition to "implemented"; otherwise the timestamp would stay null.
    implemented_at = now if status == "implemented" else None
    row = BugFix.crud_create(
        conn,
        {
            "uuid": fix_uuid,
            "bug_uuid": bug_uuid,
            "status": status,
            "fix_type": fix_type,
            "summary": summary,
            "implementation_notes": implementation_notes,
            "source_project_id": source_project_id,
            "branch": branch,
            "commit_hash": commit_hash,
            "pull_request": pull_request,
            # jsonb columns: psycopg cannot adapt a bare list/dict, and crud_*
            # passes values through as bind parameters unchanged.
            "changed_files": Jsonb(changed_files) if changed_files is not None else None,
            "tests": Jsonb(tests) if tests is not None else None,
            "author": author,
            "reviewer": reviewer,
            "started_at": started_at,
            "implemented_at": implemented_at,
            "verification_method": verification_method,
            "expected_result": expected_result,
            "revert_info": None,
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        },
    )
    if row is None:
        raise RuntimeError(f"failed to create bug fix {fix_uuid}")
    record_runtime_change(conn, plan_uuid=None, entity_type="bug_fix", entity_id=fix_uuid, action="create", changed_by=created_by)
    return _row_to_record(row)


def get_bug_fix(conn: psycopg.Connection, fix_uuid: uuid.UUID) -> BugFix | None:
    """Retrieve a bug fix record by UUID."""
    row = BugFix.crud_get(conn, fix_uuid, include_deleted=True)
    if row is None:
        return None
    return _row_to_record(row)


def list_bug_fixes(conn: psycopg.Connection, *, bug_uuid: uuid.UUID | None = None, status: str | None = None,
                   include_deleted: bool = False) -> list[BugFix]:
    """List bug fix records with optional filtering."""
    filters = {}
    if bug_uuid is not None:
        filters["bug_uuid"] = bug_uuid
    if status is not None:
        filters["status"] = status
    rows = BugFix.crud_list(
        conn,
        filters=filters if filters else None,
        include_deleted=include_deleted,
        order_by=("created_at",),
    )
    return [_row_to_record(row) for row in rows]


def update_bug_fix(conn: psycopg.Connection, fix_uuid: uuid.UUID, *, changed_by: str, status: str | None = None,
                   implementation_notes: str | None = None, branch: str | None = None,
                   commit_hash: str | None = None, pull_request: str | None = None,
                   changed_files: list[Any] | None = None, tests: list[Any] | None = None,
                   reviewer: str | None = None, summary: str | None = None) -> BugFix:
    """Update a bug fix record."""
    now = datetime.now(timezone.utc)
    values = {}
    if status is not None:
        validate_fix_status(status)
        values["status"] = status
        if status == "in_progress":
            # Stamp started_at on the transition into in_progress, mirroring the
            # implemented_at stamp below and create_bug_fix's started_at stamp;
            # otherwise a fix that begins life as "proposed" and is later moved
            # to in_progress would keep a null started_at.
            values["started_at"] = now
        if status == "implemented":
            values["implemented_at"] = now
    if summary is not None:
        values["summary"] = summary
    if implementation_notes is not None:
        values["implementation_notes"] = implementation_notes
    if branch is not None:
        values["branch"] = branch
    if commit_hash is not None:
        values["commit_hash"] = commit_hash
    if pull_request is not None:
        values["pull_request"] = pull_request
    if changed_files is not None:
        # jsonb column: wrap here, crud_update binds the value unchanged.
        values["changed_files"] = Jsonb(changed_files)
    if tests is not None:
        values["tests"] = Jsonb(tests)
    if reviewer is not None:
        values["reviewer"] = reviewer
    values["updated_at"] = now
    row = BugFix.crud_update(conn, fix_uuid, values)
    if row is None:
        raise RuntimeError(f"failed to update bug fix {fix_uuid}")
    record_runtime_change(conn, plan_uuid=None, entity_type="bug_fix", entity_id=fix_uuid, action="update", changed_by=changed_by)
    return _row_to_record(row)


def verify_bug_fix(conn: psycopg.Connection, fix_uuid: uuid.UUID, *, changed_by: str, passed: bool,
                   verification_method: str | None = None, actual_result: str | None = None) -> BugFix:
    """Verify a bug fix and record the result."""
    now = datetime.now(timezone.utc)
    new_status = "verified" if passed else "failed"
    updates = [
        "status = %s",
        "verified_at = %s",
        "passed = %s",
        "updated_at = %s",
    ]
    params = [new_status, now, passed, now]
    if verification_method is not None:
        updates.append("verification_method = %s")
        params.append(verification_method)
    if actual_result is not None:
        updates.append("actual_result = %s")
        params.append(actual_result)
    params.append(fix_uuid)
    update_clause = ", ".join(updates)
    sql = f"UPDATE bug_fix SET {update_clause} WHERE uuid = %s RETURNING *"
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    record_runtime_change(conn, plan_uuid=None, entity_type="bug_fix", entity_id=fix_uuid, action="update", changed_by=changed_by)
    return _row_to_record(row)


def revert_bug_fix(conn: psycopg.Connection, fix_uuid: uuid.UUID, *, changed_by: str, revert_info: dict[str, Any]) -> BugFix:
    """Revert a bug fix."""
    now = datetime.now(timezone.utc)
    sql = """
    UPDATE bug_fix
    SET status = %s, revert_info = %s, updated_at = %s
    WHERE uuid = %s
    RETURNING *
    """
    params = ("reverted", Jsonb(revert_info), now, fix_uuid)
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    record_runtime_change(conn, plan_uuid=None, entity_type="bug_fix", entity_id=fix_uuid, action="update", changed_by=changed_by)
    return _row_to_record(row)


def soft_delete_bug_fix(conn: psycopg.Connection, fix_uuid: uuid.UUID, *, changed_by: str) -> BugFix:
    """Soft delete a bug fix."""
    now = datetime.now(timezone.utc)
    row = BugFix.crud_soft_delete(conn, fix_uuid, deleted_at=now, updated_at=now)
    if row is None:
        raise RuntimeError(f"failed to soft delete bug fix {fix_uuid}")
    record_runtime_change(conn, plan_uuid=None, entity_type="bug_fix", entity_id=fix_uuid, action="soft_delete", changed_by=changed_by)
    return _row_to_record(row)
