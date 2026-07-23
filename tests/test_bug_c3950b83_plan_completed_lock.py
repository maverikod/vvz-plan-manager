"""Regression tests for bug c3950b83 (plan-level completion lock).

L1 design ruling 2026-07-23 (superseding an earlier per-step-status
carve-out attempt): a fully frozen, fully executed plan could never record
that it had been executed -- step_set_status/cascade_begin both refuse a
frozen plan and plan_unfreeze is disproportionate for routine closeout
bookkeeping. The fix is ONE plan-level `completed` boolean flag (plus a
free-form `comment`): once set, every OTHER mutating command that resolves
its `plan` parameter to that plan refuses with the PLAN_COMPLETED domain
code via plan_manager.commands.resolve.resolve_plan_guarded (or, for the
anchor-based todo/comment/execution_attempt/review_result/escalation/bug
paths that take a raw anchor_plan_uuid instead of a `plan` parameter, the
parallel check in domain.primary_anchor.validate_anchor); the two setter
commands (plan_completed_set, plan_comment_set) call resolve_plan directly,
unguarded, and stay reachable at all times; reads are never blocked either
way.

This module is pure unit tests (monkeypatched db_connection / fake
psycopg-shaped connections), matching this repo's established style (see
tests/test_plan_deletion.py, tests/test_plan_unfreeze.py,
tests/test_bug_26fa21a5_ts_inputs_outputs_write_rejection.py) -- no real
Postgres is required.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Any

import pytest
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands import (
    bug_confirm_command,
    cascade_begin_command,
    plan_comment_set_command,
    plan_completed_set_command,
    plan_delete_command,
    step_create_command,
    step_set_status_command,
    step_update_command,
    todo_create_command,
)
from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.plan_comment_set_command import PlanCommentSetCommand
from plan_manager.commands.plan_completed_set_command import PlanCompletedSetCommand
from plan_manager.commands.resolve import resolve_plan_guarded
from plan_manager.commands import resolve as resolve_module
from plan_manager.domain.plan import Plan, set_plan_comment, set_plan_completed
from plan_manager.domain.primary_anchor import PrimaryAnchor, validate_anchor


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000c1")
OTHER_PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000c2")


def _plan(completed: bool = False, comment: str | None = None) -> Plan:
    return Plan(
        uuid=PLAN_UUID,
        name="p",
        status="frozen",
        context_budget=4000,
        head_revision_uuid=uuid.uuid4(),
        project_ids=[],
        primary_project_id=None,
        completed=completed,
        comment=comment,
    )


def _run(coro):
    return asyncio.run(coro)


# --------------------------------------------------------------------------
# domain.plan: set_plan_completed / set_plan_comment SQL emission, and that
# they are scoped by plan_uuid (so a different plan is never touched).
# --------------------------------------------------------------------------


class _RecordingConn:
    """Records execute() statements; execute() returns a canned cursor."""

    def __init__(self, rows: list | None = None) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self._rows = rows or []

    def execute(self, sql: str, params: tuple = ()):
        self.statements.append((sql, params))
        rows = self._rows

        class _Cur:
            def fetchall(self_inner):
                return rows

            def fetchone(self_inner):
                return rows[0] if rows else None

        return _Cur()


def test_set_plan_completed_updates_only_the_targeted_plan() -> None:
    conn = _RecordingConn()
    set_plan_completed(conn, PLAN_UUID, True)
    sql, params = conn.statements[-1]
    assert "UPDATE plan SET completed" in sql
    assert "WHERE uuid = %s" in sql
    assert params == (True, PLAN_UUID)
    assert OTHER_PLAN_UUID not in params


def test_set_plan_completed_false_unsets_the_flag() -> None:
    conn = _RecordingConn()
    set_plan_completed(conn, PLAN_UUID, False)
    sql, params = conn.statements[-1]
    assert params == (False, PLAN_UUID)


def test_set_plan_comment_sets_and_clears() -> None:
    conn = _RecordingConn()
    set_plan_comment(conn, PLAN_UUID, "closeout note")
    sql, params = conn.statements[-1]
    assert "UPDATE plan SET comment" in sql
    assert params == ("closeout note", PLAN_UUID)

    set_plan_comment(conn, PLAN_UUID, None)
    sql, params = conn.statements[-1]
    assert params == (None, PLAN_UUID)


def test_plan_dataclass_defaults_not_completed_no_comment() -> None:
    p = _plan()
    assert p.completed is False
    assert p.comment is None


# --------------------------------------------------------------------------
# resolve_plan_guarded: the primary seam. Refuses a completed plan with
# PLAN_COMPLETED; passes a non-completed plan through unchanged; propagates
# PLAN_NOT_FOUND untouched.
# --------------------------------------------------------------------------


def test_resolve_plan_guarded_refuses_completed_plan(monkeypatch) -> None:
    monkeypatch.setattr(resolve_module, "resolve_plan", lambda conn, plan: _plan(completed=True))
    with pytest.raises(DomainCommandError) as exc_info:
        resolve_plan_guarded(object(), "any-plan")
    assert exc_info.value.code == "PLAN_COMPLETED"
    assert str(PLAN_UUID) in exc_info.value.message


def test_resolve_plan_guarded_admits_non_completed_plan(monkeypatch) -> None:
    monkeypatch.setattr(resolve_module, "resolve_plan", lambda conn, plan: _plan(completed=False))
    result = resolve_plan_guarded(object(), "any-plan")
    assert result.uuid == PLAN_UUID


def test_resolve_plan_guarded_propagates_plan_not_found(monkeypatch) -> None:
    def _raise(conn, plan):
        raise DomainCommandError("PLAN_NOT_FOUND", f"plan not found: {plan}")

    monkeypatch.setattr(resolve_module, "resolve_plan", _raise)
    with pytest.raises(DomainCommandError) as exc_info:
        resolve_plan_guarded(object(), "missing-plan")
    assert exc_info.value.code == "PLAN_NOT_FOUND"


# --------------------------------------------------------------------------
# The two exempt setter commands: ALWAYS reachable, including when the plan
# is ALREADY completed (toggling true->true, true->false), and each writes
# its own immutable runtime-audit record.
# --------------------------------------------------------------------------


@contextmanager
def _fake_db():
    yield object()


def _patch_setter_common(monkeypatch, module: Any, plan: Plan, audit_calls: list[dict]) -> None:
    monkeypatch.setattr(module, "db_connection", _fake_db)
    monkeypatch.setattr(module, "resolve_plan", lambda conn, p: plan)
    monkeypatch.setattr(module, "get_plan", lambda conn, plan_uuid: plan)

    def _record(conn, **kwargs):
        audit_calls.append(kwargs)

        class _Audit:
            audit_uuid = uuid.uuid4()

        return _Audit()

    monkeypatch.setattr(module, "record_runtime_change", _record)


def test_plan_completed_set_reachable_on_an_already_completed_plan(monkeypatch) -> None:
    """The setter must work even when completed is ALREADY true -- it calls
    resolve_plan directly, never resolve_plan_guarded."""
    plan = _plan(completed=True)
    audit_calls: list[dict] = []
    captured: dict = {}
    _patch_setter_common(monkeypatch, plan_completed_set_command, plan, audit_calls)
    monkeypatch.setattr(
        plan_completed_set_command, "set_plan_completed",
        lambda conn, plan_uuid, completed: captured.update(plan_uuid=plan_uuid, completed=completed),
    )

    cmd = PlanCompletedSetCommand()
    result = _run(cmd.execute(plan="p", completed=True, changed_by="tester"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured == {"plan_uuid": PLAN_UUID, "completed": True}
    assert audit_calls[0]["action"] == "plan_completed_set"
    assert audit_calls[0]["changed_by"] == "tester"
    assert audit_calls[0]["changed_fields"] == {"from": True, "to": True}


def test_plan_completed_set_unlocks_and_audits_from_to(monkeypatch) -> None:
    plan = _plan(completed=True)
    audit_calls: list[dict] = []
    captured: dict = {}
    _patch_setter_common(monkeypatch, plan_completed_set_command, plan, audit_calls)
    monkeypatch.setattr(
        plan_completed_set_command, "set_plan_completed",
        lambda conn, plan_uuid, completed: captured.update(plan_uuid=plan_uuid, completed=completed),
    )

    cmd = PlanCompletedSetCommand()
    result = _run(cmd.execute(plan="p", completed=False, changed_by="tester"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured == {"plan_uuid": PLAN_UUID, "completed": False}
    assert audit_calls[0]["changed_fields"] == {"from": True, "to": False}
    # get_plan is stubbed to always return `plan` (completed=True) -- this
    # asserts the command re-reads via get_plan rather than trusting the
    # in-memory value it just wrote.
    assert result.data["completed"] is True


def test_plan_completed_set_rejects_empty_changed_by(monkeypatch) -> None:
    plan = _plan()
    _patch_setter_common(monkeypatch, plan_completed_set_command, plan, [])
    cmd = PlanCompletedSetCommand()
    result = _run(cmd.execute(plan="p", completed=True, changed_by="   "))
    assert isinstance(result, ErrorResult)
    assert result.details.get("domain_code") == "RUNTIME_VALIDATION_ERROR"


def test_plan_comment_set_reachable_on_a_completed_plan(monkeypatch) -> None:
    plan = _plan(completed=True, comment="old")
    audit_calls: list[dict] = []
    captured: dict = {}
    _patch_setter_common(monkeypatch, plan_comment_set_command, plan, audit_calls)
    monkeypatch.setattr(
        plan_comment_set_command, "set_plan_comment",
        lambda conn, plan_uuid, comment: captured.update(plan_uuid=plan_uuid, comment=comment),
    )

    cmd = PlanCommentSetCommand()
    result = _run(cmd.execute(plan="p", changed_by="tester", comment="new note"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured == {"plan_uuid": PLAN_UUID, "comment": "new note"}
    assert audit_calls[0]["action"] == "plan_comment_set"
    assert audit_calls[0]["changed_fields"] == {"from": "old", "to": "new note"}


def test_plan_comment_set_clears_when_omitted(monkeypatch) -> None:
    plan = _plan(completed=False, comment="old")
    audit_calls: list[dict] = []
    captured: dict = {}
    _patch_setter_common(monkeypatch, plan_comment_set_command, plan, audit_calls)
    monkeypatch.setattr(
        plan_comment_set_command, "set_plan_comment",
        lambda conn, plan_uuid, comment: captured.update(plan_uuid=plan_uuid, comment=comment),
    )

    cmd = PlanCommentSetCommand()
    result = _run(cmd.execute(plan="p", changed_by="tester"))  # comment omitted -> None

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured == {"plan_uuid": PLAN_UUID, "comment": None}


def test_plan_comment_set_rejects_empty_changed_by(monkeypatch) -> None:
    plan = _plan()
    _patch_setter_common(monkeypatch, plan_comment_set_command, plan, [])
    cmd = PlanCommentSetCommand()
    result = _run(cmd.execute(plan="p", changed_by="", comment="x"))
    assert isinstance(result, ErrorResult)
    assert result.details.get("domain_code") == "RUNTIME_VALIDATION_ERROR"


# --------------------------------------------------------------------------
# Representative mutating commands refuse with PLAN_COMPLETED while the
# plan is completed: step_set_status, step_update, step_create,
# cascade_begin, plan_delete, bug_confirm. Each imports resolve_plan_guarded
# aliased as resolve_plan; monkeypatching the underlying (unguarded)
# resolve.resolve_plan to hand back a completed Plan exercises the REAL
# guard for every one of them uniformly.
# --------------------------------------------------------------------------


def _command_class_for(module: Any) -> type:
    short = module.__name__.rsplit(".", 1)[-1]
    assert short.endswith("_command")
    short = short[: -len("_command")]
    class_name = "".join(part.capitalize() for part in short.split("_")) + "Command"
    return getattr(module, class_name)


@pytest.mark.parametrize(
    "module",
    [
        step_set_status_command,
        step_update_command,
        step_create_command,
        cascade_begin_command,
        plan_delete_command,
        bug_confirm_command,
    ],
)
def test_representative_mutating_commands_refuse_with_plan_completed(monkeypatch, module) -> None:
    monkeypatch.setattr(module, "db_connection", _fake_db)
    monkeypatch.setattr(resolve_module, "resolve_plan", lambda conn, plan: _plan(completed=True))

    cmd = _command_class_for(module)()

    kwargs: dict[str, Any] = {"plan": "any-plan"}
    if module is step_set_status_command:
        kwargs.update(step_id="A-001", status="in_progress")
    elif module is step_update_command:
        kwargs.update(step_id="A-001", concepts=["C-001"])
    elif module is step_create_command:
        kwargs.update(level=3, slug="scratch")
    elif module is plan_delete_command:
        kwargs.update(hard=False)
    elif module is bug_confirm_command:
        kwargs.update(bug_id=str(uuid.uuid4()), changed_by="tester")

    result = _run(cmd.execute(**kwargs))

    assert isinstance(result, ErrorResult), f"{cmd.__class__.__name__} unexpectedly succeeded: {getattr(result, 'data', None)!r}"
    assert result.details.get("domain_code") == "PLAN_COMPLETED", (
        f"{cmd.__class__.__name__}: expected PLAN_COMPLETED, got {result.details!r} / {result.message!r}"
    )


def test_representative_command_still_admitted_when_plan_not_completed(monkeypatch) -> None:
    """Sanity counter-check: the SAME guard admits a non-completed plan
    through to whatever comes next. cascade_begin's real body then reaches
    for the plan advisory lock, which this bare-object stub cannot serve --
    that AttributeError (re-raised untouched by map_exception, since it
    matches none of its known exception types) is the expected proof the
    guard itself did NOT block the call; a real PLAN_COMPLETED refusal
    would have surfaced as an ErrorResult long before reaching the lock."""
    monkeypatch.setattr(cascade_begin_command, "db_connection", _fake_db)
    monkeypatch.setattr(resolve_module, "resolve_plan", lambda conn, plan: _plan(completed=False))

    cmd = cascade_begin_command.CascadeBeginCommand()
    try:
        result = _run(cmd.execute(plan="any-plan"))
    except AttributeError as exc:
        assert "execute" in str(exc)  # the stub conn has no .execute -- expected past the guard
        return
    assert isinstance(result, ErrorResult)
    assert result.details.get("domain_code") != "PLAN_COMPLETED"


# --------------------------------------------------------------------------
# todo_create: the one representative command that anchors to a plan via a
# raw anchor_plan_uuid rather than a `plan` (name-or-uuid) parameter, so it
# is guarded by the parallel seam in domain.primary_anchor.validate_anchor,
# not by resolve_plan_guarded.
# --------------------------------------------------------------------------


class _AnchorFakeConn:
    """Answers the plan-existence check truthily and the plan-completed
    check per the constructor flag; anything else is unexpected in this
    anchor_type='plan' path and raises loudly."""

    def __init__(self, completed: bool) -> None:
        self._completed = completed

    def execute(self, sql: str, params: tuple):
        class _Cur:
            def __init__(self_inner, row):
                self_inner._row = row

            def fetchone(self_inner):
                return self_inner._row

        if "SELECT completed FROM plan" in sql:
            return _Cur((self._completed,))
        if sql.strip().startswith("SELECT 1 FROM plan"):
            return _Cur((1,))
        raise AssertionError(f"unexpected query in this anchor test: {sql!r}")


def test_anchor_type_plan_refuses_when_plan_completed() -> None:
    anchor = PrimaryAnchor(anchor_type="plan", plan_uuid=PLAN_UUID)
    with pytest.raises(Exception) as exc_info:
        validate_anchor(_AnchorFakeConn(completed=True), anchor)
    assert "plan_completed_set" in str(exc_info.value) or "completed" in str(exc_info.value).lower()


def test_anchor_type_plan_admitted_when_plan_not_completed() -> None:
    anchor = PrimaryAnchor(anchor_type="plan", plan_uuid=PLAN_UUID)
    validate_anchor(_AnchorFakeConn(completed=False), anchor)  # must not raise


def test_anchor_type_step_also_refuses_when_plan_completed() -> None:
    """anchor_type='step' goes through validate_step_in_plan_revision
    first, then the SAME completed check -- covering comment_add/
    execution_attempt_create/escalation_create/review_result_create
    anchors of a step."""
    anchor = PrimaryAnchor(
        anchor_type="step", plan_uuid=PLAN_UUID, step_uuid=uuid.uuid4(), step_path="G-001/T-001/A-001",
    )

    class _StepAnchorConn(_AnchorFakeConn):
        def execute(self, sql: str, params: tuple):
            if sql.strip().startswith("SELECT uuid FROM step"):
                class _Cur:
                    def fetchone(self_inner):
                        return (params[0],)

                return _Cur()
            return super().execute(sql, params)

    with pytest.raises(Exception) as exc_info:
        validate_anchor(_StepAnchorConn(completed=True), anchor)
    assert "completed" in str(exc_info.value).lower()


def test_todo_create_command_refuses_when_anchored_plan_is_completed(monkeypatch) -> None:
    """End-to-end through TodoCreateCommand.execute itself, not just the
    domain-level validate_anchor unit."""

    @contextmanager
    def _fake_todo_db():
        yield _AnchorFakeConn(completed=True)

    monkeypatch.setattr(todo_create_command, "db_connection", _fake_todo_db)

    cmd = todo_create_command.TodoCreateCommand()
    result = _run(
        cmd.execute(
            title="t", description="d", kind="task", priority_nice=0,
            created_by="tester", anchor_type="plan", anchor_plan_uuid=str(PLAN_UUID),
        )
    )

    assert isinstance(result, ErrorResult), getattr(result, "data", None)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"


# --------------------------------------------------------------------------
# Other plans are unaffected: resolve_plan_guarded's decision is keyed off
# THIS plan's own `completed` value only.
# --------------------------------------------------------------------------


def test_other_plan_unaffected_by_a_different_plans_completed_flag(monkeypatch) -> None:
    other = Plan(
        uuid=OTHER_PLAN_UUID, name="other", status="draft", context_budget=4000,
        head_revision_uuid=uuid.uuid4(), project_ids=[], primary_project_id=None,
        completed=False, comment=None,
    )
    monkeypatch.setattr(resolve_module, "resolve_plan", lambda conn, plan: other)
    result = resolve_plan_guarded(object(), "other-plan")
    assert result.uuid == OTHER_PLAN_UUID
    assert result.completed is False
