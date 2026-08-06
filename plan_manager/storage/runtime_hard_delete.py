"""Store-level irreversible (hard) deletion for runtime entities (C-008): thin wrappers over DataclassEntity.crud_hard_delete; the inbound-reference admission check AND the audit write both live in the
central hard-delete guard now (plan_manager.storage.hard_delete_guard), which
raises EntityReferencedError while live referrers exist.

These wrappers deliberately no longer write their own audit record. The guard is
the single writer, so one deletion produces exactly one audit row; keeping a
local write here would double-count every removal. What each wrapper still owns
is the entity-specific context the guard cannot derive: the plan anchor column
differs per entity, and two of these entity_type values are historical table
names that must not change or existing audit_list queries stop matching.

CR-7 G-006/T-001/A-001: this module also owns the set-wise hard-delete engine,
``hard_delete_marked_set``. The shipped batch purge (entity.purge_soft_deleted_batch,
driven per entity type by the runtime_purge_batch command) removes rows one at a
time and reports a blocked row in ``refused`` while continuing with the rest.
That report-one-and-continue shape is deliberately reversed here: its admission
check (hard_delete_guard.lookup_referrers, via CENTRAL_REFERENCE_CHECKS) only
ever looks at LIVE referrers, so a referrer that is itself already marked
(soft-deleted) never blocks anything -- and if that marked referrer is not also
purged in the same pass, it is left pointing at a row that no longer exists,
dangling forever. hard_delete_marked_set instead computes the full fixed point of
marked referrers (via the relation index, not the live-only FK catalogue) before
touching a single row, and refuses the WHOLE candidate set -- nothing removed --
the moment any referrer outside the closed set is not itself marked. The command
surface that will drive this engine, and the soft-delete alignment it depends on,
are sibling CR-7 steps and are not part of this change.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

import psycopg
from psycopg import sql

from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_fix_propagation import BugFixPropagation
from plan_manager.domain.bug_impact import BugImpact
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.todo import TodoItem
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.storage.errors import NotFoundError


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


# ---------------------------------------------------------------------------
# CR-7 G-006/T-001/A-001: the set-wise hard-delete engine (C-008 supersession).
#
# Everything below operates across entity-type boundaries (any type registered
# in the identity registry with a soft-delete column), because the relation
# index it reads from is itself type-agnostic: a triple names a source and a
# target ref, never which entity-type table either lives in.
# ---------------------------------------------------------------------------


def _purge_capable_single_uuid_classes() -> list[type]:
    """Every entity class this engine can reason about.

    CR-7 G-006/T-001/A-001: restricted to classes with a single ``uuid`` id
    column (every soft-delete-capable class today satisfies this -- see
    reference_catalog.purge_capable_entity_types) because the identity
    registry, the relation index and this engine's working set are all keyed
    on one bare uuid per entity; a composite-key entity has no such single
    identifier to place in that set.
    """
    from plan_manager.storage.reference_catalog import (
        purge_capable_entity_types,
        resolve_entity_class,
    )

    classes = []
    for entity_type in purge_capable_entity_types():
        entity_cls = resolve_entity_class(entity_type)
        if entity_cls.ID_COLUMN == "uuid":
            classes.append(entity_cls)
    return classes


def _is_marked(conn: psycopg.Connection, entity_cls: type, entity_id: uuid.UUID) -> bool:
    """True when entity_id names a row of entity_cls whose SOFT_DELETE_COLUMN is set.

    CR-7 G-006/T-001/A-001: "marked" is defined exactly this way by the frozen
    step text. A class that declares SOFT_DELETE_COLUMN=None can never be
    marked -- it has no timestamp column to hold the mark -- so it always
    answers False here, which is what makes an unmarked referrer of that kind
    correctly block the whole operation below.
    """
    if entity_cls.SOFT_DELETE_COLUMN is None:
        return False
    row = entity_cls.get_by_id(conn, entity_id, include_deleted=True)
    if row is None:
        return False
    return row.get(entity_cls.SOFT_DELETE_COLUMN) is not None


def _all_marked_entities(conn: psycopg.Connection) -> dict[uuid.UUID, type]:
    """Every entity currently marked (soft-deleted), across every capable type.

    CR-7 G-006/T-001/A-001: the default starting set when hard_delete_marked_set
    is called with entity_ids=None. Reads only -- a SELECT per class -- so it
    never trips the cr7-no-out-of-mechanism-write scan, which watches INSERT
    and DELETE statements exclusively.
    """
    marked: dict[uuid.UUID, type] = {}
    for entity_cls in _purge_capable_single_uuid_classes():
        rows = conn.execute(
            sql.SQL("SELECT {} FROM {} WHERE {} IS NOT NULL").format(
                sql.Identifier(entity_cls.ID_COLUMN),
                entity_cls._table(),
                sql.Identifier(entity_cls.SOFT_DELETE_COLUMN),
            )
        ).fetchall()
        for row in rows:
            marked[row[0]] = entity_cls
    return marked


def _topological_removal_order(
    working_set: set[uuid.UUID], internal_edges: list[dict[str, Any]]
) -> list[uuid.UUID]:
    """Order removal so a referrer (source_ref) is deleted before its target.

    CR-7 G-006/T-001/A-001: Kahn's algorithm over the sub-graph the fixed point
    closed. An edge source_ref -> target_ref means the source is removed first,
    so a target's relation-index row never briefly outlives every row that used
    to point at it. None of the entity families this engine currently reaches
    carries a real foreign key across these columns (they are polymorphic
    anchors, catalogued only in the relation index), so a cycle inside the set
    is not a live concern; if one ever arose, the deterministic sorted tail
    below still removes every row, it just does not order that remainder.
    """
    in_degree: dict[uuid.UUID, int] = {entity_id: 0 for entity_id in working_set}
    outgoing: dict[uuid.UUID, list[uuid.UUID]] = {entity_id: [] for entity_id in working_set}
    for edge in internal_edges:
        source, target = edge["source_ref"], edge["target_ref"]
        if source == target or source not in working_set or target not in working_set:
            continue
        outgoing[source].append(target)
        in_degree[target] += 1

    order: list[uuid.UUID] = []
    queue = sorted((eid for eid, degree in in_degree.items() if degree == 0), key=str)
    while queue:
        current = queue.pop(0)
        order.append(current)
        for neighbor in sorted(outgoing[current], key=str):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)
        queue.sort(key=str)
    remaining = sorted((eid for eid in working_set if eid not in order), key=str)
    order.extend(remaining)
    return order


def hard_delete_marked_set(
    conn: psycopg.Connection,
    entity_ids: Iterable[uuid.UUID] | None = None,
    *,
    changed_by: str = "system",
) -> dict[str, list[uuid.UUID]]:
    """Irreversibly remove a fixed-point-closed set of marked entities, atomically.

    CR-7 G-006/T-001/A-001. Replaces the shipped report-one-and-continue purge's
    row-by-row admission (see the module docstring) with a whole-set decision:

    1. The starting set is entity_ids, or -- when None -- every entity
       currently marked (soft-deleted) across every soft-delete-capable type.
       Every EXPLICIT starting id must already be marked; one that is not
       refuses the call before any lookup of referrers even begins.
    2. The set is closed to a fixed point: repeatedly, every marked referrer
       (found via relation_index_store.referrers_of, not the live-only FK
       catalogue) of anything already in the set is added, until nothing new
       is added.
    3. Admission: once closed, every referrer of anything in the set must
       itself be a member of the set. If any referrer outside the set remains
       -- necessarily unmarked, since a marked one would already have been
       folded in by step 2 -- the WHOLE operation is refused and nothing is
       removed.
    4. Only then are rows removed: each entity row (via the entity class's own
       crud_hard_delete, so the DELETE statement itself lives in the mechanism
       file hard_delete_guard.py, not here), then every relation-index triple
       touching any removed entity. Removal is ordered so a referrer is always
       deleted before its target, and everything happens inside the caller's
       transaction -- one atomic unit, matching the guard's audit-once
       discipline (crud_hard_delete's guard records one audit row per row
       removed; this function writes no audit of its own).

    Parameters:
        conn: an open psycopg 3 connection. Every write here runs inside the
            caller's transaction; the caller commits or rolls back as a whole.
        entity_ids: the explicit starting identifiers, or None to default to
            every currently marked entity (see step 1 above).
        changed_by: actor recorded on the audit trail of every row removed.

    Returns:
        {"removed": [uuid, ...]} -- the final set actually deleted, in the
        order it was deleted (referrers before their targets).

    Raises:
        plan_manager.storage.errors.NotFoundError: an explicit starting id is
            not a registered entity at all.
        plan_manager.domain.entity.EntityNotSoftDeletedError: an explicit
            starting id names a row (or a type) that is not marked.
        plan_manager.domain.entity.EntityReferencedError: the fixed point
            closed with an unmarked referrer still outside the set; nothing
            was removed. ``.referrers`` names every such blocking triple.
    """
    from plan_manager.domain.entity import EntityNotSoftDeletedError, EntityReferencedError
    from plan_manager.storage.identity import resolve_entity_identities_batch
    from plan_manager.storage.reference_catalog import resolve_entity_class
    from plan_manager.storage.relation_index_store import referrers_of

    id_to_class: dict[uuid.UUID, type] = {}

    if entity_ids is None:
        id_to_class = _all_marked_entities(conn)
    else:
        # De-duplicated, order preserved only for readable error messages.
        starting_ids = list(dict.fromkeys(entity_ids))
        resolved = resolve_entity_identities_batch(conn, starting_ids)
        for entity_id in starting_ids:
            info = resolved.get(entity_id)
            if info is None:
                raise NotFoundError(f"entity identity not found: {entity_id}")
            try:
                entity_cls = resolve_entity_class(info["entity_type"])
            except ValueError:
                # A registry entry naming an entity_type no live class claims
                # (e.g. a stale reservation) can never be marked either.
                raise EntityNotSoftDeletedError(info["entity_type"], entity_id) from None
            if not _is_marked(conn, entity_cls, entity_id):
                raise EntityNotSoftDeletedError(entity_cls.entity_type(), entity_id)
            id_to_class[entity_id] = entity_cls

    working_set: set[uuid.UUID] = set(id_to_class)

    # Fixed-point expansion: pull in marked referrers of whatever is already
    # in the set, one wave at a time, until a wave adds nothing new.
    frontier: set[uuid.UUID] = set(working_set)
    while frontier:
        triples = referrers_of(conn, frontier)
        candidate_ids = {
            triple["source_ref"] for triple in triples if triple["source_ref"] not in working_set
        }
        frontier = set()
        if not candidate_ids:
            break
        resolved_candidates = resolve_entity_identities_batch(conn, list(candidate_ids))
        for source_ref in sorted(candidate_ids, key=str):
            info = resolved_candidates.get(source_ref)
            if info is None:
                continue  # not a registered entity at all; not an entity reference
            try:
                referrer_cls = resolve_entity_class(info["entity_type"])
            except ValueError:
                continue
            if _is_marked(conn, referrer_cls, source_ref):
                id_to_class[source_ref] = referrer_cls
                working_set.add(source_ref)
                frontier.add(source_ref)
            # An unmarked candidate is left out of the set on purpose; the
            # admission pass below is what turns its presence into a refusal.

    # Admission: every referrer of the closed set must itself be a member.
    final_triples = referrers_of(conn, working_set) if working_set else []
    internal_edges = [triple for triple in final_triples if triple["source_ref"] in working_set]
    blocking = [triple for triple in final_triples if triple["source_ref"] not in working_set]
    if blocking:
        raise EntityReferencedError(
            "hard_delete_marked_set",
            sorted(working_set, key=str),
            [
                {
                    "table": None,
                    "column": triple["field_ref"],
                    "referrer_id": triple["source_ref"],
                    "referrer_kind": "relation_index",
                }
                for triple in blocking
            ],
        )

    # Removal: referrers before their targets, entity row then relation-index
    # triples, all inside the caller's transaction.
    order = _topological_removal_order(working_set, internal_edges)
    for entity_id in order:
        entity_cls = id_to_class[entity_id]
        entity_cls.crud_hard_delete(
            conn,
            entity_id,
            returning=False,
            require_soft_deleted=True,
            changed_by=changed_by,
        )
    if working_set:
        ids = list(working_set)
        # relation_index is not in ALLOWED_TABLES (identity.EXCLUDED_TABLES):
        # it is the derived index itself, never an identity-bearing entity
        # table, so this direct statement is outside the cr7-no-out-of-
        # mechanism-write scan's scope by construction, not by exemption.
        conn.execute(
            "DELETE FROM relation_index WHERE source_ref = ANY(%s) OR target_ref = ANY(%s)",
            (ids, ids),
        )

    return {"removed": order}
