"""Store-level irreversible (hard) deletion for runtime entities (C-008): thin wrappers over DataclassEntity.crud_hard_delete; the inbound-reference admission check AND the audit write both live in the
central hard-delete guard now (plan_manager.storage.hard_delete_guard), which
raises EntityReferencedError while live referrers exist.

These wrappers deliberately no longer write their own audit record. The guard is
the single writer, so one deletion produces exactly one audit row; keeping a
local write here would double-count every removal. What each wrapper still owns
is the entity-specific context the guard cannot derive: the plan anchor column
differs per entity, and two of these entity_type values are historical table
names that must not change or existing audit_list queries stop matching.
"""

from __future__ import annotations

import uuid

import psycopg

from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_fix_propagation import BugFixPropagation
from plan_manager.domain.bug_impact import BugImpact
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.todo import TodoItem
from plan_manager.domain.runtime_comment import RuntimeComment


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
    TodoItem.crud_hard_delete(
        conn,
        todo_uuid,
        returning=False,
        require_soft_deleted=False,
        changed_by=changed_by,
        plan_uuid=plan_uuid,
        # Historical audit entity_type, kept so audit_list queries
        # over existing rows keep matching.
        audit_entity_type="todo",
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
    RuntimeComment.crud_hard_delete(
        conn,
        comment_uuid,
        returning=False,
        require_soft_deleted=False,
        changed_by=changed_by,
        plan_uuid=plan_uuid,
        # Historical audit entity_type, kept so audit_list queries
        # over existing rows keep matching.
        audit_entity_type="runtime_comment",
    )


def hard_delete_bug(
    conn: psycopg.Connection, bug_uuid: uuid.UUID, *, changed_by: str
) -> None:
    """Irreversibly remove a BugReport row and record a hard_delete audit action.

    Delegates the physical deletion to BugReport.crud_hard_delete with
    require_soft_deleted=False (the command surface deletes live rows
    directly). The entity base re-checks inbound references (anchored
    comments, duplicate/child bugs, bug impacts, bug fixes) and raises
    EntityReferencedError when live referrers exist, and unregisters the
    row's entity_identity mapping on success.

    Parameters:
        conn: An open psycopg 3 connection.
        bug_uuid: UUID of the bug report to remove.
        changed_by: Identity of the actor recorded on the audit trail.

    Raises:
        DomainCommandError: With code BUG_NOT_FOUND if no row exists.
        EntityReferencedError: When live inbound references block deletion.
    """
    current = BugReport.crud_get(conn, bug_uuid, include_deleted=True)
    if current is None:
        from plan_manager.commands.errors import DomainCommandError

        raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_uuid}")
    plan_uuid = current.get("source_plan_uuid")
    BugReport.crud_hard_delete(
        conn,
        bug_uuid,
        returning=False,
        require_soft_deleted=False,
        changed_by=changed_by,
        plan_uuid=plan_uuid,
        # Historical audit entity_type, kept so audit_list queries
        # over existing rows keep matching.
        audit_entity_type="bug_report",
    )


def hard_delete_bug_impact(
    conn: psycopg.Connection, impact_uuid: uuid.UUID, *, changed_by: str
) -> None:
    """Irreversibly remove a BugImpact row and record a hard_delete audit action.

    Delegates the physical deletion to BugImpact.crud_hard_delete with
    require_soft_deleted=False. The entity base re-checks inbound references
    (a live bug fix propagation targeting this impact blocks deletion,
    raising EntityReferencedError) and unregisters the row's
    entity_identity mapping on success.

    Parameters:
        conn: An open psycopg 3 connection.
        impact_uuid: UUID of the bug impact record to remove.
        changed_by: Identity of the actor recorded on the audit trail.

    Raises:
        DomainCommandError: With code BUG_IMPACT_NOT_FOUND if no row exists.
        EntityReferencedError: When live inbound references block deletion.
    """
    current = BugImpact.crud_get(conn, impact_uuid, include_deleted=True)
    if current is None:
        from plan_manager.commands.errors import DomainCommandError

        raise DomainCommandError("BUG_IMPACT_NOT_FOUND", f"bug impact not found: {impact_uuid}")
    plan_uuid = current.get("target_plan_uuid")
    BugImpact.crud_hard_delete(
        conn,
        impact_uuid,
        returning=False,
        require_soft_deleted=False,
        changed_by=changed_by,
        plan_uuid=plan_uuid,
        # Historical audit entity_type, kept so audit_list queries
        # over existing rows keep matching.
        audit_entity_type="bug_impact",
    )


