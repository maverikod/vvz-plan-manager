"""Store-level irreversible (hard) deletion for runtime entities (C-008): thin audited wrappers over DataclassEntity.crud_hard_delete; the inbound-reference admission check lives in the entity base (hard_delete_entity raises EntityReferencedError while live referrers exist)."""

from __future__ import annotations

import uuid

import psycopg

from plan_manager.domain.todo import TodoItem
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.storage.runtime_audit_store import record_runtime_change


def hard_delete_todo(
    conn: psycopg.Connection, todo_uuid: uuid.UUID, *, changed_by: str
) -> None:
    """Irreversibly remove a TODO item row and record a hard_delete audit action.

    Delegates the physical deletion to TodoItem.crud_hard_delete with
    require_soft_deleted=False (the command surface deletes live rows
    directly). The entity base re-checks inbound references and raises
    EntityReferencedError when live referrers exist, and unregisters the
    row's entity_identity mapping on success.

    Parameters:
        conn: An open psycopg 3 connection.
        todo_uuid: UUID of the TODO item to remove.
        changed_by: Identity of the actor recorded on the audit trail.

    Raises:
        DomainCommandError: With code TODO_NOT_FOUND if no row exists.
        EntityReferencedError: When live inbound references block deletion.
    """
    current = TodoItem.crud_get(conn, todo_uuid, include_deleted=True)
    if current is None:
        from plan_manager.commands.errors import DomainCommandError

        raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo_uuid}")
    plan_uuid = current.get("anchor_plan_uuid")
    TodoItem.crud_hard_delete(conn, todo_uuid, returning=False, require_soft_deleted=False)
    record_runtime_change(
        conn,
        plan_uuid=plan_uuid,
        entity_type="todo",
        entity_id=todo_uuid,
        action="hard_delete",
        changed_by=changed_by,
    )


def hard_delete_comment(
    conn: psycopg.Connection, comment_uuid: uuid.UUID, *, changed_by: str
) -> None:
    """Irreversibly remove a runtime comment row and record a hard_delete audit action.

    Delegates the physical deletion to RuntimeComment.crud_hard_delete with
    require_soft_deleted=False. The entity base re-checks inbound references
    (a live superseding comment blocks deletion, raising
    EntityReferencedError) and unregisters the row's entity_identity mapping
    on success.

    Parameters:
        conn: An open psycopg 3 connection.
        comment_uuid: UUID of the runtime comment to remove.
        changed_by: Identity of the actor recorded on the audit trail.

    Raises:
        DomainCommandError: With code COMMENT_NOT_FOUND if no row exists.
        EntityReferencedError: When live inbound references block deletion.
    """
    current = RuntimeComment.crud_get(conn, comment_uuid, include_deleted=True)
    if current is None:
        from plan_manager.commands.errors import DomainCommandError

        raise DomainCommandError("COMMENT_NOT_FOUND", f"comment not found: {comment_uuid}")
    plan_uuid = current.get("anchor_plan_uuid")
    RuntimeComment.crud_hard_delete(conn, comment_uuid, returning=False, require_soft_deleted=False)
    record_runtime_change(
        conn,
        plan_uuid=plan_uuid,
        entity_type="runtime_comment",
        entity_id=comment_uuid,
        action="hard_delete",
        changed_by=changed_by,
    )
