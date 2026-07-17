"""Regression tests for pushing bug_list/todo_list/comment_list filtering and
pagination fully into SQL (2026-07-18 follow-up to bug e93dd68d/8684ea59):
previously bug_list_command, todo_list_command, and comment_list_command each
fetched an entire (plan-scoped, or global) table via the sibling store's plain
list_* function and then applied every other filter -- project (transitively),
file, anchor_plan, revision, step, priority, owner/assignee, created_after/before,
active_only/unanchored_only/status -- as Python list-comprehensions, and sliced
the page with plain Python slicing after computing total via len().

This file covers the SQL-pushdown replacement:

- bug_report_store.list_bugs_page, todo_store.list_todos_page, and
  runtime_comment_store.list_comments_page build every one of those filters as a
  parameterized SQL WHERE clause (never post-fetch Python filtering), including
  the transitive project match as ONE correlated subquery (no precomputed
  plan-uuid list threaded through Python -- see project_scope.py's
  resolve_project_plan_uuids, which those three functions never call).
- LIMIT/OFFSET are pushed into SQL and total is computed via a `count(*) OVER()`
  window in the common (non-empty page) case, falling back to a single
  `SELECT count(*)` with the same WHERE clause when the requested page is empty
  (the window aggregate has no row to ride along on then).
- bug_list_command / todo_list_command / comment_list_command each call their
  store's *_page function exactly once and return its (page, total) verbatim --
  no post-fetch filtering, no re-slicing, no independent total recomputation.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from plan_manager.commands import bug_list_command, comment_list_command, todo_list_command
from plan_manager.storage.bug_report_store import list_bugs_page
from plan_manager.storage.runtime_comment_store import list_comments_page
from plan_manager.storage.todo_store import list_todos_page

NOW = dt.datetime(2026, 7, 17, 12, 0, 0, tzinfo=dt.timezone.utc)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _SequencedConn:
    """Records every execute() call's SQL/params; serves `main_rows` for the
    paginated SELECT and `count_total` for the fallback SELECT count(*) query
    (dispatched by sniffing the SQL text, matching how the two queries the
    store issues are told apart)."""

    def __init__(self, main_rows=None, count_total=0):
        self.calls: list[tuple[str, list]] = []
        self._main_rows = main_rows or []
        self._count_total = count_total

    def execute(self, sql, params=None):
        self.calls.append((sql, list(params or [])))
        if sql.strip().upper().startswith("SELECT COUNT(*)"):
            return _Result([(self._count_total,)])
        return _Result(self._main_rows)


def _bug_row(status="reported", total=None):
    row = (
        uuid.uuid4(), "title", "short", "detailed", None, None,
        None, None, None, "functional", "major", 0, status, "reporter", None,
        None, None, "project", uuid.uuid4(), None,
        None, None, None, None, None,
        None, None, None, None, None, "creator", NOW,
        NOW, None,
    )
    return row if total is None else row + (total,)


def _todo_row(status="open", total=None):
    row = (
        uuid.uuid4(), "title", "description", "feature", status, 0, "creator",
        None, NOW, NOW, None, None, None,
        "none", None, None, None,
        None, None, None, None,
        None, None, None,
    )
    return row if total is None else row + (total,)


def _comment_row(resolved=False, total=None):
    row = (
        uuid.uuid4(), "step", None, None,
        uuid.uuid4(), None, uuid.uuid4(), None,
        None, "note", "team", "tester", "body", resolved,
        None, "creator", NOW, NOW, None,
    )
    return row if total is None else row + (total,)


# --- bug_report_store.list_bugs_page: SQL construction ----------------------------


def test_list_bugs_page_active_only_excludes_terminal_statuses() -> None:
    conn = _SequencedConn()
    list_bugs_page(conn, active_only=True)
    sql, params = conn.calls[0]
    assert "status NOT IN (%s, %s, %s)" in sql
    assert {"closed", "rejected", "duplicate"}.issubset(set(params))


def test_list_bugs_page_created_after_before_are_inclusive() -> None:
    conn = _SequencedConn()
    list_bugs_page(conn, created_after="2026-01-01T00:00:00+00:00", created_before="2026-12-31T00:00:00+00:00")
    sql, params = conn.calls[0]
    assert "created_at >= %s" in sql
    assert "created_at <= %s" in sql
    assert "2026-01-01T00:00:00+00:00" in params
    assert "2026-12-31T00:00:00+00:00" in params


def test_list_bugs_page_plan_and_anchor_plan_and_together() -> None:
    """`plan` (source_plan_uuid) and `anchor_plan` (anchor_plan_uuid arg) are two
    independent inputs on the SAME column; both conditions must appear so SQL
    intersects them (an unequal pair yields zero rows), never widening scope."""
    plan_uuid = uuid.uuid4()
    other_uuid = uuid.uuid4()
    conn = _SequencedConn()
    list_bugs_page(conn, source_plan_uuid=plan_uuid, anchor_plan_uuid=other_uuid)
    sql, params = conn.calls[0]
    assert sql.count("source_plan_uuid = %s") == 2
    assert plan_uuid in params
    assert other_uuid in params


def test_list_bugs_page_pagination_and_total_from_window_function() -> None:
    total = 7
    conn = _SequencedConn(main_rows=[_bug_row(total=total), _bug_row(status="triaged", total=total)])
    records, returned_total = list_bugs_page(conn, limit=2, offset=4)
    assert returned_total == total
    assert len(records) == 2
    assert records[0].status == "reported"
    assert records[1].status == "triaged"
    sql, params = conn.calls[0]
    assert "count(*) OVER() AS total" in sql
    assert "LIMIT %s OFFSET %s" in sql
    assert params[-2:] == [2, 4]
    assert len(conn.calls) == 1, "non-empty page must not trigger the fallback COUNT(*) query"


def test_list_bugs_page_empty_page_falls_back_to_count_query() -> None:
    conn = _SequencedConn(main_rows=[], count_total=42)
    records, total = list_bugs_page(conn, limit=50, offset=1000)
    assert records == []
    assert total == 42
    assert len(conn.calls) == 2, "an empty page must trigger exactly one fallback COUNT(*) query"
    count_sql, count_params = conn.calls[1]
    assert count_sql.strip().upper().startswith("SELECT COUNT(*)")


# --- todo_store.list_todos_page: SQL construction ---------------------------------


def test_list_todos_page_active_only_is_positive_membership() -> None:
    conn = _SequencedConn()
    list_todos_page(conn, active_only=True)
    sql, params = conn.calls[0]
    assert "status IN (%s, %s, %s)" in sql
    assert {"open", "in_progress", "blocked"}.issubset(set(params))


def test_list_todos_page_unanchored_only() -> None:
    conn = _SequencedConn()
    list_todos_page(conn, unanchored_only=True)
    sql, params = conn.calls[0]
    assert "primary_anchor_type = %s" in sql
    assert "none" in params


def test_list_todos_page_owner_maps_to_created_by_and_assignee_to_assigned_to() -> None:
    conn = _SequencedConn()
    list_todos_page(conn, owner="alice", assignee="bob")
    sql, params = conn.calls[0]
    assert "created_by = %s" in sql
    assert "assigned_to = %s" in sql
    assert "alice" in params
    assert "bob" in params


def test_list_todos_page_created_after_before_are_inclusive() -> None:
    conn = _SequencedConn()
    list_todos_page(conn, created_after="2026-01-01T00:00:00+00:00", created_before="2026-12-31T00:00:00+00:00")
    sql, params = conn.calls[0]
    assert "created_at >= %s" in sql
    assert "created_at <= %s" in sql


def test_list_todos_page_pagination_and_total_from_window_function() -> None:
    total = 3
    conn = _SequencedConn(main_rows=[_todo_row(total=total)])
    records, returned_total = list_todos_page(conn, limit=1, offset=0)
    assert returned_total == total
    assert len(records) == 1
    assert records[0].status == "open"
    assert len(conn.calls) == 1


def test_list_todos_page_empty_page_falls_back_to_count_query() -> None:
    conn = _SequencedConn(main_rows=[], count_total=9)
    records, total = list_todos_page(conn, limit=50, offset=500)
    assert records == []
    assert total == 9
    assert len(conn.calls) == 2


# --- runtime_comment_store.list_comments_page: SQL construction -------------------


def test_list_comments_page_status_resolved_and_unresolved() -> None:
    conn = _SequencedConn()
    list_comments_page(conn, status="resolved")
    sql, _params = conn.calls[0]
    assert "resolved = true" in sql

    conn2 = _SequencedConn()
    list_comments_page(conn2, status="unresolved")
    sql2, _params2 = conn2.calls[0]
    assert "resolved IS NULL OR resolved = false" in sql2


def test_list_comments_page_active_only_is_independent_of_status() -> None:
    conn = _SequencedConn()
    list_comments_page(conn, active_only=True)
    sql, _params = conn.calls[0]
    assert "resolved IS NULL OR resolved = false" in sql


def test_list_comments_page_created_after_before_are_exclusive() -> None:
    """Unlike bug_list/todo_list, comment_list's created_after/before were --
    and, per the reality supplement, remain -- EXCLUSIVE bounds (> / <), not
    inclusive (>= / <=); this is a pre-existing quirk of this store, preserved
    verbatim while pushing the comparison down into SQL."""
    conn = _SequencedConn()
    list_comments_page(conn, created_after="2026-01-01T00:00:00+00:00", created_before="2026-12-31T00:00:00+00:00")
    sql, params = conn.calls[0]
    assert "created_at > %s" in sql
    assert "created_at < %s" in sql
    assert "created_at >= %s" not in sql
    assert "created_at <= %s" not in sql


def test_list_comments_page_plan_and_anchor_plan_filter_and_together() -> None:
    plan_uuid = uuid.uuid4()
    other_uuid = uuid.uuid4()
    conn = _SequencedConn()
    list_comments_page(conn, anchor_plan_uuid=plan_uuid, filter_anchor_plan_uuid=other_uuid)
    sql, params = conn.calls[0]
    assert sql.count("anchor_plan_uuid = %s") == 2
    assert plan_uuid in params
    assert other_uuid in params


def test_list_comments_page_pagination_and_total_from_window_function() -> None:
    total = 11
    conn = _SequencedConn(main_rows=[_comment_row(total=total)])
    records, returned_total = list_comments_page(conn, limit=1, offset=0)
    assert returned_total == total
    assert len(records) == 1
    assert len(conn.calls) == 1


def test_list_comments_page_empty_page_falls_back_to_count_query() -> None:
    conn = _SequencedConn(main_rows=[], count_total=2)
    records, total = list_comments_page(conn, limit=50, offset=200)
    assert records == []
    assert total == 2
    assert len(conn.calls) == 2


# --- command level: exactly one store call, no post-fetch Python filtering -------


def _fake_db_ctx():
    from contextlib import contextmanager

    @contextmanager
    def _cm():
        yield object()

    return _cm


def test_bug_list_command_calls_store_once_and_trusts_its_total(monkeypatch) -> None:
    calls = {"n": 0}

    class _FakeBugPayload:
        def to_payload(self):
            return {}

    def fake_list_bugs_page(conn, **kwargs):
        calls["n"] += 1
        return [_FakeBugPayload(), _FakeBugPayload()], 999  # mismatched total proves no Python recomputation

    monkeypatch.setattr(bug_list_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(bug_list_command, "list_bugs_page", fake_list_bugs_page)
    result = asyncio.run(bug_list_command.BugListCommand().execute())
    data = result.to_dict()["data"]
    assert calls["n"] == 1
    assert data["total"] == 999
    assert len(data["bugs"]) == 2


def test_todo_list_command_calls_store_once_and_trusts_its_total(monkeypatch) -> None:
    calls = {"n": 0}

    class _FakeTodoPayload:
        def to_payload(self):
            return {}

    def fake_list_todos_page(conn, **kwargs):
        calls["n"] += 1
        return [_FakeTodoPayload()], 123

    monkeypatch.setattr(todo_list_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_list_command, "list_todos_page", fake_list_todos_page)
    result = asyncio.run(todo_list_command.TodoListCommand().execute())
    data = result.to_dict()["data"]
    assert calls["n"] == 1
    assert data["total"] == 123
    assert len(data["todos"]) == 1


def test_comment_list_command_calls_store_once_and_trusts_its_total(monkeypatch) -> None:
    calls = {"n": 0}

    class _FakeCommentPayload:
        def to_payload(self):
            return {}

    def fake_list_comments_page(conn, **kwargs):
        calls["n"] += 1
        return [_FakeCommentPayload()], 55

    monkeypatch.setattr(comment_list_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(comment_list_command, "list_comments_page", fake_list_comments_page)
    result = asyncio.run(comment_list_command.CommentListCommand().execute())
    data = result.to_dict()["data"]
    assert calls["n"] == 1
    assert data["total"] == 55
    assert len(data["comments"]) == 1
