"""Regression tests for bug 8a13977d (todo_list response is unboundedly
verbose: 50 items = 137,022 chars, forcing consumers to spill to disk) and
its paired feature todo f9e29653 (list-family response-size control).

Live reproduction (2026-07-23, server 0.1.60, via MCP proxy-lan -> planmgr_1):
    todo_list(active_only=true, limit=50) -> 137,022 chars at the tool
    boundary; 222,558 bytes of raw JSON data (~4.45 KB/item avg over 50 rows).

Fix: every list command named in the bug/todo pair (plus the rest of the
verbose *_list inventory swept per the mandate) gains a `view` parameter
("full", the default, unchanged; "summary", a compact per-row projection).
The projection logic lives in ONE shared module,
plan_manager.commands.list_projection, and each entity declares its own
SUMMARY_FIELDS next to its to_payload() (plan_manager.domain.entity.
EntityRecord.to_summary_payload() is the single shared whitelisting
implementation every entity gets for free).

This suite is purely static/in-process (no live database, no live server),
mirroring this repo's existing convention for command-level contract tests
(see test_uniform_pagination_contract.py): dataclass entities are
constructed directly and projected through the real production code path.

Covered, per the mandate's own test list:
    - summary shape exact-field assertions, per family
    - full unchanged vs pre-fix shape
    - invalid view rejected (INVALID_FILTER)
    - default-view behavior pinned (view=full when omitted)
    - a byte-ceiling test on a maximally-populated fixture entity
"""
from __future__ import annotations

import json
import uuid

import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.list_projection import (
    VIEW_FULL,
    VIEW_SUMMARY,
    VIEW_VALUES,
    parse_view,
    project_entities,
    project_row,
    project_rows,
    view_metadata_params,
    view_schema_properties,
)
from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.model_binding import ModelBinding
from plan_manager.domain.plan import Plan
from plan_manager.domain.tool import Tool
from plan_manager.domain.todo import TodoItem
from plan_manager.storage.runtime_audit_store import RuntimeAuditRecord

# ---------------------------------------------------------------------------
# Byte ceiling: a defensible, documented cap for one view=summary row.
# ---------------------------------------------------------------------------
# 512 bytes/row is chosen as a round number comfortably above the widest
# summary row this fix produces (todo/bug's ~9-field projections with two
# 36-char UUIDs and a realistic title stay well under 300 bytes; see
# test_summary_row_stays_under_byte_ceiling below) while still being tight
# enough to catch a future SUMMARY_FIELDS regression that reintroduces a
# free-text field.
SUMMARY_ROW_BYTE_CEILING = 512

_UUID_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
_UUID_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
_LONG_TITLE = "A" * 120  # maximally-populated: a long-ish but realistic title
_LONG_TEXT = "lorem ipsum dolor sit amet " * 200  # ~5.4 KB of free text


def _maximally_populated_todo() -> TodoItem:
    return TodoItem(
        todo_uuid=_UUID_A,
        title=_LONG_TITLE,
        description=_LONG_TEXT,
        kind="task",
        status="open",
        priority_nice=-10,
        created_by="tester",
        assigned_to="tester",
        created_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T00:00:00+00:00",
        started_at=None,
        resolved_at=None,
        due_at=None,
        primary_anchor_type="bug",
        anchor_project_id=None,
        anchor_file_path=None,
        anchor_plan_uuid=None,
        anchor_revision_uuid=None,
        anchor_step_uuid=None,
        anchor_step_path=None,
        anchor_ref_id=_UUID_B,
        blocking_reason=_LONG_TEXT,
        execution_result=_LONG_TEXT,
        deleted_at=None,
    )


