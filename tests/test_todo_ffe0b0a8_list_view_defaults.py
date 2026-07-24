"""Characterizing tests for todo ffe0b0a8 (extends bug 8a13977d / bugs
7383c8a8+45f0c128's own fix): flip the default `view` to summary for every
list command whose entity already declares SUMMARY_FIELDS but whose command
still defaulted to VIEW_FULL, leaking unbounded free-text per row.

Reference implementation: plan_manager/commands/bug_list_command.py
(parse_view(view, default=VIEW_SUMMARY) + a command-local schema/metadata
override of the view property, mirroring srt_snapshot_list_command.py's
precedent for todo 4265fa4e).

The 9 commands touched by this todo:
    todo_list, comment_list, bug_fix_list, bug_impact_list,
    review_result_list, escalation_list, invocation_profile_list,
    model_binding_list, execution_attempt_list

Schema-level default=summary pinning lives in
tests/test_bug_8a13977d_list_view_projection.py
(test_todo_ffe0b0a8_command_schema_view_defaults_to_summary). THIS suite
covers the end-to-end command behavior per bugs 7383c8a8/45f0c128's own
test pattern (tests/test_bug_7383c8a8_45f0c128_response_size.py):
dataclass entities built directly with multi-KB free-text bodies,
monkeypatch over each command module's imported store functions, direct
asyncio.run(Command().execute(**kwargs)) against the real production code
path -- no mocked projection logic. For each command:
    - the default (no `view` kwarg) omits every heavy/free-text field
    - view="full" still returns the complete record, heavy fields included
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest

from plan_manager.commands import (
    bug_fix_list_command,
    bug_impact_list_command,
    comment_list_command,
    escalation_list_command,
    execution_attempt_list_command,
    invocation_profile_list_command,
    model_binding_list_command,
    review_result_list_command,
    todo_list_command,
)
from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_impact import BugImpact
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.escalation import Escalation
from plan_manager.domain.execution_attempt import ExecutionAttempt
from plan_manager.domain.invocation_profile import InvocationProfile
from plan_manager.domain.model_binding import ModelBinding
from plan_manager.domain.review_result import ReviewResult
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.domain.todo import TodoItem

_BIG_BODY = "lorem ipsum dolor sit amet " * 300  # ~8.1 KB, same shape as bug 7383c8a8's fixture
_UUID_A = uuid.uuid4()
_UUID_B = uuid.uuid4()
_TS = "2026-07-24T00:00:00+00:00"


@contextmanager
def _fake_db():
    yield object()


# ---------------------------------------------------------------------------
# Maximally-populated fixtures (heavy/free-text fields filled with _BIG_BODY)
# ---------------------------------------------------------------------------


def _todo() -> TodoItem:
    return TodoItem(
        todo_uuid=_UUID_A, title="Oversized todo", description=_BIG_BODY, kind="task",
        status="open", priority_nice=0, created_by="tester", assigned_to=None,
        created_at=_TS, updated_at=_TS, started_at=None, resolved_at=None, due_at=None,
        primary_anchor_type="none", anchor_project_id=None, anchor_file_path=None,
        anchor_plan_uuid=None, anchor_revision_uuid=None, anchor_step_uuid=None,
        anchor_step_path=None, anchor_ref_id=None,
        blocking_reason=_BIG_BODY, execution_result=_BIG_BODY, deleted_at=None,
    )


def _comment() -> RuntimeComment:
    return RuntimeComment(
        comment_uuid=_UUID_A, primary_anchor_type="plan", anchor_project_id=None,
        anchor_file_path=None, anchor_plan_uuid=_UUID_B, anchor_revision_uuid=None,
        anchor_step_uuid=None, anchor_step_path=None, anchor_ref_id=None,
        kind="comment", visibility="public", author="tester", body=_BIG_BODY,
        resolved=False, supersedes_comment_uuid=None, created_by="tester",
        created_at=_TS, updated_at=_TS, deleted_at=None,
    )


def _bug_fix() -> BugFix:
    return BugFix(
        fix_uuid=_UUID_A, bug_uuid=_UUID_B, status="implemented", fix_type="code",
        summary="short summary", implementation_notes=_BIG_BODY, source_project_id=None,
        branch="local", commit_hash="deadbeef", pull_request=None,
        changed_files=["a.py"] * 50, tests=["test_a.py"] * 50, author="tester",
        reviewer=None, started_at=None, implemented_at=None, verified_at=None,
        verification_method=None, expected_result=_BIG_BODY, actual_result=_BIG_BODY,
        passed=None, revert_info={"k": _BIG_BODY}, created_by="tester",
        created_at=_TS, updated_at=_TS, deleted_at=None,
    )


def _bug_impact() -> BugImpact:
    return BugImpact(
        impact_uuid=_UUID_A, bug_uuid=_UUID_B, target_type="project",
        target_project_id=_UUID_B, target_file_path=None, target_plan_uuid=None,
        target_revision_uuid=None, target_step_uuid=None, target_step_path=None,
        target_ref_id=_UUID_B, target_identifier=None, impact_type="uses_broken_api",
        status="suspected", reason=_BIG_BODY, skip_decided_by=None,
        discovery_method=_BIG_BODY, resolution_evidence={"k": _BIG_BODY},
        created_by="tester", created_at=_TS, updated_at=_TS, resolved_at=None, deleted_at=None,
    )


def _review_result() -> ReviewResult:
    return ReviewResult(
        review_uuid=_UUID_A, object_type="execution_attempt", reviewed_attempt_uuid=_UUID_B,
        reviewed_revision_uuid=None, reviewer="tester", status="accepted",
        findings=_BIG_BODY, evidence={"k": _BIG_BODY}, verification_commands=["cmd"] * 50,
        escalation_target_uuid=None, created_by="tester", created_at=_TS, updated_at=_TS,
        deleted_at=None,
    )


def _escalation() -> Escalation:
    return Escalation(
        escalation_uuid=_UUID_A, primary_anchor_type="plan", anchor_project_id=None,
        anchor_file_path=None, anchor_plan_uuid=_UUID_B, anchor_revision_uuid=None,
        anchor_step_uuid=None, anchor_step_path=None, anchor_ref_id=_UUID_B,
        reason=_BIG_BODY, from_level="tactical", to_level="global", status="open",
        resolution=_BIG_BODY, resolved_by=None, resolved_at=None, created_by="tester",
        created_at=_TS, updated_at=_TS, deleted_at=None, addressee_level="global",
        addressee_role="orchestrator", forwarded_from_uuid=None, chain_root_uuid=None,
        sweep_priority=None, blocks_subtree=False,
    )


def _invocation_profile() -> InvocationProfile:
    return InvocationProfile(
        profile_uuid=_UUID_A, scope="role", role="coder", plan_uuid=_UUID_B,
        spec_level=None, branch_step_uuid=None, revision_uuid=None, step_uuid=None,
        step_path=None, temperature=0.7, top_p=0.9, max_output_tokens=4096,
        reasoning_effort="high", context_window_budget=200000, timeout=600,
        retry_policy={"k": _BIG_BODY}, concurrency=1, rate_hint={"k": _BIG_BODY},
        response_format="json", response_schema={"k": _BIG_BODY}, max_tool_iterations=50,
        per_call_timeout=60, execution_mode="batch", token_budget=100000,
        cost_budget=10.0, dialogue_chain_ref=None, active=True, created_by="tester",
        created_at=_TS, updated_at=_TS, deleted_at=None,
    )


def _model_binding() -> ModelBinding:
    return ModelBinding(
        binding_uuid=_UUID_A, scope="role", role="coder", plan_uuid=_UUID_B,
        spec_level=None, branch_step_uuid=None, revision_uuid=None, step_uuid=None,
        step_path=None, provider="anthropic", model="claude-sonnet",
        fallback_provider="anthropic", fallback_model="claude-haiku", max_retries=3,
        timeout=600, context_budget=100000, active=True, created_by="tester",
        created_at=_TS, updated_at=_TS, deleted_at=None,
    )


def _execution_attempt() -> ExecutionAttempt:
    return ExecutionAttempt(
        attempt_uuid=_UUID_A, plan_uuid=_UUID_B, revision_uuid=None, step_uuid=_UUID_B,
        step_path="1.1", todo_uuid=None, bug_fix_uuid=None, assigned_binding_uuid=None,
        assigned_provider="anthropic", assigned_model="claude-sonnet",
        used_provider="anthropic", used_model="claude-sonnet", runtime=None,
        vast_instance_id=None, started_at=None, finished_at=None, status="succeeded",
        input_context_hash=None, result_summary=_BIG_BODY,
        changed_files=["a.py"] * 50, command_test_results={"k": _BIG_BODY},
        resource_accounting={"k": _BIG_BODY}, acct_tokens_in=100, acct_tokens_out=200,
        acct_provider="anthropic", acct_model="claude-sonnet", acct_wall_ms=1000,
        acct_cost_estimate=0.5, transcript_ref=_BIG_BODY, error=None,
        escalation_reason=None, parent_attempt_uuid=None, created_by="tester",
        created_at=_TS, updated_at=_TS, deleted_at=None,
    )


def _bug(source_plan_uuid=None) -> BugReport:
    return BugReport(
        bug_uuid=_UUID_B, title="anchor bug", short_description="short",
        detailed_description=_BIG_BODY, expected_behavior=_BIG_BODY,
        actual_behavior=_BIG_BODY, reproduction=_BIG_BODY, evidence={"k": "v"},
        environment=_BIG_BODY, kind="performance", severity="minor", priority_nice=0,
        status="reported", reporter="tester", owner=None, duplicate_of_uuid=None,
        parent_bug_uuid=None, source_anchor_type="project", source_project_id=None,
        source_file_path=None, source_plan_uuid=source_plan_uuid, source_revision_uuid=None,
        source_step_uuid=None, source_step_path=None, source_ref_id=None,
        source_command=None, source_service=None, confirmed_at=None, closed_at=None,
        reopened_at=None, created_by="tester", created_at=_TS, updated_at=_TS, deleted_at=None,
    )


# ---------------------------------------------------------------------------
# todo_list
# ---------------------------------------------------------------------------

_TODO_HEAVY_FIELDS = ("description", "blocking_reason", "execution_result")


def _run_todo_list(monkeypatch, **kwargs):
    def fake_list_todos_page(conn, **_kwargs):
        return [_todo()], 1

    monkeypatch.setattr(todo_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(todo_list_command, "list_todos_page", fake_list_todos_page)
    result = asyncio.run(todo_list_command.TodoListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_todo_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_todo_list(monkeypatch)["todos"][0]
    for field in _TODO_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default todo_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_todo_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_todo_list(monkeypatch, view="full")["todos"][0]
    for field in _TODO_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full todo_list row"
    assert row["description"] == _BIG_BODY


# ---------------------------------------------------------------------------
# comment_list
# ---------------------------------------------------------------------------

_COMMENT_HEAVY_FIELDS = ("body",)


def _run_comment_list(monkeypatch, **kwargs):
    def fake_list_comments_page(conn, **_kwargs):
        return [_comment()], 1

    monkeypatch.setattr(comment_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(comment_list_command, "list_comments_page", fake_list_comments_page)
    result = asyncio.run(comment_list_command.CommentListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_comment_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_comment_list(monkeypatch)["comments"][0]
    for field in _COMMENT_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default comment_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_comment_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_comment_list(monkeypatch, view="full")["comments"][0]
    for field in _COMMENT_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full comment_list row"
    assert row["body"] == _BIG_BODY


# ---------------------------------------------------------------------------
# bug_fix_list
# ---------------------------------------------------------------------------

_BUG_FIX_HEAVY_FIELDS = ("implementation_notes", "changed_files", "tests", "expected_result", "actual_result", "revert_info")


def _run_bug_fix_list(monkeypatch, **kwargs):
    monkeypatch.setattr(bug_fix_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_fix_list_command, "get_bug", lambda conn, bug_uuid: _bug(source_plan_uuid=None))
    monkeypatch.setattr(bug_fix_list_command, "list_bug_fixes", lambda conn, **_kwargs: [_bug_fix()])
    kwargs.setdefault("bug", str(_UUID_B))
    result = asyncio.run(bug_fix_list_command.BugFixListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_bug_fix_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_bug_fix_list(monkeypatch)["bug_fixes"][0]
    for field in _BUG_FIX_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default bug_fix_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_bug_fix_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_bug_fix_list(monkeypatch, view="full")["bug_fixes"][0]
    for field in _BUG_FIX_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full bug_fix_list row"
    assert row["implementation_notes"] == _BIG_BODY


# ---------------------------------------------------------------------------
# bug_impact_list
# ---------------------------------------------------------------------------

_BUG_IMPACT_HEAVY_FIELDS = ("reason", "resolution_evidence", "discovery_method")


def _run_bug_impact_list(monkeypatch, **kwargs):
    monkeypatch.setattr(bug_impact_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_impact_list_command, "get_bug", lambda conn, bug_uuid: _bug(source_plan_uuid=None))
    monkeypatch.setattr(bug_impact_list_command, "list_bug_impacts", lambda conn, **_kwargs: [_bug_impact()])
    kwargs.setdefault("bug_id", str(_UUID_B))
    result = asyncio.run(bug_impact_list_command.BugImpactListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_bug_impact_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_bug_impact_list(monkeypatch)["bug_impacts"][0]
    for field in _BUG_IMPACT_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default bug_impact_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_bug_impact_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_bug_impact_list(monkeypatch, view="full")["bug_impacts"][0]
    for field in _BUG_IMPACT_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full bug_impact_list row"
    assert row["reason"] == _BIG_BODY


# ---------------------------------------------------------------------------
# review_result_list
# ---------------------------------------------------------------------------

_REVIEW_RESULT_HEAVY_FIELDS = ("findings", "evidence", "verification_commands")


def _run_review_result_list(monkeypatch, **kwargs):
    monkeypatch.setattr(review_result_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(review_result_list_command, "list_review_results", lambda conn, **_kwargs: [_review_result()])
    result = asyncio.run(review_result_list_command.ReviewResultListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_review_result_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_review_result_list(monkeypatch)["review_results"][0]
    for field in _REVIEW_RESULT_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default review_result_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_review_result_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_review_result_list(monkeypatch, view="full")["review_results"][0]
    for field in _REVIEW_RESULT_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full review_result_list row"
    assert row["findings"] == _BIG_BODY


# ---------------------------------------------------------------------------
# escalation_list
# ---------------------------------------------------------------------------

_ESCALATION_HEAVY_FIELDS = ("reason", "resolution")


def _run_escalation_list(monkeypatch, **kwargs):
    monkeypatch.setattr(escalation_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(escalation_list_command, "list_escalations", lambda conn, **_kwargs: [_escalation()])
    result = asyncio.run(escalation_list_command.EscalationListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_escalation_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_escalation_list(monkeypatch)["escalations"][0]
    for field in _ESCALATION_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default escalation_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_escalation_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_escalation_list(monkeypatch, view="full")["escalations"][0]
    for field in _ESCALATION_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full escalation_list row"
    assert row["reason"] == _BIG_BODY


# ---------------------------------------------------------------------------
# invocation_profile_list
# ---------------------------------------------------------------------------

_INVOCATION_PROFILE_HEAVY_FIELDS = ("temperature", "top_p", "retry_policy", "rate_hint", "response_schema")


def _run_invocation_profile_list(monkeypatch, **kwargs):
    monkeypatch.setattr(invocation_profile_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(invocation_profile_list_command, "list_invocation_profiles", lambda conn, **_kwargs: [_invocation_profile()])
    result = asyncio.run(invocation_profile_list_command.InvocationProfileListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_invocation_profile_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_invocation_profile_list(monkeypatch)["profiles"][0]
    for field in _INVOCATION_PROFILE_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default invocation_profile_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_invocation_profile_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_invocation_profile_list(monkeypatch, view="full")["profiles"][0]
    for field in _INVOCATION_PROFILE_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full invocation_profile_list row"
    assert row["temperature"] == 0.7


# ---------------------------------------------------------------------------
# model_binding_list
# ---------------------------------------------------------------------------

_MODEL_BINDING_HEAVY_FIELDS = ("fallback_provider", "fallback_model", "max_retries", "timeout", "context_budget")


def _run_model_binding_list(monkeypatch, **kwargs):
    monkeypatch.setattr(model_binding_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(model_binding_list_command, "list_model_bindings", lambda conn, **_kwargs: [_model_binding()])
    result = asyncio.run(model_binding_list_command.ModelBindingListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_model_binding_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_model_binding_list(monkeypatch)["bindings"][0]
    for field in _MODEL_BINDING_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default model_binding_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_model_binding_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_model_binding_list(monkeypatch, view="full")["bindings"][0]
    for field in _MODEL_BINDING_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full model_binding_list row"
    assert row["fallback_provider"] == "anthropic"


# ---------------------------------------------------------------------------
# execution_attempt_list
# ---------------------------------------------------------------------------

_EXECUTION_ATTEMPT_HEAVY_FIELDS = ("result_summary", "command_test_results", "resource_accounting", "transcript_ref")


def _run_execution_attempt_list(monkeypatch, **kwargs):
    monkeypatch.setattr(execution_attempt_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(execution_attempt_list_command, "list_execution_attempts", lambda conn, **_kwargs: [_execution_attempt()])
    result = asyncio.run(execution_attempt_list_command.ExecutionAttemptListCommand().execute(**kwargs))
    return result.to_dict()["data"]


def test_execution_attempt_list_default_omits_heavy_fields(monkeypatch) -> None:
    row = _run_execution_attempt_list(monkeypatch)["execution_attempts"][0]
    for field in _EXECUTION_ATTEMPT_HEAVY_FIELDS:
        assert field not in row, f"{field!r} leaked into the default execution_attempt_list row: {sorted(row)}"
    assert row["uuid"] == str(_UUID_A)


def test_execution_attempt_list_view_full_still_returns_heavy_fields(monkeypatch) -> None:
    row = _run_execution_attempt_list(monkeypatch, view="full")["execution_attempts"][0]
    for field in _EXECUTION_ATTEMPT_HEAVY_FIELDS:
        assert field in row, f"{field!r} missing from the view=full execution_attempt_list row"
    assert row["result_summary"] == _BIG_BODY


# ---------------------------------------------------------------------------
# view=summary explicit matches the implicit default, per command (sanity
# check that the default really IS summary, not some other silently-narrower
# shape)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "runner,data_key",
    [
        (_run_todo_list, "todos"),
        (_run_comment_list, "comments"),
        (_run_bug_fix_list, "bug_fixes"),
        (_run_bug_impact_list, "bug_impacts"),
        (_run_review_result_list, "review_results"),
        (_run_escalation_list, "escalations"),
        (_run_invocation_profile_list, "profiles"),
        (_run_model_binding_list, "bindings"),
        (_run_execution_attempt_list, "execution_attempts"),
    ],
    ids=[
        "todo_list", "comment_list", "bug_fix_list", "bug_impact_list",
        "review_result_list", "escalation_list", "invocation_profile_list",
        "model_binding_list", "execution_attempt_list",
    ],
)
def test_view_summary_explicit_matches_default(monkeypatch, runner, data_key) -> None:
    default_data = runner(monkeypatch)
    explicit_data = runner(monkeypatch, view="summary")
    assert default_data[data_key] == explicit_data[data_key]
