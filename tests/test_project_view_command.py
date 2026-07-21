"""Tests for project_view (bug 18951d08): the missing project-centric runtime read
surface. Covers the bug's own acceptance criterion (UUID-set/counter equality with
todo_list/bug_list under identical filters), match_source (direct vs transitive_plan)
correctness, diagnostics/summary counts, pagination stability, and the
unknown-project-is-a-valid-empty-view / invalid-project-uuid-is-an-error contrast.

Follows the existing project-scope test harness style (tests/test_project_scope_family.py):
fake context-manager connection + monkeypatch.setattr on the command module's imported
store functions, direct asyncio.run(Command().execute(**kwargs)) -- no real DB.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import project_view_command, todo_list_command, bug_list_command

PROJECT = uuid.uuid4()
OTHER_PROJECT = uuid.uuid4()


@contextmanager
def _fake_db():
    yield object()


class _FakeTodo:
    def __init__(self, row_uuid, status, anchor_project_id=None, transitive_project_id=None):
        self.uuid = row_uuid
        self.status = status
        self.anchor_project_id = anchor_project_id
        self._transitive_project_id = transitive_project_id

    def to_payload(self):
        return {"uuid": str(self.uuid), "status": self.status}


class _FakeBug:
    def __init__(self, row_uuid, status, source_project_id=None, transitive_project_id=None):
        self.uuid = row_uuid
        self.status = status
        self.source_project_id = source_project_id
        self._transitive_project_id = transitive_project_id

    def to_payload(self):
        return {"uuid": str(self.uuid), "status": self.status}


class _FakeComment:
    def __init__(self, row_uuid, anchor_project_id=None, transitive_project_id=None):
        self.uuid = row_uuid
        self.anchor_project_id = anchor_project_id
        self._transitive_project_id = transitive_project_id

    def to_payload(self):
        return {"uuid": str(self.uuid)}


def _make_fake_page_fn(all_rows, project_field, active_statuses):
    """In-memory stand-in for a *_page store function: applies the same
    direct-OR-transitive-via-project_field/_transitive_project_id membership and
    active_only semantics a real store function's SQL predicate would, then
    paginates. Records every call's kwargs for assertion."""
    calls: list[dict] = []

    def fake(conn, *, project_id=None, active_only=False, limit=50, offset=0, include_deleted=False, **_ignored):
        calls.append({"project_id": project_id, "active_only": active_only, "limit": limit, "offset": offset})
        matched = [
            r for r in all_rows
            if getattr(r, project_field) == project_id or r._transitive_project_id == project_id
        ]
        if active_only and active_statuses is not None:
            matched = [r for r in matched if r.status in active_statuses]
        total = len(matched)
        page = matched[offset:offset + limit]
        return page, total

    fake.calls = calls
    return fake


_TODO_ACTIVE = {"open", "in_progress", "blocked"}
_BUG_ACTIVE = {"reported", "triaged", "confirmed", "fixing", "fixed_source", "propagating", "reopened"}


def _run_project_view(monkeypatch, todos, bugs, comments=None, **kwargs):
    fake_todo = _make_fake_page_fn(todos, "anchor_project_id", _TODO_ACTIVE)
    fake_bug = _make_fake_page_fn(bugs, "source_project_id", _BUG_ACTIVE)
    fake_comment = _make_fake_page_fn(comments or [], "anchor_project_id", None)
    monkeypatch.setattr(project_view_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_view_command, "list_todos_page", fake_todo)
    monkeypatch.setattr(project_view_command, "list_bugs_page", fake_bug)
    monkeypatch.setattr(project_view_command, "list_comments_page", fake_comment)
    result = asyncio.run(project_view_command.ProjectViewCommand().execute(**kwargs))
    return result, fake_todo, fake_bug, fake_comment


def _todo_universe():
    return [
        _FakeTodo(uuid.uuid4(), "open", anchor_project_id=PROJECT),                 # direct, active
        _FakeTodo(uuid.uuid4(), "in_progress", transitive_project_id=PROJECT),      # transitive, active
        _FakeTodo(uuid.uuid4(), "open", anchor_project_id=OTHER_PROJECT),           # foreign, excluded
        _FakeTodo(uuid.uuid4(), "closed", anchor_project_id=PROJECT),               # direct, terminal
    ]


def _bug_universe():
    return [
        _FakeBug(uuid.uuid4(), "reported", source_project_id=PROJECT),              # direct, active
        _FakeBug(uuid.uuid4(), "triaged", transitive_project_id=PROJECT),           # transitive, active
        _FakeBug(uuid.uuid4(), "reported", source_project_id=OTHER_PROJECT),        # foreign, excluded
        _FakeBug(uuid.uuid4(), "closed", source_project_id=PROJECT),                # direct, terminal
    ]


# --- (a) equality-by-construction: project_view's UUID sets == todo_list/bug_list's --


