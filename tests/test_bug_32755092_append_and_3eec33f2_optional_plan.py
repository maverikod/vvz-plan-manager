"""Regression tests for two related bug-command-group defects:

BUG 32755092 (minor): bug_update.detailed_description and
bug_fix_update.implementation_notes silently REPLACE the whole field
instead of appending -- history-loss footgun. Fix (L1 design ruling): an
optional `append` boolean (default False, preserving old replace
semantics) on bug_update's detailed_description/expected_behavior/
actual_behavior/reproduction and bug_fix_update's implementation_notes.
append=True joins the existing stored value and the incoming text with a
blank line ("\\n\\n"); appending to an empty/null field just sets it.

BUG 3eec33f2 (minor): the bug command group required a mandatory `plan`
parameter even for project-anchored bugs (source_type=project, no plan
anchor), so an unrelated completed plan's PLAN_COMPLETED lock could block
mutation of a bug that has nothing to do with that plan. Fix (L1 design
ruling): `plan` becomes OPTIONAL across the bug/bug_fix mutating and
lifecycle commands.
  - bug_create: `plan` required ONLY when source_type is plan/revision/step
    (the anchor needs it); optional for project/file/command/
    runtime_service/execution_attempt/unidentified anchors.
  - bug_id/bug_fix-addressing commands: when `plan` is omitted, the entity
    is resolved globally by its own UUID and the PLAN_COMPLETED guard
    applies only to the entity's OWN plan anchor (already-existing
    plan_completion_guard seam); when `plan` is supplied, the prior
    behavior (resolve_plan_guarded on the supplied plan) is preserved
    unchanged.

Pure unit tests (monkeypatched db_connection / fake psycopg-shaped
connections), matching this repo's established style -- see
tests/test_bug_c3950b83_plan_completed_lock.py, which these tests are
written to stay consistent with (same _Entity/_fake_db_ctx idioms).
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Any

import pytest
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands import (
    bug_close_command,
    bug_confirm_command,
    bug_create_command,
    bug_fix_create_command,
    bug_fix_update_command,
    bug_fix_verify_command,
    bug_mark_duplicate_command,
    bug_reanchor_command,
    bug_reject_command,
    bug_reopen_command,
    bug_triage_command,
    bug_update_command,
    plan_completion_guard,
)
from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.text_merge import merge_text_field


def _run(coro):
    return asyncio.run(coro)


@contextmanager
def _fake_db_ctx(conn):
    yield conn


class _Entity:
    """Generic attribute bag standing in for any domain dataclass; matches
    the idiom in tests/test_bug_c3950b83_plan_completed_lock.py."""

    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)

    def to_payload(self) -> dict:
        return {"uuid": "stub"}


class _NoPlanQueryConn:
    """A connection that raises AssertionError on ANY query -- proves the
    no-plan-supplied path never touches the plan table at all."""

    def execute(self, sql: str, params: tuple = ()):
        raise AssertionError(f"must not query when plan is omitted and bug has no plan anchor: {sql!r}")


# ---------------------------------------------------------------------------
# BUG 32755092: merge_text_field, the shared helper.
# ---------------------------------------------------------------------------


def test_merge_text_field_append_false_replaces() -> None:
    assert merge_text_field("old text", "new text", append=False) == "new text"


def test_merge_text_field_append_true_joins_with_blank_line() -> None:
    assert merge_text_field("old text", "new text", append=True) == "old text\n\nnew text"


def test_merge_text_field_append_true_onto_empty_field_just_sets_it() -> None:
    assert merge_text_field(None, "new text", append=True) is None or merge_text_field(None, "new text", append=True) == "new text"
    assert merge_text_field("", "new text", append=True) == "new text"


def test_merge_text_field_append_true_twice_accumulates_history() -> None:
    first = merge_text_field(None, "first entry", append=True)
    second = merge_text_field(first, "second entry", append=True)
    assert first == "first entry"
    assert second == "first entry\n\nsecond entry"
    assert "first entry" in second and "second entry" in second


# ---------------------------------------------------------------------------
# BUG 32755092: bug_update command-level wiring.
# ---------------------------------------------------------------------------


def _bug_for_update(**overrides: Any) -> _Entity:
    fields = dict(
        source_plan_uuid=None,
        detailed_description="original detailed description",
        expected_behavior="original expected",
        actual_behavior="original actual",
        reproduction="original repro",
    )
    fields.update(overrides)
    return _Entity(**fields)


def test_bug_update_default_append_false_replaces_detailed_description(monkeypatch) -> None:
    """Reproduces bug 32755092: without append (default), the field is replaced,
    not appended -- this is the DOCUMENTED, preserved default behavior."""
    bug = _bug_for_update()
    captured: dict = {}

    monkeypatch.setattr(bug_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_update_command, "get_bug", lambda conn, bug_uuid: bug)

    def fake_update_bug(conn, bug_uuid, **kwargs):
        captured.update(kwargs)
        return _Entity(uuid=bug_uuid, to_payload=lambda: {"uuid": str(bug_uuid)})

    monkeypatch.setattr(bug_update_command, "update_bug", fake_update_bug)

    cmd = bug_update_command.BugUpdateCommand()
    result = _run(cmd.execute(bug_id=str(uuid.uuid4()), changed_by="tester", detailed_description="new text"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["detailed_description"] == "new text"


def test_bug_update_append_true_preserves_history_across_two_calls(monkeypatch) -> None:
    """The core regression proof: append=True twice must retain BOTH texts."""
    state = {"detailed_description": "original detailed description"}
    captured_calls: list[str] = []

    monkeypatch.setattr(bug_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_update_command, "get_bug", lambda conn, bug_uuid: _bug_for_update(detailed_description=state["detailed_description"]))

    def fake_update_bug(conn, bug_uuid, **kwargs):
        if kwargs.get("detailed_description") is not None:
            state["detailed_description"] = kwargs["detailed_description"]
            captured_calls.append(kwargs["detailed_description"])
        return _Entity(to_payload=lambda: {"uuid": str(bug_uuid)})

    monkeypatch.setattr(bug_update_command, "update_bug", fake_update_bug)

    cmd = bug_update_command.BugUpdateCommand()
    bug_id = str(uuid.uuid4())

    r1 = _run(cmd.execute(bug_id=bug_id, changed_by="tester", detailed_description="first note", append=True))
    r2 = _run(cmd.execute(bug_id=bug_id, changed_by="tester", detailed_description="second note", append=True))

    assert isinstance(r1, SuccessResult), getattr(r1, "message", r1)
    assert isinstance(r2, SuccessResult), getattr(r2, "message", r2)
    assert "original detailed description" in captured_calls[0]
    assert "first note" in captured_calls[0]
    final = captured_calls[-1]
    assert "original detailed description" in final
    assert "first note" in final
    assert "second note" in final


def test_bug_update_append_true_applies_to_all_four_free_text_fields(monkeypatch) -> None:
    bug = _bug_for_update()
    captured: dict = {}

    monkeypatch.setattr(bug_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_update_command, "get_bug", lambda conn, bug_uuid: bug)

    def fake_update_bug(conn, bug_uuid, **kwargs):
        captured.update(kwargs)
        return _Entity(to_payload=lambda: {"uuid": str(bug_uuid)})

    monkeypatch.setattr(bug_update_command, "update_bug", fake_update_bug)

    cmd = bug_update_command.BugUpdateCommand()
    result = _run(
        cmd.execute(
            bug_id=str(uuid.uuid4()),
            changed_by="tester",
            detailed_description="d2",
            expected_behavior="e2",
            actual_behavior="a2",
            reproduction="r2",
            append=True,
        )
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["detailed_description"] == "original detailed description\n\nd2"
    assert captured["expected_behavior"] == "original expected\n\ne2"
    assert captured["actual_behavior"] == "original actual\n\na2"
    assert captured["reproduction"] == "original repro\n\nr2"


def test_bug_update_append_true_field_not_supplied_stays_none(monkeypatch) -> None:
    """Omitted fields are untouched regardless of append (only supplied fields merge)."""
    bug = _bug_for_update()
    captured: dict = {}

    monkeypatch.setattr(bug_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_update_command, "get_bug", lambda conn, bug_uuid: bug)

    def fake_update_bug(conn, bug_uuid, **kwargs):
        captured.update(kwargs)
        return _Entity(to_payload=lambda: {"uuid": str(bug_uuid)})

    monkeypatch.setattr(bug_update_command, "update_bug", fake_update_bug)

    cmd = bug_update_command.BugUpdateCommand()
    result = _run(cmd.execute(bug_id=str(uuid.uuid4()), changed_by="tester", detailed_description="d2", append=True))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["detailed_description"] == "original detailed description\n\nd2"
    assert captured["expected_behavior"] is None
    assert captured["actual_behavior"] is None
    assert captured["reproduction"] is None


# ---------------------------------------------------------------------------
# BUG 32755092: bug_fix_update command-level wiring (implementation_notes).
# ---------------------------------------------------------------------------


def test_bug_fix_update_append_true_preserves_history(monkeypatch) -> None:
    fix = _Entity(bug_uuid=uuid.uuid4(), status="in_progress", implementation_notes="first pass done")
    captured: dict = {}

    monkeypatch.setattr(bug_fix_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_fix_update_command, "get_bug_fix", lambda conn, fix_uuid: fix)
    monkeypatch.setattr(plan_completion_guard, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))

    def fake_update_bug_fix(conn, fix_uuid, **kwargs):
        captured.update(kwargs)
        return _Entity(to_payload=lambda: {"uuid": str(fix_uuid)})

    monkeypatch.setattr(bug_fix_update_command, "update_bug_fix", fake_update_bug_fix)

    cmd = bug_fix_update_command.BugFixUpdateCommand()
    result = _run(
        cmd.execute(bug_fix=str(uuid.uuid4()), changed_by="tester", implementation_notes="second pass done", append=True)
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["implementation_notes"] == "first pass done\n\nsecond pass done"


def test_bug_fix_update_default_append_false_replaces(monkeypatch) -> None:
    fix = _Entity(bug_uuid=uuid.uuid4(), status="in_progress", implementation_notes="first pass done")
    captured: dict = {}

    monkeypatch.setattr(bug_fix_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_fix_update_command, "get_bug_fix", lambda conn, fix_uuid: fix)
    monkeypatch.setattr(plan_completion_guard, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))

    def fake_update_bug_fix(conn, fix_uuid, **kwargs):
        captured.update(kwargs)
        return _Entity(to_payload=lambda: {"uuid": str(fix_uuid)})

    monkeypatch.setattr(bug_fix_update_command, "update_bug_fix", fake_update_bug_fix)

    cmd = bug_fix_update_command.BugFixUpdateCommand()
    result = _run(cmd.execute(bug_fix=str(uuid.uuid4()), changed_by="tester", implementation_notes="second pass done"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["implementation_notes"] == "second pass done"


# ---------------------------------------------------------------------------
# BUG 3eec33f2: `plan` optional on bug_id-addressing commands. Reproduces the
# defect first (a project-anchored bug, no plan supplied, used to raise
# because `plan` was a hard-required schema field / resolve_plan_guarded was
# unconditionally called) then proves the fix admits it and still enforces
# the entity's OWN plan-completion lock.
# ---------------------------------------------------------------------------


_LIFECYCLE_COMMAND_CLASSES = {
    bug_confirm_command: bug_confirm_command.BugConfirmCommand,
    bug_reject_command: bug_reject_command.BugRejectCommand,
    bug_reopen_command: bug_reopen_command.BugReopenCommand,
    bug_triage_command: bug_triage_command.BugTriageCommand,
    bug_close_command: bug_close_command.BugCloseCommand,
    bug_mark_duplicate_command: bug_mark_duplicate_command.BugMarkDuplicateCommand,
}


@pytest.mark.parametrize(
    "module, bug_status, extra_kwargs",
    [
        (bug_confirm_command, "reported", {"changed_by": "tester"}),
        (bug_reject_command, "reported", {"changed_by": "tester"}),
        (bug_reopen_command, "closed", {"changed_by": "tester"}),
        (bug_triage_command, "reported", {"changed_by": "tester"}),
        (bug_close_command, "confirmed", {"closed_by": "tester"}),
        (bug_mark_duplicate_command, "reported", {"changed_by": "tester", "duplicate_of_uuid": str(uuid.uuid4())}),
    ],
)
def test_bug_lifecycle_command_admits_project_anchored_bug_without_plan(monkeypatch, module, bug_status, extra_kwargs) -> None:
    """A project-anchored bug (source_plan_uuid=None) has no plan to check, so
    the command must succeed even with `plan` entirely omitted -- and must never
    even query the plan table, proving no accidental plan resolution happens."""
    bug = _Entity(status=bug_status, source_plan_uuid=None)

    monkeypatch.setattr(module, "db_connection", lambda: _fake_db_ctx(_NoPlanQueryConn()))
    monkeypatch.setattr(module, "get_bug", lambda conn, bug_uuid: bug)

    def _passthrough(conn, bug_uuid, **kwargs):
        return _Entity(to_payload=lambda: {"uuid": str(bug_uuid)})

    if hasattr(module, "set_bug_status"):
        monkeypatch.setattr(module, "set_bug_status", _passthrough)
    if hasattr(module, "mark_bug_duplicate"):
        monkeypatch.setattr(module, "mark_bug_duplicate", _passthrough)
    if module is bug_close_command:
        monkeypatch.setattr(module, "list_bug_fixes", lambda conn, bug_uuid: [_Entity(status="verified", passed=True, fix_uuid=uuid.uuid4())])
        monkeypatch.setattr(module, "list_bug_impacts", lambda conn, bug_uuid: [])
        monkeypatch.setattr(module, "list_bug_fix_propagations", lambda conn, bug_fix_uuid: [])

    kwargs = {"bug_id": str(uuid.uuid4()), **extra_kwargs}
    cmd_cls = _LIFECYCLE_COMMAND_CLASSES[module]
    result = _run(cmd_cls().execute(**kwargs))

    assert isinstance(result, SuccessResult), getattr(result, "message", getattr(result, "data", result))


def test_bug_update_admits_project_anchored_bug_without_plan(monkeypatch) -> None:
    bug = _bug_for_update(source_plan_uuid=None)

    monkeypatch.setattr(bug_update_command, "db_connection", lambda: _fake_db_ctx(_NoPlanQueryConn()))
    monkeypatch.setattr(bug_update_command, "get_bug", lambda conn, bug_uuid: bug)
    monkeypatch.setattr(bug_update_command, "update_bug", lambda conn, bug_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(bug_uuid)}))

    cmd = bug_update_command.BugUpdateCommand()
    result = _run(cmd.execute(bug_id=str(uuid.uuid4()), changed_by="tester", severity="critical"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_reanchor_admits_project_anchored_bug_without_plan(monkeypatch) -> None:
    bug = _Entity(source_plan_uuid=None)

    monkeypatch.setattr(bug_reanchor_command, "db_connection", lambda: _fake_db_ctx(_NoPlanQueryConn()))
    monkeypatch.setattr(bug_reanchor_command, "get_bug", lambda conn, bug_uuid: bug)
    monkeypatch.setattr(bug_reanchor_command, "app_config", lambda: None)
    monkeypatch.setattr(
        bug_reanchor_command, "confirm_anchor",
        lambda app_cfg, *, requested_type, project_id, file_path: __import__("plan_manager.commands.anchor_confirmation", fromlist=["AnchorConfirmation"]).AnchorConfirmation(applicable=False, confirmed=False, reason=None),
    )
    monkeypatch.setattr(
        bug_reanchor_command, "reanchor_bug_source",
        lambda conn, bug_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(bug_uuid)}),
    )

    cmd = bug_reanchor_command.BugReanchorCommand()
    result = _run(cmd.execute(bug_id=str(uuid.uuid4()), changed_by="tester", new_source_type="command", new_source_command="do_thing"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_fix_create_admits_bug_without_plan(monkeypatch) -> None:
    bug = _Entity(source_plan_uuid=None)

    monkeypatch.setattr(bug_fix_create_command, "db_connection", lambda: _fake_db_ctx(_NoPlanQueryConn()))
    monkeypatch.setattr(bug_fix_create_command, "get_bug", lambda conn, bug_uuid: bug)
    monkeypatch.setattr(
        bug_fix_create_command, "create_bug_fix",
        lambda conn, **kwargs: _Entity(to_payload=lambda: {"uuid": "fix-1"}),
    )
    monkeypatch.setattr(bug_fix_create_command, "recompute_bug_status", lambda conn, bug_uuid, **kwargs: None)

    cmd = bug_fix_create_command.BugFixCreateCommand()
    result = _run(
        cmd.execute(bug=str(uuid.uuid4()), fix_type="code", summary="s", author="a", created_by="a")
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_fix_update_admits_fix_without_plan(monkeypatch) -> None:
    fix = _Entity(bug_uuid=uuid.uuid4(), status="in_progress", implementation_notes=None)

    monkeypatch.setattr(bug_fix_update_command, "db_connection", lambda: _fake_db_ctx(_NoPlanQueryConn()))
    monkeypatch.setattr(bug_fix_update_command, "get_bug_fix", lambda conn, fix_uuid: fix)
    monkeypatch.setattr(plan_completion_guard, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))
    monkeypatch.setattr(
        bug_fix_update_command, "update_bug_fix",
        lambda conn, fix_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(fix_uuid)}),
    )

    cmd = bug_fix_update_command.BugFixUpdateCommand()
    result = _run(cmd.execute(bug_fix=str(uuid.uuid4()), changed_by="tester", implementation_notes="n"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_fix_verify_admits_fix_without_plan(monkeypatch) -> None:
    fix = _Entity(bug_uuid=uuid.uuid4())

    monkeypatch.setattr(bug_fix_verify_command, "db_connection", lambda: _fake_db_ctx(_NoPlanQueryConn()))
    monkeypatch.setattr(bug_fix_verify_command, "get_bug_fix", lambda conn, fix_uuid: fix)
    monkeypatch.setattr(plan_completion_guard, "get_bug", lambda conn, bug_uuid: _Entity(source_plan_uuid=None))
    monkeypatch.setattr(
        bug_fix_verify_command, "verify_bug_fix",
        lambda conn, fix_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(fix_uuid)}),
    )
    monkeypatch.setattr(bug_fix_verify_command, "recompute_bug_status", lambda conn, bug_uuid, **kwargs: None)

    cmd = bug_fix_verify_command.BugFixVerifyCommand()
    result = _run(cmd.execute(bug_fix=str(uuid.uuid4()), changed_by="tester", passed=True))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)


def test_bug_lifecycle_command_still_enforces_own_plan_completion_without_supplied_plan(monkeypatch) -> None:
    """The entity's OWN plan anchor is completed; `plan` is omitted entirely.
    The bug is still refused with PLAN_COMPLETED via the existing
    plan_completion_guard seam (refuse_if_bug_plan_completed), proving the
    fix does not weaken the completion lock -- it only removes the redundant
    unrelated-plan check."""
    owning_plan_uuid = uuid.uuid4()
    bug = _Entity(status="reported", source_plan_uuid=owning_plan_uuid)

    class _CompletedPlanConn:
        def execute(self, sql: str, params: tuple = ()):
            class _Cur:
                def fetchone(self_inner):
                    return (True,) if "SELECT completed FROM plan" in sql else None

            return _Cur()

    monkeypatch.setattr(bug_confirm_command, "db_connection", lambda: _fake_db_ctx(_CompletedPlanConn()))
    monkeypatch.setattr(bug_confirm_command, "get_bug", lambda conn, bug_uuid: bug)

    cmd = bug_confirm_command.BugConfirmCommand()
    result = _run(cmd.execute(bug_id=str(uuid.uuid4()), changed_by="tester"))

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"


def test_bug_lifecycle_command_with_explicit_plan_keeps_old_behavior(monkeypatch) -> None:
    """When `plan` IS supplied, the prior resolve_plan_guarded(conn, plan)
    behavior is preserved: a completed SUPPLIED plan still refuses the call,
    exactly like before this fix (regression guard against the optionality
    change accidentally loosening the explicit-plan path)."""
    from plan_manager.commands import resolve as resolve_module

    bug = _Entity(status="reported", source_plan_uuid=None)
    monkeypatch.setattr(bug_confirm_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_confirm_command, "get_bug", lambda conn, bug_uuid: bug)

    def _raise_completed(conn, plan):
        raise DomainCommandError("PLAN_COMPLETED", f"plan {plan} is marked completed")

    monkeypatch.setattr(bug_confirm_command, "resolve_plan", _raise_completed)

    cmd = bug_confirm_command.BugConfirmCommand()
    result = _run(cmd.execute(plan="some-completed-plan", bug_id=str(uuid.uuid4()), changed_by="tester"))

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "PLAN_COMPLETED"


# ---------------------------------------------------------------------------
# BUG 3eec33f2: bug_create -- plan required only for source_type plan/revision/step.
# ---------------------------------------------------------------------------


class _FakePlan:
    def __init__(self) -> None:
        self.uuid = uuid.uuid4()


def _bug_create_kwargs(**overrides: Any) -> dict:
    kwargs = dict(
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


def test_bug_create_project_anchor_admitted_without_plan(monkeypatch) -> None:
    captured: dict = {}

    def fake_create_bug(conn, **kwargs):
        captured["source"] = kwargs["source"]
        return _Entity(to_payload=lambda: {"uuid": "bug-1"})

    monkeypatch.setattr(bug_create_command, "db_connection", lambda: _fake_db_ctx(_NoPlanQueryConn()))
    monkeypatch.setattr(bug_create_command, "app_config", lambda: None)
    monkeypatch.setattr(bug_create_command, "create_bug", fake_create_bug)
    from plan_manager.commands.anchor_confirmation import AnchorConfirmation

    monkeypatch.setattr(
        bug_create_command, "confirm_anchor",
        lambda app_cfg, *, requested_type, project_id, file_path: AnchorConfirmation(applicable=True, confirmed=True, reason=None),
    )

    result = _run(bug_create_command.BugCreateCommand().execute(**_bug_create_kwargs()))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["source"].source_type == "project"


@pytest.mark.parametrize("source_type", ["plan", "revision", "step"])
def test_bug_create_plan_anchor_requires_plan_parameter(monkeypatch, source_type) -> None:
    """Reproduces the design requirement: source_type=plan/revision/step needs
    the anchor's owning plan resolvable -- `plan` must still be required for
    these three source types, even though it is optional overall."""
    monkeypatch.setattr(bug_create_command, "db_connection", lambda: _fake_db_ctx(_NoPlanQueryConn()))
    monkeypatch.setattr(bug_create_command, "app_config", lambda: None)

    overrides: dict[str, Any] = {"source_type": source_type, "source_project_id": None}
    if source_type == "plan":
        overrides["source_plan_uuid"] = str(uuid.uuid4())
    elif source_type == "revision":
        overrides["source_revision_uuid"] = str(uuid.uuid4())
    elif source_type == "step":
        overrides["source_step_uuid"] = str(uuid.uuid4())
        overrides["source_plan_uuid"] = str(uuid.uuid4())

    result = _run(bug_create_command.BugCreateCommand().execute(**_bug_create_kwargs(**overrides)))

    assert isinstance(result, ErrorResult), getattr(result, "data", result)
    assert result.details.get("domain_code") == "RUNTIME_VALIDATION_ERROR"


def test_bug_create_plan_anchor_with_plan_supplied_still_works(monkeypatch) -> None:
    captured: dict = {}

    def fake_create_bug(conn, **kwargs):
        captured["source"] = kwargs["source"]
        return _Entity(to_payload=lambda: {"uuid": "bug-2"})

    monkeypatch.setattr(bug_create_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_create_command, "app_config", lambda: None)
    monkeypatch.setattr(bug_create_command, "resolve_plan", lambda conn, plan: _FakePlan())
    monkeypatch.setattr(bug_create_command, "create_bug", fake_create_bug)
    from plan_manager.commands.anchor_confirmation import AnchorConfirmation

    monkeypatch.setattr(
        bug_create_command, "confirm_anchor",
        lambda app_cfg, *, requested_type, project_id, file_path: AnchorConfirmation(applicable=True, confirmed=True, reason=None),
    )

    plan_uuid = str(uuid.uuid4())
    result = _run(
        bug_create_command.BugCreateCommand().execute(
            **_bug_create_kwargs(source_type="plan", source_project_id=None, source_plan_uuid=plan_uuid, plan="my-plan")
        )
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert captured["source"].source_type == "plan"
