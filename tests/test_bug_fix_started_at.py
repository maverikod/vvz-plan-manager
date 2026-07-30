"""Regression test for bug fa0a7ac2: update_bug_fix must stamp started_at when a fix
attempt moves to in_progress, mirroring the implemented_at stamp."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from plan_manager.storage import bug_fix_store


class _Column:
    """Stands in for a psycopg column description, which is read by .name."""

    def __init__(self, name: str) -> None:
        self.name = name


# Column order of the bug_fix SELECT, matching BugFix.COLUMNS. The store now
# routes through crud_*, which builds a row dict from cursor.description, so the
# fake has to model that attribute as a real cursor does.
_BUG_FIX_COLUMNS = (
    "uuid", "bug_uuid", "status", "fix_type", "summary", "implementation_notes",
    "source_project_id", "branch", "commit_hash", "pull_request", "changed_files",
    "tests", "author", "reviewer", "started_at", "implemented_at", "verified_at",
    "verification_method", "expected_result", "actual_result", "passed",
    "revert_info", "created_by", "created_at", "updated_at", "deleted_at",
)


class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.description = [_Column(name) for name in _BUG_FIX_COLUMNS]

    def fetchone(self):
        return self._row

    def fetchall(self):
        return [] if self._row is None else [self._row]


class _FakeConn:
    def __init__(self, row):
        self._row = row
        self.statements: list[tuple[str, object]] = []

    def execute(self, sql, params=None):
        self.statements.append((sql, params))
        return _FakeCursor(self._row)


def _bug_fix_row(*, status: str, started_at) -> tuple:
    now = datetime(2026, 7, 12, tzinfo=timezone.utc)
    return (
        uuid.uuid4(),            # uuid
        uuid.uuid4(),            # bug_uuid
        status,                  # status
        "code_change",           # fix_type
        "summary",               # summary
        None,                     # implementation_notes
        None,                     # source_project_id
        None,                     # branch
        None,                     # commit_hash
        None,                     # pull_request
        None,                     # changed_files
        None,                     # tests
        "author",                # author
        None,                     # reviewer
        started_at,              # started_at
        None,                     # implemented_at
        None,                     # verified_at
        None,                     # verification_method
        None,                     # expected_result
        None,                     # actual_result
        None,                     # passed
        None,                     # revert_info
        "creator",               # created_by
        now,                      # created_at
        now,                      # updated_at
        None,                     # deleted_at
    )


def test_update_to_in_progress_stamps_started_at(monkeypatch) -> None:
    monkeypatch.setattr(bug_fix_store, "record_runtime_change", lambda *a, **k: None)
    now = datetime(2026, 7, 12, 10, 0, tzinfo=timezone.utc)
    conn = _FakeConn(_bug_fix_row(status="in_progress", started_at=now))

    record = bug_fix_store.update_bug_fix(
        conn, uuid.uuid4(), changed_by="agent", status="in_progress"
    )

    sql, params = conn.statements[0]
    # The store no longer hand-writes this UPDATE: it delegates to
    # crud_update, which composes the statement from identifiers. So assert
    # that started_at is part of the update, not that a particular SQL string
    # was assembled.
    assert "started_at" in str(sql)
    assert record.started_at is not None


def test_update_without_status_does_not_touch_started_at(monkeypatch) -> None:
    monkeypatch.setattr(bug_fix_store, "record_runtime_change", lambda *a, **k: None)
    conn = _FakeConn(_bug_fix_row(status="proposed", started_at=None))

    bug_fix_store.update_bug_fix(conn, uuid.uuid4(), changed_by="agent", summary="new")

    sql, _ = conn.statements[0]
    assert "started_at" not in sql