def test_project_view_todos_uuid_set_matches_todo_list_under_identical_filters(monkeypatch) -> None:
    todos = _todo_universe()
    fake_todo = _make_fake_page_fn(todos, "anchor_project_id", _TODO_ACTIVE)

    monkeypatch.setattr(project_view_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_view_command, "list_todos_page", fake_todo)
    monkeypatch.setattr(project_view_command, "list_bugs_page", _make_fake_page_fn([], "source_project_id", _BUG_ACTIVE))
    monkeypatch.setattr(project_view_command, "list_comments_page", _make_fake_page_fn([], "anchor_project_id", None))
    view_result = asyncio.run(project_view_command.ProjectViewCommand().execute(project=str(PROJECT)))
    view_uuids = {row["uuid"] for row in view_result.to_dict()["data"]["todos"]}

    # Same fake backing function, same filters (project, active_only), via todo_list itself.
    monkeypatch.setattr(todo_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(todo_list_command, "list_todos_page", fake_todo)
    list_result = asyncio.run(todo_list_command.TodoListCommand().execute(project=str(PROJECT), active_only=True))
    list_uuids = {row["uuid"] for row in list_result.to_dict()["data"]["todos"]}

    assert view_uuids == list_uuids
    assert view_uuids == {str(todos[0].uuid), str(todos[1].uuid)}  # direct + transitive; foreign/terminal excluded


def test_project_view_bugs_uuid_set_matches_bug_list_under_identical_filters(monkeypatch) -> None:
    bugs = _bug_universe()
    fake_bug = _make_fake_page_fn(bugs, "source_project_id", _BUG_ACTIVE)

    monkeypatch.setattr(project_view_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_view_command, "list_todos_page", _make_fake_page_fn([], "anchor_project_id", _TODO_ACTIVE))
    monkeypatch.setattr(project_view_command, "list_bugs_page", fake_bug)
    monkeypatch.setattr(project_view_command, "list_comments_page", _make_fake_page_fn([], "anchor_project_id", None))
    view_result = asyncio.run(project_view_command.ProjectViewCommand().execute(project=str(PROJECT)))
    view_uuids = {row["uuid"] for row in view_result.to_dict()["data"]["bugs"]}

    monkeypatch.setattr(bug_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_list_command, "list_bugs_page", fake_bug)
    list_result = asyncio.run(bug_list_command.BugListCommand().execute(project=str(PROJECT), active_only=True))
    list_uuids = {row["uuid"] for row in list_result.to_dict()["data"]["bugs"]}

    assert view_uuids == list_uuids
    assert view_uuids == {str(bugs[0].uuid), str(bugs[1].uuid)}


# --- (b) match_source correctness ---------------------------------------------------


def test_match_source_direct_vs_transitive_for_todos_and_bugs(monkeypatch) -> None:
    todos = _todo_universe()
    bugs = _bug_universe()
    result, *_ = _run_project_view(monkeypatch, todos, bugs, project=str(PROJECT))
    data = result.to_dict()["data"]

    todo_by_uuid = {row["uuid"]: row["match_source"] for row in data["todos"]}
    assert todo_by_uuid[str(todos[0].uuid)] == "direct"
    assert todo_by_uuid[str(todos[1].uuid)] == "transitive_plan"

    bug_by_uuid = {row["uuid"]: row["match_source"] for row in data["bugs"]}
    assert bug_by_uuid[str(bugs[0].uuid)] == "direct"
    assert bug_by_uuid[str(bugs[1].uuid)] == "transitive_plan"


# --- (c) diagnostics counts -----------------------------------------------------------


def test_diagnostics_counts_per_collection(monkeypatch) -> None:
    todos = _todo_universe()
    bugs = _bug_universe()
    comments = [
        _FakeComment(uuid.uuid4(), anchor_project_id=PROJECT),
        _FakeComment(uuid.uuid4(), transitive_project_id=PROJECT),
        _FakeComment(uuid.uuid4(), anchor_project_id=OTHER_PROJECT),
    ]
    result, *_ = _run_project_view(monkeypatch, todos, bugs, comments=comments, project=str(PROJECT))
    diag = result.to_dict()["data"]["diagnostics"]

    assert diag["todos"] == {"direct_project_anchor_count": 1, "transitive_plan_match_count": 1}
    assert diag["bugs"] == {"direct_project_anchor_count": 1, "transitive_plan_match_count": 1}
    assert diag["comments"] == {"direct_project_anchor_count": 1, "transitive_plan_match_count": 1}
    assert result.to_dict()["data"]["comments"] == {"total": 2}


def test_summary_status_counts_and_totals(monkeypatch) -> None:
    todos = _todo_universe()
    bugs = _bug_universe()
    result, *_ = _run_project_view(monkeypatch, todos, bugs, project=str(PROJECT), active_only=False)
    summary = result.to_dict()["data"]["summary"]

    assert summary["todos"]["open"] == 1
    assert summary["todos"]["in_progress"] == 1
    assert summary["todos"]["closed"] == 1  # active_only=False -> terminal included
    assert summary["todos"]["total"] == 3  # foreign todo excluded regardless of active_only

    assert summary["bugs"]["reported"] == 1
    assert summary["bugs"]["triaged"] == 1
    assert summary["bugs"]["closed"] == 1
    assert summary["bugs"]["total"] == 3


def test_active_only_default_true_excludes_terminal_statuses(monkeypatch) -> None:
    todos = _todo_universe()
    bugs = _bug_universe()
    result, *_ = _run_project_view(monkeypatch, todos, bugs, project=str(PROJECT))
    summary = result.to_dict()["data"]["summary"]
    assert summary["todos"]["total"] == 2  # closed todo excluded by default active_only
    assert summary["todos"]["closed"] == 0
    assert summary["bugs"]["total"] == 2
    assert summary["bugs"]["closed"] == 0


# --- (d) pagination stability -----------------------------------------------------


def test_pagination_stability_across_offsets(monkeypatch) -> None:
    many_todos = [_FakeTodo(uuid.uuid4(), "open", anchor_project_id=PROJECT) for _ in range(5)]
    result_page1, *_ = _run_project_view(monkeypatch, many_todos, [], project=str(PROJECT), todo_limit=2, todo_offset=0)
    result_page2, *_ = _run_project_view(monkeypatch, many_todos, [], project=str(PROJECT), todo_limit=2, todo_offset=2)
    result_page3, *_ = _run_project_view(monkeypatch, many_todos, [], project=str(PROJECT), todo_limit=2, todo_offset=4)

    uuids_1 = [row["uuid"] for row in result_page1.to_dict()["data"]["todos"]]
    uuids_2 = [row["uuid"] for row in result_page2.to_dict()["data"]["todos"]]
    uuids_3 = [row["uuid"] for row in result_page3.to_dict()["data"]["todos"]]

    assert len(uuids_1) == 2 and len(uuids_2) == 2 and len(uuids_3) == 1
    assert set(uuids_1) | set(uuids_2) | set(uuids_3) == {str(t.uuid) for t in many_todos}
    assert not (set(uuids_1) & set(uuids_2))  # no overlap between pages
    # totals/diagnostics are page-independent (computed over the full matched set)
    assert result_page1.to_dict()["data"]["todo_total"] == 5
    assert result_page2.to_dict()["data"]["todo_total"] == 5
    assert result_page1.to_dict()["data"]["diagnostics"]["todos"]["direct_project_anchor_count"] == 5


def test_pagination_defaults_match_list_command_defaults(monkeypatch) -> None:
    result, *_ = _run_project_view(monkeypatch, [], [], project=str(PROJECT))
    data = result.to_dict()["data"]
    assert data["todo_limit"] == 50
    assert data["todo_offset"] == 0
    assert data["bug_limit"] == 50
    assert data["bug_offset"] == 0


# --- (e) unknown project uuid -> valid empty view; invalid uuid -> error ------------


def test_unknown_project_uuid_is_a_valid_empty_view(monkeypatch) -> None:
    unknown_project = uuid.uuid4()
    result, *_ = _run_project_view(monkeypatch, _todo_universe(), _bug_universe(), project=str(unknown_project))
    data = result.to_dict()["data"]
    assert data["todos"] == []
    assert data["bugs"] == []
    assert data["todo_total"] == 0
    assert data["bug_total"] == 0
    assert data["summary"]["todos"]["total"] == 0
    assert data["summary"]["bugs"]["total"] == 0
    assert "error" not in result.to_dict()


def test_invalid_project_uuid_raises_runtime_validation_error(monkeypatch) -> None:
    monkeypatch.setattr(project_view_command, "db_connection", _fake_db)
    result = asyncio.run(project_view_command.ProjectViewCommand().execute(project="not-a-uuid"))
    payload = result.to_dict()
    assert "error" in payload
    assert payload["error"]["data"]["domain_code"] == "RUNTIME_VALIDATION_ERROR"


# --- omitted kinds -------------------------------------------------------------------


def test_omitted_count_by_reason_lists_the_three_uncovered_kinds(monkeypatch) -> None:
    result, *_ = _run_project_view(monkeypatch, [], [], project=str(PROJECT))
    omitted = result.to_dict()["data"]["omitted_count_by_reason"]
    assert set(omitted.keys()) == {"bug_impact", "bug_fix", "bug_fix_propagation"}
    for reason in omitted.values():
        assert isinstance(reason, str) and len(reason) > 0


# --- schema/metadata sanity ------------------------------------------------------------


def test_schema_requires_only_project() -> None:
    schema = project_view_command.ProjectViewCommand.get_schema()
    assert schema["required"] == ["project"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"].keys()) == {
        "project", "active_only", "todo_limit", "todo_offset", "bug_limit", "bug_offset",
    }


def test_metadata_matches_class_attributes() -> None:
    metadata = project_view_command.ProjectViewCommand.metadata()
    assert metadata["name"] == "project_view"
    assert metadata["category"] == project_view_command.ProjectViewCommand.category
    assert metadata["parameters"]["project"]["required"] is True
    assert metadata["parameters"]["active_only"]["required"] is False