def _maximally_populated_bug() -> BugReport:
    return BugReport(
        bug_uuid=_UUID_A,
        title=_LONG_TITLE,
        short_description=_LONG_TEXT,
        detailed_description=_LONG_TEXT,
        expected_behavior=_LONG_TEXT,
        actual_behavior=_LONG_TEXT,
        reproduction=_LONG_TEXT,
        evidence={"k": "v" * 500},
        environment=_LONG_TEXT,
        kind="performance",
        severity="major",
        priority_nice=-4,
        status="reported",
        reporter="tester",
        owner=None,
        duplicate_of_uuid=None,
        parent_bug_uuid=None,
        source_anchor_type="command",
        source_project_id=None,
        source_file_path=None,
        source_plan_uuid=None,
        source_revision_uuid=None,
        source_step_uuid=None,
        source_step_path=None,
        source_ref_id=_UUID_B,
        source_command="todo_list",
        source_service=None,
        confirmed_at=None,
        closed_at=None,
        reopened_at=None,
        created_by="tester",
        created_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T00:00:00+00:00",
        deleted_at=None,
    )


def _bug_fix() -> BugFix:
    return BugFix(
        fix_uuid=_UUID_A,
        bug_uuid=_UUID_B,
        status="implemented",
        fix_type="code",
        summary=_LONG_TITLE,
        implementation_notes=_LONG_TEXT,
        source_project_id=None,
        branch="local",
        commit_hash="deadbeef",
        pull_request=None,
        changed_files=["a.py", "b.py"],
        tests=["test_a.py"],
        author="tester",
        reviewer=None,
        started_at=None,
        implemented_at=None,
        verified_at=None,
        verification_method=None,
        expected_result=_LONG_TEXT,
        actual_result=_LONG_TEXT,
        passed=None,
        revert_info=None,
        created_by="tester",
        created_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T00:00:00+00:00",
        deleted_at=None,
    )


def _tool() -> Tool:
    return Tool(
        tool_uuid=_UUID_A,
        name="my-tool",
        server_id="server-1",
        command="do_thing",
        pinned_options={"opt": "value" * 50},
        description=_LONG_TEXT,
        created_by="tester",
        created_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T00:00:00+00:00",
        deleted_at=None,
    )


def _model_binding() -> ModelBinding:
    return ModelBinding(
        binding_uuid=_UUID_A,
        scope="role",
        role="coder",
        plan_uuid=_UUID_B,
        spec_level=None,
        branch_step_uuid=None,
        revision_uuid=None,
        step_uuid=None,
        step_path=None,
        provider="anthropic",
        model="claude-sonnet",
        fallback_provider=None,
        fallback_model=None,
        max_retries=3,
        timeout=600,
        context_budget=None,
        active=True,
        created_by="tester",
        created_at="2026-07-23T00:00:00+00:00",
        updated_at="2026-07-23T00:00:00+00:00",
        deleted_at=None,
    )


def _audit_record() -> RuntimeAuditRecord:
    return RuntimeAuditRecord(
        audit_uuid=_UUID_A,
        plan_uuid=_UUID_B,
        target_type="todo",
        target_id=_UUID_B,
        action="update",
        changed_by="tester",
        change_reason=_LONG_TEXT,
        changed_fields={"title": {"old": "a", "new": "b" * 500}},
        linked_attempt_id=None,
        linked_review_id=None,
        created_at="2026-07-23T00:00:00+00:00",
    )


def _plan() -> Plan:
    return Plan(
        uuid=_UUID_A,
        name="my-plan",
        status="draft",
        context_budget=4000,
        head_revision_uuid=None,
        project_ids=[str(_UUID_B)] * 20,
        primary_project_id=str(_UUID_B),
        deleted_at=None,
        completed=False,
        comment=_LONG_TEXT,
    )


# ---------------------------------------------------------------------------
# parse_view: default pinning + invalid-value rejection
# ---------------------------------------------------------------------------

def test_parse_view_defaults_to_full_when_omitted() -> None:
    assert parse_view(None) == VIEW_FULL


def test_parse_view_accepts_summary() -> None:
    assert parse_view("summary") == VIEW_SUMMARY


def test_parse_view_rejects_invalid_value() -> None:
    with pytest.raises(DomainCommandError) as exc_info:
        parse_view("bogus")
    assert exc_info.value.code == "INVALID_FILTER"


