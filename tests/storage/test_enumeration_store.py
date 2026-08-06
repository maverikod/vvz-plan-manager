"""Regression suite for CR-7 G-001/T-003/A-001: closed-enumeration storage.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import uuid

import pytest

import plan_manager.storage.enumeration_store as enum_store
from plan_manager.storage.enumeration_store import (
    enumeration_values,
    get_enumeration,
    schema_update_enumerations,
)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _ScriptedConn:
    """Consumes scripted result sets in call order; records every statement."""

    def __init__(self, rows_per_call):
        self._rows_per_call = list(rows_per_call)
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        self.executed.append((" ".join(str(sql).split()), tuple(params)))
        rows = self._rows_per_call.pop(0) if self._rows_per_call else []
        return _FakeCursor(rows)


def test_runtime_surface_exports_no_ordinary_mutation() -> None:
    """The module's public surface is read-only apart from the one schema gate."""
    mutating = [
        name
        for name in dir(enum_store)
        if not name.startswith("_")
        and callable(getattr(enum_store, name))
        and any(verb in name for verb in ("create", "update", "delete", "add", "remove", "set"))
        and name != "schema_update_enumerations"
    ]
    assert mutating == [], f"unexpected mutating exports: {mutating}"


def test_seed_creates_enumeration_and_values_with_pinned_refs() -> None:
    enum_ref = uuid.uuid4()
    value_ref = uuid.uuid4()
    conn = _ScriptedConn(
        [
            [],  # get_enumeration: absent
            [],  # INSERT enumeration
            [],  # register enumeration identity
            [],  # list values: empty
            [],  # INSERT value
            [],  # register value identity
        ]
    )

    report = schema_update_enumerations(
        conn,
        {"bug_kind": ["functional"]},
        fixed_refs={"bug_kind": enum_ref, "bug_kind.functional": value_ref},
    )

    assert report == {
        "created_enumerations": 1,
        "created_values": 1,
        "removed_values": 0,
    }
    inserts = [entry for entry in conn.executed if entry[0].startswith("INSERT INTO enumeration")]
    assert inserts[0][1][0] == enum_ref  # pinned deterministic refs survive
    assert inserts[1][1][0] == value_ref
    registry = [sql for sql, _ in conn.executed if sql.startswith("INSERT INTO entity_identity")]
    assert len(registry) == 2  # both records registered as entities


def test_reapplying_the_same_vocabulary_changes_nothing() -> None:
    enum_ref = uuid.uuid4()
    conn = _ScriptedConn(
        [
            [(enum_ref, "bug_kind")],           # enumeration already present
            [(uuid.uuid4(), "functional")],      # value already present
        ]
    )
    report = schema_update_enumerations(conn, {"bug_kind": ["functional"]})
    assert report == {
        "created_enumerations": 0,
        "created_values": 0,
        "removed_values": 0,
    }
    assert not any(sql.startswith("INSERT") for sql, _ in conn.executed)


def test_remove_missing_values_is_an_explicit_schema_decision() -> None:
    enum_ref = uuid.uuid4()
    conn = _ScriptedConn(
        [
            [(enum_ref, "bug_kind")],
            [(uuid.uuid4(), "functional"), (uuid.uuid4(), "legacy")],
            [],  # DELETE of the obsolete value
        ]
    )
    report = schema_update_enumerations(
        conn, {"bug_kind": ["functional"]}, remove_missing_values=True
    )
    assert report["removed_values"] == 1
    deletes = [entry for entry in conn.executed if entry[0].startswith("DELETE FROM enumeration_value")]
    assert len(deletes) == 1
    assert deletes[0][1] == (enum_ref, "legacy")


def test_pinned_ref_must_be_a_valid_uuid4() -> None:
    conn = _ScriptedConn([[]])
    with pytest.raises(ValueError):
        schema_update_enumerations(
            conn, {"bug_kind": ["functional"]}, fixed_refs={"bug_kind": "not-a-uuid"}
        )


def test_read_surface_shapes() -> None:
    enum_ref = uuid.uuid4()
    conn = _ScriptedConn([[(enum_ref, "bug_kind")]])
    assert get_enumeration(conn, "bug_kind") == {"ref": enum_ref, "name": "bug_kind"}

    conn = _ScriptedConn([[(uuid.uuid4(), "functional"), (uuid.uuid4(), "regression")]])
    assert enumeration_values(conn, "bug_kind") == ["functional", "regression"]
