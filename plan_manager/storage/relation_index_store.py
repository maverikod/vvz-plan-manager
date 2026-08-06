"""Derived relation index over immutable source-target-field triples.

CR-7 G-001/T-002/A-002 (C-003). Canonical references live in scalar UUID
columns of source entity rows; this index is a derived projection of those
values for speed, never canonical truth. A concrete non-NULL UUID value is an
entity reference exactly when it resolves through the identity registry —
membership is the sole criterion, consumed from the identity helpers, not
re-implemented here. A marked (soft-deleted) target remains an admissible
reference target.

Triples are immutable: changing a source property deletes its old triple and
creates the new one inside the same CRUD transaction; a triple is never
updated in place. Distinct source properties keep distinct field refs even
when they point at the same target — field refs come from the reference-field
catalogue's ensure operation.

Rebuild support treats the stored index as replaceable: canonical triples are
recomputed by scanning the catalogued base-table UUID columns against the
registry, diffed against the stored index, and the index can be replaced
atomically inside the caller's transaction.
"""

from __future__ import annotations

import uuid
from typing import Any, Iterable

import psycopg

from plan_manager.storage.identity import resolve_entity_identities_batch
from plan_manager.storage.reference_catalog import (
    REFERENCE_CATALOG,
    ensure_reference_field,
)

Triple = tuple[uuid.UUID, uuid.UUID, uuid.UUID]
"""(source_ref, target_ref, field_ref) — the immutable relation triple."""


def record_reference(
    conn: psycopg.Connection,
    *,
    source_ref: uuid.UUID,
    target_ref: uuid.UUID | None,
    property_name: str,
) -> uuid.UUID | None:
    """Project one source-property write into the index, replace-on-change.

    Deletes the property's previous triple and, when target_ref is a
    registry-resolvable reference, inserts the new one — both inside the
    caller's CRUD transaction. target_ref=None clears the property (the
    reference was nulled). A UUID that does not resolve through the registry
    is not an entity reference and produces no triple (the old triple is
    still cleared: the property no longer holds a reference).

    Returns:
        The field_ref used, or None when the property cleared to no triple.
    """
    field_ref = ensure_reference_field(conn, property_name)
    conn.execute(
        "DELETE FROM relation_index WHERE source_ref = %s AND field_ref = %s",
        (source_ref, field_ref),
    )
    if target_ref is None:
        return None
    resolved = resolve_entity_identities_batch(conn, [target_ref])
    if target_ref not in resolved:
        return None
    conn.execute(
        "INSERT INTO relation_index (source_ref, target_ref, field_ref) "
        "VALUES (%s, %s, %s)",
        (source_ref, target_ref, field_ref),
    )
    return field_ref


def referrers_of(
    conn: psycopg.Connection, target_refs: Iterable[uuid.UUID]
) -> list[dict[str, Any]]:
    """Every stored triple pointing AT any of the given targets, batch-shaped."""
    targets = list(target_refs)
    if not targets:
        return []
    rows = conn.execute(
        "SELECT source_ref, target_ref, field_ref FROM relation_index "
        "WHERE target_ref = ANY(%s)",
        (targets,),
    ).fetchall()
    return [
        {"source_ref": row[0], "target_ref": row[1], "field_ref": row[2]}
        for row in rows
    ]


def references_from(
    conn: psycopg.Connection, source_refs: Iterable[uuid.UUID]
) -> list[dict[str, Any]]:
    """Every stored triple originating FROM any of the given sources."""
    sources = list(source_refs)
    if not sources:
        return []
    rows = conn.execute(
        "SELECT source_ref, target_ref, field_ref FROM relation_index "
        "WHERE source_ref = ANY(%s)",
        (sources,),
    ).fetchall()
    return [
        {"source_ref": row[0], "target_ref": row[1], "field_ref": row[2]}
        for row in rows
    ]


def compute_canonical_triples(conn: psycopg.Connection) -> set[Triple]:
    """Recompute the canonical triple set from base tables and the registry.

    Scans every catalogued (source_table, source_column) pair whose target
    column is the single-column entity ref, pairing each row's own uuid with
    the referenced value, and admits a triple only when the referenced value
    resolves through the registry. Expensive by design — this is the
    maintenance path; ordinary CRUD updates the index incrementally.
    """
    triples: set[Triple] = set()
    for (source_table, source_column), entry in sorted(REFERENCE_CATALOG.items()):
        if entry.target_column != "uuid" or entry.array:
            continue
        try:
            rows = conn.execute(
                f"SELECT uuid, {source_column} FROM {source_table} "
                f"WHERE {source_column} IS NOT NULL"
            ).fetchall()
        except Exception:  # noqa: BLE001 - a missing table is simply not scanned
            continue
        if not rows:
            continue
        candidates = list({row[1] for row in rows})
        resolved = resolve_entity_identities_batch(conn, candidates)
        field_ref = ensure_reference_field(conn, source_column)
        for row in rows:
            if row[1] in resolved:
                triples.add((row[0], row[1], field_ref))
    return triples


def diff_index(conn: psycopg.Connection) -> dict[str, list[Triple]]:
    """Compare stored triples with the recomputed canonical set."""
    canonical = compute_canonical_triples(conn)
    stored_rows = conn.execute(
        "SELECT source_ref, target_ref, field_ref FROM relation_index",
        (),
    ).fetchall()
    stored = {(row[0], row[1], row[2]) for row in stored_rows}
    return {
        "missing": sorted(canonical - stored, key=str),
        "extra": sorted(stored - canonical, key=str),
    }


def replace_index(conn: psycopg.Connection, triples: Iterable[Triple]) -> int:
    """Replace the whole stored index with the given triple set, atomically.

    Runs inside the caller's transaction: the DELETE and every INSERT commit
    together or roll back together. Returns the number of triples written.
    """
    conn.execute("DELETE FROM relation_index", ())
    written = 0
    for source_ref, target_ref, field_ref in triples:
        conn.execute(
            "INSERT INTO relation_index (source_ref, target_ref, field_ref) "
            "VALUES (%s, %s, %s)",
            (source_ref, target_ref, field_ref),
        )
        written += 1
    return written
