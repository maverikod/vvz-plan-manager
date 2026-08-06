"""Repair surface for scalar UUID references whose target row does not exist.

CR-7 G-006/T-002/A-001 (C-003, C-008, C-009, C-011). Three operations, in
increasing order of danger:

1. :func:`find_dangling_references` -- read-only. Scans every catalogued
   single-uuid reference column (:data:`plan_manager.storage.reference_catalog.
   REFERENCE_CATALOG`) against the identity registry, the same source of
   canonical truth :func:`plan_manager.storage.relation_index_store.
   compute_canonical_triples` walks, and reports every value that does not
   resolve.
2. :func:`clear_reference` -- nulls one offending field, admitted only when
   the source property's schema statically declares the column nullable
   (see :func:`nullability_for`). The relation-index triple for that
   (source, property) pair is retired in the same transaction.
3. :func:`delete_carrier` -- removes the entities carrying references that
   cannot be repaired by clearing. Dry-run by default: it reports the
   fixed-point closure and admission verdict the set-wise purge engine
   (:func:`plan_manager.storage.runtime_hard_delete.hard_delete_marked_set`)
   would apply, WITHOUT writing anything. A live (non-dry-run) call
   delegates the removal itself to that engine, so it inherits every rule
   of the set-wise purge discipline (C-008) unchanged -- including that an
   explicit starting id must already be marked.

NULLABILITY, the reason clear can refuse a column that is not actually
constrained NOT NULL. Deriving nullability from the migration-chain DDL
would need a live connection and a full DDL parse just to answer a yes/no
question this module asks constantly; the entity descriptors already carry
that knowledge in one cheaper place -- a source property's dataclass field
is typed ``X | None`` exactly when the column is nullable (bug-checked
convention, not incidental: see e.g. TodoItem.anchor_plan_uuid vs.
Step.plan_uuid). :func:`nullability_for` reads that type hint. Two
situations make the answer unreachable and are conservatively classified
"unknown" (clear refuses those exactly like "not_nullable"): the source
table's entity class cannot be found at all (e.g. Paragraph.TABLE_NAME is
None -- paragraph rows are not addressed through this registry), or the
column is not a plain dataclass field of that class (composite-keyed rows
such as Relation and Concept do not declare "uuid"/"plan_uuid" as fields of
their own; every catalogued reference column on either table happens to
schema-NOT-NULL, but this module has no static way to see that, so it
answers "unknown" rather than guessing).

REGISTRY RECOVERY (C-009). :func:`audit_registry` and
:func:`restore_missing_identities` are direct re-exports of the existing
primitives in :mod:`plan_manager.storage.identity_audit` -- this module adds
no logic on top of them, only the two operations that primitive set does not
already provide: :func:`remove_unreferenced_extra_identities` (the batch
form of ``remove_extra_identity_if_unreferenced``, applied to every "extra"
entry an audit reports) and :func:`rebuild_relation_index` (the atomic
compute-then-replace wrapper over
:func:`plan_manager.storage.relation_index_store.compute_canonical_triples`
and ``replace_index``, run inside the caller's transaction).

Every write here runs inside the caller's transaction; nothing in this
module commits or rolls back on its own, matching every other storage
module in the package.
"""

from __future__ import annotations

import typing
import uuid
from typing import Any, Iterable

import psycopg
from psycopg import sql

from plan_manager.storage.identity import resolve_entity_identities_batch
from plan_manager.storage.identity_audit import (
    audit_registry,
    remove_extra_identity_if_unreferenced,
    restore_missing_identities,
)
from plan_manager.storage.reference_catalog import REFERENCE_CATALOG
from plan_manager.storage.relation_index_store import (
    compute_canonical_triples,
    record_reference,
    referrers_of,
    replace_index,
)

# Re-exported for callers of this module's C-009 surface; see the module
# docstring's REGISTRY RECOVERY section. audit_registry and
# restore_missing_identities are used exactly as identity_audit defines them.
__all__ = [
    "NULLABLE",
    "NOT_NULLABLE",
    "UNKNOWN",
    "nullability_for",
    "find_dangling_references",
    "clear_reference",
    "delete_carrier",
    "audit_registry",
    "restore_missing_identities",
    "remove_unreferenced_extra_identities",
    "rebuild_relation_index",
]


