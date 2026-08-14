"""Regression tests for bug 26107e40 (plan-guard acknowledgment).

Before this fix, perform_guarded_runtime_update (the shared helper backing
bug_update, bug_impact_update, bug_propagation_update, bug_fix_update, and
several other guarded update commands) called resolve_scope(conn) purely
for its PLAN_COMPLETED side effect and threw the return value away -- a
caller who supplied `plan` had no way to see, from the response, which
plan the guard actually checked. The fix captures resolve_scope's return
value and, when it carries a `uuid` attribute (the shape resolve_plan_guarded
returns), merges `plan_guard": {"checked_plan_uuid": "..."}` into the
response payload. Callers that omit `plan` (resolve_scope=None) never see
the key -- there is nothing to acknowledge.

Also covers the description-hardening half of the same bug: the `plan`
parameter description across the 10-command family gains a sentence
clarifying that supplying `plan` never moves the bug's anchor.

Pure unit tests (monkeypatched db_connection / fake psycopg-shaped
connections), matching the established idiom in
tests/test_bug_32755092_append_and_3eec33f2_optional_plan.py.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Any

from mcp_proxy_adapter.commands.result import SuccessResult

from plan_manager.commands import bug_fix_update_command, bug_update_command


def _run(coro):
    return asyncio.run(coro)


@contextmanager
def _fake_db_ctx(conn):
    yield conn


class _Entity:
    """Generic attribute bag standing in for any domain dataclass; matches
    the idiom in tests/test_bug_32755092_append_and_3eec33f2_optional_plan.py."""

    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)

    def to_payload(self) -> dict:
        return {"uuid": "stub"}


class _FakePlan:
    """Stands in for the Plan record resolve_plan_guarded returns."""

    def __init__(self, plan_uuid: uuid.UUID) -> None:
        self.uuid = plan_uuid


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


# ---------------------------------------------------------------------------
# (a) bug_update WITH plan: plan_guard ack, severity applied, anchor untouched.
# ---------------------------------------------------------------------------


def test_bug_update_with_plan_acks_checked_plan_uuid_and_leaves_anchor_untouched(monkeypatch) -> None:
    resolved_plan_uuid = uuid.uuid4()
    # The bug's OWN anchor stays None (project-anchored, say) -- refuse_if_bug_plan_completed
    # is then a no-op that never touches conn, keeping the fake connection minimal; the
    # `plan` parameter here is an unrelated, explicitly supplied scope to acknowledge.
    bug = _bug_for_update(source_plan_uuid=None)
    captured: dict = {}

    monkeypatch.setattr(bug_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_update_command, "get_bug", lambda conn, bug_uuid: bug)
    monkeypatch.setattr(bug_update_command, "resolve_plan", lambda conn, plan: _FakePlan(resolved_plan_uuid))

    def fake_update_bug(conn, bug_uuid, **kwargs):
        captured.update(kwargs)
        return _Entity(to_payload=lambda: {"uuid": str(bug_uuid), "severity": kwargs.get("severity")})

    monkeypatch.setattr(bug_update_command, "update_bug", fake_update_bug)

    cmd = bug_update_command.BugUpdateCommand()
    result = _run(
        cmd.execute(bug_id=str(uuid.uuid4()), changed_by="tester", plan="some-plan", severity="critical")
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    payload = result.data
    assert payload["plan_guard"] == {"checked_plan_uuid": str(resolved_plan_uuid)}
    assert payload["severity"] == "critical"
    assert captured["severity"] == "critical"
    # bug_update never mutates the anchor: source_plan_uuid is not among the
    # fields it ever passes to update_bug, plan-supplied or not.
    assert "source_plan_uuid" not in captured


# ---------------------------------------------------------------------------
# (b) bug_update WITHOUT plan: no plan_guard key at all.
# ---------------------------------------------------------------------------


def test_bug_update_without_plan_has_no_plan_guard_key(monkeypatch) -> None:
    bug = _bug_for_update(source_plan_uuid=None)

    monkeypatch.setattr(bug_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_update_command, "get_bug", lambda conn, bug_uuid: bug)
    monkeypatch.setattr(
        bug_update_command, "update_bug",
        lambda conn, bug_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(bug_uuid)}),
    )

    cmd = bug_update_command.BugUpdateCommand()
    result = _run(cmd.execute(bug_id=str(uuid.uuid4()), changed_by="tester", severity="minor"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert "plan_guard" not in result.data


# ---------------------------------------------------------------------------
# (c) bug_fix_update WITH plan: same ack via the shared helper, including the
# build_result_data-wrapped ("bug_fix": {...}) payload shape.
# ---------------------------------------------------------------------------


def test_bug_fix_update_with_plan_acks_checked_plan_uuid_under_wrapped_payload(monkeypatch) -> None:
    resolved_plan_uuid = uuid.uuid4()
    fix = _Entity(bug_uuid=uuid.uuid4(), status="in_progress", implementation_notes="first pass done")

    monkeypatch.setattr(bug_fix_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_fix_update_command, "get_bug_fix", lambda conn, fix_uuid: fix)
    monkeypatch.setattr(bug_fix_update_command, "resolve_plan", lambda conn, plan: _FakePlan(resolved_plan_uuid))
    monkeypatch.setattr(
        bug_fix_update_command, "_guard_bug_fix_update",
        lambda conn, existing, update_fields: None,
    )
    monkeypatch.setattr(
        bug_fix_update_command, "update_bug_fix",
        lambda conn, fix_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(fix_uuid)}),
    )

    cmd = bug_fix_update_command.BugFixUpdateCommand()
    result = _run(
        cmd.execute(bug_fix=str(uuid.uuid4()), changed_by="tester", plan="some-plan", summary="s2")
    )

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    payload = result.data
    assert payload["plan_guard"] == {"checked_plan_uuid": str(resolved_plan_uuid)}
    assert "bug_fix" in payload  # build_result_data's wrapping key is preserved alongside plan_guard


def test_bug_fix_update_without_plan_has_no_plan_guard_key(monkeypatch) -> None:
    fix = _Entity(bug_uuid=uuid.uuid4(), status="in_progress", implementation_notes="first pass done")

    monkeypatch.setattr(bug_fix_update_command, "db_connection", lambda: _fake_db_ctx(object()))
    monkeypatch.setattr(bug_fix_update_command, "get_bug_fix", lambda conn, fix_uuid: fix)
    monkeypatch.setattr(
        bug_fix_update_command, "_guard_bug_fix_update",
        lambda conn, existing, update_fields: None,
    )
    monkeypatch.setattr(
        bug_fix_update_command, "update_bug_fix",
        lambda conn, fix_uuid, **kwargs: _Entity(to_payload=lambda: {"uuid": str(fix_uuid)}),
    )

    cmd = bug_fix_update_command.BugFixUpdateCommand()
    result = _run(cmd.execute(bug_fix=str(uuid.uuid4()), changed_by="tester", summary="s2"))

    assert isinstance(result, SuccessResult), getattr(result, "message", result)
    assert "plan_guard" not in result.data["bug_fix"]
    assert "plan_guard" not in result.data


# ---------------------------------------------------------------------------
# Description hardening: the anchor-stability sentence is present on all ten
# family members' `plan` parameter description.
# ---------------------------------------------------------------------------


def test_plan_description_across_the_ten_command_family_notes_anchor_is_unaffected() -> None:
    from plan_manager.commands import (
        bug_close_command,
        bug_confirm_command,
        bug_impact_update_command,
        bug_mark_duplicate_command,
        bug_propagation_update_command,
        bug_reject_command,
        bug_reopen_command,
        bug_triage_command,
    )

    modules_and_classes = [
        (bug_update_command, bug_update_command.BugUpdateCommand),
        (bug_impact_update_command, bug_impact_update_command.BugImpactUpdateCommand),
        (bug_propagation_update_command, bug_propagation_update_command.BugPropagationUpdateCommand),
        (bug_fix_update_command, bug_fix_update_command.BugFixUpdateCommand),
        (bug_close_command, bug_close_command.BugCloseCommand),
        (bug_confirm_command, bug_confirm_command.BugConfirmCommand),
        (bug_reject_command, bug_reject_command.BugRejectCommand),
        (bug_reopen_command, bug_reopen_command.BugReopenCommand),
        (bug_triage_command, bug_triage_command.BugTriageCommand),
        (bug_mark_duplicate_command, bug_mark_duplicate_command.BugMarkDuplicateCommand),
    ]
    for module, command_cls in modules_and_classes:
        schema = command_cls.get_schema()
        descr = schema["properties"]["plan"]["description"]
        assert "never changes the bug's anchor" in descr, module.__name__
        assert "bug_reanchor" in descr, module.__name__