def test_view_values_are_exactly_full_and_summary() -> None:
    assert set(VIEW_VALUES) == {"full", "summary"}


def test_view_schema_and_metadata_fragments_are_uniform() -> None:
    """Every touched command imports these two functions verbatim (no
    hand-rolled per-command 'view' property), so their shape is pinned once
    here rather than duplicated per command test.
    """
    schema = view_schema_properties()
    metadata = view_metadata_params()
    assert set(schema) == {"view"}
    assert set(metadata) == {"view"}
    assert schema["view"]["enum"] == ["full", "summary"]
    assert metadata["view"]["enum"] == ["full", "summary"]
    assert metadata["view"]["required"] is False


# ---------------------------------------------------------------------------
# Per-entity summary shape: exact-field assertions
# ---------------------------------------------------------------------------

def test_todo_summary_shape_is_exact() -> None:
    todo = _maximally_populated_todo()
    full = todo.to_payload()
    summary = todo.to_summary_payload()
    assert set(summary) == {
        "uuid", "todo_uuid", "title", "status", "kind",
        "priority_nice", "primary_anchor_type", "anchor_ref_id", "updated_at",
    }
    # The verbose fields that caused the bug are gone from the summary.
    for verbose_field in ("description", "blocking_reason", "execution_result"):
        assert verbose_field not in summary
        assert verbose_field in full  # still present in the full shape (unchanged)


def test_bug_summary_shape_is_exact() -> None:
    bug = _maximally_populated_bug()
    full = bug.to_payload()
    summary = bug.to_summary_payload()
    assert set(summary) == {
        "uuid", "bug_uuid", "title", "kind", "severity", "status",
        "priority_nice", "source_anchor_type", "source_ref_id", "updated_at",
    }
    for verbose_field in (
        "short_description", "detailed_description", "expected_behavior",
        "actual_behavior", "reproduction", "evidence", "environment",
    ):
        assert verbose_field not in summary
        assert verbose_field in full


def test_bug_fix_summary_shape_is_exact() -> None:
    fix = _bug_fix()
    summary = fix.to_summary_payload()
    assert set(summary) == {"uuid", "bug_uuid", "status", "fix_type", "summary", "author", "updated_at"}
    assert "implementation_notes" not in summary
    assert "revert_info" not in summary


def test_tool_summary_shape_is_exact() -> None:
    tool = _tool()
    summary = tool.to_summary_payload()
    assert set(summary) == {"uuid", "name", "server_id", "command", "updated_at"}
    assert "pinned_options" not in summary
    assert "description" not in summary


def test_model_binding_summary_shape_is_exact() -> None:
    binding = _model_binding()
    summary = binding.to_summary_payload()
    assert set(summary) == {"uuid", "scope", "role", "plan_uuid", "provider", "model", "active", "updated_at"}
    assert "fallback_provider" not in summary
    assert "context_budget" not in summary


def test_audit_summary_shape_is_exact() -> None:
    record = _audit_record()
    summary = record.to_summary_payload()
    assert set(summary) == {"uuid", "entity_type", "entity_id", "action", "changed_by", "created_at"}
    assert "changed_fields" not in summary
    assert "change_reason" not in summary


def test_entity_without_summary_fields_falls_back_to_full() -> None:
    """An entity that has not declared SUMMARY_FIELDS gets the full payload
    back from to_summary_payload() -- the safe default, never an empty dict.
    """
    plan = _plan()
    # Plan does not use EntityRecord.SUMMARY_FIELDS (plan_list hand-builds its
    # own row and projects it via project_row(), tested separately below);
    # exercise the base-class fallback directly through to_summary_payload().
    assert plan.SUMMARY_FIELDS == ()
    assert plan.to_summary_payload() == plan.to_payload()


# ---------------------------------------------------------------------------
# project_row / project_rows / project_entities: shared helper behavior
# ---------------------------------------------------------------------------

def test_project_entities_full_view_is_byte_for_byte_to_payload() -> None:
    """view=full must reproduce the EXACT pre-fix shape -- this is the
    backward-compatibility guarantee the whole fix rests on.
    """
    todo = _maximally_populated_todo()
    assert project_entities([todo], VIEW_FULL) == [todo.to_payload()]


