"""Regression test for 0.1.26 hotfix defect 3: todo update/resolve/close on a nonexistent id.

Previously these crashed with "'NoneType' object has no attribute 'anchor_plan_uuid'"; they must
now raise a DomainCommandError carrying the TODO_NOT_FOUND code."""
from __future__ import annotations

import uuid

import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.storage import todo_store


class _Cursor:
    def fetchone(self):
        return None


class _MissingConn:
    """Connection whose every SELECT returns no row (id does not exist)."""

    def execute(self, sql, params=()):
        return _Cursor()


@pytest.mark.parametrize(
    "call",
    [
        lambda conn, tid: todo_store.update_todo(conn, tid, changed_by="x", title="t"),
        lambda conn, tid: todo_store.resolve_todo(conn, tid, changed_by="x"),
        lambda conn, tid: todo_store.close_todo(conn, tid, changed_by="x"),
    ],
)
def test_todo_mutators_raise_not_found_for_missing_id(call) -> None:
    with pytest.raises(DomainCommandError) as excinfo:
        call(_MissingConn(), uuid.uuid4())
    assert excinfo.value.code == "TODO_NOT_FOUND"
