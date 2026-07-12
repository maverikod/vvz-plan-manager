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


def _row_to_record(row: tuple[Any, ...]) -> BugFix:
    """Build a BugFix from a raw DB row tuple in bug_fix table column order."""
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
    sql = """
    INSERT INTO bug_fix (
        uuid, bug_uuid, status, fix_type, summary, implementation_notes,
        source_project_id, branch, commit_hash, pull_request, changed_files, tests,
        author, reviewer, started_at, implemented_at, verified_at, verification_method,
        expected_result, actual_result, passed, revert_info,
        created_by, created_at, updated_at, deleted_at
    ) VALUES (
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s, %s, %s,
        %s, %s, %s, %s,
        %s, %s, %s, %s
    )
    RETURNING *
    """
    params = (
        fix_uuid, bug_uuid, status, fix_type, summary, implementation_notes,
        source_project_id, branch, commit_hash, pull_request,
        Jsonb(changed_files) if changed_files is not None else None,
        Jsonb(tests) if tests is not None else None,
        author, reviewer, started_at, implemented_at, None, verification_method,
        expected_result, None, None, None,
        created_by, now, now, None,
    )
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    record_runtime_change(conn, plan_uuid=None, entity_type="bug_fix", entity_id=fix_uuid, action="create", changed_by=created_by)
    return _row_to_record(row)


def get_bug_fix(conn: psycopg.Connection, fix_uuid: uuid.UUID) -> BugFix | None:
    """Retrieve a bug fix record by UUID."""
    sql = "SELECT * FROM bug_fix WHERE uuid = %s"
    cursor = conn.execute(sql, (fix_uuid,))
    row = cursor.fetchone()
    if row is None:
        return None
    return _row_to_record(row)


def list_bug_fixes(conn: psycopg.Connection, *, bug_uuid: uuid.UUID | None = None, status: str | None = None,
                   include_deleted: bool = False) -> list[BugFix]:
    """List bug fix records with optional filtering."""
    conditions = []
    params = []
    if bug_uuid is not None:
        conditions.append("bug_uuid = %s")
        params.append(bug_uuid)
    if status is not None:
        conditions.append("status = %s")
        params.append(status)
    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    where_clause = " AND ".join(conditions) if conditions else "1=1"
    sql = f"SELECT * FROM bug_fix WHERE {where_clause} ORDER BY created_at ASC"
    cursor = conn.execute(sql, params)
    return [_row_to_record(row) for row in cursor.fetchall()]


def update_bug_fix(conn: psycopg.Connection, fix_uuid: uuid.UUID, *, changed_by: str, status: str | None = None,
                   implementation_notes: str | None = None, branch: str | None = None,
                   commit_hash: str | None = None, pull_request: str | None = None,
                   changed_files: list[Any] | None = None, tests: list[Any] | None = None,
                   reviewer: str | None = None, summary: str | None = None) -> BugFix:
    """Update a bug fix record."""
    now = datetime.now(timezone.utc)
    updates = []
    params = []
    if status is not None:
        validate_fix_status(status)
        updates.append("status = %s")
        params.append(status)
        if status == "implemented":
            updates.append("implemented_at = %s")
            params.append(now)
    if summary is not None:
        updates.append("summary = %s")
        params.append(summary)
    if implementation_notes is not None:
        updates.append("implementation_notes = %s")
        params.append(implementation_notes)
    if branch is not None:
        updates.append("branch = %s")
        params.append(branch)
    if commit_hash is not None:
        updates.append("commit_hash = %s")
        params.append(commit_hash)
    if pull_request is not None:
        updates.append("pull_request = %s")
        params.append(pull_request)
    if changed_files is not None:
        updates.append("changed_files = %s")
        params.append(Jsonb(changed_files))
    if tests is not None:
        updates.append("tests = %s")
        params.append(Jsonb(tests))
    if reviewer is not None:
        updates.append("reviewer = %s")
        params.append(reviewer)
    updates.append("updated_at = %s")
    params.append(now)
    params.append(fix_uuid)
    update_clause = ", ".join(updates)
    sql = f"UPDATE bug_fix SET {update_clause} WHERE uuid = %s RETURNING *"
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
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
    sql = """
    UPDATE bug_fix
    SET deleted_at = %s, updated_at = %s
    WHERE uuid = %s
    RETURNING *
    """
    params = (now, now, fix_uuid)
    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    record_runtime_change(conn, plan_uuid=None, entity_type="bug_fix", entity_id=fix_uuid, action="soft_delete", changed_by=changed_by)
    return _row_to_record(row)