NULLABLE = "nullable"
NOT_NULLABLE = "not_nullable"
UNKNOWN = "unknown"
"""The three nullability verdicts :func:`nullability_for` returns.

Only NULLABLE admits :func:`clear_reference`; NOT_NULLABLE and UNKNOWN both
refuse it, deliberately treated alike by the caller -- an unclearable column
is unclearable whether that is because the schema forbids it or because this
module could not find out.
"""


# ---------------------------------------------------------------------------
# Tier 0: nullability classification shared by find (reporting) and clear
# (admission).
# ---------------------------------------------------------------------------


def _table_class_map() -> dict[str, type]:
    """Every registered entity class, indexed by its real TABLE_NAME.

    Rebuilt on every call rather than cached at import time: entity classes
    are discovered by walking DataclassEntity subclasses (see
    reference_catalog._entity_classes), which itself imports every
    plan_manager.domain module on first use, and doing that lazily here
    keeps this module free of import-order requirements. A class whose
    TABLE_NAME is None (Paragraph: the paragraph table is not addressed
    through this registry) is naturally absent from the map, which is what
    makes a paragraph column resolve to UNKNOWN below rather than raising.
    """
    # Imported lazily and by its private name deliberately: domain/entity.py
    # already imports this same private helper directly for the identical
    # reason (see _walk_recursive_admission), so this is a precedented reuse
    # of the one table-name-keyed walk, not a new pattern.
    from plan_manager.storage.reference_catalog import _entity_classes

    return {cls.TABLE_NAME: cls for cls in _entity_classes() if cls.TABLE_NAME}


def nullability_for(source_table: str, source_column: str) -> str:
    """Classify one catalogued reference column as NULLABLE/NOT_NULLABLE/UNKNOWN.

    See the module docstring's NULLABILITY section for the full rationale.
    Reads the resolved type hint of the dataclass field named exactly
    ``source_column`` on the entity class whose TABLE_NAME is
    ``source_table``; a ``X | None`` (or ``Optional[X]``) hint means
    NULLABLE, any other concrete hint means NOT_NULLABLE, and anything this
    lookup cannot reach -- no such class, no such field, or a hint that does
    not resolve at all -- means UNKNOWN.
    """
    entity_cls = _table_class_map().get(source_table)
    if entity_cls is None:
        return UNKNOWN
    try:
        hints = typing.get_type_hints(entity_cls)
    except Exception:  # noqa: BLE001 - an unresolvable annotation is unknown, not fatal
        return UNKNOWN
    hint = hints.get(source_column)
    if hint is None:
        return UNKNOWN
    args = typing.get_args(hint)
    if not args:
        return NOT_NULLABLE
    return NULLABLE if type(None) in args else NOT_NULLABLE


# ---------------------------------------------------------------------------
# Tier 1: find (read-only).
# ---------------------------------------------------------------------------


