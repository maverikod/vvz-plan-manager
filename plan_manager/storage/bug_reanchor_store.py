"""Bug re-anchor storage function: moves a bug report's primary source anchor with an audit record (C-012)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import psycopg

from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.bug_source import BugSource, bug_source_to_columns, validate_bug_source
from plan_manager.domain.reanchor_guard import guard_reanchor_target_not_frozen
from plan_manager.storage.bug_report_store import get_bug
from plan_manager.storage.runtime_audit_store import record_runtime_change


def reanchor_bug_source(
    conn: psycopg.Connection,
    bug_uuid: uuid.UUID,
    *,
    changed_by: str,
    new_source: BugSource,
) -> BugReport:
    """Move a bug report's primary source anchor to a new target, with an audit record.

    Parameters:
        conn: psycopg.Connection
            Open connection used to perform the move.
        bug_uuid: uuid.UUID
            The bug report whose primary source anchor is being moved.
        changed_by: str
            Identity of the actor performing the re-anchor move, recorded on
            the appended audit record.
        new_source: BugSource
            The candidate new primary source anchor target.

    Returns:
        BugReport
            The bug report after its source columns are overwritten with the
            new target.

    Raises:
        DomainCommandError: With code BUG_NOT_FOUND when bug_uuid does not
            resolve to an existing bug report, either before or after the
            update.
        RuntimeValidationError: When new_source fails validate_bug_source's
            shape checks for its source_type.
        FrozenTruthMutationError: When new_source targets a frozen plan or a
            frozen step (guard_reanchor_target_not_frozen).
    """
    from plan_manager.commands.errors import DomainCommandError

    existing = get_bug(conn, bug_uuid)
    if existing is None:
        raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_uuid}")

    validate_bug_source(conn, new_source)
    guard_reanchor_target_not_frozen(
        conn,
        new_source.source_type,
        new_source.plan_uuid,
        new_source.step_uuid,
    )

    old_source: dict[str, Any] = {
        "source_type": existing.source_anchor_type,
        "project_id": str(existing.source_project_id) if existing.source_project_id is not None else None,
        "file_path": existing.source_file_path,
        "plan_uuid": str(existing.source_plan_uuid) if existing.source_plan_uuid is not None else None,
        "revision_uuid": str(existing.source_revision_uuid) if existing.source_revision_uuid is not None else None,
        "step_uuid": str(existing.source_step_uuid) if existing.source_step_uuid is not None else None,
        "step_path": existing.source_step_path,
        "ref_id": str(existing.source_ref_id) if existing.source_ref_id is not None else None,
        "command": existing.source_command,
        "service": existing.source_service,
    }
    new_source_payload: dict[str, Any] = {
        "source_type": new_source.source_type,
        "project_id": str(new_source.project_id) if new_source.project_id is not None else None,
        "file_path": new_source.file_path,
        "plan_uuid": str(new_source.plan_uuid) if new_source.plan_uuid is not None else None,
        "revision_uuid": str(new_source.revision_uuid) if new_source.revision_uuid is not None else None,
        "step_uuid": str(new_source.step_uuid) if new_source.step_uuid is not None else None,
        "step_path": new_source.step_path,
        "ref_id": str(new_source.ref_id) if new_source.ref_id is not None else None,
        "command": new_source.command,
        "service": new_source.service,
    }

    columns = bug_source_to_columns(new_source)
    now = datetime.now(timezone.utc)
    conn.execute(
        "UPDATE bug_report SET source_anchor_type = %s, source_project_id = %s, "
        "source_file_path = %s, source_plan_uuid = %s, source_revision_uuid = %s, "
        "source_step_uuid = %s, source_step_path = %s, source_ref_id = %s, "
        "source_command = %s, source_service = %s, updated_at = %s WHERE uuid = %s",
        (
            columns["source_anchor_type"],
            columns["source_project_id"],
            columns["source_file_path"],
            columns["source_plan_uuid"],
            columns["source_revision_uuid"],
            columns["source_step_uuid"],
            columns["source_step_path"],
            columns["source_ref_id"],
            columns["source_command"],
            columns["source_service"],
            now,
            bug_uuid,
        ),
    )

    updated = get_bug(conn, bug_uuid)
    if updated is None:
        raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_uuid}")

    record_runtime_change(
        conn,
        plan_uuid=updated.source_plan_uuid,
        entity_type="bug_report",
        entity_id=bug_uuid,
        action="update",
        changed_by=changed_by,
        changed_fields={"old_source": old_source, "new_source": new_source_payload},
    )

    return updated
