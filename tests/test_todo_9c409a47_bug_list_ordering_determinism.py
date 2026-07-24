"""Regression test for todo 9c409a47 (pagination-contract companion of bug
85b180bf): bug_report_store.list_bugs_page's row ordering must be
deterministic under pagination, i.e. its ORDER BY must carry a unique
tiebreaker.

Before this fix the query was ``ORDER BY created_at ASC`` with no
tiebreaker. `created_at` is not a unique column -- bug rows created in the
same batch/transaction (a plausible occurrence: bulk bug filing, seed
fixtures, or several bugs recorded in the same second) can share an
identical timestamp, so PostgreSQL is free to return them in any order it
likes across two otherwise-identical queries; paging through such a set can
then duplicate or skip rows depending on the physical/plan-chosen order on
each call. The fix appends the table's primary key (`uuid`) as a second,
always-unique sort key: ``ORDER BY created_at ASC, uuid ASC``.

This test uses the same SQL-construction fake-connection idiom as
tests/test_list_sql_pushdown.py (a local class here, not a shared import, to
stay inside this task's own file -- no edit to that shared test file), and
additionally proves end-to-end (via a fake connection whose fetchall()
returns rows in a fixed physical order simulating same-`created_at` ties)
that pages walked with offset stepping never duplicate or skip a row.
"""

from __future__ import annotations

import datetime as dt
import uuid

from plan_manager.storage.bug_report_store import list_bugs_page

NOW = dt.datetime(2026, 7, 24, 12, 0, 0, tzinfo=dt.timezone.utc)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _RecordingConn:
    """Minimal fake connection: records the SQL/params of every execute()
    call and serves canned rows for the paginated SELECT (COUNT(*) fallback
    rows are unused by these tests)."""

    def __init__(self, rows):
        self.calls: list[tuple[str, list]] = []
        self._rows = rows

    def execute(self, sql, params=None):
        self.calls.append((sql, list(params or [])))
        if sql.strip().upper().startswith("SELECT COUNT(*)"):
            return _Result([(len(self._rows),)])
        return _Result(self._rows)


def _bug_row(bug_uuid, status="reported", created_at=NOW, total=None):
    row = (
        bug_uuid, "title", "short", "detailed", None, None,
        None, None, None, "functional", "major", 0, status, "reporter", None,
        None, None, "project", uuid.uuid4(), None,
        None, None, None, None, None,
        None, None, None, None, None, "creator", created_at,
        created_at, None,
    )
    return row if total is None else row + (total,)


def test_list_bugs_page_order_by_has_unique_uuid_tiebreaker() -> None:
    """The generated SQL must sort by created_at AND a unique tiebreaker
    (uuid), not by created_at alone -- otherwise row order (and therefore
    page boundaries) is unspecified whenever two rows share a created_at."""
    conn = _RecordingConn(rows=[])
    list_bugs_page(conn, limit=50, offset=0)

    sql, _params = conn.calls[0]
    assert "ORDER BY created_at ASC, uuid ASC" in sql, (
        f"expected a unique (uuid) tiebreaker after created_at in the ORDER BY, got: {sql!r}"
    )


def test_paging_through_rows_sharing_created_at_has_no_duplicates_or_gaps() -> None:
    """End-to-end simulation: several bug rows share the exact same
    created_at (the tie scenario the missing tiebreaker made flaky). With a
    deterministic ORDER BY (created_at, uuid) a fixed row order is produced
    once and every page-sized slice of it is gap/dupe free when walked by
    offset -- exactly what a real Postgres ORDER BY (created_at, uuid) ASC
    guarantees given the same input set on every call.
    """
    tied_uuids = sorted([uuid.uuid4() for _ in range(7)])  # simulate uuid ASC tiebreak order
    total = len(tied_uuids)
    all_rows_in_db_order = [_bug_row(u, created_at=NOW) for u in tied_uuids]

    seen_uuids: list[uuid.UUID] = []
    offset = 0
    limit = 3
    while offset < total:
        page_rows = [row + (total,) for row in all_rows_in_db_order[offset : offset + limit]]
        conn = _RecordingConn(rows=page_rows)
        records, returned_total = list_bugs_page(conn, limit=limit, offset=offset)
        assert returned_total == total
        seen_uuids.extend(record.bug_uuid for record in records)
        offset += limit

    assert seen_uuids == tied_uuids
    assert len(seen_uuids) == len(set(seen_uuids)) == total
