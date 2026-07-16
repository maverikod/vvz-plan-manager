"""Regression coverage for bug 113a7888: todo_delete raised KeyError('todo_uuid')
(surfaced to callers as -32603) for every existing TODO, including dry_run=true.

Root cause: TodoItem.HARD_DELETE_REFERENCE_CHECKS pinned source_column="todo_uuid"
(the dataclass field name), but plan_manager.domain.entity.find_entity_reference_counts
builds its id_values dict from DataclassEntity.get_by_id's row, whose keys are the raw
DB column names — and the todo_item table's primary key column is "uuid", not
"todo_uuid". comment_delete never hit this because RuntimeComment defines no
HARD_DELETE_REFERENCE_CHECKS at all.

These tests exercise TodoDeleteCommand.execute() end to end (dry_run, soft-delete
happy path, and the DELETE_BLOCKED path) against a fake connection that mirrors the
exact conn.execute() call sequence find_entity_reference_counts issues, matching the
repo idiom of faking the store/connection layer (see test_hotfix_uuid_guards.py,
test_bug_fix_started_at.py).
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from plan_manager.commands import todo_delete_command
from plan_manager.domain.todo import TodoItem

TODO_UUID = uuid.uuid4()
NOW = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)


def _todo_item(**overrides: Any) -> TodoItem:
    fields: dict[str, Any] = dict(
        todo_uuid=TODO_UUID,
        title="fix the thing",
        description="a todo used for delete-command tests",
        kind="task",
        status="open",
        priority_nice=50,
        created_by="tester",
        assigned_to=None,
        created_at=NOW.isoformat(),
        updated_at=NOW.isoformat(),
        started_at=None,
        resolved_at=None,
        due_at=None,
        primary_anchor_type="none",
        anchor_project_id=None,
        anchor_file_path=None,
        anchor_plan_uuid=None,
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=None,
        blocking_reason=None,
        execution_result=None,
        deleted_at=None,
    )
    fields.update(overrides)
    return TodoItem(**fields)


def _todo_row_mapping() -> dict[str, Any]:
    """The dict TodoItem.get_by_id (crud_get) would hand back for `SELECT * FROM
    todo_item WHERE uuid = %s`: DB column names, keyed exactly as the table defines
    them (see plan_manager_db/migrations/0010_todo_work_items.sql) — notably "uuid",
    never "todo_uuid".
    """
    return {
        "uuid": TODO_UUID,
        "title": "fix the thing",
        "description": "a todo used for delete-command tests",
        "kind": "task",
        "status": "open",
        "priority_nice": 50,
        "created_by": "tester",
        "assigned_to": None,
        "created_at": NOW,
        "updated_at": NOW,
        "started_at": None,
        "resolved_at": None,
        "due_at": None,
        "primary_anchor_type": "none",
        "anchor_project_id": None,
        "anchor_file_path": None,
        "anchor_plan_uuid": None,
        "anchor_revision_uuid": None,
        "anchor_step_uuid": None,
        "anchor_step_path": None,
        "anchor_ref_id": None,
        "blocking_reason": None,
        "execution_result": None,
        "deleted_at": None,
    }


class _FakeCursor:
    def __init__(self, fetchone_result: Any = None, fetchall_result: list[Any] | None = None) -> None:
        self._fetchone_result = fetchone_result
        self._fetchall_result = fetchall_result if fetchall_result is not None else []

    def fetchone(self) -> Any:
        return self._fetchone_result

    def fetchall(self) -> list[Any]:
        return self._fetchall_result


class _FakeConn:
    """Fakes conn.execute() for the exact query sequence
    plan_manager.domain.entity.find_entity_reference_counts issues when called as
    TodoItem.crud_reference_counts(conn, todo_uuid):

      0. TodoItem.get_by_id (crud_get: 'SELECT * FROM todo_item WHERE uuid = %s')
         -> composed SQL, dict row via fetchone()
      1. _foreign_key_reference_checks' information_schema probe
         -> raw SQL string, fetchall() -> [] (no additional FK constraints probed)
      2-5. CENTRAL_REFERENCE_CHECKS['todo'] (4 checks, in declared order)
         -> composed SQL 'SELECT count(*) ...', fetchone() (count,)
      6-9. TodoItem.HARD_DELETE_REFERENCE_CHECKS (4 checks, in declared order) —
         this is exactly the range the pre-fix KeyError('todo_uuid') never let
         execution reach.
         -> composed SQL 'SELECT count(*) ...', fetchone() (count,)

    `blocked_at` maps a call index (2-9) to a nonzero count, to simulate one live
    inbound reference at that check.
    """

    def __init__(self, blocked_at: dict[int, int] | None = None) -> None:
        self._blocked_at = blocked_at or {}
        self._index = -1

    def execute(self, query: Any, params: Any = None) -> _FakeCursor:
        self._index += 1
        idx = self._index
        if idx == 0:
            return _FakeCursor(fetchone_result=_todo_row_mapping())
        if idx == 1:
            return _FakeCursor(fetchall_result=[])
        return _FakeCursor(fetchone_result=(self._blocked_at.get(idx, 0),))


@contextmanager
def _fake_db(blocked_at: dict[int, int] | None = None):
    yield _FakeConn(blocked_at=blocked_at)


def _install_fakes(monkeypatch, *, blocked_at: dict[int, int] | None = None, soft_delete_result: TodoItem | None = None) -> None:
    monkeypatch.setattr(todo_delete_command, "db_connection", lambda: _fake_db(blocked_at))
    monkeypatch.setattr(todo_delete_command, "get_todo", lambda conn, todo_uuid: _todo_item())
    if soft_delete_result is not None:
        monkeypatch.setattr(
            todo_delete_command,
            "soft_delete_todo",
            lambda conn, todo_uuid, *, changed_by: soft_delete_result,
        )


def test_todo_delete_dry_run_on_existing_unreferenced_todo_does_not_raise(monkeypatch) -> None:
    """Bug 113a7888 reproduction: dry_run=true on an existing todo must preview
    cleanly, not raise KeyError('todo_uuid')."""
    _install_fakes(monkeypatch)

    result = asyncio.run(
        todo_delete_command.TodoDeleteCommand().execute(
            todo=str(TODO_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["would_delete"] == str(TODO_UUID)
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["blocked"] is False
    assert payload["data"]["references"] == {}


def test_todo_delete_soft_deletes_existing_unreferenced_todo(monkeypatch) -> None:
    """Bug 113a7888 reproduction: the non-dry-run happy path on an existing,
    unreferenced todo must soft-delete it, not raise KeyError('todo_uuid')."""
    deleted = _todo_item(deleted_at=NOW.isoformat())
    _install_fakes(monkeypatch, soft_delete_result=deleted)

    result = asyncio.run(
        todo_delete_command.TodoDeleteCommand().execute(todo=str(TODO_UUID), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["dry_run"] is False
    assert payload["data"]["mode"] == "soft"
    assert payload["data"]["todo"]["todo_uuid"] == str(TODO_UUID)
    assert payload["data"]["todo"]["deleted_at"] is not None


def test_todo_delete_dry_run_reports_blocked_for_central_reference_check(monkeypatch) -> None:
    """A live reference visible through CENTRAL_REFERENCE_CHECKS['todo'] (index 2:
    execution_attempt.todo_uuid) must be reported, not swallowed."""
    _install_fakes(monkeypatch, blocked_at={2: 3})

    result = asyncio.run(
        todo_delete_command.TodoDeleteCommand().execute(
            todo=str(TODO_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["blocked"] is True
    assert payload["data"]["references"] == {"execution_attempt.todo_uuid": 3}


def test_todo_delete_dry_run_reports_blocked_for_hard_delete_reference_check(monkeypatch) -> None:
    """A live reference visible only through TodoItem.HARD_DELETE_REFERENCE_CHECKS
    (index 6: todo_link.from_todo_uuid) must be reported. This is precisely the
    check range whose explicit source_column="todo_uuid" caused the KeyError before
    the fix — reaching this assertion at all is the regression guard."""
    _install_fakes(monkeypatch, blocked_at={6: 1})

    result = asyncio.run(
        todo_delete_command.TodoDeleteCommand().execute(
            todo=str(TODO_UUID), changed_by="tester", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True, payload
    assert payload["data"]["blocked"] is True
    assert payload["data"]["references"] == {"todo_link.from_todo_uuid": 1}


def test_todo_delete_blocked_by_live_reference_refuses_non_dry_run_delete(monkeypatch) -> None:
    """Outside dry_run, a live reference must refuse the deletion with DELETE_BLOCKED."""
    _install_fakes(monkeypatch, blocked_at={2: 3})

    result = asyncio.run(
        todo_delete_command.TodoDeleteCommand().execute(todo=str(TODO_UUID), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "DELETE_BLOCKED"
    assert payload["error"]["data"]["references"] == {"execution_attempt.todo_uuid": 3}


def test_todo_delete_reports_todo_not_found_for_missing_todo(monkeypatch) -> None:
    """Sanity check on the sibling branch untouched by this fix: a nonexistent todo
    still reports TODO_NOT_FOUND, not KeyError."""
    monkeypatch.setattr(todo_delete_command, "db_connection", lambda: _fake_db())
    monkeypatch.setattr(todo_delete_command, "get_todo", lambda conn, todo_uuid: None)

    result = asyncio.run(
        todo_delete_command.TodoDeleteCommand().execute(todo=str(uuid.uuid4()), changed_by="tester")
    )

    payload = result.to_dict()
    assert payload["success"] is False, payload
    assert payload["error"]["data"]["domain_code"] == "TODO_NOT_FOUND"
