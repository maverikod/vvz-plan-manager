"""Regression suite for CR-7 G-001/T-002/A-002: the derived relation index.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import uuid

from plan_manager.storage.relation_index_store import (
    record_reference,
    referrers_of,
    references_from,
    replace_index,
)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _ScriptedConn:
    """Matches statements by predicate; records everything executed."""

    def __init__(self, script=None):
        self._script = list(script or [])
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        flat = " ".join(str(sql).split())
        self.executed.append((flat, tuple(params)))
        for predicate, rows in self._script:
            if predicate(flat):
                return _FakeCursor(rows)
        return _FakeCursor([])


def _field_hit(field_ref):
    return (
        lambda sql: sql.startswith("SELECT field_ref FROM reference_field"),
        [(field_ref,)],
    )


def test_record_replaces_the_old_triple_and_inserts_the_new_one() -> None:
    source, target, field_ref = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = _ScriptedConn(
        [
            _field_hit(field_ref),
            (
                lambda sql: sql.startswith("SELECT id, table_name, entity_type"),
                [(target, "plan", "plan", None)],
            ),
        ]
    )

    used = record_reference(
        conn, source_ref=source, target_ref=target, property_name="plan_uuid"
    )

    assert used == field_ref
    statements = [sql for sql, _ in conn.executed]
    delete_pos = next(i for i, s in enumerate(statements) if s.startswith("DELETE FROM relation_index"))
    insert_pos = next(i for i, s in enumerate(statements) if s.startswith("INSERT INTO relation_index"))
    assert delete_pos < insert_pos  # replace-on-change, never update-in-place
    assert conn.executed[insert_pos][1] == (source, target, field_ref)


def test_record_with_none_clears_the_property_without_a_new_triple() -> None:
    source, field_ref = uuid.uuid4(), uuid.uuid4()
    conn = _ScriptedConn([_field_hit(field_ref)])

    assert record_reference(
        conn, source_ref=source, target_ref=None, property_name="plan_uuid"
    ) is None
    statements = [sql for sql, _ in conn.executed]
    assert any(s.startswith("DELETE FROM relation_index") for s in statements)
    assert not any(s.startswith("INSERT INTO relation_index") for s in statements)


def test_a_uuid_outside_the_registry_is_not_a_reference() -> None:
    source, stranger, field_ref = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = _ScriptedConn(
        [
            _field_hit(field_ref),
            (lambda sql: sql.startswith("SELECT id, table_name, entity_type"), []),
        ]
    )

    assert record_reference(
        conn, source_ref=source, target_ref=stranger, property_name="plan_uuid"
    ) is None
    assert not any(
        sql.startswith("INSERT INTO relation_index") for sql, _ in conn.executed
    )


def test_batch_lookups_short_circuit_on_empty_input() -> None:
    conn = _ScriptedConn()
    assert referrers_of(conn, []) == []
    assert references_from(conn, []) == []
    assert conn.executed == []


def test_batch_lookups_return_triple_dicts() -> None:
    source, target, field_ref = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    conn = _ScriptedConn(
        [
            (
                lambda sql: "WHERE target_ref = ANY" in sql,
                [(source, target, field_ref)],
            )
        ]
    )
    rows = referrers_of(conn, [target])
    assert rows == [
        {"source_ref": source, "target_ref": target, "field_ref": field_ref}
    ]


def test_replace_index_is_a_single_delete_then_reinsert_pass() -> None:
    triples = [(uuid.uuid4(), uuid.uuid4(), uuid.uuid4()) for _ in range(3)]
    conn = _ScriptedConn()

    written = replace_index(conn, triples)

    assert written == 3
    statements = [sql for sql, _ in conn.executed]
    assert statements[0] == "DELETE FROM relation_index"
    assert sum(1 for s in statements if s.startswith("INSERT INTO relation_index")) == 3
