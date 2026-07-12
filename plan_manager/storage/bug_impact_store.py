"""Bug impact persistence: create/update/list one-affected-object records over bug_impact with audit + soft delete (C-022)."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Any
import psycopg
from psycopg.types.json import Jsonb
from plan_manager.domain.bug_impact import (
    BugImpact, BUG_IMPACT_TARGET_TYPES, BUG_IMPACT_TYPES, BUG_IMPACT_STATUSES,
    validate_impact_target_type, validate_impact_type, validate_impact_status,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change


def _row_to_record(row: tuple[Any, ...]) -> BugImpact:
    """Convert a database row to a BugImpact record."""
    (uuid_val, bug_uuid, target_type, target_project_id, target_file_path,
     target_plan_uuid, target_revision_uuid, target_step_uuid, target_step_path,
     target_ref_id, target_identifier, impact_type, status, reason, skip_decided_by,
     discovery_method, resolution_evidence, created_by, created_at, updated_at,
     resolved_at, deleted_at) = row

    return BugImpact(
        impact_uuid=uuid_val,
        bug_uuid=bug_uuid,
        target_type=target_type,
        target_project_id=target_project_id,
        target_file_path=target_file_path,
        target_plan_uuid=target_plan_uuid,
        target_revision_uuid=target_revision_uuid,
        target_step_uuid=target_step_uuid,
        target_step_path=target_step_path,
        target_ref_id=target_ref_id,
        target_identifier=target_identifier,
        impact_type=impact_type,
        status=status,
        reason=reason,
        skip_decided_by=skip_decided_by,
        discovery_method=discovery_method,
        resolution_evidence=resolution_evidence,
        created_by=created_by,
        created_at=created_at.isoformat(),
        updated_at=updated_at.isoformat(),
        resolved_at=resolved_at.isoformat() if resolved_at is not None else None,
        deleted_at=deleted_at.isoformat() if deleted_at is not None else None,
    )


def create_bug_impact(conn: psycopg.Connection, *, bug_uuid: uuid.UUID, target_type: str, impact_type: str,
                      created_by: str, status: str = "suspected", reason: str | None = None,
                      discovery_method: str | None = None, target_project_id: uuid.UUID | None = None,
                      target_file_path: str | None = None, target_plan_uuid: uuid.UUID | None = None,
                      target_revision_uuid: uuid.UUID | None = None, target_step_uuid: uuid.UUID | None = None,
                      target_step_path: str | None = None, target_ref_id: uuid.UUID | None = None,
                      target_identifier: str | None = None, skip_decided_by: str | None = None) -> BugImpact:
    """Create a new bug impact record."""
    validate_impact_target_type(target_type)
    validate_impact_type(impact_type)
    validate_impact_status(status)

    if status == "skipped":
        if not reason or not isinstance(reason, str) or not reason.strip():
            raise RuntimeValidationError("status 'skipped' requires a non-empty reason string")
        if not skip_decided_by or not isinstance(skip_decided_by, str) or not skip_decided_by.strip():
            raise RuntimeValidationError("status 'skipped' requires a non-empty skip_decided_by string")

    check_row_exists(conn, "bug_report", bug_uuid, frozenset({"bug_report"}))

    impact_uuid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    created_at = updated_at = now
    resolved_at = None
    deleted_at = None

    sql = """
        INSERT INTO bug_impact (
            uuid, bug_uuid, target_type, target_project_id, target_file_path,
            target_plan_uuid, target_revision_uuid, target_step_uuid, target_step_path,
            target_ref_id, target_identifier, impact_type, status, reason,
            skip_decided_by, discovery_method, resolution_evidence, created_by,
            created_at, updated_at, resolved_at, deleted_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        )
    """
    params = (
        impact_uuid, bug_uuid, target_type, target_project_id, target_file_path,
        target_plan_uuid, target_revision_uuid, target_step_uuid, target_step_path,
        target_ref_id, target_identifier, impact_type, status, reason,
        skip_decided_by, discovery_method, None,
        created_by, created_at, updated_at, resolved_at, deleted_at
    )
    conn.execute(sql, params)

    record_runtime_change(conn, plan_uuid=target_plan_uuid, entity_type="bug_impact",
                         entity_id=impact_uuid, action="create", changed_by=created_by)

    return BugImpact(
        impact_uuid=impact_uuid,
        bug_uuid=bug_uuid,
        target_type=target_type,
        target_project_id=target_project_id,
        target_file_path=target_file_path,
        target_plan_uuid=target_plan_uuid,
        target_revision_uuid=target_revision_uuid,
        target_step_uuid=target_step_uuid,
        target_step_path=target_step_path,
        target_ref_id=target_ref_id,
        target_identifier=target_identifier,
        impact_type=impact_type,
        status=status,
        reason=reason,
        skip_decided_by=skip_decided_by,
        discovery_method=discovery_method,
        resolution_evidence=None,
        created_by=created_by,
        created_at=created_at.isoformat(),
        updated_at=updated_at.isoformat(),
        resolved_at=None,
        deleted_at=None,
    )


def get_bug_impact(conn: psycopg.Connection, impact_uuid: uuid.UUID) -> BugImpact | None:
    """Retrieve a bug impact record by UUID."""
    sql = """
        SELECT uuid, bug_uuid, target_type, target_project_id, target_file_path,
               target_plan_uuid, target_revision_uuid, target_step_uuid, target_step_path,
               target_ref_id, target_identifier, impact_type, status, reason, skip_decided_by,
               discovery_method, resolution_evidence, created_by, created_at, updated_at,
               resolved_at, deleted_at
        FROM bug_impact
        WHERE uuid = %s
    """
    result = conn.execute(sql, (impact_uuid,)).fetchone()
    if result is None:
        return None
    return _row_to_record(result)


def list_bug_impacts(conn: psycopg.Connection, *, bug_uuid: uuid.UUID | None = None, status: str | None = None,
                     target_project_id: uuid.UUID | None = None, include_deleted: bool = False) -> list[BugImpact]:
    """List bug impact records with optional filtering."""
    sql = """
        SELECT uuid, bug_uuid, target_type, target_project_id, target_file_path,
               target_plan_uuid, target_revision_uuid, target_step_uuid, target_step_path,
               target_ref_id, target_identifier, impact_type, status, reason, skip_decided_by,
               discovery_method, resolution_evidence, created_by, created_at, updated_at,
               resolved_at, deleted_at
        FROM bug_impact
        WHERE 1=1
    """
    params: list[Any] = []

    if bug_uuid is not None:
        sql += " AND bug_uuid = %s"
        params.append(bug_uuid)

    if status is not None:
        sql += " AND status = %s"
        params.append(status)

    if target_project_id is not None:
        sql += " AND target_project_id = %s"
        params.append(target_project_id)

    if not include_deleted:
        sql += " AND deleted_at IS NULL"

    sql += " ORDER BY created_at ASC"

    results = conn.execute(sql, params).fetchall()
    return [_row_to_record(row) for row in results]


def update_bug_impact(conn: psycopg.Connection, impact_uuid: uuid.UUID, *, changed_by: str, status: str | None = None,
                      reason: str | None = None, skip_decided_by: str | None = None, discovery_method: str | None = None,
                      resolution_evidence: dict[str, Any] | None = None) -> BugImpact:
    """Update a bug impact record."""
    current = get_bug_impact(conn, impact_uuid)
    if current is None:
        raise RuntimeValidationError(f"Bug impact {impact_uuid} not found")

    if status is not None:
        validate_impact_status(status)
    else:
        status = current.status

    if status == "skipped":
        final_reason = reason if reason is not None else current.reason
        final_skip_decided_by = skip_decided_by if skip_decided_by is not None else current.skip_decided_by

        if not final_reason or not isinstance(final_reason, str) or not final_reason.strip():
            raise RuntimeValidationError("status 'skipped' requires a non-empty reason string")
        if not final_skip_decided_by or not isinstance(final_skip_decided_by, str) or not final_skip_decided_by.strip():
            raise RuntimeValidationError("status 'skipped' requires a non-empty skip_decided_by string")

    now = datetime.now(timezone.utc)

    updates: list[str] = []
    params: list[Any] = []

    if status is not None:
        updates.append("status = %s")
        params.append(status)

    if reason is not None:
        updates.append("reason = %s")
        params.append(reason)

    if skip_decided_by is not None:
        updates.append("skip_decided_by = %s")
        params.append(skip_decided_by)

    if discovery_method is not None:
        updates.append("discovery_method = %s")
        params.append(discovery_method)

    if resolution_evidence is not None:
        updates.append("resolution_evidence = %s")
        params.append(Jsonb(resolution_evidence))

    if status in ("resolved", "verified"):
        updates.append("resolved_at = %s")
        params.append(now)

    updates.append("updated_at = %s")
    params.append(now)

    if updates:
        sql = f"UPDATE bug_impact SET {', '.join(updates)} WHERE uuid = %s"
        params.append(impact_uuid)
        conn.execute(sql, params)

    record_runtime_change(conn, plan_uuid=None, entity_type="bug_impact",
                         entity_id=impact_uuid, action="update", changed_by=changed_by)

    result = get_bug_impact(conn, impact_uuid)
    if result is None:
        raise RuntimeValidationError(f"Bug impact {impact_uuid} not found after update")
    return result


def soft_delete_bug_impact(conn: psycopg.Connection, impact_uuid: uuid.UUID, *, changed_by: str) -> BugImpact:
    """Soft delete a bug impact record."""
    now = datetime.now(timezone.utc)

    sql = "UPDATE bug_impact SET deleted_at = %s, updated_at = %s WHERE uuid = %s"
    result = conn.execute(sql, (now, now, impact_uuid))

    if result.rowcount == 0:
        raise RuntimeValidationError(f"Bug impact {impact_uuid} not found")

    record_runtime_change(conn, plan_uuid=None, entity_type="bug_impact",
                         entity_id=impact_uuid, action="soft_delete", changed_by=changed_by)

    result = get_bug_impact(conn, impact_uuid)
    if result is None:
        raise RuntimeValidationError(f"Bug impact {impact_uuid} not found after soft delete")
    return result