def test_project_entities_summary_view_uses_to_summary_payload() -> None:
    todo = _maximally_populated_todo()
    assert project_entities([todo], VIEW_SUMMARY) == [todo.to_summary_payload()]


def test_project_row_full_view_passes_through_dict_unchanged() -> None:
    row = {"a": 1, "b": 2, "c": 3}
    assert project_row(row, VIEW_FULL, ("a",)) == row


def test_project_row_summary_view_whitelists_fields() -> None:
    row = {"a": 1, "b": 2, "c": 3}
    assert project_row(row, VIEW_SUMMARY, ("a", "c")) == {"a": 1, "c": 3}


def test_project_rows_applies_to_every_row() -> None:
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert project_rows(rows, VIEW_SUMMARY, ("a",)) == [{"a": 1}, {"a": 3}]


# ---------------------------------------------------------------------------
# Non-entity list commands: plan_list (hand-built row) and para_list (plain dicts)
# ---------------------------------------------------------------------------

def test_plan_list_summary_projection_is_exact() -> None:
    from plan_manager.commands.plan_list_command import PLAN_LIST_SUMMARY_FIELDS

    row = {
        "uuid": str(_UUID_A), "name": "my-plan", "status": "draft",
        "context_budget": 4000, "has_head": False, "project_ids": [str(_UUID_B)],
        "project_count": 1, "primary_project_id": str(_UUID_B),
        "deleted": False, "completed": False, "comment": _LONG_TEXT,
    }
    summary = project_row(row, VIEW_SUMMARY, PLAN_LIST_SUMMARY_FIELDS)
    assert set(summary) == {"uuid", "name", "status", "primary_project_id", "deleted"}
    full = project_row(row, VIEW_FULL, PLAN_LIST_SUMMARY_FIELDS)
    assert full == row


def test_para_list_summary_projection_is_exact() -> None:
    from plan_manager.commands.para_list_command import PARA_LIST_SUMMARY_FIELDS

    row = {"label": "a1b2", "binding": True, "position": 0, "text": _LONG_TEXT}
    summary = project_row(row, VIEW_SUMMARY, PARA_LIST_SUMMARY_FIELDS)
    assert summary == {"label": "a1b2", "binding": True, "position": 0}
    assert "text" not in summary


def test_step_list_summary_keys_drop_only_the_fields_key() -> None:
    from plan_manager.commands.step_list_command import ENTRY_KEYS, STEP_SUMMARY_KEYS

    assert set(STEP_SUMMARY_KEYS) == ENTRY_KEYS - {"fields"}
    assert "fields" not in STEP_SUMMARY_KEYS


# ---------------------------------------------------------------------------
# Byte ceiling
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "build_entity",
    [_maximally_populated_todo, _maximally_populated_bug, _bug_fix, _tool, _model_binding, _audit_record],
    ids=["todo", "bug", "bug_fix", "tool", "model_binding", "audit"],
)
def test_summary_row_stays_under_byte_ceiling(build_entity) -> None:
    entity = build_entity()
    summary = entity.to_summary_payload()
    size = len(json.dumps(summary).encode("utf-8"))
    assert size < SUMMARY_ROW_BYTE_CEILING, (
        f"{type(entity).__name__} summary row is {size} bytes, "
        f"exceeding the documented {SUMMARY_ROW_BYTE_CEILING}-byte ceiling: {summary}"
    )


def test_full_row_of_the_same_fixtures_exceeds_the_ceiling() -> None:
    """Sanity check that the ceiling is meaningful: the FULL payload of the
    same maximally-populated fixtures blows well past it, proving the
    summary projection is doing real work, not coincidentally small already.
    """
    todo = _maximally_populated_todo()
    full_size = len(json.dumps(todo.to_payload()).encode("utf-8"))
    assert full_size > SUMMARY_ROW_BYTE_CEILING * 10


