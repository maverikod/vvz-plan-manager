"""Regression tests for BUG 8972f59e (list-surface fixes, 0.1.28):

1c. INVALID_FILTER on bad enum filter values (parse_filters `enums` param).
1c. BUG_NOT_FOUND when bug_impact_list is given a nonexistent bug_id.
1a. todo_list's anchor_plan filter still declared in schema/metadata (name-or-UUID
    resolution now happens via resolve_plan rather than parse_filters).
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import bug_impact_list_command, todo_list_command
from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.runtime_filtering import parse_filters


@contextmanager
def _fake_db():
    yield object()


class _DummyPlan:
    def __init__(self):
        self.uuid = uuid.uuid4()


def _assert_domain_error(result, code: str) -> None:
    payload = result.to_dict()
    assert "error" in payload, f"expected an error result, got: {payload}"
    assert payload["error"]["data"]["domain_code"] == code


# --- parse_filters `enums` param -------------------------------------------------


def test_parse_filters_enum_valid_value_passes() -> None:
    filters = parse_filters(
        {"status": "open"}, ["status"], enums={"status": frozenset({"open", "closed"})}
    )
    assert filters.get("status") == "open"


def test_parse_filters_enum_invalid_value_raises_invalid_filter() -> None:
    try:
        parse_filters(
            {"status": "bogus"}, ["status"], enums={"status": frozenset({"open", "closed"})}
        )
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "INVALID_FILTER"


def test_parse_filters_enum_none_is_backward_compatible() -> None:
    # No enums kwarg at all: any string value passes, matching pre-existing behavior.
    filters = parse_filters({"status": "anything-goes"}, ["status"])
    assert filters.get("status") == "anything-goes"


def test_parse_filters_enum_dict_provided_but_field_not_a_key_is_unchecked() -> None:
    # enums is provided, but "kind" is not one of its keys, so no vocabulary check applies.
    filters = parse_filters(
        {"kind": "whatever"}, ["kind"], enums={"status": frozenset({"open", "closed"})}
    )
    assert filters.get("kind") == "whatever"


def test_parse_filters_enum_absent_value_is_not_checked() -> None:
    # Field not present in params at all: enums check never runs, no error.
    filters = parse_filters({}, ["status"], enums={"status": frozenset({"open", "closed"})})
    assert filters.get("status") is None


# --- todo_list: anchor_plan stays declared in schema/metadata --------------------


def test_todo_list_schema_declares_anchor_plan() -> None:
    schema = todo_list_command.TodoListCommand.get_schema()
    assert "anchor_plan" in schema["properties"]


def test_todo_list_metadata_declares_anchor_plan() -> None:
    metadata = todo_list_command.TodoListCommand.metadata()
    assert "anchor_plan" in metadata["parameters"]


# --- bug_impact_list: BUG_NOT_FOUND on a missing bug_id --------------------------


def test_bug_impact_list_raises_bug_not_found_for_missing_bug(monkeypatch) -> None:
    monkeypatch.setattr(bug_impact_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(bug_impact_list_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(bug_impact_list_command, "get_bug", lambda conn, bug_uuid: None)

    result = asyncio.run(
        bug_impact_list_command.BugImpactListCommand().execute(
            plan="p", bug_id=str(uuid.uuid4())
        )
    )
    _assert_domain_error(result, "BUG_NOT_FOUND")