def hard_delete_bug_fix(
    conn: psycopg.Connection, fix_uuid: uuid.UUID, *, changed_by: str
) -> None:
    """Irreversibly remove a BugFix row and record a hard_delete audit action.

    Delegates the physical deletion to BugFix.crud_hard_delete with
    require_soft_deleted=False. The entity base re-checks inbound references
    (anchored comments, execution attempts, bug-fix propagations) and raises
    EntityReferencedError when live referrers exist, and unregisters the
    row's entity_identity mapping on success. plan_uuid is always recorded
    as None on the audit trail: BugFix carries no plan_uuid field of its
    own (only bug_uuid), matching the same convention already used by every
    bug_fix_store mutation (create/update/soft_delete all record plan_uuid=None).

    Parameters:
        conn: An open psycopg 3 connection.
        fix_uuid: UUID of the bug fix attempt to remove.
        changed_by: Identity of the actor recorded on the audit trail.

    Raises:
        DomainCommandError: With code BUG_FIX_NOT_FOUND if no row exists.
        EntityReferencedError: When live inbound references block deletion.
    """
    current = BugFix.crud_get(conn, fix_uuid, include_deleted=True)
    if current is None:
        from plan_manager.commands.errors import DomainCommandError

        raise DomainCommandError("BUG_FIX_NOT_FOUND", f"bug fix not found: {fix_uuid}")
    BugFix.crud_hard_delete(
        conn,
        fix_uuid,
        returning=False,
        require_soft_deleted=False,
        changed_by=changed_by,
        plan_uuid=None,
        # Historical audit entity_type, kept so audit_list queries
        # over existing rows keep matching.
        audit_entity_type="bug_fix",
    )


def hard_delete_bug_fix_propagation(
    conn: psycopg.Connection, propagation_uuid: uuid.UUID, *, changed_by: str
) -> None:
    """Irreversibly remove a BugFixPropagation row and record a hard_delete audit action.

    Delegates the physical deletion to BugFixPropagation.crud_hard_delete
    with require_soft_deleted=False. BugFixPropagation is a leaf entity (no
    domain-specific HARD_DELETE_REFERENCE_CHECKS); the entity base still
    re-checks any generic FK-derived inbound reference and raises
    EntityReferencedError when one is live, and unregisters the row's
    entity_identity mapping on success.

    Parameters:
        conn: An open psycopg 3 connection.
        propagation_uuid: UUID of the bug fix propagation record to remove.
        changed_by: Identity of the actor recorded on the audit trail.

    Raises:
        DomainCommandError: With code BUG_PROPAGATION_NOT_FOUND if no row exists.
        EntityReferencedError: When live inbound references block deletion.
    """
    current = BugFixPropagation.crud_get(conn, propagation_uuid, include_deleted=True)
    if current is None:
        from plan_manager.commands.errors import DomainCommandError

        raise DomainCommandError("BUG_PROPAGATION_NOT_FOUND", f"bug propagation not found: {propagation_uuid}")
    plan_uuid = current.get("linked_plan_uuid")
    BugFixPropagation.crud_hard_delete(
        conn,
        propagation_uuid,
        returning=False,
        require_soft_deleted=False,
        changed_by=changed_by,
        plan_uuid=plan_uuid,
        # Historical audit entity_type, kept so audit_list queries
        # over existing rows keep matching.
        audit_entity_type="bug_fix_propagation",
    )
