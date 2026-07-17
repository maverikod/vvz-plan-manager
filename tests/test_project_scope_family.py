"""Regression tests for the scope-contract defect family closure (2026-07-17):

`project` becomes a first-class, TRANSITIVELY-matching OPTIONAL scope across the
runtime work-registry command surface (bug_list, todo_list, comment_list,
escalation_list, bug_fix_list, bug_impact_list, bug_propagation_list,
review_result_list); `plan` becomes optional everywhere in that family (with a
plan/record consistency check preserved where one already existed: bug_get,
bug_fix_list, bug_impact_list); and project_dependents' plan parameter becomes
existence-only (the underlying table has no plan column to filter by).

Covers:
- plan_manager.storage.project_scope.resolve_project_plan_uuids: resolves
  plan.project_ids -> the set of plan uuids bound to a project.
- The exact SMOKE-CR1 null-anchor-invisibility bug shape: a record whose own
  direct project anchor (source_project_id / anchor_project_id / target_project_id)
  is NULL is still reachable by a project filter when the record's plan is bound
  to that project, for bug_list, todo_list, comment_list, bug_fix_list, and
  bug_impact_list (in-command transitive filtering).
- The store-pushed-down transitive project filter for escalation_list,
  bug_propagation_list, and review_result_list (SQL clause construction against a
  fake connection).
- bug_get: works with no plan; a mismatched plan raises BUG_NOT_FOUND; a NULL
  source_plan_uuid bug is accepted under any supplied plan.
- project_dependents: works without plan (resolve_plan is never called); with a
  supplied plan it is checked only for existence.
- plan is optional (schema + metadata) across the whole family without raising.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import (
    bug_fix_list_command,
    bug_get_command,
    bug_impact_list_command,
    bug_list_command,
    bug_propagation_list_command,
    comment_list_command,
    escalation_list_command,
    project_dependents_command,
    review_result_list_command,
    todo_list_command,
)
from plan_manager.commands.errors import DomainCommandError
from plan_manager.storage import project_scope
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations
from plan_manager.storage.escalation_store import list_escalations
from plan_manager.storage.review_result_store import list_review_results

PROJECT_UUID = uuid.uuid4()
OTHER_PROJECT_UUID = uuid.uuid4()
PLAN_UUID = uuid.uuid4()
PLAN_NAME = "my-plan"


@contextmanager
def _fake_db():
    yield object()


class _DummyPlan:
    def __init__(self, plan_uuid: uuid.UUID = PLAN_UUID):
        self.uuid = plan_uuid


def _fake_resolve_plan(conn, plan):
    """Mimic plan_manager.commands.resolve.resolve_plan for one known plan."""
    if plan in (PLAN_NAME, str(PLAN_UUID)):
        return _DummyPlan()
    raise DomainCommandError("PLAN_NOT_FOUND", f"plan not found: {plan}")


def _assert_domain_error(result, code: str) -> None:
    payload = result.to_dict()
    assert "error" in payload, f"expected an error result, got: {payload}"
    assert payload["error"]["data"]["domain_code"] == code


class _FakeQueryResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    """Records every execute() call's SQL/params; returns configured rows for the
    plan.project_ids lookup and a separate default for everything else."""

    def __init__(self, project_plan_rows=None, default_rows=None):
        self.calls: list[tuple[str, list]] = []
        self._project_plan_rows = project_plan_rows or []
        self._default_rows = default_rows or []

    def execute(self, sql, params=None):
        self.calls.append((sql, list(params or [])))
        if "FROM plan WHERE" in sql and "project_ids" in sql:
            return _FakeQueryResult(self._project_plan_rows)
        return _FakeQueryResult(self._default_rows)


# --- resolve_project_plan_uuids ---------------------------------------------------


def test_resolve_project_plan_uuids_queries_project_ids_array() -> None:
    bound_plan = uuid.uuid4()
    conn = _FakeConn(project_plan_rows=[(bound_plan,)])
    result = project_scope.resolve_project_plan_uuids(conn, PROJECT_UUID)
    assert result == {bound_plan}
    sql, params = conn.calls[0]
    assert "ANY(project_ids)" in sql
    assert params == [str(PROJECT_UUID)]


def test_resolve_project_plan_uuids_empty_when_no_plan_bound() -> None:
    conn = _FakeConn(project_plan_rows=[])
    assert project_scope.resolve_project_plan_uuids(conn, PROJECT_UUID) == set()


# --- bug_list: null-anchor invisibility bug shape, reached via plan binding -------


class _FakeBug:
    def __init__(self, source_project_id=None, source_plan_uuid=None):
        self.source_project_id = source_project_id
        self.source_plan_uuid = source_plan_uuid
        self.source_file_path = None
        self.source_revision_uuid = None
        self.source_step_uuid = None
        self.priority_nice = 0
        self.created_at = "2026-07-17T00:00:00+00:00"
        self.status = "reported"

    def to_payload(self):
        return {"source_project_id": str(self.source_project_id) if self.source_project_id else None}


def test_bug_list_project_filter_reaches_null_anchored_bug_via_plan_binding(monkeypatch) -> None:
    bound_plan = uuid.uuid4()
    null_anchor_bug = _FakeBug(source_project_id=None, source_plan_uuid=bound_plan)
    foreign_bug = _FakeBug(source_project_id=None, source_plan_uuid=uuid.uuid4())
    direct_bug = _FakeBug(source_project_id=PROJECT_UUID, source_plan_uuid=None)

    monkeypatch.setattr(bug_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_list_command, "list_bugs", lambda conn, **kw: [null_anchor_bug, foreign_bug, direct_bug])
    monkeypatch.setattr(
        bug_list_command, "resolve_project_plan_uuids", lambda conn, project_id: {bound_plan} if project_id == PROJECT_UUID else set()
    )
    # No plan supplied at all: demonstrates plan is optional (bug e93dd68d/8684ea59 family).
    result = asyncio.run(bug_list_command.BugListCommand().execute(project=str(PROJECT_UUID)))
    data = result.to_dict()["data"]
    assert data["total"] == 2  # null_anchor_bug (transitive) + direct_bug (direct); foreign excluded


# --- todo_list: same null-anchor bug shape ----------------------------------------


class _FakeTodo:
    def __init__(self, anchor_project_id=None, anchor_plan_uuid=None):
        self.anchor_project_id = anchor_project_id
        self.anchor_plan_uuid = anchor_plan_uuid

    def to_payload(self):
        return {}


def test_todo_list_project_filter_reaches_null_anchored_todo_via_plan_binding(monkeypatch) -> None:
    bound_plan = uuid.uuid4()
    null_anchor = _FakeTodo(anchor_project_id=None, anchor_plan_uuid=bound_plan)
    foreign = _FakeTodo(anchor_project_id=None, anchor_plan_uuid=uuid.uuid4())
    direct = _FakeTodo(anchor_project_id=PROJECT_UUID, anchor_plan_uuid=None)

    monkeypatch.setattr(todo_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(todo_list_command, "list_todos", lambda conn, **kw: [null_anchor, foreign, direct])
    monkeypatch.setattr(todo_list_command, "resolve_project_plan_uuids", lambda conn, project_id: {bound_plan})
    result = asyncio.run(todo_list_command.TodoListCommand().execute(project=str(PROJECT_UUID)))
    data = result.to_dict()["data"]
    assert data["total"] == 2


# --- comment_list: same null-anchor bug shape, plan omitted -----------------------


class _FakeComment:
    def __init__(self, anchor_project_id=None, anchor_plan_uuid=None):
        self.anchor_project_id = anchor_project_id
        self.anchor_plan_uuid = anchor_plan_uuid
        self.anchor_file_path = None
        self.anchor_revision_uuid = None
        self.kind = "note"
        self.author = "tester"
        self.resolved = False
        self.created_at = "2026-07-17T00:00:00+00:00"

    def to_payload(self):
        return {}


def test_comment_list_project_filter_reaches_null_anchored_comment_via_plan_binding(monkeypatch) -> None:
    bound_plan = uuid.uuid4()
    null_anchor = _FakeComment(anchor_project_id=None, anchor_plan_uuid=bound_plan)
    foreign = _FakeComment(anchor_project_id=None, anchor_plan_uuid=uuid.uuid4())
    direct = _FakeComment(anchor_project_id=PROJECT_UUID, anchor_plan_uuid=None)
    captured: dict = {}

    def fake_list_comments(conn, **kwargs):
        captured.update(kwargs)
        return [null_anchor, foreign, direct]

    monkeypatch.setattr(comment_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(comment_list_command, "list_comments", fake_list_comments)
    monkeypatch.setattr(comment_list_command, "resolve_project_plan_uuids", lambda conn, project_id: {bound_plan})
    result = asyncio.run(comment_list_command.CommentListCommand().execute(project=str(PROJECT_UUID)))
    data = result.to_dict()["data"]
    assert data["total"] == 2
    assert captured["anchor_plan_uuid"] is None  # plan omitted entirely -> no plan scoping applied


# --- bug_fix_list: transitive via the OWNING BUG's plan binding -------------------


class _FakeParentBug:
    def __init__(self, source_plan_uuid=None):
        self.source_plan_uuid = source_plan_uuid


class _FakeFix:
    def __init__(self, source_project_id=None):
        self.source_project_id = source_project_id
        self.status = "proposed"
        self.created_at = "2026-07-17T00:00:00+00:00"

    def to_payload(self):
        return {}


def test_bug_fix_list_project_filter_reaches_null_anchored_fix_via_bug_plan_binding(monkeypatch) -> None:
    """When the owning bug's plan is bound to the project, every fix under that bug
    is in scope transitively (the check is at the parent-bug level, since bug_fix
    carries no plan column of its own) — this is what makes a fix with
    source_project_id NULL (the SMOKE-CR1 shape) reachable."""
    bound_plan = uuid.uuid4()
    bug_record = _FakeParentBug(source_plan_uuid=bound_plan)
    null_anchor_fix = _FakeFix(source_project_id=None)
    direct_fix = _FakeFix(source_project_id=PROJECT_UUID)

    monkeypatch.setattr(bug_fix_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_fix_list_command, "get_bug", lambda conn, bug_uuid: bug_record)
    monkeypatch.setattr(bug_fix_list_command, "list_bug_fixes", lambda conn, **kw: [null_anchor_fix, direct_fix])
    monkeypatch.setattr(bug_fix_list_command, "resolve_project_plan_uuids", lambda conn, project_id: {bound_plan})
    result = asyncio.run(
        bug_fix_list_command.BugFixListCommand().execute(bug=str(uuid.uuid4()), project=str(PROJECT_UUID))
    )
    data = result.to_dict()["data"]
    assert data["total"] == 2  # null_anchor_fix (transitive via bug's plan) + direct_fix (direct match)


def test_bug_fix_list_project_filter_excludes_fix_when_bug_not_bound_and_no_direct_match(monkeypatch) -> None:
    """The converse: when the owning bug's plan is NOT bound to the project, only
    fixes with a direct source_project_id match survive; a NULL-anchored fix and a
    fix explicitly tagged with a different project are both excluded."""
    bug_record = _FakeParentBug(source_plan_uuid=uuid.uuid4())
    null_anchor_fix = _FakeFix(source_project_id=None)
    foreign_fix = _FakeFix(source_project_id=OTHER_PROJECT_UUID)
    direct_fix = _FakeFix(source_project_id=PROJECT_UUID)

    monkeypatch.setattr(bug_fix_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_fix_list_command, "get_bug", lambda conn, bug_uuid: bug_record)
    monkeypatch.setattr(bug_fix_list_command, "list_bug_fixes", lambda conn, **kw: [null_anchor_fix, foreign_fix, direct_fix])
    monkeypatch.setattr(bug_fix_list_command, "resolve_project_plan_uuids", lambda conn, project_id: set())
    result = asyncio.run(
        bug_fix_list_command.BugFixListCommand().execute(bug=str(uuid.uuid4()), project=str(PROJECT_UUID))
    )
    data = result.to_dict()["data"]
    assert data["total"] == 1  # only direct_fix


def test_bug_fix_list_no_plan_supplied_works(monkeypatch) -> None:
    monkeypatch.setattr(bug_fix_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_fix_list_command, "get_bug", lambda conn, bug_uuid: _FakeParentBug(source_plan_uuid=PLAN_UUID))
    monkeypatch.setattr(bug_fix_list_command, "list_bug_fixes", lambda conn, **kw: [])
    result = asyncio.run(bug_fix_list_command.BugFixListCommand().execute(bug=str(uuid.uuid4())))
    assert result.to_dict()["data"]["total"] == 0


# --- bug_impact_list: transitive via the IMPACT's OWN plan binding ----------------


class _FakeImpact:
    def __init__(self, target_project_id=None, target_plan_uuid=None):
        self.target_project_id = target_project_id
        self.target_plan_uuid = target_plan_uuid
        self.impact_type = "code_dependency"
        self.status = "suspected"
        self.created_at = "2026-07-17T00:00:00+00:00"

    def to_payload(self):
        return {}


def test_bug_impact_list_project_filter_reaches_null_anchored_impact_via_own_plan_binding(monkeypatch) -> None:
    bound_plan = uuid.uuid4()
    null_anchor = _FakeImpact(target_project_id=None, target_plan_uuid=bound_plan)
    foreign = _FakeImpact(target_project_id=None, target_plan_uuid=uuid.uuid4())
    direct = _FakeImpact(target_project_id=PROJECT_UUID, target_plan_uuid=None)

    monkeypatch.setattr(bug_impact_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_impact_list_command, "get_bug", lambda conn, bug_uuid: _FakeParentBug(source_plan_uuid=None))
    monkeypatch.setattr(bug_impact_list_command, "list_bug_impacts", lambda conn, **kw: [null_anchor, foreign, direct])
    monkeypatch.setattr(bug_impact_list_command, "resolve_project_plan_uuids", lambda conn, project_id: {bound_plan})
    result = asyncio.run(
        bug_impact_list_command.BugImpactListCommand().execute(bug_id=str(uuid.uuid4()), project=str(PROJECT_UUID))
    )
    data = result.to_dict()["data"]
    assert data["total"] == 2


# --- escalation_store: store-level transitive project filter (SQL construction) ---


def test_list_escalations_sql_project_filter_transitive_or() -> None:
    conn = _FakeConn()
    bound = [uuid.uuid4(), uuid.uuid4()]
    list_escalations(conn, anchor_project_id=PROJECT_UUID, project_bound_plan_uuids=bound)
    sql, params = conn.calls[0]
    assert "anchor_project_id = %s OR anchor_plan_uuid = ANY(%s)" in sql
    assert PROJECT_UUID in params
    assert bound in params


def test_list_escalations_sql_project_filter_direct_only_when_no_bound_plans() -> None:
    conn = _FakeConn()
    list_escalations(conn, anchor_project_id=PROJECT_UUID, project_bound_plan_uuids=[])
    sql, params = conn.calls[0]
    assert "anchor_project_id = %s" in sql
    assert "ANY" not in sql
    assert params == [PROJECT_UUID]


def test_list_escalations_sql_without_project_filter_unchanged() -> None:
    conn = _FakeConn()
    list_escalations(conn)
    sql, params = conn.calls[0]
    assert "anchor_project_id" not in sql
    assert params == []


# --- bug_fix_propagation_store: store-level transitive project filter ------------


def test_list_bug_fix_propagations_sql_project_filter_transitive_or() -> None:
    conn = _FakeConn()
    bound = [uuid.uuid4()]
    list_bug_fix_propagations(conn, source_project_id=PROJECT_UUID, project_bound_plan_uuids=bound)
    sql, params = conn.calls[0]
    assert "b.source_project_id = %s OR b.source_plan_uuid = ANY(%s)" in sql
    assert PROJECT_UUID in params
    assert bound in params


def test_list_bug_fix_propagations_sql_project_filter_direct_only_when_no_bound_plans() -> None:
    conn = _FakeConn()
    list_bug_fix_propagations(conn, source_project_id=PROJECT_UUID, project_bound_plan_uuids=[])
    sql, params = conn.calls[0]
    assert "b.source_project_id = %s" in sql
    assert "ANY" not in sql


# --- review_result_store: PURELY transitive project filter (no direct column) ----


def test_list_review_results_sql_project_filter_transitive() -> None:
    conn = _FakeConn()
    bound = [uuid.uuid4()]
    list_review_results(conn, project_bound_plan_uuids=bound)
    sql, params = conn.calls[0]
    assert "ea.plan_uuid = ANY(%s)" in sql
    assert bound in params


def test_list_review_results_sql_project_filter_zero_bound_plans_forces_empty() -> None:
    conn = _FakeConn()
    list_review_results(conn, project_bound_plan_uuids=[])
    sql, params = conn.calls[0]
    assert "1 = 0" in sql


def test_list_review_results_sql_without_project_filter_unchanged() -> None:
    conn = _FakeConn()
    list_review_results(conn)
    sql, params = conn.calls[0]
    assert "1 = 0" not in sql
    assert "ea.plan_uuid = ANY" not in sql


# --- bug_get: plan optional with consistency check --------------------------------


class _FakeBugGet:
    def __init__(self, source_plan_uuid=None):
        self.source_plan_uuid = source_plan_uuid

    def to_payload(self):
        return {"bug": "payload"}


def _run_bug_get(monkeypatch, bug_record, plan=None):
    monkeypatch.setattr(bug_get_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_get_command, "resolve_plan", _fake_resolve_plan)
    monkeypatch.setattr(bug_get_command, "get_bug", lambda conn, bug_uuid: bug_record)
    return asyncio.run(bug_get_command.BugGetCommand().execute(bug_id=str(uuid.uuid4()), plan=plan))


def test_bug_get_no_plan_works(monkeypatch) -> None:
    result = _run_bug_get(monkeypatch, _FakeBugGet(source_plan_uuid=PLAN_UUID))
    assert result.to_dict()["data"] == {"bug": "payload"}


def test_bug_get_matching_plan_works(monkeypatch) -> None:
    result = _run_bug_get(monkeypatch, _FakeBugGet(source_plan_uuid=PLAN_UUID), plan=PLAN_NAME)
    assert result.to_dict()["data"] == {"bug": "payload"}


def test_bug_get_mismatched_plan_raises_bug_not_found(monkeypatch) -> None:
    result = _run_bug_get(monkeypatch, _FakeBugGet(source_plan_uuid=uuid.uuid4()), plan=PLAN_NAME)
    _assert_domain_error(result, "BUG_NOT_FOUND")


def test_bug_get_null_plan_bug_accepted_under_any_supplied_plan(monkeypatch) -> None:
    result = _run_bug_get(monkeypatch, _FakeBugGet(source_plan_uuid=None), plan=PLAN_NAME)
    assert result.to_dict()["data"] == {"bug": "payload"}


def test_bug_get_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result = _run_bug_get(monkeypatch, _FakeBugGet(source_plan_uuid=PLAN_UUID), plan="no-such-plan")
    _assert_domain_error(result, "PLAN_NOT_FOUND")


# --- project_dependents: plan optional, existence-only when supplied -------------


def test_project_dependents_works_without_plan(monkeypatch) -> None:
    calls = {"resolve_plan": 0}

    def fake_resolve_plan(conn, plan):
        calls["resolve_plan"] += 1
        return _DummyPlan()

    monkeypatch.setattr(project_dependents_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_dependents_command, "resolve_plan", fake_resolve_plan)
    monkeypatch.setattr(project_dependents_command, "list_reverse_dependents", lambda conn, pid: [])
    result = asyncio.run(project_dependents_command.ProjectDependentsCommand().execute(project_id=str(PROJECT_UUID)))
    assert result.to_dict()["data"] == {"reverse_dependents": []}
    assert calls["resolve_plan"] == 0


def test_project_dependents_with_plan_checks_existence_only(monkeypatch) -> None:
    monkeypatch.setattr(project_dependents_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_dependents_command, "resolve_plan", _fake_resolve_plan)
    monkeypatch.setattr(project_dependents_command, "list_reverse_dependents", lambda conn, pid: [])
    result = asyncio.run(
        project_dependents_command.ProjectDependentsCommand().execute(project_id=str(PROJECT_UUID), plan=PLAN_NAME)
    )
    assert result.to_dict()["data"] == {"reverse_dependents": []}


def test_project_dependents_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    monkeypatch.setattr(project_dependents_command, "db_connection", _fake_db)
    monkeypatch.setattr(project_dependents_command, "resolve_plan", _fake_resolve_plan)
    result = asyncio.run(
        project_dependents_command.ProjectDependentsCommand().execute(project_id=str(PROJECT_UUID), plan="no-such-plan")
    )
    _assert_domain_error(result, "PLAN_NOT_FOUND")


# --- plan is optional (schema + metadata) across the whole family ----------------


def test_plan_is_optional_schema_and_metadata_across_family() -> None:
    for command_cls in (
        bug_list_command.BugListCommand,
        comment_list_command.CommentListCommand,
        escalation_list_command.EscalationListCommand,
        bug_fix_list_command.BugFixListCommand,
        bug_impact_list_command.BugImpactListCommand,
        bug_propagation_list_command.BugPropagationListCommand,
        review_result_list_command.ReviewResultListCommand,
        project_dependents_command.ProjectDependentsCommand,
    ):
        schema = command_cls.get_schema()
        assert "plan" not in schema["required"], command_cls.name
        metadata = command_cls.metadata()
        assert metadata["parameters"]["plan"]["required"] is False, command_cls.name


def test_bug_get_plan_is_optional_schema_and_metadata() -> None:
    schema = bug_get_command.BugGetCommand.get_schema()
    assert "plan" not in schema["required"]
    assert "bug_id" in schema["required"]
    metadata = bug_get_command.BugGetCommand.metadata()
    assert metadata["parameters"]["plan"]["required"] is False
