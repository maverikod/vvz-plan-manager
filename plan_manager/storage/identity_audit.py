"""Registry audit, rebuild and v4-validation helpers (CR-7 G-001/T-001/A-001).

Split out of plan_manager.storage.identity to honour the 400-line file
budget; identity re-exports this surface, so callers import from either
module. The registry stays a derived index for speed, never canonical truth.
"""

import uuid
from typing import Any

import psycopg

from plan_manager.storage.identity import (
    ALLOWED_TABLES,
    ENTITY_KIND,
    new_entity_uuid,
    register_entity_identity,
)


def ensure_v4_entity_uuid(value: uuid.UUID | str | None = None) -> uuid.UUID:
    """Mint or validate the immutable ref identity (CR-7 G-001/T-001/A-001).

    Ordinary creation generates a version-4 UUID when the caller supplies no
    ref, and accepts a caller-supplied ref only when it is a valid version-4
    UUID; any other input is an error. The returned value is the sole
    immutable identity of the entity row and never changes afterwards.

    Parameters:
        value: uuid.UUID | str | None
            The caller-supplied candidate ref, or None to mint a fresh one.

    Returns:
        uuid.UUID
            A version-4 UUID: either the validated candidate or a new one.

    Raises:
        ValueError
            When the candidate does not parse as a UUID at all, or parses
            but is not version 4. The message names the offending value.
    """
    if value is None:
        return new_entity_uuid()
    if isinstance(value, uuid.UUID):
        candidate = value
    else:
        try:
            candidate = uuid.UUID(str(value))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid entity uuid: {value!r}") from exc
    if candidate.version != 4:
        raise ValueError(
            f"entity uuid must be version 4: {candidate} (version={candidate.version})"
        )
    return candidate


PRIMARY_KEY_COLUMNS: dict[str, str] = {}
"""Per-table override of the canonical identity column used by the audit.

Every ALLOWED_TABLES member defaults to a ``uuid`` column; a table whose
identity lives under another column name is declared here explicitly. The
audit treats a table it cannot scan as *unscanned*, never as clean.
"""


def audit_registry(conn: psycopg.Connection) -> dict[str, Any]:
    """Compare the derived identity registry with canonical entity rows.

    The registry is a derived index for speed, never canonical truth
    (CR-7 C-001): this audit reads every ALLOWED_TABLES member and the
    registry's ENTITY_KIND rows and reports their differences without
    mutating either side. Namespace reservations (RESERVED_KIND) are not
    entity rows and are ignored here.

    Returns:
        dict[str, Any] with four lists:
            missing: canonical rows with no registry entry, each as
                {"id", "table_name"} — recoverable via
                restore_missing_identities.
            extra: registry entries whose canonical row is absent, each as
                {"id", "table_name"} — removable only when unreferenced
                (remove_extra_identity_if_unreferenced); a referenced entry
                is retained so create with recovery_mode can restore the row.
            conflicts: identifiers whose registry table and canonical table
                disagree, or which appear in more than one canonical table,
                each as {"id", "registry_table", "canonical_tables"}.
            unscanned: tables the audit could not read (missing table or
                identity column), each as {"table_name", "reason"} — an
                unscanned table is an open question, not a clean verdict.
    """
    registry: dict[uuid.UUID, str] = {}
    rows = conn.execute(
        "SELECT id, table_name FROM entity_identity WHERE kind = %s",
        (ENTITY_KIND,),
    ).fetchall()
    for row in rows:
        registry[row[0]] = row[1]

    canonical: dict[uuid.UUID, list[str]] = {}
    unscanned: list[dict[str, str]] = []
    for table in sorted(ALLOWED_TABLES):
        column = PRIMARY_KEY_COLUMNS.get(table, "uuid")
        try:
            table_rows = conn.execute(f"SELECT {column} FROM {table}").fetchall()
        except Exception as exc:  # noqa: BLE001 - any scan failure is reported, never swallowed
            unscanned.append({"table_name": table, "reason": str(exc)})
            continue
        for table_row in table_rows:
            canonical.setdefault(table_row[0], []).append(table)

    missing = [
        {"id": entity_id, "table_name": tables[0]}
        for entity_id, tables in sorted(canonical.items(), key=lambda item: str(item[0]))
        if entity_id not in registry and len(tables) == 1
    ]
    extra = [
        {"id": entity_id, "table_name": table}
        for entity_id, table in sorted(registry.items(), key=lambda item: str(item[0]))
        if entity_id not in canonical
    ]
    conflicts: list[dict[str, Any]] = []
    for entity_id, tables in sorted(canonical.items(), key=lambda item: str(item[0])):
        registry_table = registry.get(entity_id)
        if len(tables) > 1 or (registry_table is not None and registry_table not in tables):
            conflicts.append(
                {
                    "id": entity_id,
                    "registry_table": registry_table,
                    "canonical_tables": sorted(tables),
                }
            )
    return {
        "missing": missing,
        "extra": extra,
        "conflicts": conflicts,
        "unscanned": unscanned,
    }


def restore_missing_identities(
    conn: psycopg.Connection, audit_report: dict[str, Any] | None = None
) -> int:
    """Restore registry entries for canonical rows the audit found missing.

    Runs audit_registry first when no report is supplied, then registers
    each missing identifier from its target row via register_entity_identity
    (idempotent by design). Conflicted identifiers are never auto-restored:
    a cross-table conflict needs a human decision, not a silent write.

    Returns:
        int: the number of registry entries written.
    """
    report = audit_report if audit_report is not None else audit_registry(conn)
    restored = 0
    for entry in report["missing"]:
        register_entity_identity(
            conn,
            entity_id=entry["id"],
            table_name=entry["table_name"],
            entity_type=entry["table_name"],
        )
        restored += 1
    return restored


def remove_extra_identity_if_unreferenced(
    conn: psycopg.Connection, entity_id: uuid.UUID
) -> bool:
    """Remove one extra registry entry, but only when nothing references it.

    An extra entry whose identifier is still referenced anywhere is retained
    on purpose: keeping it lets a caller restore the missing entity by create
    with recovery_mode=true instead of orphaning the referrers (CR-7 c7r6).
    Reference evidence comes from the derived relation index; when that index
    is not deployed yet, the entry is conservatively retained.

    Returns:
        bool: True when the entry was removed, False when it was retained
        (referenced, or the relation index is unavailable).
    """
    index_row = conn.execute(
        "SELECT to_regclass('relation_index')",
        (),
    ).fetchone()
    if index_row is None or index_row[0] is None:
        return False
    referenced = conn.execute(
        "SELECT 1 FROM relation_index WHERE target_ref = %s OR source_ref = %s LIMIT 1",
        (entity_id, entity_id),
    ).fetchone()
    if referenced is not None:
        return False
    conn.execute(
        "DELETE FROM entity_identity WHERE id = %s AND kind = %s",
        (entity_id, ENTITY_KIND),
    )
    return True
