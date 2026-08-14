"""Command-layer regression suite for the group-3 anchoring-symmetry fix (bugs
2c568c0c/5c0ddc16): wish_reanchor, calendar_entry_reanchor, escalation_reanchor
and comment_reanchor.

(f) schema/validate_params coverage for all four commands: each exposes the
uniform new_anchor_type + new_anchor_* target-field shape
todo_reanchor_command.py documents, and validate_params UUID-checks the
identifier and every UUID-shaped new_anchor_* field.

(d) command-level anchor-confirmation wiring for wish/calendar_entry/
escalation (bug 5926d536 precedent: an unconfirmed project/file anchor falls
back to anchor_type "none"), monkeypatched exactly as
tests/test_anchor_confirmation_commands.py already does for todo_reanchor/
bug_reanchor -- no live database or CA server. comment_reanchor deliberately
does not wire confirm_anchor at all (see comment_reanchor_command.py's module
docstring); its own distinctive "none" rejection is exercised at the store
layer already (tests/test_group3_comment_reanchor_store.py) and, here, via a
command-level execute() smoke test.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest
from mcp_proxy_adapter.core.errors import InvalidParamsError, ValidationError

from plan_manager.commands import (
    calendar_entry_reanchor_command,
    comment_reanchor_command,
    escalation_reanchor_command,
    wish_reanchor_command,
)
from plan_manager.commands.anchor_confirmation import AnchorConfirmation


def _fake_db_ctx():
    @contextmanager
    def _cm():
        yield object()

    return _cm


class _FakeRecord:
    def __init__(self, payload):
        self._payload = payload

    def to_payload(self):
        return dict(self._payload)


def _confirm_anchor_stub(applicable, confirmed, reason):
    def _fake(app_cfg, *, requested_type, project_id, file_path):
        return AnchorConfirmation(applicable=applicable, confirmed=confirmed, reason=reason)

    return _fake


# ---------------------------------------------------------------------------
# (f) schema / validate_params, uniform across all four commands.
# ---------------------------------------------------------------------------

_COMMAND_CASES = [
    (wish_reanchor_command.WishReanchorCommand, "wish"),
    (calendar_entry_reanchor_command.CalendarEntryReanchorCommand, "calendar_entry"),
    (escalation_reanchor_command.EscalationReanchorCommand, "escalation_uuid"),
    (comment_reanchor_command.CommentReanchorCommand, "comment_uuid"),
]

_NEW_ANCHOR_FIELDS = (
    "new_anchor_type", "new_anchor_project_id", "new_anchor_file_path",
    "new_anchor_plan_uuid", "new_anchor_revision_uuid", "new_anchor_step_uuid",
    "new_anchor_step_path", "new_anchor_ref_id",
)


@pytest.mark.parametrize("command_cls,id_field", _COMMAND_CASES)
def test_schema_exposes_uniform_new_anchor_shape(command_cls, id_field):
    schema = command_cls.get_schema()
    properties = schema["properties"]
    for field in _NEW_ANCHOR_FIELDS:
        assert field in properties, f"{command_cls.__name__} schema missing {field}"
    assert id_field in properties
    assert set(schema["required"]) == {id_field, "changed_by", "new_anchor_type"}
    assert schema["additionalProperties"] is False


@pytest.mark.parametrize("command_cls,id_field", _COMMAND_CASES)
def test_metadata_builds_without_error_and_carries_reanchor_error_cases(command_cls, id_field):
    meta = command_cls.metadata()
    assert "FROZEN_TRUTH_WRITE" in meta["error_cases"]
    assert meta["parameters"][id_field]["required"] is True
    assert meta["parameters"]["new_anchor_type"]["required"] is True


@pytest.mark.parametrize("command_cls,id_field", _COMMAND_CASES)
def test_validate_params_rejects_malformed_identifier_uuid(command_cls, id_field):
    instance = command_cls()
    with pytest.raises(InvalidParamsError):
        instance.validate_params({id_field: "not-a-uuid", "changed_by": "alice", "new_anchor_type": "none"})


@pytest.mark.parametrize("command_cls,id_field", _COMMAND_CASES)
def test_validate_params_rejects_malformed_new_anchor_uuid_field(command_cls, id_field):
    instance = command_cls()
    with pytest.raises(InvalidParamsError):
        instance.validate_params({
            id_field: str(uuid.uuid4()),
            "changed_by": "alice",
            "new_anchor_type": "plan",
            "new_anchor_plan_uuid": "not-a-uuid",
        })


@pytest.mark.parametrize("command_cls,id_field", _COMMAND_CASES)
def test_validate_params_rejects_unknown_parameter(command_cls, id_field):
    instance = command_cls()
    with pytest.raises(ValidationError):
        instance.validate_params({
            id_field: str(uuid.uuid4()),
            "changed_by": "alice",
            "new_anchor_type": "none",
            "bogus_field": "x",
        })


# ---------------------------------------------------------------------------
# (d) unconfirmed project/file anchor falls back to anchor_type "none"
# (wish/calendar_entry/escalation; bug 5926d536 precedent).
# ---------------------------------------------------------------------------


def test_wish_reanchor_unconfirmed_falls_back_to_none(monkeypatch):
    captured = {}

    def fake_reanchor(conn, wish_uuid, *, changed_by, new_anchor, entity_type, get_entity, not_found_code):
        captured["new_anchor"] = new_anchor
        return _FakeRecord({"uuid": str(wish_uuid)})

    monkeypatch.setattr(wish_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(wish_reanchor_command, "app_config", lambda: None)
    monkeypatch.setattr(wish_reanchor_command, "reanchor_owner_form_entity", fake_reanchor)
    monkeypatch.setattr(
        wish_reanchor_command, "confirm_anchor", _confirm_anchor_stub(True, False, "not_found")
    )
    result = asyncio.run(
        wish_reanchor_command.WishReanchorCommand().execute(
            wish=str(uuid.uuid4()),
            changed_by="alice",
            new_anchor_type="project",
            new_anchor_project_id=str(uuid.uuid4()),
        )
    )
    data = result.to_dict()["data"]
    assert captured["new_anchor"].anchor_type == "none"
    assert data["anchor_confirmation"] == {"requested_type": "project", "confirmed": False, "reason": "not_found"}


def test_calendar_entry_reanchor_confirmed_moves_as_requested(monkeypatch):
    captured = {}
    project_id = str(uuid.uuid4())

    def fake_reanchor(conn, entry_uuid, *, changed_by, new_anchor, entity_type, get_entity, not_found_code):
        captured["new_anchor"] = new_anchor
        return _FakeRecord({"uuid": str(entry_uuid)})

    monkeypatch.setattr(calendar_entry_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(calendar_entry_reanchor_command, "app_config", lambda: None)
    monkeypatch.setattr(calendar_entry_reanchor_command, "reanchor_owner_form_entity", fake_reanchor)
    monkeypatch.setattr(
        calendar_entry_reanchor_command, "confirm_anchor", _confirm_anchor_stub(True, True, None)
    )
    result = asyncio.run(
        calendar_entry_reanchor_command.CalendarEntryReanchorCommand().execute(
            calendar_entry=str(uuid.uuid4()),
            changed_by="alice",
            new_anchor_type="project",
            new_anchor_project_id=project_id,
        )
    )
    data = result.to_dict()["data"]
    assert str(captured["new_anchor"].project_id) == project_id
    assert data["anchor_confirmation"]["confirmed"] is True


def test_escalation_reanchor_unconfirmed_falls_back_to_none_and_skips_completion_guard_when_not_found(monkeypatch):
    captured = {}

    def fake_reanchor(conn, escalation_uuid, *, changed_by, new_anchor, entity_type, get_entity, not_found_code):
        captured["new_anchor"] = new_anchor
        return _FakeRecord({"uuid": str(escalation_uuid)})

    monkeypatch.setattr(escalation_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(escalation_reanchor_command, "app_config", lambda: None)
    monkeypatch.setattr(escalation_reanchor_command, "get_escalation", lambda conn, u: None)
    monkeypatch.setattr(escalation_reanchor_command, "reanchor_owner_form_entity", fake_reanchor)
    monkeypatch.setattr(
        escalation_reanchor_command, "confirm_anchor", _confirm_anchor_stub(True, False, "ca_unreachable")
    )
    result = asyncio.run(
        escalation_reanchor_command.EscalationReanchorCommand().execute(
            escalation_uuid=str(uuid.uuid4()),
            changed_by="alice",
            new_anchor_type="file",
            new_anchor_project_id=str(uuid.uuid4()),
            new_anchor_file_path="src/x.py",
        )
    )
    data = result.to_dict()["data"]
    assert captured["new_anchor"].anchor_type == "none"
    assert data["anchor_confirmation"]["reason"] == "ca_unreachable"


# ---------------------------------------------------------------------------
# comment_reanchor: no confirm_anchor wiring; a plain pass-through smoke test.
# ---------------------------------------------------------------------------


def test_comment_reanchor_passes_requested_anchor_through_untouched(monkeypatch):
    captured = {}

    def fake_reanchor(conn, comment_uuid, *, changed_by, new_anchor):
        captured["new_anchor"] = new_anchor
        captured["changed_by"] = changed_by
        return _FakeRecord({"uuid": str(comment_uuid)})

    monkeypatch.setattr(comment_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(comment_reanchor_command, "get_comment", lambda conn, u: None)
    monkeypatch.setattr(comment_reanchor_command, "reanchor_comment", fake_reanchor)
    step_uuid = str(uuid.uuid4())
    plan_uuid = str(uuid.uuid4())
    result = asyncio.run(
        comment_reanchor_command.CommentReanchorCommand().execute(
            comment_uuid=str(uuid.uuid4()),
            changed_by="alice",
            new_anchor_type="step",
            new_anchor_plan_uuid=plan_uuid,
            new_anchor_step_uuid=step_uuid,
        )
    )
    assert "error" not in result.to_dict()
    assert captured["new_anchor"].anchor_type == "step"
    assert str(captured["new_anchor"].step_uuid) == step_uuid
    assert captured["changed_by"] == "alice"


def test_comment_reanchor_schema_excludes_none_from_description_and_documents_escalation():
    schema = comment_reanchor_command.CommentReanchorCommand.get_schema()
    description = schema["properties"]["new_anchor_type"]["description"]
    assert "'none' is not allowed" in description
    assert "escalation" in description
