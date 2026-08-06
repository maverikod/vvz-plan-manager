"""Regression suite for CR-7 G-001/T-001/A-001: identity helpers and registry audit.

Fake psycopg connections only; no live PostgreSQL instance is required.
"""

from __future__ import annotations

import uuid

import pytest

from plan_manager.storage.identity import (
    ALLOWED_TABLES,
    ENTITY_KIND,
    audit_registry,
    ensure_v4_entity_uuid,
    remove_extra_identity_if_unreferenced,
    restore_missing_identities,
)


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class _ScriptedConn:
    """Replays scripted result sets per matching SQL prefix and records writes."""

    def __init__(self, script):
        # script: list of (predicate(sql) -> bool, rows) evaluated in order.
        self._script = list(script)
        self.executed: list[tuple[str, tuple]] = []

    def execute(self, sql, params=()):
        flat = " ".join(str(sql).split())
        self.executed.append((flat, tuple(params)))
        for predicate, rows in self._script:
            if predicate(flat):
                return _FakeCursor(rows)
        return _FakeCursor([])


def test_ensure_v4_mints_a_fresh_uuid4_when_omitted() -> None:
    minted = ensure_v4_entity_uuid(None)
    assert isinstance(minted, uuid.UUID)
    assert minted.version == 4


def test_ensure_v4_accepts_a_valid_v4_in_both_shapes() -> None:
    original = uuid.uuid4()
    assert ensure_v4_entity_uuid(original) == original
    assert ensure_v4_entity_uuid(str(original)) == original


def test_ensure_v4_rejects_garbage_and_non_v4() -> None:
    with pytest.raises(ValueError, match="invalid entity uuid"):
        ensure_v4_entity_uuid("not-a-uuid")
    v1 = uuid.uuid1()
    with pytest.raises(ValueError, match="must be version 4"):
        ensure_v4_entity_uuid(v1)
    with pytest.raises(ValueError, match="must be version 4"):
        ensure_v4_entity_uuid(str(uuid.uuid5(uuid.NAMESPACE_DNS, "x")))


def _registry_script(registry_rows, per_table_rows, broken_tables=()):
    """Build a script: registry SELECT, then one SELECT per allowed table."""

    def registry_pred(sql):
        return sql.startswith("SELECT id, table_name FROM entity_identity")

    script = [(registry_pred, registry_rows)]
    for table in sorted(ALLOWED_TABLES):
        rows = per_table_rows.get(table, [])
        if table in broken_tables:
            def broken(sql, table=table):
                if sql == f"SELECT uuid FROM {table}":
                    raise RuntimeError(f"relation {table} does not exist")
                return False

            script.append((broken, []))
        else:
            script.append(
                (lambda sql, table=table: sql == f"SELECT uuid FROM {table}", rows)
            )
    return script


def test_audit_detects_missing_extra_and_cross_table_conflicts() -> None:
    missing_id = uuid.uuid4()
    extra_id = uuid.uuid4()
    conflict_id = uuid.uuid4()
    duplicated_id = uuid.uuid4()
    clean_id = uuid.uuid4()

    registry_rows = [
        (extra_id, "plan"),          # registry-only: canonical row is gone
        (conflict_id, "concept"),    # registry says concept, row lives in plan
        (clean_id, "plan"),          # perfectly consistent
    ]
    per_table_rows = {
        "plan": [(missing_id,), (conflict_id,), (clean_id,), (duplicated_id,)],
        "step": [(duplicated_id,)],  # same id in two canonical tables
    }
    conn = _ScriptedConn(_registry_script(registry_rows, per_table_rows))

    report = audit_registry(conn)

    assert {entry["id"] for entry in report["missing"]} == {missing_id}
    assert report["missing"][0]["table_name"] == "plan"
    assert {entry["id"] for entry in report["extra"]} == {extra_id}
    conflict_ids = {entry["id"] for entry in report["conflicts"]}
    assert conflict_ids == {conflict_id, duplicated_id}
    by_id = {entry["id"]: entry for entry in report["conflicts"]}
    assert by_id[conflict_id]["registry_table"] == "concept"
    assert by_id[conflict_id]["canonical_tables"] == ["plan"]
    assert by_id[duplicated_id]["canonical_tables"] == ["plan", "step"]
    assert report["unscanned"] == []


def test_audit_reports_unscannable_tables_instead_of_calling_them_clean() -> None:
    conn = _ScriptedConn(_registry_script([], {}, broken_tables={"todo_item"}))
    report = audit_registry(conn)
    assert [entry["table_name"] for entry in report["unscanned"]] == ["todo_item"]
    assert "does not exist" in report["unscanned"][0]["reason"]


def test_restore_missing_registers_each_missing_row_idempotently() -> None:
    missing_id = uuid.uuid4()
    conn = _ScriptedConn([])
    report = {
        "missing": [{"id": missing_id, "table_name": "todo_item"}],
        "extra": [],
        "conflicts": [],
        "unscanned": [],
    }

    restored = restore_missing_identities(conn, report)

    assert restored == 1
    inserts = [sql for sql, _ in conn.executed if sql.startswith("INSERT INTO entity_identity")]
    assert len(inserts) == 1
    assert "ON CONFLICT (id) DO NOTHING" in inserts[0]


def test_extra_entry_is_retained_without_a_relation_index() -> None:
    entity_id = uuid.uuid4()
    conn = _ScriptedConn([(lambda sql: sql.startswith("SELECT to_regclass"), [(None,)])])
    assert remove_extra_identity_if_unreferenced(conn, entity_id) is False
    assert not any(sql.startswith("DELETE") for sql, _ in conn.executed)


def test_extra_entry_is_retained_when_referenced() -> None:
    entity_id = uuid.uuid4()
    conn = _ScriptedConn(
        [
            (lambda sql: sql.startswith("SELECT to_regclass"), [("relation_index",)]),
            (lambda sql: sql.startswith("SELECT 1 FROM relation_index"), [(1,)]),
        ]
    )
    assert remove_extra_identity_if_unreferenced(conn, entity_id) is False
    assert not any(sql.startswith("DELETE") for sql, _ in conn.executed)


def test_extra_entry_is_removed_only_when_unreferenced() -> None:
    entity_id = uuid.uuid4()
    conn = _ScriptedConn(
        [
            (lambda sql: sql.startswith("SELECT to_regclass"), [("relation_index",)]),
            (lambda sql: sql.startswith("SELECT 1 FROM relation_index"), []),
        ]
    )
    assert remove_extra_identity_if_unreferenced(conn, entity_id) is True
    deletes = [
        (sql, params)
        for sql, params in conn.executed
        if sql.startswith("DELETE FROM entity_identity")
    ]
    assert len(deletes) == 1
    assert deletes[0][1] == (entity_id, ENTITY_KIND)