def find_dangling_references(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Scan every catalogued scalar UUID column for values the registry cannot resolve.

    Walks the same subset of REFERENCE_CATALOG that
    relation_index_store.compute_canonical_triples walks -- single-uuid,
    non-array target columns; scoped (concept) and array (Step.concepts)
    entries are out of scope for a scalar UUID repair surface by
    construction, not by omission. A source table absent from this schema
    (or a column absent from it) is simply not scanned, mirroring that same
    function's tolerance.

    Returns:
        One dict per dangling reference, ordered by (source_table,
        source_column, source_ref) for determinism, each with:
            source_table, source_column: where the value lives.
            source_ref: the referring row's own ``uuid`` column value.
            property_name: the property name (same as source_column) --
                named separately because it is also the relation-index
                field-catalogue key (reference_catalog.ensure_reference_field).
            missing_target: the value that does not resolve.
            target_table: the table the column is supposed to reference.
            nullability: NULLABLE/NOT_NULLABLE/UNKNOWN (see nullability_for).
    """
    findings: list[dict[str, Any]] = []
    for (source_table, source_column), entry in sorted(REFERENCE_CATALOG.items()):
        if entry.target_column != "uuid" or entry.array:
            continue
        try:
            rows = conn.execute(
                f"SELECT uuid, {source_column} FROM {source_table} "
                f"WHERE {source_column} IS NOT NULL"
            ).fetchall()
        except Exception:  # noqa: BLE001 - a missing table/column is simply not scanned
            continue
        if not rows:
            continue
        candidates = list({row[1] for row in rows})
        resolved = resolve_entity_identities_batch(conn, candidates)
        nullability = nullability_for(source_table, source_column)
        for source_ref, target_value in sorted(rows, key=lambda row: str(row[0])):
            if target_value in resolved:
                continue
            findings.append(
                {
                    "source_table": source_table,
                    "source_column": source_column,
                    "source_ref": source_ref,
                    "property_name": source_column,
                    "missing_target": target_value,
                    "target_table": entry.target_table,
                    "nullability": nullability,
                }
            )
    return findings


# ---------------------------------------------------------------------------
# Tier 2: clear (admitted only where nullable).
# ---------------------------------------------------------------------------


def clear_reference(
    conn: psycopg.Connection,
    *,
    source_table: str,
    source_column: str,
    source_ref: uuid.UUID,
) -> dict[str, Any]:
    """Null one dangling reference field and retire its relation-index triple.

    Admitted only when nullability_for(source_table, source_column) reports
    NULLABLE; NOT_NULLABLE and UNKNOWN both raise PermissionError. This is a
    direct parameterized UPDATE rather than the entity class's caller-facing
    crud_update: the repair surface intentionally reaches columns ordinary
    CRUD does not always expose for update (immutable anchors, historical
    fields), and an UPDATE statement is outside the
    cr7-no-out-of-mechanism-write scan's scope by construction -- that scan
    watches only INSERT/DELETE on registered tables (see
    pipeline_checks.registry.g004_scan), never UPDATE.

    Args:
        source_table, source_column: identify the catalogued column
            (must be a REFERENCE_CATALOG key).
        source_ref: the referring row's own ``uuid`` column value.

    Returns:
        {"source_table", "source_column", "source_ref", "cleared": True}.

    Raises:
        KeyError: (source_table, source_column) is not a catalogued
            reference at all.
        PermissionError: the column's nullability is not NULLABLE.
    """
    entry = REFERENCE_CATALOG.get((source_table, source_column))
    if entry is None:
        raise KeyError(f"not a catalogued reference: {source_table}.{source_column}")
    nullability = nullability_for(source_table, source_column)
    if nullability != NULLABLE:
        raise PermissionError(
            f"{source_table}.{source_column} is {nullability}; clear refused "
            "(only a statically-nullable column may be cleared)"
        )
    query = sql.SQL("UPDATE {} SET {} = NULL WHERE uuid = %s AND {} IS NOT NULL").format(
        sql.Identifier(entry.source_table),
        sql.Identifier(entry.source_column),
        sql.Identifier(entry.source_column),
    )
    conn.execute(query, (source_ref,))
    # Retire the relation-index triple for this (source, property) pair in the
    # same transaction; target_ref=None deletes the old triple and inserts
    # nothing, exactly the "the reference was nulled" branch record_reference
    # already implements for ordinary CRUD writes.
    record_reference(conn, source_ref=source_ref, target_ref=None, property_name=source_column)
    return {
        "source_table": source_table,
        "source_column": source_column,
        "source_ref": source_ref,
        "cleared": True,
    }


# ---------------------------------------------------------------------------
# Tier 3: delete-carrier (dry-run by default; real removal delegates to the
# set-wise purge engine unchanged).
# ---------------------------------------------------------------------------


def delete_carrier(
    conn: psycopg.Connection,
    entity_ids: Iterable[uuid.UUID],
    *,
    dry_run: bool = True,
    changed_by: str = "system",
) -> dict[str, Any]:
    """Remove the entities carrying irreparable dangling references.

    Danger tier 3: the row itself is removed, not just the offending field.
    Delegates the actual removal to
    plan_manager.storage.runtime_hard_delete.hard_delete_marked_set so every
    rule of the set-wise purge discipline (C-008) applies unchanged --
    including that every explicit starting id must already be marked
    (soft-deleted); this function performs no soft-delete of its own.

    dry_run=True (the default) never calls that engine and never writes:
    it independently walks the same fixed-point closure over marked
    referrers (via relation_index_store.referrers_of) and reports the same
    admission verdict the engine would reach, purely by reading.

    Args:
        entity_ids: the explicit starting identifiers (already marked, for a
            live call to succeed).
        dry_run: default True. False performs the real removal.
        changed_by: actor recorded on the audit trail of a live removal.

    Returns:
        Live (dry_run=False): {"dry_run": False, "removed": [uuid, ...]}
            -- passed through from hard_delete_marked_set.
        Dry run: {"dry_run": True, "would_remove": [...], "blocked_by": [...],
            "unresolved": [...], "admissible": bool} -- "would_remove" is the
            closed working set, "blocked_by" the relation-index triples that
            would refuse the whole operation (empty when admissible),
            "unresolved" the given ids the identity registry does not know.
    """
    ids = list(dict.fromkeys(entity_ids))
    if not dry_run:
        # Imported locally: mirrors runtime_hard_delete's own local imports of
        # its collaborators, and keeps this module free of a module-level
        # dependency on the set-wise engine for callers that only ever use
        # find/clear.
        from plan_manager.storage.runtime_hard_delete import hard_delete_marked_set

        result = hard_delete_marked_set(conn, ids, changed_by=changed_by)
        return {"dry_run": False, "removed": result["removed"]}
    return {"dry_run": True, **_preview_marked_closure(conn, ids)}


def _preview_marked_closure(conn: psycopg.Connection, ids: list[uuid.UUID]) -> dict[str, Any]:
    """Read-only mirror of hard_delete_marked_set's closure and admission.

    Reuses runtime_hard_delete's own "is this row currently marked" check
    (_is_marked) rather than re-implementing it, so the dry-run preview and
    the live engine can never disagree about what "marked" means. Touches
    nothing: only SELECTs, via resolve_entity_identities_batch and
    referrers_of, exactly like the engine's own closure phase before it ever
    reaches removal.
    """
    from plan_manager.storage.reference_catalog import resolve_entity_class
    from plan_manager.storage.runtime_hard_delete import _is_marked

    id_to_class: dict[uuid.UUID, type] = {}
    unresolved: list[uuid.UUID] = []
    resolved = resolve_entity_identities_batch(conn, ids)
    for entity_id in ids:
        info = resolved.get(entity_id)
        if info is None:
            unresolved.append(entity_id)
            continue
        try:
            id_to_class[entity_id] = resolve_entity_class(info["entity_type"])
        except ValueError:
            unresolved.append(entity_id)

    working_set: set[uuid.UUID] = set(id_to_class)
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
                continue
            try:
                referrer_cls = resolve_entity_class(info["entity_type"])
            except ValueError:
                continue
            if referrer_cls.SOFT_DELETE_COLUMN is not None and _is_marked(
                conn, referrer_cls, source_ref
            ):
                id_to_class[source_ref] = referrer_cls
                working_set.add(source_ref)
                frontier.add(source_ref)

    final_triples = referrers_of(conn, working_set) if working_set else []
    blocking = [triple for triple in final_triples if triple["source_ref"] not in working_set]
    return {
        "would_remove": sorted(working_set, key=str),
        "blocked_by": blocking,
        "unresolved": unresolved,
        "admissible": not blocking,
    }


# ---------------------------------------------------------------------------
# Registry recovery (C-009). audit_registry and restore_missing_identities
# are re-exported as-is from identity_audit (see module docstring); the two
# functions below are the only logic this module adds on top of that set.
# ---------------------------------------------------------------------------


def remove_unreferenced_extra_identities(
    conn: psycopg.Connection, audit_report: dict[str, Any] | None = None
) -> dict[str, list[uuid.UUID]]:
    """Remove every "extra" registry entry that nothing references, batched.

    Runs audit_registry first when no report is supplied. Each entry is
    removed via identity_audit.remove_extra_identity_if_unreferenced, which
    already refuses a referenced entry on its own (CR-7 c7r6: a referenced
    extra entry stays so a caller can restore the missing row with
    create(recovery_mode=true)); this function only adds the batching over
    every entry an audit found.

    Returns:
        {"removed": [...], "retained": [...]} -- the ids removed and the
        ids kept because something still references them (or the relation
        index was unavailable).
    """
    report = audit_report if audit_report is not None else audit_registry(conn)
    removed: list[uuid.UUID] = []
    retained: list[uuid.UUID] = []
    for entry in report["extra"]:
        entity_id = entry["id"]
        if remove_extra_identity_if_unreferenced(conn, entity_id):
            removed.append(entity_id)
        else:
            retained.append(entity_id)
    return {"removed": removed, "retained": retained}


def rebuild_relation_index(conn: psycopg.Connection) -> dict[str, int]:
    """Recompute and atomically replace the whole relation index, in one transaction.

    Wraps relation_index_store.compute_canonical_triples (the scan) and
    replace_index (the atomic DELETE-then-INSERT-all) so the recovered
    registry's canonical triples become the stored index as a single unit,
    on the caller's own connection/transaction -- neither call commits.

    Returns:
        {"written": int} -- the number of triples written.
    """
    triples = compute_canonical_triples(conn)
    written = replace_index(conn, triples)
    return {"written": written}
