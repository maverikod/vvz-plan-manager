"""Shared re-anchor storage implementation for wish_item, calendar_entry, escalation
and runtime_comment (group-3 fix, bugs 2c568c0c/5c0ddc16): the audit-record shape and
the anchor-column UPDATE mechanics exist here exactly ONCE, reused by all four new
command surfaces (wish_reanchor, calendar_entry_reanchor, escalation_reanchor,
comment_reanchor).

Two entry points:

  * reanchor_owner_form_entity -- for the three entities registered in
    plan_manager.domain.reanchor_guard.OWNER_UPDATE_TABLES (wish_item, calendar_entry,
    escalation). Routes a "none"/"project"/"file"/"plan"/"revision"/"step"/"todo"
    candidate anchor through the existing, already-pinned
    reanchor_guard.guard_owner_update (the owner-form entry the wish path of bug
    5c0ddc16 already uses) -- acyclicity, the frozen-truth guard and the
    relation_index bookkeeping all come from that one shared collaborator. A
    candidate "execution_attempt"/"review_result"/"bug"/"bug_fix" anchor is instead
    applied by a direct discriminated UPDATE (the same technique
    storage.todo_reanchor_store/storage.bug_reanchor_store already use) --
    deliberately NOT translated through guard_owner_update's owner-form, because
    owner_form_to_anchor treats any owner uuid absent from the identity registry as
    an EXTERNAL PROJECT id (primary_anchor.py's own documented root-state fallback);
    validate_anchor never checks existence for these four ref kinds (only "todo"
    does, via check_row_exists), so a stale/typo'd ref_id would silently be
    reinterpreted as a "project" anchor instead of being persisted (or refused) under
    the caller's own declared kind. Going direct avoids that masking. Cycle detection
    is not lost by skipping guard_owner_update here: none of these four ref tables is
    itself a member of OWNER_UPDATE_TABLES, so the ownership-ancestry walk
    (reanchor_guard._owner_ancestry_edges) would stop at them immediately regardless.

  * reanchor_comment -- runtime_comment is deliberately NOT added to
    OWNER_UPDATE_TABLES; see the module docstring note on comment_reanchor_command
    for the reason (comments reject anchor_type "none", which guard_owner_update's
    generic owner-form has no hook to forbid). comment_reanchor always applies a
    direct discriminated UPDATE, using RuntimeComment's own anchor vocabulary
    (validate_comment_anchor_type plus the "escalation" branch runtime_comment_store.
    add_comment already documents) rather than the legacy PrimaryAnchorType checks.

Both entry points fetch the pre-image row through TABLE_NAME on the returned
DataclassEntity class rather than an entity-specific import, refuse a frozen-truth
target through the SAME guard_reanchor_target_not_frozen todo_reanchor/bug_reanchor
already route through, and append exactly one runtime_audit_log row shaped
{"old_anchor": ..., "new_anchor": ...} -- the same shape
storage.todo_reanchor_store.reanchor_todo already uses for its own audit record.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable

import psycopg

from plan_manager.domain.primary_anchor import (
    InvalidAnchorError,
    PrimaryAnchor,
    anchor_to_columns,
    validate_anchor,
)
from plan_manager.domain.reanchor_guard import guard_owner_update, guard_reanchor_target_not_frozen
from plan_manager.domain.runtime_comment import RuntimeComment, validate_comment_anchor_type
from plan_manager.domain.runtime_validation import RuntimeValidationError, check_row_exists
from plan_manager.storage.runtime_audit_store import record_runtime_change

# The legacy anchor column set, identical across every OWNER_UPDATE_TABLES member
# AND runtime_comment (same migration-0012/0025 shape); kept as a local tuple
# (rather than importing reanchor_guard's private _ANCHOR_COLUMNS) since this
# module owns its own direct-UPDATE technique for the entity kinds
# guard_owner_update does not serve.
_ANCHOR_COLUMNS: tuple[str, ...] = (
    "primary_anchor_type",
    "anchor_project_id",
    "anchor_file_path",
    "anchor_plan_uuid",
    "anchor_revision_uuid",
    "anchor_step_uuid",
    "anchor_step_path",
    "anchor_ref_id",
)

# Anchor kinds guard_owner_update's owner-form genuinely fits (see module
# docstring); every other member of primary_anchor.ANCHOR_TYPES goes through
# the direct-UPDATE path below instead.
_OWNER_FORM_ANCHOR_TYPES: frozenset[str] = frozenset(
    {"none", "project", "file", "plan", "revision", "step", "todo"}
)


def _anchor_to_payload(anchor: PrimaryAnchor) -> dict[str, Any]:
    """Render a PrimaryAnchor as the JSON-safe audit-record shape (matches
    storage.todo_reanchor_store's own old_anchor/new_anchor dict keys)."""
    return {
        "anchor_type": anchor.anchor_type,
        "project_id": str(anchor.project_id) if anchor.project_id is not None else None,
        "file_path": anchor.file_path,
        "plan_uuid": str(anchor.plan_uuid) if anchor.plan_uuid is not None else None,
        "revision_uuid": str(anchor.revision_uuid) if anchor.revision_uuid is not None else None,
        "step_uuid": str(anchor.step_uuid) if anchor.step_uuid is not None else None,
        "step_path": anchor.step_path,
        "ref_id": str(anchor.ref_id) if anchor.ref_id is not None else None,
    }


def _existing_anchor_payload(existing: Any) -> dict[str, Any]:
    """Snapshot an entity's CURRENT anchor columns (uniform across wish_item,
    calendar_entry, escalation and runtime_comment: all four carry
    primary_anchor_type/anchor_* per migrations 0012/0025) as the audit shape."""
    return _anchor_to_payload(
        PrimaryAnchor(
            anchor_type=existing.primary_anchor_type,
            project_id=existing.anchor_project_id,
            file_path=existing.anchor_file_path,
            plan_uuid=existing.anchor_plan_uuid,
            revision_uuid=existing.anchor_revision_uuid,
            step_uuid=existing.anchor_step_uuid,
            step_path=existing.anchor_step_path,
            ref_id=existing.anchor_ref_id,
        )
    )


def _record_reanchor_audit(
    conn: psycopg.Connection,
    *,
    plan_uuid: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID,
    changed_by: str,
    old_anchor: dict[str, Any],
    new_anchor: dict[str, Any],
) -> None:
    """Append the one shared runtime audit record shape every group-3 re-anchor
    command uses -- the sole place this shape is built (checklist requirement:
    the audit-writing implementation exists ONCE across all four commands)."""
    record_runtime_change(
        conn,
        plan_uuid=plan_uuid,
        entity_type=entity_type,
        entity_id=entity_id,
        action="update",
        changed_by=changed_by,
        changed_fields={"old_anchor": old_anchor, "new_anchor": new_anchor},
    )


def _direct_anchor_update(
    conn: psycopg.Connection, table_name: str, entity_ref: uuid.UUID, anchor: PrimaryAnchor
) -> None:
    """Overwrite the eight legacy anchor columns of one row, in place -- an UPDATE
    only, exactly as storage.todo_reanchor_store/storage.bug_reanchor_store already
    do, generalized here to any table sharing the same column family."""
    columns = anchor_to_columns(anchor)
    now = datetime.now(timezone.utc)
    set_clause = ", ".join(f"{column} = %s" for column in _ANCHOR_COLUMNS)
    conn.execute(
        f"UPDATE {table_name} SET {set_clause}, updated_at = %s WHERE uuid = %s",
        (*(columns[column] for column in _ANCHOR_COLUMNS), now, entity_ref),
    )


def _owner_form_from_anchor(anchor: PrimaryAnchor) -> tuple[uuid.UUID | None, dict[str, Any]]:
    """Translate a validated owner-form-eligible PrimaryAnchor into the
    (owner, kwargs) shape reanchor_guard.guard_owner_update expects."""
    anchor_type = anchor.anchor_type
    if anchor_type == "none":
        return None, {}
    if anchor_type == "project":
        return anchor.project_id, {}
    if anchor_type == "file":
        return None, {"project_id": anchor.project_id, "path": anchor.file_path}
    if anchor_type == "plan":
        return anchor.plan_uuid, {}
    if anchor_type == "revision":
        return anchor.revision_uuid, {}
    if anchor_type == "step":
        return anchor.step_uuid, {"plan_uuid": anchor.plan_uuid}
    if anchor_type == "todo":
        return anchor.ref_id, {}
    raise InvalidAnchorError(f"{anchor_type!r} is not an owner-form-eligible anchor type")


def reanchor_owner_form_entity(
    conn: psycopg.Connection,
    entity_ref: uuid.UUID,
    *,
    changed_by: str,
    new_anchor: PrimaryAnchor,
    entity_type: str,
    get_entity: Callable[[psycopg.Connection, uuid.UUID], Any],
    not_found_code: str,
) -> Any:
    """Move a wish_item/calendar_entry/escalation row's primary anchor to a new
    target, with an audit record -- the shared implementation behind
    wish_reanchor, calendar_entry_reanchor and escalation_reanchor.

    Parameters:
        conn: Open connection; the caller owns the transaction.
        entity_ref: The entity being moved (its own uuid).
        changed_by: Actor recorded on the appended audit record.
        new_anchor: The candidate new primary anchor; validated exactly as
            todo_reanchor/bug_reanchor validate theirs.
        entity_type: The runtime_audit_log entity_type to record (matches the
            entity's own DataclassEntity.ENTITY_TYPE, e.g. "wish").
        get_entity: The entity's own get_* store function (get_wish/
            get_calendar_entry/get_escalation), used both to fetch the
            pre-image (for not-found and the old_anchor snapshot) and the
            post-image (the returned, updated record).
        not_found_code: The DomainCommandError code raised when entity_ref
            does not resolve (e.g. "WISH_NOT_FOUND").

    Returns:
        The updated entity record (as returned by get_entity), reflecting the
        new anchor.

    Raises:
        DomainCommandError: With code not_found_code when entity_ref does not
            resolve, either before or after the move.
        InvalidAnchorError: When new_anchor fails validate_anchor's shape/
            existence checks for its anchor_type.
        FrozenTruthMutationError: When new_anchor targets a frozen plan or a
            frozen step.
        AdmissionCycleError: When the move would close an ownership cycle
            (only reachable when new_anchor targets another OWNER_UPDATE_TABLES
            entity, i.e. anchor_type "todo").
    """
    from plan_manager.commands.errors import DomainCommandError

    existing = get_entity(conn, entity_ref)
    if existing is None:
        raise DomainCommandError(not_found_code, f"{entity_type} not found: {entity_ref}")

    validate_anchor(conn, new_anchor)
    guard_reanchor_target_not_frozen(conn, new_anchor.anchor_type, new_anchor.plan_uuid, new_anchor.step_uuid)

    old_anchor = _existing_anchor_payload(existing)
    table_name = type(existing).TABLE_NAME

    if new_anchor.anchor_type in _OWNER_FORM_ANCHOR_TYPES:
        owner, owner_kwargs = _owner_form_from_anchor(new_anchor)
        guard_owner_update(conn, entity_ref, owner, **owner_kwargs)
        if new_anchor.anchor_type == "step" and new_anchor.step_path is not None:
            # guard_owner_update's owner-form has no step_path slot (a step
            # OWNER is a bare uuid); patch the optional descriptive path
            # in the same transaction, still an UPDATE of the same row.
            conn.execute(
                f"UPDATE {table_name} SET anchor_step_path = %s WHERE uuid = %s",
                (new_anchor.step_path, entity_ref),
            )
    else:
        _direct_anchor_update(conn, table_name, entity_ref, new_anchor)

    updated = get_entity(conn, entity_ref)
    if updated is None:
        raise DomainCommandError(not_found_code, f"{entity_type} not found: {entity_ref}")

    _record_reanchor_audit(
        conn,
        plan_uuid=updated.anchor_plan_uuid,
        entity_type=entity_type,
        entity_id=entity_ref,
        changed_by=changed_by,
        old_anchor=old_anchor,
        new_anchor=_anchor_to_payload(new_anchor),
    )
    return updated


def reanchor_comment(
    conn: psycopg.Connection,
    comment_uuid: uuid.UUID,
    *,
    changed_by: str,
    new_anchor: PrimaryAnchor,
) -> RuntimeComment:
    """Move a RuntimeComment's primary anchor to a new target, with an audit record.

    Always a direct discriminated UPDATE (see module docstring): runtime_comment
    is not a member of reanchor_guard.OWNER_UPDATE_TABLES because its anchor
    vocabulary differs from the legacy PrimaryAnchorType family in exactly two
    ways -- "none" is rejected outright (a comment always attaches to a subject)
    and "escalation" is accepted (with its own ref_id-existence check), neither
    of which guard_owner_update's generic owner-form has a hook to express.

    Parameters:
        conn: Open connection; the caller owns the transaction.
        comment_uuid: The comment being moved.
        changed_by: Actor recorded on the appended audit record.
        new_anchor: The candidate new primary anchor.

    Returns:
        RuntimeComment
            The comment after its anchor columns are overwritten with the new
            target.

    Raises:
        DomainCommandError: With code COMMENT_NOT_FOUND when comment_uuid does
            not resolve, either before or after the move.
        RuntimeValidationError: When new_anchor.anchor_type is "none" (comments
            reject it) or is outside the eleven-kind comment anchor vocabulary,
            or fails the applicable shape/existence check.
        FrozenTruthMutationError: When new_anchor targets a frozen plan or a
            frozen step.
    """
    from plan_manager.commands.errors import DomainCommandError
    from plan_manager.storage.runtime_comment_store import get_comment

    existing = get_comment(conn, comment_uuid)
    if existing is None:
        raise DomainCommandError("COMMENT_NOT_FOUND", f"comment not found: {comment_uuid}")

    if new_anchor.anchor_type == "none":
        raise RuntimeValidationError(
            "comments may not be unanchored: 'none' is not a valid comment anchor type"
        )
    validate_comment_anchor_type(new_anchor.anchor_type)
    if new_anchor.anchor_type == "escalation":
        if new_anchor.ref_id is None:
            raise RuntimeValidationError("escalation anchor requires ref_id")
        check_row_exists(conn, "escalation", new_anchor.ref_id, frozenset({"escalation"}))
    else:
        # The remaining ten comment anchor kinds are exactly
        # primary_anchor.ANCHOR_TYPES minus "none" -- validate_anchor applies.
        validate_anchor(conn, new_anchor)

    guard_reanchor_target_not_frozen(conn, new_anchor.anchor_type, new_anchor.plan_uuid, new_anchor.step_uuid)

    old_anchor = _existing_anchor_payload(existing)
    _direct_anchor_update(conn, "runtime_comment", comment_uuid, new_anchor)

    updated = get_comment(conn, comment_uuid)
    if updated is None:
        raise DomainCommandError("COMMENT_NOT_FOUND", f"comment not found: {comment_uuid}")

    _record_reanchor_audit(
        conn,
        plan_uuid=updated.anchor_plan_uuid,
        entity_type="comment",
        entity_id=comment_uuid,
        changed_by=changed_by,
        old_anchor=old_anchor,
        new_anchor=_anchor_to_payload(new_anchor),
    )
    return updated
