"""Regression test for bug fa0a7ac2: update_bug_fix must stamp started_at when a fix
attempt moves to in_progress, mirroring the implemented_at stamp."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from plan_manager.storage import bug_fix_store


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


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
    assert "started_at = %s" in sql
    assert record.started_at is not None


def test_update_without_status_does_not_touch_started_at(monkeypatch) -> None:
    monkeypatch.setattr(bug_fix_store, "record_runtime_change", lambda *a, **k: None)
    conn = _FakeConn(_bug_fix_row(status="proposed", started_at=None))

    bug_fix_store.update_bug_fix(conn, uuid.uuid4(), changed_by="agent", summary="new")

    sql, _ = conn.statements[0]
    assert "started_at" not in sql
