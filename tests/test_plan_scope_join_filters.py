"""Regression tests for BUG 8684ea59 (child of e93dd68d, 0.1.42): remaining
list commands that resolved the required `plan` parameter and discarded it.

- review_result_list: plan scope = review results whose reviewed execution
  attempt belongs to the resolved plan (semi-join on execution_attempt.plan_uuid);
  attempt-less (reviewed_attempt_uuid NULL) and foreign-plan rows are excluded.
- bug_propagation_list: plan scope = propagations whose parent bug is anchored
  to the resolved plan (semi-join propagation -> bug_fix ->
  bug_report.source_plan_uuid); NULL/foreign excluded. linked_plan_uuid is the
  propagation TARGET, never the scope column.
- project_dependency_list: plan scope = edges where at least one endpoint is
  among the resolved plan's bound project uuids (plan_project bindings); a plan
  with zero bound projects yields an empty page.
- bug_fix_list / bug_impact_list: plan/bug consistency guard — a bug whose
  source_plan_uuid is set and differs from the resolved plan raises
  BUG_NOT_FOUND; a bug with source_plan_uuid NULL is accepted under any valid
  plan (preserves command-anchored runtime flows).

Covered per command: plan-name and plan-uuid addressing both reach the
store/SQL as the resolved uuid; foreign/NULL exclusion at the SQL level;
unknown plan -> PLAN_NOT_FOUND, not a silent empty page.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import (
    bug_fix_list_command,
    bug_impact_list_command,
    bug_propagation_list_command,
    project_dependency_list_command,
    review_result_list_command,
)
from plan_manager.commands.errors import DomainCommandError
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations
from plan_manager.storage.project_dependency_store import list_project_dependencies
from plan_manager.storage.review_result_store import list_review_results

PLAN_UUID = uuid.uuid4()
FOREIGN_PLAN_UUID = uuid.uuid4()
PLAN_NAME = "my-plan"
BOUND_PROJECT_IDS = [str(uuid.uuid4()), str(uuid.uuid4())]
BUG_UUID = uuid.uuid4()


@contextmanager
def _fake_db():
    yield object()


class _DummyPlan:
    def __init__(self, plan_uuid: uuid.UUID = PLAN_UUID, project_ids: list[str] | None = None):
        self.uuid = plan_uuid
        self.project_ids = list(project_ids or [])


def _make_resolve_plan(project_ids: list[str] | None = None):
    """Mimic plan_manager.commands.resolve.resolve_plan for one known plan."""

    def _fake_resolve_plan(conn, plan):
        if plan in (PLAN_NAME, str(PLAN_UUID)):
            return _DummyPlan(project_ids=project_ids)
        raise DomainCommandError("PLAN_NOT_FOUND", f"plan not found: {plan}")

    return _fake_resolve_plan


def _assert_domain_error(result, code: str) -> None:
    payload = result.to_dict()
    assert "error" in payload, f"expected an error result, got: {payload}"
    assert payload["error"]["data"]["domain_code"] == code


class _FakeResult:
    def fetchall(self):
        return []


class _FakeConn:
    """Records the SQL and params of every execute call; returns no rows."""

    def __init__(self):
        self.calls: list[tuple[str, list]] = []

    def execute(self, sql, params=None):
        self.calls.append((sql, list(params or [])))
        return _FakeResult()


class _DummyBug:
    def __init__(self, source_plan_uuid: uuid.UUID | None):
        self.source_plan_uuid = source_plan_uuid


# --- review_result_list: resolved plan uuid reaches the store --------------------


def _run_review_result_list(monkeypatch, plan: str):
    captured: dict = {}

    def fake_list(conn, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(review_result_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(review_result_list_command, "resolve_plan", _make_resolve_plan())
    monkeypatch.setattr(review_result_list_command, "list_review_results", fake_list)
    result = asyncio.run(review_result_list_command.ReviewResultListCommand().execute(plan=plan))
    return result, captured


def test_review_result_list_passes_resolved_plan_uuid_by_name(monkeypatch) -> None:
    result, captured = _run_review_result_list(monkeypatch, PLAN_NAME)
    assert result.to_dict()["data"]["total"] == 0
    assert captured["plan_uuid"] == PLAN_UUID


def test_review_result_list_passes_resolved_plan_uuid_by_uuid(monkeypatch) -> None:
    result, captured = _run_review_result_list(monkeypatch, str(PLAN_UUID))
    assert result.to_dict()["data"]["total"] == 0
    assert captured["plan_uuid"] == PLAN_UUID


def test_review_result_list_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result, captured = _run_review_result_list(monkeypatch, "no-such-plan")
    _assert_domain_error(result, "PLAN_NOT_FOUND")
    assert captured == {}, "store must not be queried for an unknown plan"


def test_list_review_results_sql_semijoins_execution_attempt_plan() -> None:
    conn = _FakeConn()
    list_review_results(conn, plan_uuid=PLAN_UUID)
    sql, params = conn.calls[0]
    assert "execution_attempt" in sql
    assert "ea.plan_uuid = %s" in sql
    assert "ea.uuid = review_result.reviewed_attempt_uuid" in sql
    assert PLAN_UUID in params


def test_list_review_results_sql_without_plan_scope_unchanged() -> None:
    conn = _FakeConn()
    list_review_results(conn)
    sql, params = conn.calls[0]
    assert "execution_attempt" not in sql
    assert params == []


# --- bug_propagation_list: resolved plan uuid reaches the store ------------------


def _run_bug_propagation_list(monkeypatch, plan: str, **kwargs):
    captured: dict = {}

    def fake_list(conn, **store_kwargs):
        captured.update(store_kwargs)
        return []

    monkeypatch.setattr(bug_propagation_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_propagation_list_command, "resolve_plan", _make_resolve_plan())
    monkeypatch.setattr(bug_propagation_list_command, "list_bug_fix_propagations", fake_list)
    result = asyncio.run(
        bug_propagation_list_command.BugPropagationListCommand().execute(plan=plan, **kwargs)
    )
    return result, captured


def test_bug_propagation_list_passes_resolved_plan_uuid_by_name(monkeypatch) -> None:
    result, captured = _run_bug_propagation_list(monkeypatch, PLAN_NAME)
    assert result.to_dict()["data"]["total"] == 0
    assert captured["source_plan_uuid"] == PLAN_UUID


def test_bug_propagation_list_passes_resolved_plan_uuid_by_uuid(monkeypatch) -> None:
    result, captured = _run_bug_propagation_list(monkeypatch, str(PLAN_UUID))
    assert result.to_dict()["data"]["total"] == 0
    assert captured["source_plan_uuid"] == PLAN_UUID


def test_bug_propagation_list_bug_fix_filter_intersects_plan_scope(monkeypatch) -> None:
    bug_fix_id = uuid.uuid4()
    result, captured = _run_bug_propagation_list(monkeypatch, PLAN_NAME, bug_fix_id=str(bug_fix_id))
    assert result.to_dict()["data"]["total"] == 0
    assert captured["bug_fix_uuid"] == bug_fix_id
    assert captured["source_plan_uuid"] == PLAN_UUID, "plan scope must survive the bug_fix_id filter"


def test_bug_propagation_list_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result, captured = _run_bug_propagation_list(monkeypatch, "no-such-plan")
    _assert_domain_error(result, "PLAN_NOT_FOUND")
    assert captured == {}, "store must not be queried for an unknown plan"


def test_list_bug_fix_propagations_sql_semijoins_parent_bug_plan() -> None:
    conn = _FakeConn()
    list_bug_fix_propagations(conn, source_plan_uuid=PLAN_UUID)
    sql, params = conn.calls[0]
    assert "JOIN bug_report b ON b.uuid = f.bug_uuid" in sql
    assert "b.source_plan_uuid = %s" in sql
    assert "f.uuid = bug_fix_propagation.bug_fix_uuid" in sql
    assert "linked_plan_uuid = %s" not in sql, "linked_plan_uuid is the propagation target, not the scope column"
    assert PLAN_UUID in params


def test_list_bug_fix_propagations_sql_without_plan_scope_unchanged() -> None:
    conn = _FakeConn()
    list_bug_fix_propagations(conn)
    sql, params = conn.calls[0]
    assert "bug_report" not in sql
    assert params == []


# --- project_dependency_list: bound project uuids reach the store ----------------


def _run_project_dependency_list(monkeypatch, plan: str, project_ids: list[str] | None = None, **kwargs):
    captured: dict = {}

    def fake_list(conn, **store_kwargs):
        captured.update(store_kwargs)
        return []

    monkeypatch.setattr(project_dependency_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        project_dependency_list_command, "resolve_plan", _make_resolve_plan(project_ids=project_ids)
    )
    monkeypatch.setattr(project_dependency_list_command, "list_project_dependencies", fake_list)
    result = asyncio.run(
        project_dependency_list_command.ProjectDependencyListCommand().execute(plan=plan, **kwargs)
    )
    return result, captured


def test_project_dependency_list_passes_bound_project_uuids_by_name(monkeypatch) -> None:
    result, captured = _run_project_dependency_list(monkeypatch, PLAN_NAME, project_ids=BOUND_PROJECT_IDS)
    assert result.to_dict()["data"]["total"] == 0
    assert captured["project_ids"] == [uuid.UUID(pid) for pid in BOUND_PROJECT_IDS]


def test_project_dependency_list_passes_bound_project_uuids_by_uuid(monkeypatch) -> None:
    result, captured = _run_project_dependency_list(
        monkeypatch, str(PLAN_UUID), project_ids=BOUND_PROJECT_IDS
    )
    assert result.to_dict()["data"]["total"] == 0
    assert captured["project_ids"] == [uuid.UUID(pid) for pid in BOUND_PROJECT_IDS]


def test_project_dependency_list_zero_bound_projects_empty_page(monkeypatch) -> None:
    result, captured = _run_project_dependency_list(monkeypatch, PLAN_NAME, project_ids=[])
    data = result.to_dict()["data"]
    assert data["total"] == 0
    assert data["project_dependencies"] == []
    assert captured["project_ids"] == []


def test_project_dependency_list_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result, captured = _run_project_dependency_list(monkeypatch, "no-such-plan")
    _assert_domain_error(result, "PLAN_NOT_FOUND")
    assert captured == {}, "store must not be queried for an unknown plan"


def test_list_project_dependencies_sql_scopes_either_endpoint() -> None:
    conn = _FakeConn()
    bound = [uuid.UUID(pid) for pid in BOUND_PROJECT_IDS]
    list_project_dependencies(conn, project_ids=bound)
    sql, params = conn.calls[0]
    assert "(dependent_project_id = ANY(%s) OR depends_on_project_id = ANY(%s))" in sql
    assert params.count(bound) == 2


def test_list_project_dependencies_empty_scope_short_circuits() -> None:
    conn = _FakeConn()
    assert list_project_dependencies(conn, project_ids=[]) == []
    assert conn.calls == [], "an empty bound-project scope must not query the database"


def test_list_project_dependencies_sql_without_plan_scope_unchanged() -> None:
    conn = _FakeConn()
    list_project_dependencies(conn)
    sql, params = conn.calls[0]
    assert "ANY" not in sql
    assert params == []


# --- bug_fix_list: plan/bug consistency guard ------------------------------------


def _run_bug_fix_list(monkeypatch, plan: str, bug_record):
    captured: dict = {}

    def fake_get_bug(conn, bug_uuid):
        captured["get_bug"] = bug_uuid
        return bug_record

    def fake_list(conn, **store_kwargs):
        captured["list"] = store_kwargs
        return []

    monkeypatch.setattr(bug_fix_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_fix_list_command, "resolve_plan", _make_resolve_plan())
    monkeypatch.setattr(bug_fix_list_command, "get_bug", fake_get_bug)
    monkeypatch.setattr(bug_fix_list_command, "list_bug_fixes", fake_list)
    result = asyncio.run(
        bug_fix_list_command.BugFixListCommand().execute(plan=plan, bug=str(BUG_UUID))
    )
    return result, captured


def test_bug_fix_list_foreign_anchored_bug_rejected(monkeypatch) -> None:
    result, captured = _run_bug_fix_list(monkeypatch, PLAN_NAME, _DummyBug(FOREIGN_PLAN_UUID))
    _assert_domain_error(result, "BUG_NOT_FOUND")
    assert "list" not in captured, "fixes of a foreign-plan bug must never be listed"


def test_bug_fix_list_null_anchored_bug_accepted(monkeypatch) -> None:
    result, captured = _run_bug_fix_list(monkeypatch, PLAN_NAME, _DummyBug(None))
    assert result.to_dict()["data"]["total"] == 0
    assert captured["list"]["bug_uuid"] == BUG_UUID


def test_bug_fix_list_same_plan_bug_accepted_by_name_and_uuid(monkeypatch) -> None:
    for plan in (PLAN_NAME, str(PLAN_UUID)):
        result, captured = _run_bug_fix_list(monkeypatch, plan, _DummyBug(PLAN_UUID))
        assert result.to_dict()["data"]["total"] == 0
        assert captured["list"]["bug_uuid"] == BUG_UUID


def test_bug_fix_list_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result, captured = _run_bug_fix_list(monkeypatch, "no-such-plan", _DummyBug(PLAN_UUID))
    _assert_domain_error(result, "PLAN_NOT_FOUND")
    assert captured == {}, "the bug must not be fetched for an unknown plan"


# --- bug_impact_list: plan/bug consistency guard ---------------------------------


def _run_bug_impact_list(monkeypatch, plan: str, bug_record):
    captured: dict = {}

    def fake_get_bug(conn, bug_uuid):
        captured["get_bug"] = bug_uuid
        return bug_record

    def fake_list(conn, **store_kwargs):
        captured["list"] = store_kwargs
        return []

    monkeypatch.setattr(bug_impact_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_impact_list_command, "resolve_plan", _make_resolve_plan())
    monkeypatch.setattr(bug_impact_list_command, "get_bug", fake_get_bug)
    monkeypatch.setattr(bug_impact_list_command, "list_bug_impacts", fake_list)
    result = asyncio.run(
        bug_impact_list_command.BugImpactListCommand().execute(plan=plan, bug_id=str(BUG_UUID))
    )
    return result, captured


def test_bug_impact_list_foreign_anchored_bug_rejected(monkeypatch) -> None:
    result, captured = _run_bug_impact_list(monkeypatch, PLAN_NAME, _DummyBug(FOREIGN_PLAN_UUID))
    _assert_domain_error(result, "BUG_NOT_FOUND")
    assert "list" not in captured, "impacts of a foreign-plan bug must never be listed"


def test_bug_impact_list_null_anchored_bug_accepted(monkeypatch) -> None:
    result, captured = _run_bug_impact_list(monkeypatch, PLAN_NAME, _DummyBug(None))
    assert result.to_dict()["data"]["total"] == 0
    assert captured["list"]["bug_uuid"] == BUG_UUID


def test_bug_impact_list_same_plan_bug_accepted_by_name_and_uuid(monkeypatch) -> None:
    for plan in (PLAN_NAME, str(PLAN_UUID)):
        result, captured = _run_bug_impact_list(monkeypatch, plan, _DummyBug(PLAN_UUID))
        assert result.to_dict()["data"]["total"] == 0
        assert captured["list"]["bug_uuid"] == BUG_UUID


def test_bug_impact_list_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result, captured = _run_bug_impact_list(monkeypatch, "no-such-plan", _DummyBug(PLAN_UUID))
    _assert_domain_error(result, "PLAN_NOT_FOUND")
    assert captured == {}, "the bug must not be fetched for an unknown plan"


# --- metadata surfaces the real semantics ----------------------------------------


def test_plan_scope_documented_in_metadata() -> None:
    """plan became OPTIONAL on review_result_list, bug_propagation_list, bug_fix_list,
    and bug_impact_list (bug 8684ea59 follow-on: project as a first-class scope);
    project_dependency_list is NOT part of that family (its plan parameter is the
    sole mechanism resolving the bound-project scope, not a direct anchor filter)
    and keeps plan required."""
    for command_cls, scope_marker, plan_required in (
        (review_result_list_command.ReviewResultListCommand, "execution_attempt.plan_uuid", False),
        (bug_propagation_list_command.BugPropagationListCommand, "source_plan_uuid", False),
        (project_dependency_list_command.ProjectDependencyListCommand, "plan_project bindings", True),
        (bug_fix_list_command.BugFixListCommand, "source_plan_uuid", False),
        (bug_impact_list_command.BugImpactListCommand, "source_plan_uuid", False),
    ):
        metadata = command_cls.metadata()
        assert metadata["parameters"]["plan"]["required"] is plan_required
        assert scope_marker in metadata["parameters"]["plan"]["description"]
        assert "PLAN_NOT_FOUND" in metadata["error_cases"]
        schema = command_cls.get_schema()
        assert ("plan" in schema["required"]) is plan_required
        assert scope_marker in schema["properties"]["plan"]["description"]
        assert schema["additionalProperties"] is False


def test_propagation_metadata_disclaims_linked_plan_uuid() -> None:
    description = bug_propagation_list_command.BugPropagationListCommand.metadata()["parameters"]["plan"]["description"]
    assert "linked_plan_uuid" in description
    assert "NOT the" in description


def test_bug_plan_mismatch_documented_in_error_cases() -> None:
    for command_cls in (
        bug_fix_list_command.BugFixListCommand,
        bug_impact_list_command.BugImpactListCommand,
    ):
        case = command_cls.metadata()["error_cases"]["BUG_NOT_FOUND"]
        assert "source_plan_uuid" in case["description"]
        assert "NULL" in case["description"]
