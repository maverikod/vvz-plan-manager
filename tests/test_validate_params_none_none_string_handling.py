"""Regression tests for bug c72e047c-ad6b-4e02-825e-a0f6b8683149: todo_create
(and, generically, every plan_manager command) rejected a required string
parameter set to the literal value "none" as though it were missing.

Root cause: the vendored ``mcp_proxy_adapter.commands.base.Command
.validate_params`` deletes any parameter whose value is Python ``None`` OR a
string case-insensitively equal to "null"/"none"/"" -- BEFORE the required-
parameters check runs -- conflating a genuinely omitted/null parameter with
a legitimate literal string value. ``anchor_type="none"`` is a real,
documented member of ``plan_manager.domain.primary_anchor.PrimaryAnchorType``
(an explicitly unanchored TODO/bug), yet it was rejected identically to an
omitted/null/empty-string anchor_type.

Fix: ``plan_manager.commands.base_command.Command`` (the new shared base
every plan_manager command now subclasses instead of the adapter's Command
directly) only treats a true ``None``/absent key as missing; literal string
values -- including "none", "null", and "" in any case -- are preserved and
reach schema/domain validation untouched.

These tests cover:
  (a) the validate_params-level matrix for a required string param, using
      TodoCreateCommand's own schema (title is required and typed string) --
      "none"/"null"/"" survive, while a truly missing key or a JSON null
      still raise ValidationError with the standard "Missing required
      parameters" message.
  (b) the todo_create success path at the command layer for
      anchor_type="none": creates an unanchored TODO directly, with no CA
      confirmation call side effect distinguishable from the "none" skip and
      no anchor_confirmation diagnostic in the response (mirrors
      test_anchor_confirmation_commands.py's existing execute()-level
      coverage, but this file additionally proves the fix at the
      validate_params gate the old code never got past).
  (c) the domain-level PrimaryAnchor validator still rejects an empty-string
      anchor_type with a correct, non-misleading INVALID_ANCHOR-style error
      (not "missing required parameter") -- satisfying the bug's acceptance
      criterion that missing/null/"" anchor_type must still fail, just with
      an accurate error.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest

from mcp_proxy_adapter.core.errors import ValidationError

from plan_manager.commands import todo_create_command
from plan_manager.commands.anchor_confirmation import AnchorConfirmation
from plan_manager.commands.todo_create_command import TodoCreateCommand
from plan_manager.domain.primary_anchor import InvalidAnchorError, PrimaryAnchor, validate_anchor


def _base_todo_create_kwargs(**overrides: object) -> dict:
    kwargs: dict = dict(
        title="t",
        description="d",
        kind="task",
        priority_nice=0,
        created_by="alice",
        anchor_type="none",
    )
    kwargs.update(overrides)
    return kwargs


# --- (a) validate_params-level matrix for a required string param -----------------


def test_validate_params_preserves_literal_none_string_for_required_param() -> None:
    cmd = TodoCreateCommand()
    kwargs = _base_todo_create_kwargs(anchor_type="none")
    validated = cmd.validate_params(kwargs)
    assert validated["anchor_type"] == "none"


@pytest.mark.parametrize("literal", ["none", "None", "NONE", "null", "Null", "NULL", ""])
def test_validate_params_preserves_literal_sentinel_strings_case_insensitive(literal: str) -> None:
    cmd = TodoCreateCommand()
    kwargs = _base_todo_create_kwargs(anchor_type=literal)
    validated = cmd.validate_params(kwargs)
    assert "anchor_type" in validated
    assert validated["anchor_type"] == literal


def test_validate_params_still_rejects_missing_required_param() -> None:
    cmd = TodoCreateCommand()
    kwargs = _base_todo_create_kwargs()
    del kwargs["anchor_type"]
    with pytest.raises(ValidationError) as excinfo:
        cmd.validate_params(kwargs)
    assert "anchor_type" in str(excinfo.value)
    assert "Missing required parameters" in str(excinfo.value)


def test_validate_params_still_rejects_json_null_required_param() -> None:
    cmd = TodoCreateCommand()
    kwargs = _base_todo_create_kwargs(anchor_type=None)
    with pytest.raises(ValidationError) as excinfo:
        cmd.validate_params(kwargs)
    assert "anchor_type" in str(excinfo.value)
    assert "Missing required parameters" in str(excinfo.value)


def test_validate_params_missing_and_null_and_empty_are_not_conflated_with_none_literal() -> None:
    """The old bug made omitted/null/""/"none" byte-identical failures. Prove
    they now diverge: only the literal string "none" is accepted; the other
    three are still rejected (missing/null at the validate_params gate;
    "" later, at the domain layer -- see test_empty_string_anchor_type_*)."""
    cmd = TodoCreateCommand()

    # "none" -> accepted (survives validate_params)
    validated = cmd.validate_params(_base_todo_create_kwargs(anchor_type="none"))
    assert validated["anchor_type"] == "none"

    # missing -> ValidationError
    missing_kwargs = _base_todo_create_kwargs()
    del missing_kwargs["anchor_type"]
    with pytest.raises(ValidationError):
        cmd.validate_params(missing_kwargs)

    # null -> ValidationError
    with pytest.raises(ValidationError):
        cmd.validate_params(_base_todo_create_kwargs(anchor_type=None))


# --- (b) todo_create anchor_type="none" success path at the command layer ---------


def _fake_db_ctx():
    @contextmanager
    def _cm():
        yield object()

    return _cm


class _FakeRecord:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def to_payload(self) -> dict:
        return dict(self._payload)


def test_todo_create_anchor_type_none_end_to_end_creates_unanchored_todo_no_ca_no_fallback(
    monkeypatch,
) -> None:
    captured: dict = {}
    confirm_calls = {"n": 0}

    def fake_create_todo(conn, **kwargs):
        captured["anchor"] = kwargs["anchor"]
        return _FakeRecord({"uuid": "todo-none-1"})

    def fake_confirm_anchor(app_cfg, *, requested_type, project_id, file_path):
        confirm_calls["n"] += 1
        return AnchorConfirmation(applicable=False, confirmed=True, reason=None)

    monkeypatch.setattr(todo_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_create_command, "app_config", lambda: None)
    monkeypatch.setattr(todo_create_command, "create_todo", fake_create_todo)
    monkeypatch.setattr(todo_create_command, "confirm_anchor", fake_confirm_anchor)

    cmd = TodoCreateCommand()
    raw_kwargs = _base_todo_create_kwargs(anchor_type="none")

    # This is the exact path the old bug never reached: validate_params used
    # to raise "Missing required parameters: anchor_type" right here.
    validated = cmd.validate_params(raw_kwargs)
    result = asyncio.run(cmd.execute(**validated))
    data = result.to_dict()["data"]

    assert captured["anchor"].anchor_type == "none"
    assert captured["anchor"].project_id is None
    assert captured["anchor"].file_path is None
    assert confirm_calls["n"] == 1
    assert "anchor_confirmation" not in data


# --- (c) missing/null/"" anchor_type still fail, with a correct error -------------


def test_empty_string_anchor_type_survives_validate_params_but_domain_layer_rejects_it() -> None:
    cmd = TodoCreateCommand()
    validated = cmd.validate_params(_base_todo_create_kwargs(anchor_type=""))
    # Preserved untouched through validate_params (per the fix contract) --
    # NOT silently dropped/treated as missing.
    assert validated["anchor_type"] == ""

    # The domain validator is the one that must reject it, with a specific,
    # non-misleading error (never "missing required parameter").
    anchor = PrimaryAnchor(anchor_type="")
    with pytest.raises(InvalidAnchorError) as excinfo:
        validate_anchor(None, anchor)
    assert "missing" not in str(excinfo.value).lower()
    assert "unknown anchor type" in str(excinfo.value)


def test_none_anchor_type_domain_validator_accepts_it_directly() -> None:
    """Sanity check that the domain layer's own acceptance of anchor_type="none"
    (all identifier fields null) is untouched by this fix -- the bug was
    purely in the transport-level validate_params gate."""
    anchor = PrimaryAnchor(anchor_type="none")
    validate_anchor(None, anchor)  # must not raise
