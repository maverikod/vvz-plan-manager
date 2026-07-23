"""Regression tests for 0.1.28: runtime write commands must surface their DOCUMENTED
error_cases domain codes instead of collapsing every domain validation failure into the
generic RUNTIME_VALIDATION_ERROR fallback, and must not leak a raw exception (-32603) when a
referenced entity (comment, execution attempt, escalation, model binding target, bug fix,
bug impact) does not exist.

Uses the monkeypatch _fake_db / _DummyPlan pattern established by test_hotfix_uuid_guards.py:
db_connection is monkeypatched to a no-op context manager, resolve_plan (where applicable) to a
stub returning a dummy plan, and the relevant store getter to return None to simulate a missing
referenced row. Domain-shape failures (malformed anchor, out-of-range priority, inconsistent
binding scope fields, unrecognized runtime role) are exercised directly, since those raise before
any real database access occurs.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.commands import (
    plan_completion_guard,
    bug_propagation_create_command,
    comment_add_command,
    comment_resolve_command,
    comment_supersede_command,
    escalation_resolve_command,
    execution_attempt_report_command,
    model_binding_resolve_command,
    model_binding_set_command,
    todo_create_command,
)
from plan_manager.commands.errors import DOMAIN_CODES


@contextmanager
def _fake_db():
    yield object()


class _DummyPlan:
    def __init__(self):
        self.uuid = uuid.uuid4()


def _assert_code(result, code: str) -> None:
    payload = result.to_dict()
    assert "error" in payload, f"expected an error result, got: {payload}"
    assert payload["error"]["data"]["domain_code"] == code, payload["error"]["data"]


# --- INVALID_ANCHOR ---------------------------------------------------------------------


def test_todo_create_rejects_malformed_anchor_shape(monkeypatch) -> None:
    monkeypatch.setattr(todo_create_command, "db_connection", _fake_db)
    result = asyncio.run(
        todo_create_command.TodoCreateCommand().execute(
            title="t",
            description="d",
            kind="task",
            priority_nice=0,
            created_by="x",
            anchor_type="project",
            anchor_project_id=None,
        )
    )
    _assert_code(result, "INVALID_ANCHOR")


def test_comment_add_rejects_malformed_anchor_shape(monkeypatch) -> None:
    monkeypatch.setattr(comment_add_command, "db_connection", _fake_db)
    monkeypatch.setattr(comment_add_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    result = asyncio.run(
        comment_add_command.CommentAddCommand().execute(
            plan="p",
            anchor_type="project",
            anchor_project_id=None,
            kind="comment",
            visibility="audit_only",
            author="a",
            body="b",
            created_by="c",
        )
    )
    _assert_code(result, "INVALID_ANCHOR")


# --- INVALID_NICE_PRIORITY ---------------------------------------------------------------


def test_todo_create_rejects_out_of_range_priority(monkeypatch) -> None:
    monkeypatch.setattr(todo_create_command, "db_connection", _fake_db)
    result = asyncio.run(
        todo_create_command.TodoCreateCommand().execute(
            title="t",
            description="d",
            kind="task",
            priority_nice=100,
            created_by="x",
            anchor_type="none",
        )
    )
    _assert_code(result, "INVALID_NICE_PRIORITY")


# --- INVALID_BINDING_SCOPE / INVALID_RUNTIME_ROLE ----------------------------------------


def test_model_binding_set_rejects_inconsistent_scope_fields(monkeypatch) -> None:
    monkeypatch.setattr(model_binding_set_command, "db_connection", _fake_db)
    result = asyncio.run(
        model_binding_set_command.ModelBindingSetCommand().execute(
            scope="plan",
            provider="p",
            model="m",
            max_retries=1,
            timeout=60,
            created_by="x",
            plan=None,
        )
    )
    _assert_code(result, "INVALID_BINDING_SCOPE")


def test_model_binding_set_rejects_invalid_role(monkeypatch) -> None:
    monkeypatch.setattr(model_binding_set_command, "db_connection", _fake_db)
    result = asyncio.run(
        model_binding_set_command.ModelBindingSetCommand().execute(
            scope="role",
            role="not_a_real_role",
            provider="p",
            model="m",
            max_retries=1,
            timeout=60,
            created_by="x",
        )
    )
    _assert_code(result, "INVALID_RUNTIME_ROLE")


def test_model_binding_resolve_rejects_invalid_role(monkeypatch) -> None:
    monkeypatch.setattr(model_binding_resolve_command, "db_connection", _fake_db)
    result = asyncio.run(
        model_binding_resolve_command.ModelBindingResolveCommand().execute(
            plan=str(uuid.uuid4()), role="not_a_real_role"
        )
    )
    _assert_code(result, "INVALID_RUNTIME_ROLE")


# --- *_NOT_FOUND on the write path --------------------------------------------------------


def test_comment_supersede_rejects_missing_comment(monkeypatch) -> None:
    monkeypatch.setattr(comment_supersede_command, "db_connection", _fake_db)
    monkeypatch.setattr(comment_supersede_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(comment_supersede_command, "get_comment", lambda conn, comment_uuid: None)
    result = asyncio.run(
        comment_supersede_command.CommentSupersedeCommand().execute(
            plan="p", comment_uuid=str(uuid.uuid4()), body="corrected", changed_by="x"
        )
    )
    _assert_code(result, "COMMENT_NOT_FOUND")


def test_comment_resolve_rejects_missing_comment(monkeypatch) -> None:
    monkeypatch.setattr(comment_resolve_command, "db_connection", _fake_db)
    monkeypatch.setattr(comment_resolve_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(comment_resolve_command, "get_comment", lambda conn, comment_uuid: None)
    result = asyncio.run(
        comment_resolve_command.CommentResolveCommand().execute(
            plan="p", comment_uuid=str(uuid.uuid4()), changed_by="x"
        )
    )
    _assert_code(result, "COMMENT_NOT_FOUND")


def test_execution_attempt_report_rejects_missing_attempt(monkeypatch) -> None:
    monkeypatch.setattr(execution_attempt_report_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        execution_attempt_report_command, "get_execution_attempt", lambda conn, attempt_uuid: None
    )
    result = asyncio.run(
        execution_attempt_report_command.ExecutionAttemptReportCommand().execute(
            attempt_id=str(uuid.uuid4()), changed_by="x"
        )
    )
    _assert_code(result, "EXECUTION_ATTEMPT_NOT_FOUND")


def test_escalation_resolve_rejects_missing_escalation(monkeypatch) -> None:
    monkeypatch.setattr(escalation_resolve_command, "db_connection", _fake_db)
    monkeypatch.setattr(escalation_resolve_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(escalation_resolve_command, "get_escalation", lambda conn, escalation_uuid: None)
    result = asyncio.run(
        escalation_resolve_command.EscalationResolveCommand().execute(
            plan="p", escalation_uuid=str(uuid.uuid4()), resolved_by="x", resolution="y"
        )
    )
    _assert_code(result, "ESCALATION_NOT_FOUND")


def test_model_binding_resolve_rejects_when_no_binding_applies(monkeypatch) -> None:
    monkeypatch.setattr(model_binding_resolve_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        model_binding_resolve_command, "list_bindings_for_resolution", lambda conn, plan_uuid: []
    )
    result = asyncio.run(
        model_binding_resolve_command.ModelBindingResolveCommand().execute(
            plan=str(uuid.uuid4()), role="as_author"
        )
    )
    _assert_code(result, "MODEL_BINDING_NOT_FOUND")


def test_bug_propagation_create_rejects_missing_bug_fix(monkeypatch) -> None:
    monkeypatch.setattr(bug_propagation_create_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_propagation_create_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(bug_propagation_create_command, "get_bug_fix", lambda conn, bug_fix_uuid: None)
    result = asyncio.run(
        bug_propagation_create_command.BugPropagationCreateCommand().execute(
            plan="p",
            bug_fix_id=str(uuid.uuid4()),
            impact_id=str(uuid.uuid4()),
            action="rebuild_package",
            created_by="x",
        )
    )
    _assert_code(result, "BUG_FIX_NOT_FOUND")


def test_bug_propagation_create_rejects_missing_bug_impact(monkeypatch) -> None:
    class _FixStub:
        bug_uuid = uuid.uuid4()

    monkeypatch.setattr(bug_propagation_create_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_propagation_create_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(bug_propagation_create_command, "get_bug_fix", lambda conn, bug_fix_uuid: _FixStub())
    monkeypatch.setattr(plan_completion_guard, "get_bug", lambda conn, bug_uuid: None)
    monkeypatch.setattr(bug_propagation_create_command, "get_bug_impact", lambda conn, impact_uuid: None)
    result = asyncio.run(
        bug_propagation_create_command.BugPropagationCreateCommand().execute(
            plan="p",
            bug_fix_id=str(uuid.uuid4()),
            impact_id=str(uuid.uuid4()),
            action="rebuild_package",
            created_by="x",
        )
    )
    _assert_code(result, "BUG_IMPACT_NOT_FOUND")


# --- guard: malformed UUID must still yield the generic RUNTIME_VALIDATION_ERROR contract -


def test_model_binding_resolve_rejects_malformed_plan_uuid(monkeypatch) -> None:
    monkeypatch.setattr(model_binding_resolve_command, "db_connection", _fake_db)
    result = asyncio.run(
        model_binding_resolve_command.ModelBindingResolveCommand().execute(
            plan="not-a-valid-uuid", role="as_author"
        )
    )
    _assert_code(result, "RUNTIME_VALIDATION_ERROR")


# --- documented error_cases sanity: every fixed code is registered and advertised ---------


FIXED_CODES_BY_COMMAND = [
    (todo_create_command.TodoCreateCommand, ("INVALID_ANCHOR", "INVALID_NICE_PRIORITY")),
    (comment_add_command.CommentAddCommand, ("INVALID_ANCHOR",)),
    (comment_supersede_command.CommentSupersedeCommand, ("COMMENT_NOT_FOUND",)),
    (comment_resolve_command.CommentResolveCommand, ("COMMENT_NOT_FOUND",)),
    (execution_attempt_report_command.ExecutionAttemptReportCommand, ("EXECUTION_ATTEMPT_NOT_FOUND",)),
    (escalation_resolve_command.EscalationResolveCommand, ("ESCALATION_NOT_FOUND",)),
    (model_binding_set_command.ModelBindingSetCommand, ("INVALID_BINDING_SCOPE", "INVALID_RUNTIME_ROLE")),
    (
        model_binding_resolve_command.ModelBindingResolveCommand,
        ("MODEL_BINDING_NOT_FOUND", "INVALID_RUNTIME_ROLE"),
    ),
    (bug_propagation_create_command.BugPropagationCreateCommand, ("BUG_FIX_NOT_FOUND", "BUG_IMPACT_NOT_FOUND")),
]


@pytest.mark.parametrize("command_cls,codes", FIXED_CODES_BY_COMMAND)
def test_documented_codes_are_registered_and_advertised(command_cls, codes) -> None:
    metadata = command_cls.metadata()
    for code in codes:
        assert code in DOMAIN_CODES, f"{code} missing from DOMAIN_CODES"
        assert code in metadata["error_cases"], f"{code} missing from {command_cls.__name__} error_cases"