# ---------------------------------------------------------------------------
# Command-surface wiring: every touched command's schema/metadata is uniform
# ---------------------------------------------------------------------------

_TOUCHED_LIST_COMMAND_MODULES = [
    ("plan_manager.commands.todo_list_command", "TodoListCommand"),
    ("plan_manager.commands.bug_list_command", "BugListCommand"),
    ("plan_manager.commands.bug_fix_list_command", "BugFixListCommand"),
    ("plan_manager.commands.bug_impact_list_command", "BugImpactListCommand"),
    ("plan_manager.commands.bug_propagation_list_command", "BugPropagationListCommand"),
    ("plan_manager.commands.audit_list_command", "AuditListCommand"),
    ("plan_manager.commands.plan_list_command", "PlanListCommand"),
    ("plan_manager.commands.step_list_command", "StepListCommand"),
    ("plan_manager.commands.tool_list_command", "ToolListCommand"),
    ("plan_manager.commands.toolset_list_command", "ToolsetListCommand"),
    ("plan_manager.commands.role_list_command", "RoleListCommand"),
    ("plan_manager.commands.provider_list_command", "ProviderListCommand"),
    ("plan_manager.commands.model_list_command", "ModelListCommand"),
    ("plan_manager.commands.invocation_profile_list_command", "InvocationProfileListCommand"),
    ("plan_manager.commands.model_binding_list_command", "ModelBindingListCommand"),
    ("plan_manager.commands.comment_list_command", "CommentListCommand"),
    ("plan_manager.commands.escalation_list_command", "EscalationListCommand"),
    ("plan_manager.commands.execution_attempt_list_command", "ExecutionAttemptListCommand"),
    ("plan_manager.commands.review_result_list_command", "ReviewResultListCommand"),
    ("plan_manager.commands.srt_snapshot_list_command", "SrtSnapshotListCommand"),
    ("plan_manager.commands.para_list_command", "ParaListCommand"),
]


def _load_command_classes() -> list:
    import importlib

    classes = []
    for module_name, class_name in _TOUCHED_LIST_COMMAND_MODULES:
        module = importlib.import_module(module_name)
        classes.append(getattr(module, class_name))
    return classes


@pytest.mark.parametrize(
    "module_name,class_name", _TOUCHED_LIST_COMMAND_MODULES, ids=[c for _, c in _TOUCHED_LIST_COMMAND_MODULES]
)
def test_touched_command_schema_declares_view_parameter(module_name: str, class_name: str) -> None:
    import importlib

    command = getattr(importlib.import_module(module_name), class_name)
    properties = command.get_schema()["properties"]
    assert "view" in properties, f"{command.name}: schema missing 'view' property"
    assert properties["view"]["enum"] == ["full", "summary"], command.name


@pytest.mark.parametrize(
    "module_name,class_name", _TOUCHED_LIST_COMMAND_MODULES, ids=[c for _, c in _TOUCHED_LIST_COMMAND_MODULES]
)
def test_touched_command_metadata_documents_view_parameter(module_name: str, class_name: str) -> None:
    import importlib

    command = getattr(importlib.import_module(module_name), class_name)
    parameters = command.metadata()["parameters"]
    assert "view" in parameters, f"{command.name}: metadata missing 'view' parameter"
    assert parameters["view"]["required"] is False, command.name
    assert parameters["view"]["enum"] == ["full", "summary"], command.name


@pytest.mark.parametrize(
    "module_name,class_name", _TOUCHED_LIST_COMMAND_MODULES, ids=[c for _, c in _TOUCHED_LIST_COMMAND_MODULES]
)
def test_touched_command_schema_view_defaults_to_full(module_name: str, class_name: str) -> None:
    """Pins the default-view decision: every touched command keeps view=full
    as the default (opt-in summary), for backward compatibility with existing
    callers (client facade, live_smoke recipes, internal command chains).
    """
    import importlib

    command = getattr(importlib.import_module(module_name), class_name)
    properties = command.get_schema()["properties"]
    assert properties["view"].get("default", "full") == "full", command.name
