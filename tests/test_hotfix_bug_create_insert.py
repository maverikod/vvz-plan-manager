"""Regression test for 0.1.26 hotfix defect 1: bug_report INSERT placeholder/param parity.

Reproduces the JSON-RPC -32603 "the query has 33 placeholders but 34 parameters were passed"
error by asserting, via a psycopg-shaped fake connection, that every executed statement binds as
many parameters as it has %s placeholders, and that create_bug -> get_bug roundtrips."""
from __future__ import annotations

import uuid

from plan_manager.domain.bug_source import BugSource, BugSourceType
from plan_manager.storage import bug_report_store


class _Cursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _FakeConn:
    """Minimal psycopg-shaped connection.

    Mirrors psycopg's placeholder/parameter parity check (the source of defect 1),
    stores the inserted bug_report row, and serves get_bug's SELECT * from it. The
    bug_report INSERT column order, SELECT * order, and _row_to_record unpack order
    are identical, so the captured params tuple is a valid SELECT * row.
    """

    def __init__(self):
        self._bug_row = None

    def execute(self, sql, params=()):
        params = tuple(params)
        placeholders = sql.count("%s")
        assert placeholders == len(params), (
            f"the query has {placeholders} placeholders but {len(params)} parameters were passed"
        )
        normalized = " ".join(sql.split()).upper()
        if normalized.startswith("INSERT INTO BUG_REPORT"):
            self._bug_row = params
            return _Cursor(None)
        if normalized.startswith("SELECT * FROM BUG_REPORT"):
            return _Cursor(self._bug_row)
        return _Cursor(None)


def _project_source() -> BugSource:
    return BugSource(source_type=BugSourceType.PROJECT.value, project_id=uuid.uuid4())


def test_create_bug_placeholder_count_matches_params_and_roundtrips() -> None:
    conn = _FakeConn()
    created = bug_report_store.create_bug(
        conn,
        title="crash on save",
        short_description="short",
        detailed_description="detailed",
        kind="functional",
        severity="major",
        priority_nice=0,
        reporter="tester",
        created_by="tester",
        source=_project_source(),
    )
    assert created.title == "crash on save"

    fetched = bug_report_store.get_bug(conn, created.bug_uuid)
    assert fetched is not None
    assert fetched.bug_uuid == created.bug_uuid
    assert fetched.title == "crash on save"
    assert fetched.kind == "functional"
    assert fetched.severity == "major"
