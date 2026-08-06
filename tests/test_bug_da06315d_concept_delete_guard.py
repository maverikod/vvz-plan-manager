"""Regression for bug da06315d (CR-7 G-004/T-001/A-025).

Removing a concept that relations still reference must be refused through the
deletion guard's catalog probe instead of silently leaving the relations
dangling. Fake psycopg connections only; no live PostgreSQL instance.
"""
from __future__ import annotations

import uuid

import pytest

from plan_manager.domain.concept_store import remove_concept
from plan_manager.domain.entity import EntityReferencedError


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)

    @property
    def description(self):  # pragma: no cover
        return []


class _FakeConn:
    """Replays scripted rows per rendered-SQL predicate; records statements."""

    def __init__(self, script):
        self._script = list(script)
        self.executed: list[str] = []

    def execute(self, sql, params=()):
        rendered = sql.as_string(None) if hasattr(sql, "as_string") else str(sql)
        flat = " ".join(rendered.replace('"', "").split())
        self.executed.append(flat)
        for predicate, rows in self._script:
            if predicate(flat):
                return _FakeCursor(rows)
        return _FakeCursor([])

    def transaction(self):
        """No-op savepoint stand-in for the audit write's FK-race guard."""
        conn = self

        class _Tx:
            def __enter__(self):
                return conn

            def __exit__(self, *exc):
                return False

        return _Tx()

    def cursor(self):
        """Reads may go through cursors; writes are asserted on `executed`."""
        conn = self

        class _Ctx:
            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def execute(self, sql, params=()):
                self._cur = conn.execute(sql, params)
                return self._cur

            def fetchone(self):
                return self._cur.fetchone()

            def fetchall(self):
                return self._cur.fetchall()

        return _Ctx()


_PLAN = uuid.uuid4()
_ROW = uuid.uuid4()
_CONCEPT_ROW = ("C-001", "name", "definition", None, None)


def test_referenced_concept_removal_is_refused() -> None:
    conn = _FakeConn(
        script=[
            # get_concept read
            (lambda s: s.startswith("SELECT") and "FROM concept" in s, [_CONCEPT_ROW]),
            # guard probe: a relation row still references C-001
            (lambda s: s.startswith("SELECT uuid FROM relation"), [(uuid.uuid4(),)]),
        ]
    )
    with pytest.raises(EntityReferencedError):
        remove_concept(conn, _PLAN, "C-001")
    assert not any(s.startswith("DELETE") for s in conn.executed)


def test_unreferenced_concept_removal_goes_through_the_engine_delete() -> None:
    conn = _FakeConn(
        script=[
            (lambda s: s.startswith("SELECT") and "FROM concept WHERE plan_uuid = %s AND concept_id" in s, [_CONCEPT_ROW]),
            (lambda s: s.startswith("SELECT uuid FROM relation"), []),
            (lambda s: s.startswith("SELECT uuid FROM concept"), [(_ROW,)]),
        ]
    )
    removed = remove_concept(conn, _PLAN, "C-001")
    assert removed.concept_id == "C-001"
    assert any(s.startswith("DELETE FROM concept WHERE uuid = %s") for s in conn.executed)
