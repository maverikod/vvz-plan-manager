"""Regression tests for BUG e93dd68d (plan scope dropped by list commands, 0.1.41):

bug_list, comment_list, and escalation_list resolved their required `plan`
parameter but discarded the result, returning GLOBAL lists. The fix scopes
each listing by direct anchor equality against the resolved plan uuid
(bug_list: source_plan_uuid; comment_list/escalation_list: anchor_plan_uuid),
excluding NULL and foreign plan anchors, with no transitive matching.

Covered per command:
- plan-name and plan-uuid addressing both reach the store/SQL as the resolved uuid;
- foreign-plan and null-plan rows are excluded (store SQL WHERE clause tests);
- unknown plan -> PLAN_NOT_FOUND, not a silent empty page.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import bug_list_command, comment_list_command, escalation_list_command
from plan_manager.commands.errors import DomainCommandError
from plan_manager.storage.bug_report_store import list_bugs
from plan_manager.storage.escalation_store import list_escalations

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


# --- bug_list: resolved plan uuid reaches the store ------------------------------


def _run_bug_list(monkeypatch, plan: str):
    captured: dict = {}

    def fake_list_bugs(conn, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(bug_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_list_command, "resolve_plan", _fake_resolve_plan)
    monkeypatch.setattr(bug_list_command, "list_bugs", fake_list_bugs)
    result = asyncio.run(bug_list_command.BugListCommand().execute(plan=plan))
    return result, captured


def test_bug_list_passes_resolved_plan_uuid_by_name(monkeypatch) -> None:
    result, captured = _run_bug_list(monkeypatch, PLAN_NAME)
    assert result.to_dict()["data"]["total"] == 0
    assert captured["source_plan_uuid"] == PLAN_UUID


def test_bug_list_passes_resolved_plan_uuid_by_uuid(monkeypatch) -> None:
    result, captured = _run_bug_list(monkeypatch, str(PLAN_UUID))
    assert result.to_dict()["data"]["total"] == 0
    assert captured["source_plan_uuid"] == PLAN_UUID


def test_bug_list_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result, captured = _run_bug_list(monkeypatch, "no-such-plan")
    _assert_domain_error(result, "PLAN_NOT_FOUND")
    assert captured == {}, "store must not be queried for an unknown plan"


# --- bug_report_store.list_bugs: SQL WHERE clause --------------------------------


def test_list_bugs_sql_filters_on_source_plan_uuid() -> None:
    conn = _FakeConn()
    list_bugs(conn, source_plan_uuid=PLAN_UUID)
    sql, params = conn.calls[0]
    assert "source_plan_uuid = %s" in sql
    assert PLAN_UUID in params


def test_list_bugs_sql_without_plan_scope_unchanged() -> None:
    conn = _FakeConn()
    list_bugs(conn)
    sql, params = conn.calls[0]
    assert "source_plan_uuid" not in sql
    assert params == []


# --- comment_list: resolved plan uuid reaches the store --------------------------


def _run_comment_list(monkeypatch, plan: str, records=None, **kwargs):
    captured: dict = {}

    def fake_list_comments(conn, **store_kwargs):
        captured.update(store_kwargs)
        return list(records or [])

    monkeypatch.setattr(comment_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(comment_list_command, "resolve_plan", _fake_resolve_plan)
    monkeypatch.setattr(comment_list_command, "list_comments", fake_list_comments)
    result = asyncio.run(comment_list_command.CommentListCommand().execute(plan=plan, **kwargs))
    return result, captured


def test_comment_list_passes_resolved_plan_uuid_by_name(monkeypatch) -> None:
    result, captured = _run_comment_list(monkeypatch, PLAN_NAME)
    assert result.to_dict()["data"]["total"] == 0
    assert captured["anchor_plan_uuid"] == PLAN_UUID


def test_comment_list_passes_resolved_plan_uuid_by_uuid(monkeypatch) -> None:
    result, captured = _run_comment_list(monkeypatch, str(PLAN_UUID))
    assert result.to_dict()["data"]["total"] == 0
    assert captured["anchor_plan_uuid"] == PLAN_UUID


def test_comment_list_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result, captured = _run_comment_list(monkeypatch, "no-such-plan")
    _assert_domain_error(result, "PLAN_NOT_FOUND")
    assert captured == {}, "store must not be queried for an unknown plan"


class _FakeComment:
    """Minimal RuntimeComment stand-in for the in-command filter path."""

    def __init__(self, anchor_plan_uuid):
        self.anchor_plan_uuid = anchor_plan_uuid
        self.anchor_project_id = None
        self.anchor_file_path = None
        self.anchor_revision_uuid = None
        self.kind = "note"
        self.author = "tester"
        self.resolved = False
        self.created_at = "2026-07-17T00:00:00+00:00"

    def to_payload(self):
        return {"anchor_plan_uuid": str(self.anchor_plan_uuid)}


def test_comment_list_anchor_plan_filter_intersects_plan_scope(monkeypatch) -> None:
    # The store already returns the plan-scoped set; a different anchor_plan
    # value must intersect to empty, never widen the scope.
    records = [_FakeComment(PLAN_UUID)]
    other_plan = uuid.uuid4()
    result, _ = _run_comment_list(monkeypatch, PLAN_NAME, records=records, anchor_plan=str(other_plan))
    assert result.to_dict()["data"]["total"] == 0
    result, _ = _run_comment_list(monkeypatch, PLAN_NAME, records=records, anchor_plan=str(PLAN_UUID))
    assert result.to_dict()["data"]["total"] == 1


# --- runtime_comment_store.list_comments SQL is pre-existing; escalation store ---


def test_list_escalations_sql_filters_on_anchor_plan_uuid() -> None:
    conn = _FakeConn()
    list_escalations(conn, anchor_plan_uuid=PLAN_UUID)
    sql, params = conn.calls[0]
    assert "anchor_plan_uuid = %s" in sql
    assert PLAN_UUID in params


def test_list_escalations_sql_without_plan_scope_unchanged() -> None:
    conn = _FakeConn()
    list_escalations(conn)
    sql, params = conn.calls[0]
    assert "anchor_plan_uuid" not in sql
    assert params == []


# --- escalation_list: resolved plan uuid reaches the store -----------------------


def _run_escalation_list(monkeypatch, plan: str):
    captured: dict = {}

    def fake_list_escalations(conn, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(escalation_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(escalation_list_command, "resolve_plan", _fake_resolve_plan)
    monkeypatch.setattr(escalation_list_command, "list_escalations", fake_list_escalations)
    result = asyncio.run(escalation_list_command.EscalationListCommand().execute(plan=plan))
    return result, captured


def test_escalation_list_passes_resolved_plan_uuid_by_name(monkeypatch) -> None:
    result, captured = _run_escalation_list(monkeypatch, PLAN_NAME)
    assert result.to_dict()["data"]["total"] == 0
    assert captured["anchor_plan_uuid"] == PLAN_UUID


def test_escalation_list_passes_resolved_plan_uuid_by_uuid(monkeypatch) -> None:
    result, captured = _run_escalation_list(monkeypatch, str(PLAN_UUID))
    assert result.to_dict()["data"]["total"] == 0
    assert captured["anchor_plan_uuid"] == PLAN_UUID


def test_escalation_list_unknown_plan_raises_plan_not_found(monkeypatch) -> None:
    result, captured = _run_escalation_list(monkeypatch, "no-such-plan")
    _assert_domain_error(result, "PLAN_NOT_FOUND")
    assert captured == {}, "store must not be queried for an unknown plan"


# --- metadata surfaces the real semantics ---------------------------------------


def test_plan_scope_documented_in_metadata() -> None:
    for command_cls, anchor_column in (
        (bug_list_command.BugListCommand, "source_plan_uuid"),
        (comment_list_command.CommentListCommand, "anchor_plan_uuid"),
        (escalation_list_command.EscalationListCommand, "anchor_plan_uuid"),
    ):
        metadata = command_cls.metadata()
        assert metadata["parameters"]["plan"]["required"] is True
        assert anchor_column in metadata["parameters"]["plan"]["description"]
        assert "PLAN_NOT_FOUND" in metadata["error_cases"]
        schema = command_cls.get_schema()
        assert "plan" in schema["required"]
        assert anchor_column in schema["properties"]["plan"]["description"]
        assert schema["additionalProperties"] is False
