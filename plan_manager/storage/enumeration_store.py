"""Closed-enumeration and enumeration-value storage.

CR-7 G-001/T-003/A-001 (C-004). Exactly one shared enumeration store and one
shared value store for every closed vocabulary of the system. Each enumeration
and each value is an entity record with an immutable ref identity registered
through the identity helpers; a value row carries its enumeration association
and a stable value identifier.

Admission boundary, by design:
  * Runtime callers get READ access only - the list/get surfaces below. This
    module deliberately exports no mutating function for ordinary CRUD.
  * Creation, modification and deletion of enumerations and values are
    admitted only to code-and-schema migration paths through the single,
    explicitly named schema-update entry point ``schema_update_enumerations``.
    Migrations pass their vocabularies in; nothing here hard-codes a value
    list.
Seeding is deterministic and idempotent: re-applying the same vocabulary
changes nothing, and stable identifiers survive re-seeding.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping, Sequence

import psycopg

from plan_manager.storage.identity import (
    ensure_v4_entity_uuid,
    register_entity_identity,
)

_ENUMERATION_TABLE = "enumeration"
_VALUE_TABLE = "enumeration_value"


# ---------------------------------------------------------------------------
# Runtime read surface (the only access ordinary CRUD receives).
# ---------------------------------------------------------------------------


def get_enumeration(conn: psycopg.Connection, name: str) -> dict[str, Any] | None:
    """Return {"ref", "name"} for one enumeration, or None when absent."""
    row = conn.execute(
        f"SELECT ref, name FROM {_ENUMERATION_TABLE} WHERE name = %s",
        (name,),
    ).fetchone()
    if row is None:
        return None
    return {"ref": row[0], "name": row[1]}


def list_enumerations(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Every enumeration, ordered by name."""
    rows = conn.execute(
        f"SELECT ref, name FROM {_ENUMERATION_TABLE} ORDER BY name",
        (),
    ).fetchall()
    return [{"ref": row[0], "name": row[1]} for row in rows]


def list_enumeration_values(
    conn: psycopg.Connection, name: str
) -> list[dict[str, Any]]:
    """Every value of one enumeration, ordered by its stable identifier."""
    rows = conn.execute(
        f"SELECT v.ref, v.value FROM {_VALUE_TABLE} v "
        f"JOIN {_ENUMERATION_TABLE} e ON e.ref = v.enumeration_ref "
        "WHERE e.name = %s ORDER BY v.value",
        (name,),
    ).fetchall()
    return [{"ref": row[0], "value": row[1]} for row in rows]


def enumeration_values(conn: psycopg.Connection, name: str) -> list[str]:
    """The plain closed value list of one enumeration (schema-enum shape)."""
    return [entry["value"] for entry in list_enumeration_values(conn, name)]


# ---------------------------------------------------------------------------
# The single schema-update mutation admission.
# ---------------------------------------------------------------------------


def schema_update_enumerations(
    conn: psycopg.Connection,
    vocabularies: Mapping[str, Sequence[str]],
    *,
    fixed_refs: Mapping[str, uuid.UUID | str] | None = None,
    remove_missing_values: bool = False,
) -> dict[str, Any]:
    """Create or align closed vocabularies - migrations' ONLY entry point.

    Idempotent and deterministic: an enumeration or value that already exists
    is left untouched (its ref is stable across re-application). fixed_refs
    lets a migration pin deterministic refs by key - the enumeration name for
    an enumeration row, "<enumeration>.<value>" for a value row - so the same
    migration text yields the same identities on every database.

    remove_missing_values=True additionally deletes value rows the supplied
    vocabulary no longer contains; that too is a code-and-schema decision,
    never reachable from runtime CRUD.

    Returns:
        {"created_enumerations", "created_values", "removed_values"} counts.
    """
    pinned = dict(fixed_refs or {})
    created_enumerations = 0
    created_values = 0
    removed_values = 0
    for name in sorted(vocabularies):
        values = vocabularies[name]
        existing = get_enumeration(conn, name)
        if existing is None:
            enum_ref = ensure_v4_entity_uuid(pinned.get(name))
            conn.execute(
                f"INSERT INTO {_ENUMERATION_TABLE} (ref, name) VALUES (%s, %s) "
                "ON CONFLICT (name) DO NOTHING",
                (enum_ref, name),
            )
            register_entity_identity(
                conn,
                entity_id=enum_ref,
                table_name=_ENUMERATION_TABLE,
                entity_type="enumeration",
            )
            created_enumerations += 1
        else:
            enum_ref = existing["ref"]

        stored = {entry["value"] for entry in list_enumeration_values(conn, name)}
        for value in values:
            if value in stored:
                continue
            value_ref = ensure_v4_entity_uuid(pinned.get(f"{name}.{value}"))
            conn.execute(
                f"INSERT INTO {_VALUE_TABLE} (ref, enumeration_ref, value) "
                "VALUES (%s, %s, %s) "
                "ON CONFLICT (enumeration_ref, value) DO NOTHING",
                (value_ref, enum_ref, value),
            )
            register_entity_identity(
                conn,
                entity_id=value_ref,
                table_name=_VALUE_TABLE,
                entity_type="enumeration_value",
            )
            created_values += 1
        if remove_missing_values:
            obsolete = sorted(stored - set(values))
            for value in obsolete:
                conn.execute(
                    f"DELETE FROM {_VALUE_TABLE} "
                    "WHERE enumeration_ref = %s AND value = %s",
                    (enum_ref, value),
                )
                removed_values += 1
    return {
        "created_enumerations": created_enumerations,
        "created_values": created_values,
        "removed_values": removed_values,
    }
