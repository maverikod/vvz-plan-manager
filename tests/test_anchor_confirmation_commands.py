"""Command-level wiring tests for bug 5926d536 (live CA anchor confirmation):

bug_create, bug_reanchor, todo_create, and todo_reanchor each route their
candidate project/file anchor through
``plan_manager.commands.anchor_confirmation.confirm_anchor`` before calling
their store function. These tests monkeypatch ``confirm_anchor`` (and the
store/db plumbing) at each command module's own namespace -- the same style
``test_list_sql_pushdown.py`` uses for ``list_bugs_page``/``list_todos_page``
-- to prove, without a real database or CA server:

(a) confirmed -> the store function receives the requested anchor untouched,
    and the response's anchor_confirmation.confirmed is True.
(b) CA says not-found -> the store function receives an UNANCHORED source/
    anchor (source_type="unidentified" / anchor_type="none"), never the
    requested project/file, and anchor_confirmation.reason == "not_found".
(c) CA unreachable/unconfigured -> same unanchored downgrade, with
    anchor_confirmation.reason == "ca_unreachable"; the create is never lost.
(d) a non-project/file anchor type (confirm_anchor's applicable=False) skips
    CA entirely: the requested anchor passes through unchanged and no
    anchor_confirmation key is added to the response.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import (
    bug_create_command,
    bug_reanchor_command,
    todo_create_command,
    todo_reanchor_command,
)
from plan_manager.commands.anchor_confirmation import AnchorConfirmation


def _fake_db_ctx():
    @contextmanager
    def _cm():
        yield object()

    return _cm


class _FakePlan:
    def __init__(self):
        self.uuid = uuid.uuid4()


class _FakeRecord:
    def __init__(self, payload):
        self._payload = payload

    def to_payload(self):
        return dict(self._payload)


def _confirm_anchor_stub(applicable, confirmed, reason, captured):
    def _fake(app_cfg, *, requested_type, project_id, file_path):
        captured["requested_type"] = requested_type
        captured["project_id"] = project_id
        captured["file_path"] = file_path
        return AnchorConfirmation(applicable=applicable, confirmed=confirmed, reason=reason)

    return _fake


# --- bug_create -------------------------------------------------------------------


def _bug_create_kwargs(**overrides):
    kwargs = dict(
        plan="my-plan",
        title="t",
        short_description="s",
        detailed_description="d",
        kind="functional",
        severity="major",
        priority_nice=0,
        reporter="alice",
        created_by="alice",
        source_type="project",
        source_project_id=str(uuid.uuid4()),
    )
    kwargs.update(overrides)
    return kwargs


def test_bug_create_confirmed_project_anchors_as_requested(monkeypatch) -> None:
    captured_source = {}

    def fake_create_bug(conn, **kwargs):
        captured_source["source"] = kwargs["source"]
        return _FakeRecord({"uuid": "bug-1"})

    monkeypatch.setattr(bug_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(bug_create_command, "app_config", lambda: None)
    monkeypatch.setattr(bug_create_command, "resolve_plan", lambda conn, plan: _FakePlan())
    monkeypatch.setattr(bug_create_command, "create_bug", fake_create_bug)
    monkeypatch.setattr(
        bug_create_command, "confirm_anchor", _confirm_anchor_stub(True, True, None, {})
    )
    kwargs = _bug_create_kwargs()
    result = asyncio.run(bug_create_command.BugCreateCommand().execute(**kwargs))
    data = result.to_dict()["data"]
    assert captured_source["source"].source_type == "project"
    assert str(captured_source["source"].project_id) == kwargs["source_project_id"]
    assert data["anchor_confirmation"] == {"requested_type": "project", "confirmed": True, "reason": None}


def test_bug_create_not_found_records_unanchored(monkeypatch) -> None:
    captured_source = {}

    def fake_create_bug(conn, **kwargs):
        captured_source["source"] = kwargs["source"]
        return _FakeRecord({"uuid": "bug-2"})

    monkeypatch.setattr(bug_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(bug_create_command, "app_config", lambda: None)
    monkeypatch.setattr(bug_create_command, "resolve_plan", lambda conn, plan: _FakePlan())
    monkeypatch.setattr(bug_create_command, "create_bug", fake_create_bug)
    monkeypatch.setattr(
        bug_create_command, "confirm_anchor", _confirm_anchor_stub(True, False, "not_found", {})
    )
    kwargs = _bug_create_kwargs(source_type="file", source_file_path="src/missing.py")
    result = asyncio.run(bug_create_command.BugCreateCommand().execute(**kwargs))
    data = result.to_dict()["data"]
    source = captured_source["source"]
    assert source.source_type == "unidentified"
    assert source.project_id is None
    assert source.file_path is None
    assert data["anchor_confirmation"] == {"requested_type": "file", "confirmed": False, "reason": "not_found"}


def test_bug_create_ca_unreachable_records_unanchored_and_never_loses_create(monkeypatch) -> None:
    captured_source = {}

    def fake_create_bug(conn, **kwargs):
        captured_source["source"] = kwargs["source"]
        return _FakeRecord({"uuid": "bug-3"})

    monkeypatch.setattr(bug_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(bug_create_command, "app_config", lambda: None)
    monkeypatch.setattr(bug_create_command, "resolve_plan", lambda conn, plan: _FakePlan())
    monkeypatch.setattr(bug_create_command, "create_bug", fake_create_bug)
    monkeypatch.setattr(
        bug_create_command, "confirm_anchor", _confirm_anchor_stub(True, False, "ca_unreachable", {})
    )
    kwargs = _bug_create_kwargs()
    result = asyncio.run(bug_create_command.BugCreateCommand().execute(**kwargs))
    data = result.to_dict()["data"]
    assert "error" not in result.to_dict(), "CA unreachable must never fail/lose the create"
    assert captured_source["source"].source_type == "unidentified"
    assert data["anchor_confirmation"] == {"requested_type": "project", "confirmed": False, "reason": "ca_unreachable"}


def test_bug_create_non_project_file_type_skips_ca_and_omits_diagnostic(monkeypatch) -> None:
    captured_source = {}
    confirm_calls = {"n": 0}

    def fake_create_bug(conn, **kwargs):
        captured_source["source"] = kwargs["source"]
        return _FakeRecord({"uuid": "bug-4"})

    def fake_confirm_anchor(app_cfg, *, requested_type, project_id, file_path):
        confirm_calls["n"] += 1
        return AnchorConfirmation(applicable=False, confirmed=True, reason=None)

    monkeypatch.setattr(bug_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(bug_create_command, "app_config", lambda: None)
    monkeypatch.setattr(bug_create_command, "resolve_plan", lambda conn, plan: _FakePlan())
    monkeypatch.setattr(bug_create_command, "create_bug", fake_create_bug)
    monkeypatch.setattr(bug_create_command, "confirm_anchor", fake_confirm_anchor)
    kwargs = _bug_create_kwargs(source_type="unidentified", source_project_id=None)
    result = asyncio.run(bug_create_command.BugCreateCommand().execute(**kwargs))
    data = result.to_dict()["data"]
    assert captured_source["source"].source_type == "unidentified"
    assert "anchor_confirmation" not in data
    assert confirm_calls["n"] == 1


# --- bug_reanchor -----------------------------------------------------------------


def test_bug_reanchor_not_found_moves_bug_to_unanchored(monkeypatch) -> None:
    captured = {}

    def fake_reanchor_bug_source(conn, bug_uuid, *, changed_by, new_source):
        captured["new_source"] = new_source
        return _FakeRecord({"uuid": str(bug_uuid)})

    monkeypatch.setattr(bug_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(bug_reanchor_command, "app_config", lambda: None)
    monkeypatch.setattr(bug_reanchor_command, "resolve_plan", lambda conn, plan: _FakePlan())
    monkeypatch.setattr(bug_reanchor_command, "get_bug", lambda conn, u: None)
    monkeypatch.setattr(bug_reanchor_command, "reanchor_bug_source", fake_reanchor_bug_source)
    monkeypatch.setattr(
        bug_reanchor_command, "confirm_anchor", _confirm_anchor_stub(True, False, "not_found", {})
    )
    result = asyncio.run(
        bug_reanchor_command.BugReanchorCommand().execute(
            plan="my-plan",
            bug_id=str(uuid.uuid4()),
            changed_by="alice",
            new_source_type="project",
            new_source_project_id=str(uuid.uuid4()),
        )
    )
    data = result.to_dict()["data"]
    assert captured["new_source"].source_type == "unidentified"
    assert data["anchor_confirmation"]["reason"] == "not_found"


def test_bug_reanchor_confirmed_moves_as_requested(monkeypatch) -> None:
    captured = {}
    project_id = str(uuid.uuid4())

    def fake_reanchor_bug_source(conn, bug_uuid, *, changed_by, new_source):
        captured["new_source"] = new_source
        return _FakeRecord({"uuid": str(bug_uuid)})

    monkeypatch.setattr(bug_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(bug_reanchor_command, "app_config", lambda: None)
    monkeypatch.setattr(bug_reanchor_command, "resolve_plan", lambda conn, plan: _FakePlan())
    monkeypatch.setattr(bug_reanchor_command, "get_bug", lambda conn, u: None)
    monkeypatch.setattr(bug_reanchor_command, "reanchor_bug_source", fake_reanchor_bug_source)
    monkeypatch.setattr(
        bug_reanchor_command, "confirm_anchor", _confirm_anchor_stub(True, True, None, {})
    )
    result = asyncio.run(
        bug_reanchor_command.BugReanchorCommand().execute(
            plan="my-plan",
            bug_id=str(uuid.uuid4()),
            changed_by="alice",
            new_source_type="project",
            new_source_project_id=project_id,
        )
    )
    data = result.to_dict()["data"]
    assert str(captured["new_source"].project_id) == project_id
    assert data["anchor_confirmation"]["confirmed"] is True


# --- todo_create ------------------------------------------------------------------


def test_todo_create_confirmed_project_anchors_as_requested(monkeypatch) -> None:
    captured = {}
    project_id = str(uuid.uuid4())

    def fake_create_todo(conn, **kwargs):
        captured["anchor"] = kwargs["anchor"]
        return _FakeRecord({"uuid": "todo-1"})

    monkeypatch.setattr(todo_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_create_command, "app_config", lambda: None)
    monkeypatch.setattr(todo_create_command, "create_todo", fake_create_todo)
    monkeypatch.setattr(
        todo_create_command, "confirm_anchor", _confirm_anchor_stub(True, True, None, {})
    )
    result = asyncio.run(
        todo_create_command.TodoCreateCommand().execute(
            title="t",
            description="d",
            kind="task",
            priority_nice=0,
            created_by="alice",
            anchor_type="project",
            anchor_project_id=project_id,
        )
    )
    data = result.to_dict()["data"]
    assert str(captured["anchor"].project_id) == project_id
    assert captured["anchor"].anchor_type == "project"
    assert data["anchor_confirmation"] == {"requested_type": "project", "confirmed": True, "reason": None}


def test_todo_create_ca_unreachable_records_unanchored(monkeypatch) -> None:
    captured = {}

    def fake_create_todo(conn, **kwargs):
        captured["anchor"] = kwargs["anchor"]
        return _FakeRecord({"uuid": "todo-2"})

    monkeypatch.setattr(todo_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_create_command, "app_config", lambda: None)
    monkeypatch.setattr(todo_create_command, "create_todo", fake_create_todo)
    monkeypatch.setattr(
        todo_create_command, "confirm_anchor", _confirm_anchor_stub(True, False, "ca_unreachable", {})
    )
    result = asyncio.run(
        todo_create_command.TodoCreateCommand().execute(
            title="t",
            description="d",
            kind="task",
            priority_nice=0,
            created_by="alice",
            anchor_type="file",
            anchor_project_id=str(uuid.uuid4()),
            anchor_file_path="src/x.py",
        )
    )
    data = result.to_dict()["data"]
    assert "error" not in result.to_dict()
    assert captured["anchor"].anchor_type == "none"
    assert captured["anchor"].project_id is None
    assert data["anchor_confirmation"] == {"requested_type": "file", "confirmed": False, "reason": "ca_unreachable"}


def test_todo_create_none_anchor_skips_ca(monkeypatch) -> None:
    captured = {}
    confirm_calls = {"n": 0}

    def fake_create_todo(conn, **kwargs):
        captured["anchor"] = kwargs["anchor"]
        return _FakeRecord({"uuid": "todo-3"})

    def fake_confirm_anchor(app_cfg, *, requested_type, project_id, file_path):
        confirm_calls["n"] += 1
        return AnchorConfirmation(applicable=False, confirmed=True, reason=None)

    monkeypatch.setattr(todo_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_create_command, "app_config", lambda: None)
    monkeypatch.setattr(todo_create_command, "create_todo", fake_create_todo)
    monkeypatch.setattr(todo_create_command, "confirm_anchor", fake_confirm_anchor)
    result = asyncio.run(
        todo_create_command.TodoCreateCommand().execute(
            title="t", description="d", kind="task", priority_nice=0, created_by="alice", anchor_type="none",
        )
    )
    data = result.to_dict()["data"]
    assert captured["anchor"].anchor_type == "none"
    assert "anchor_confirmation" not in data
    assert confirm_calls["n"] == 1


# --- todo_reanchor ------------------------------------------------------------------


def test_todo_reanchor_not_found_moves_to_unanchored(monkeypatch) -> None:
    captured = {}

    def fake_reanchor_todo(conn, todo_uuid, *, changed_by, new_anchor):
        captured["new_anchor"] = new_anchor
        return _FakeRecord({"uuid": str(todo_uuid)})

    monkeypatch.setattr(todo_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_reanchor_command, "app_config", lambda: None)
    monkeypatch.setattr(todo_reanchor_command, "get_todo", lambda conn, u: None)
    monkeypatch.setattr(todo_reanchor_command, "reanchor_todo", fake_reanchor_todo)
    monkeypatch.setattr(
        todo_reanchor_command, "confirm_anchor", _confirm_anchor_stub(True, False, "not_found", {})
    )
    result = asyncio.run(
        todo_reanchor_command.TodoReanchorCommand().execute(
            todo=str(uuid.uuid4()),
            changed_by="alice",
            new_anchor_type="project",
            new_anchor_project_id=str(uuid.uuid4()),
        )
    )
    data = result.to_dict()["data"]
    assert captured["new_anchor"].anchor_type == "none"
    assert data["anchor_confirmation"] == {"requested_type": "project", "confirmed": False, "reason": "not_found"}


def test_todo_reanchor_confirmed_moves_as_requested(monkeypatch) -> None:
    captured = {}
    project_id = str(uuid.uuid4())

    def fake_reanchor_todo(conn, todo_uuid, *, changed_by, new_anchor):
        captured["new_anchor"] = new_anchor
        return _FakeRecord({"uuid": str(todo_uuid)})

    monkeypatch.setattr(todo_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_reanchor_command, "app_config", lambda: None)
    monkeypatch.setattr(todo_reanchor_command, "get_todo", lambda conn, u: None)
    monkeypatch.setattr(todo_reanchor_command, "reanchor_todo", fake_reanchor_todo)
    monkeypatch.setattr(
        todo_reanchor_command, "confirm_anchor", _confirm_anchor_stub(True, True, None, {})
    )
    result = asyncio.run(
        todo_reanchor_command.TodoReanchorCommand().execute(
            todo=str(uuid.uuid4()),
            changed_by="alice",
            new_anchor_type="file",
            new_anchor_project_id=project_id,
            new_anchor_file_path="src/x.py",
        )
    )
    data = result.to_dict()["data"]
    assert str(captured["new_anchor"].project_id) == project_id
    assert captured["new_anchor"].file_path == "src/x.py"
    assert data["anchor_confirmation"]["confirmed"] is True
