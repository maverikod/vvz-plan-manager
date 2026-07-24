"""Regression tests for bug 0d8755bd-066d-4d42-a3d2-f71389c190df, Class 2, group A.

Same root cause as Class 1 (see test_bug_0d8755bd_class1_validate_params.py):
a bare ``uuid.UUID(x)`` call on an untrusted client-supplied string, executed
directly inside a Command's ``execute()`` with no prior ``validate_params``
check, raises a plain ``ValueError`` that ``plan_manager.commands.errors.
map_exception`` does not recognize (it re-raises unknown exceptions), which
then falls through ``mcp_proxy_adapter.commands.base.Command.run``'s generic
``except Exception`` branch and surfaces as a raw JSON-RPC -32603 "Unexpected
error executing command ..." instead of a clean -32602 invalid-params
``ErrorResult``.

Group A covers the 12 todo/comment command files (excluding todo_delete and
comment_delete, which carry their own Class 1 fix and coverage) where every
ID-shaped string parameter is now pre-validated in a ``validate_params``
override using the established idiom: catch ``ValueError`` from
``uuid.UUID(...)`` and re-raise ``InvalidParamsError`` (imported from
``mcp_proxy_adapter.core.errors``). ``map_exception`` itself is untouched --
adding a ValueError branch there would mask genuine internal errors (L1
decision).

This module drives the real adapter dispatch path (``Command.run``, the same
classmethod the JSON-RPC handler calls) for the negative (malformed-UUID)
cases -- exactly like the Class 1 sibling module -- because calling
``execute()`` directly bypasses ``validate_params`` entirely and never
touches ``run()``'s error-mapping branches, which is precisely why these
defects went undetected. The positive cases additionally drive ``Command.run``
with well-formed params against a monkeypatched db_connection/storage layer
(mirroring this repo's established fake-conn unit-test style, e.g.
tests/test_validate_params_none_none_string_handling.py) to prove the new
validate_params guard does not reject legitimate calls.

Two candidates from the original heuristic list were investigated and found
to be FALSE POSITIVES (not covered by this module because there is nothing to
fix): todo_list_command.py and comment_list_command.py. Their ID-shaped
filter params (project, revision, step, and -- for comment_list -- anchor_plan)
are already validated as UUID-format strings by
plan_manager.commands.runtime_filtering.parse_filters (format=="uuid" check
against FILTER_FIELDS) BEFORE either command's execute() reaches its own
uuid.UUID(...)/validate_uuid(...) calls on those same values; parse_filters
raises a typed DomainCommandError("INVALID_FILTER", ...) for a malformed
value, which map_exception maps to a domain_error (-32000), never reaching
the raw ValueError path. Their `plan`/`anchor_plan` parameters accept a plan
name OR a UUID (resolved via resolve_plan) and must not be forced to UUID
per this bug's own scope note.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

import pytest
from mcp_proxy_adapter.commands import command_registry as command_registry_module
from mcp_proxy_adapter.commands.command_registry import CommandRegistry
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands import (
    comment_add_command,
    comment_get_command,
    comment_resolve_command,
    comment_supersede_command,
    todo_close_command,
    todo_create_command,
    todo_link_add_command,
    todo_link_remove_command,
    todo_promote_to_cascade_request_command,
    todo_reanchor_command,
    todo_resolve_command,
    todo_update_command,
)
from plan_manager.commands.comment_add_command import CommentAddCommand
from plan_manager.commands.comment_get_command import CommentGetCommand
from plan_manager.commands.comment_resolve_command import CommentResolveCommand
from plan_manager.commands.comment_supersede_command import CommentSupersedeCommand
from plan_manager.commands.todo_close_command import TodoCloseCommand
from plan_manager.commands.todo_create_command import TodoCreateCommand
from plan_manager.commands.todo_link_add_command import TodoLinkAddCommand
from plan_manager.commands.todo_link_remove_command import TodoLinkRemoveCommand
from plan_manager.commands.todo_promote_to_cascade_request_command import (
    TodoPromoteToCascadeRequestCommand,
)
from plan_manager.commands.todo_reanchor_command import TodoReanchorCommand
from plan_manager.commands.todo_resolve_command import TodoResolveCommand
from plan_manager.commands.todo_update_command import TodoUpdateCommand


VALID_UUID_1 = "11111111-1111-1111-1111-111111111111"
VALID_UUID_2 = "22222222-2222-2222-2222-222222222222"
BAD_UUID = "not-a-uuid"


@pytest.fixture()
def register_command(monkeypatch):
    """Provide a helper that swaps in a throwaway registry holding one command.

    Mirrors tests/test_bug_0d8755bd_class1_validate_params.py's fixture of the
    same name: ``Command.run`` re-imports ``registry`` from
    ``mcp_proxy_adapter.commands.command_registry`` on every call (a local
    import inside the method body), so patching the module attribute here is
    picked up live without touching the real process-wide singleton.
    """

    def _register(command_cls: type) -> CommandRegistry:
        registry = CommandRegistry()
        registry.register(command_cls, "custom")
        monkeypatch.setattr(command_registry_module, "registry", registry)
        return registry

    return _register


def _assert_typed_invalid_params(payload: dict, expected_message_fragment: str) -> None:
    """Assert a ``Command.run`` result payload is a clean typed -32602 error.

    Raises:
        AssertionError: If the payload does not match the expected typed
            -32602 shape, or the bug's raw -32603 symptom is still present.
    """
    assert payload["success"] is False
    error = payload["error"]
    assert error["code"] == InvalidParamsError().code == -32602
    assert "Unexpected error" not in error["message"]
    assert expected_message_fragment in error["message"]
    assert "original_error" not in payload["error"].get("data", {})


def _fake_db_ctx():
    @contextmanager
    def _cm():
        yield object()

    return _cm


class _FakeRecord:
    """Minimal stand-in for a domain record: carries arbitrary attributes
    plus a to_payload() the way every real *Record/domain dataclass does."""

    def __init__(self, payload: dict | None = None, **extra: object) -> None:
        self._payload = payload if payload is not None else {}
        for key, value in extra.items():
            setattr(self, key, value)

    def to_payload(self) -> dict:
        return dict(self._payload)


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# Negative cases: malformed UUID -> typed -32602, not raw -32603
# ===========================================================================


# --- todo_close -------------------------------------------------------------


def test_todo_close_bad_todo_uuid_is_typed_invalid_params(register_command) -> None:
    register_command(TodoCloseCommand)
    result = _run(TodoCloseCommand.run(todo=BAD_UUID, changed_by="tester"))
    _assert_typed_invalid_params(result.to_dict(), "todo is not a valid UUID")


# --- todo_create --------------------------------------------------------------


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


@pytest.mark.parametrize(
    "field",
    ["anchor_project_id", "anchor_plan_uuid", "anchor_revision_uuid", "anchor_step_uuid", "anchor_ref_id"],
)
def test_todo_create_bad_anchor_uuid_field_is_typed_invalid_params(register_command, field) -> None:
    register_command(TodoCreateCommand)
    result = _run(TodoCreateCommand.run(**_base_todo_create_kwargs(**{field: BAD_UUID})))
    _assert_typed_invalid_params(result.to_dict(), f"{field} is not a valid UUID")


# --- todo_link_add ------------------------------------------------------------


@pytest.mark.parametrize("field", ["from_todo", "to_todo"])
def test_todo_link_add_bad_uuid_field_is_typed_invalid_params(register_command, field) -> None:
    register_command(TodoLinkAddCommand)
    kwargs = dict(from_todo=VALID_UUID_1, to_todo=VALID_UUID_2, link_type="relates_to", created_by="tester")
    kwargs[field] = BAD_UUID
    result = _run(TodoLinkAddCommand.run(**kwargs))
    _assert_typed_invalid_params(result.to_dict(), f"{field} is not a valid UUID")


# --- todo_link_remove ----------------------------------------------------------


def test_todo_link_remove_bad_link_uuid_is_typed_invalid_params(register_command) -> None:
    register_command(TodoLinkRemoveCommand)
    result = _run(TodoLinkRemoveCommand.run(link=BAD_UUID, changed_by="tester"))
    _assert_typed_invalid_params(result.to_dict(), "link is not a valid UUID")


# --- todo_promote_to_cascade_request -------------------------------------------


@pytest.mark.parametrize("field", ["todo", "revision"])
def test_todo_promote_to_cascade_request_bad_uuid_field_is_typed_invalid_params(
    register_command, field
) -> None:
    register_command(TodoPromoteToCascadeRequestCommand)
    kwargs = dict(
        plan="some-plan",
        todo=VALID_UUID_1,
        target_artifact="TS",
        reason="because",
        created_by="tester",
        revision=VALID_UUID_2,
    )
    kwargs[field] = BAD_UUID
    result = _run(TodoPromoteToCascadeRequestCommand.run(**kwargs))
    _assert_typed_invalid_params(result.to_dict(), f"{field} is not a valid UUID")


# --- todo_reanchor --------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "todo",
        "new_anchor_project_id",
        "new_anchor_plan_uuid",
        "new_anchor_revision_uuid",
        "new_anchor_step_uuid",
        "new_anchor_ref_id",
    ],
)
def test_todo_reanchor_bad_uuid_field_is_typed_invalid_params(register_command, field) -> None:
    register_command(TodoReanchorCommand)
    kwargs = dict(todo=VALID_UUID_1, changed_by="tester", new_anchor_type="none")
    kwargs[field] = BAD_UUID
    result = _run(TodoReanchorCommand.run(**kwargs))
    _assert_typed_invalid_params(result.to_dict(), f"{field} is not a valid UUID")


# --- todo_resolve ----------------------------------------------------------------


def test_todo_resolve_bad_todo_uuid_is_typed_invalid_params(register_command) -> None:
    register_command(TodoResolveCommand)
    result = _run(TodoResolveCommand.run(todo=BAD_UUID, changed_by="tester"))
    _assert_typed_invalid_params(result.to_dict(), "todo is not a valid UUID")


# --- todo_update -----------------------------------------------------------------


def test_todo_update_bad_todo_uuid_is_typed_invalid_params(register_command) -> None:
    register_command(TodoUpdateCommand)
    result = _run(TodoUpdateCommand.run(todo=BAD_UUID, changed_by="tester", priority_nice=1))
    _assert_typed_invalid_params(result.to_dict(), "todo is not a valid UUID")


# --- comment_add -------------------------------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "anchor_project_id",
        "anchor_plan_uuid",
        "anchor_revision_uuid",
        "anchor_step_uuid",
        "anchor_ref_id",
        "supersedes_comment_uuid",
    ],
)
def test_comment_add_bad_uuid_field_is_typed_invalid_params(register_command, field) -> None:
    register_command(CommentAddCommand)
    kwargs = dict(
        plan="some-plan",
        anchor_type="step",
        kind="comment",
        visibility="audit_only",
        author="alice",
        body="body text",
        created_by="alice",
    )
    kwargs[field] = BAD_UUID
    result = _run(CommentAddCommand.run(**kwargs))
    _assert_typed_invalid_params(result.to_dict(), f"{field} is not a valid UUID")


# --- comment_get -------------------------------------------------------------------


def test_comment_get_bad_comment_uuid_is_typed_invalid_params(register_command) -> None:
    register_command(CommentGetCommand)
    result = _run(CommentGetCommand.run(plan="some-plan", comment_uuid=BAD_UUID))
    _assert_typed_invalid_params(result.to_dict(), "comment_uuid is not a valid UUID")


# --- comment_resolve ---------------------------------------------------------------


def test_comment_resolve_bad_comment_uuid_is_typed_invalid_params(register_command) -> None:
    register_command(CommentResolveCommand)
    result = _run(CommentResolveCommand.run(plan="some-plan", comment_uuid=BAD_UUID, changed_by="tester"))
    _assert_typed_invalid_params(result.to_dict(), "comment_uuid is not a valid UUID")


# --- comment_supersede ---------------------------------------------------------------


def test_comment_supersede_bad_comment_uuid_is_typed_invalid_params(register_command) -> None:
    register_command(CommentSupersedeCommand)
    result = _run(
        CommentSupersedeCommand.run(
            plan="some-plan", comment_uuid=BAD_UUID, body="new body", changed_by="tester"
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "comment_uuid is not a valid UUID")


# ===========================================================================
# Positive cases: one per command family -- valid params still work.
# ===========================================================================


def test_todo_close_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(TodoCloseCommand)
    monkeypatch.setattr(todo_close_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_close_command, "get_todo", lambda conn, todo_uuid: _FakeRecord())
    monkeypatch.setattr(todo_close_command, "refuse_if_todo_plan_completed", lambda conn, todo: None)
    monkeypatch.setattr(
        todo_close_command, "close_todo",
        lambda conn, todo_uuid, changed_by: _FakeRecord({"uuid": str(todo_uuid), "status": "closed"}),
    )
    result = _run(TodoCloseCommand.run(todo=VALID_UUID_1, changed_by="tester"))
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["status"] == "closed"


def test_todo_create_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(TodoCreateCommand)
    captured: dict = {}

    def fake_create_todo(conn, **kwargs):
        captured["anchor"] = kwargs["anchor"]
        return _FakeRecord({"uuid": "todo-1"})

    monkeypatch.setattr(todo_create_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_create_command, "app_config", lambda: None)
    monkeypatch.setattr(todo_create_command, "create_todo", fake_create_todo)
    result = _run(TodoCreateCommand.run(**_base_todo_create_kwargs(anchor_type="none")))
    payload = result.to_dict()
    assert payload["success"] is True
    assert captured["anchor"].anchor_type == "none"


def test_todo_link_add_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(TodoLinkAddCommand)
    monkeypatch.setattr(todo_link_add_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_link_add_command, "get_todo", lambda conn, todo_uuid: None)
    monkeypatch.setattr(
        todo_link_add_command, "create_todo_link",
        lambda conn, **kwargs: _FakeRecord({"uuid": "link-1", "link_type": kwargs["link_type"]}),
    )
    result = _run(
        TodoLinkAddCommand.run(
            from_todo=VALID_UUID_1, to_todo=VALID_UUID_2, link_type="relates_to", created_by="tester"
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["link_type"] == "relates_to"


def test_todo_link_remove_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(TodoLinkRemoveCommand)
    existing = _FakeRecord(from_todo_uuid=uuid.UUID(VALID_UUID_1), to_todo_uuid=uuid.UUID(VALID_UUID_2))
    monkeypatch.setattr(todo_link_remove_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_link_remove_command, "get_todo_link", lambda conn, link_uuid: existing)
    monkeypatch.setattr(todo_link_remove_command, "get_todo", lambda conn, todo_uuid: None)
    monkeypatch.setattr(
        todo_link_remove_command, "remove_todo_link",
        lambda conn, link_uuid, changed_by: _FakeRecord({"uuid": str(link_uuid), "deleted": True}),
    )
    result = _run(TodoLinkRemoveCommand.run(link=VALID_UUID_1, changed_by="tester"))
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["deleted"] is True


def test_todo_promote_to_cascade_request_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(TodoPromoteToCascadeRequestCommand)
    monkeypatch.setattr(todo_promote_to_cascade_request_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(
        todo_promote_to_cascade_request_command, "resolve_plan",
        lambda conn, plan: _FakeRecord(uuid=uuid.uuid4()),
    )
    monkeypatch.setattr(
        todo_promote_to_cascade_request_command, "get_todo", lambda conn, todo_uuid: _FakeRecord()
    )
    monkeypatch.setattr(
        todo_promote_to_cascade_request_command, "refuse_if_todo_plan_completed", lambda conn, todo: None
    )
    monkeypatch.setattr(
        todo_promote_to_cascade_request_command, "create_cascade_request",
        lambda conn, **kwargs: _FakeRecord({"uuid": "cascade-req-1", "target_artifact": kwargs["target_artifact"]}),
    )
    result = _run(
        TodoPromoteToCascadeRequestCommand.run(
            plan="some-plan", todo=VALID_UUID_1, target_artifact="TS", reason="because", created_by="tester"
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["target_artifact"] == "TS"


def test_todo_reanchor_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(TodoReanchorCommand)
    monkeypatch.setattr(todo_reanchor_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_reanchor_command, "get_todo", lambda conn, todo_uuid: None)
    monkeypatch.setattr(
        todo_reanchor_command, "reanchor_todo",
        lambda conn, todo_uuid, changed_by, new_anchor: _FakeRecord(
            {"uuid": str(todo_uuid), "primary_anchor_type": new_anchor.anchor_type}
        ),
    )
    result = _run(TodoReanchorCommand.run(todo=VALID_UUID_1, changed_by="tester", new_anchor_type="none"))
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["primary_anchor_type"] == "none"


def test_todo_resolve_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(TodoResolveCommand)
    monkeypatch.setattr(todo_resolve_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_resolve_command, "get_todo", lambda conn, todo_uuid: _FakeRecord())
    monkeypatch.setattr(todo_resolve_command, "refuse_if_todo_plan_completed", lambda conn, todo: None)
    monkeypatch.setattr(
        todo_resolve_command, "resolve_todo",
        lambda conn, todo_uuid, changed_by: _FakeRecord({"uuid": str(todo_uuid), "status": "resolved"}),
    )
    result = _run(TodoResolveCommand.run(todo=VALID_UUID_1, changed_by="tester"))
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["status"] == "resolved"


def test_todo_update_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(TodoUpdateCommand)
    monkeypatch.setattr(todo_update_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(todo_update_command, "get_todo", lambda conn, todo_uuid: _FakeRecord())
    monkeypatch.setattr(todo_update_command, "refuse_if_todo_plan_completed", lambda conn, todo: None)
    monkeypatch.setattr(
        todo_update_command, "update_todo",
        lambda conn, todo_uuid, **kwargs: _FakeRecord({"uuid": str(todo_uuid), "priority_nice": kwargs["priority_nice"]}),
    )
    result = _run(TodoUpdateCommand.run(todo=VALID_UUID_1, changed_by="tester", priority_nice=-5))
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["priority_nice"] == -5


def test_comment_add_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(CommentAddCommand)
    monkeypatch.setattr(comment_add_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(
        comment_add_command, "resolve_plan", lambda conn, plan: _FakeRecord(uuid=uuid.uuid4())
    )
    monkeypatch.setattr(comment_add_command, "validate_comment_anchor_type", lambda anchor_type: None)
    monkeypatch.setattr(
        comment_add_command, "add_comment",
        lambda conn, **kwargs: _FakeRecord({"uuid": "comment-1", "kind": kwargs["kind"]}),
    )
    result = _run(
        CommentAddCommand.run(
            plan="some-plan",
            anchor_type="step",
            kind="comment",
            visibility="audit_only",
            author="alice",
            body="body text",
            created_by="alice",
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["kind"] == "comment"


def test_comment_get_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(CommentGetCommand)
    monkeypatch.setattr(comment_get_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(comment_get_command, "resolve_plan", lambda conn, plan: _FakeRecord(uuid=uuid.uuid4()))
    monkeypatch.setattr(
        comment_get_command, "get_comment",
        lambda conn, comment_uuid: _FakeRecord({"uuid": str(comment_uuid), "body": "hi"}),
    )
    result = _run(CommentGetCommand.run(plan="some-plan", comment_uuid=VALID_UUID_1))
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["body"] == "hi"


def test_comment_resolve_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(CommentResolveCommand)
    monkeypatch.setattr(comment_resolve_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(
        comment_resolve_command, "resolve_plan", lambda conn, plan: _FakeRecord(uuid=uuid.uuid4())
    )
    monkeypatch.setattr(
        comment_resolve_command, "get_comment",
        lambda conn, comment_uuid: _FakeRecord(anchor_plan_uuid=None),
    )
    monkeypatch.setattr(
        comment_resolve_command, "refuse_if_comment_plan_completed", lambda conn, comment: None
    )
    monkeypatch.setattr(
        comment_resolve_command, "resolve_comment",
        lambda conn, comment_uuid, changed_by: _FakeRecord({"uuid": str(comment_uuid), "resolved": True}),
    )
    result = _run(CommentResolveCommand.run(plan="some-plan", comment_uuid=VALID_UUID_1, changed_by="tester"))
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["resolved"] is True


def test_comment_supersede_valid_params_still_succeeds(register_command, monkeypatch) -> None:
    register_command(CommentSupersedeCommand)
    monkeypatch.setattr(comment_supersede_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(
        comment_supersede_command, "resolve_plan", lambda conn, plan: _FakeRecord(uuid=uuid.uuid4())
    )
    monkeypatch.setattr(
        comment_supersede_command, "get_comment",
        lambda conn, comment_uuid: _FakeRecord(anchor_plan_uuid=None),
    )
    monkeypatch.setattr(
        comment_supersede_command, "refuse_if_comment_plan_completed", lambda conn, comment: None
    )
    monkeypatch.setattr(
        comment_supersede_command, "supersede_comment",
        lambda conn, comment_uuid, new_body, changed_by: _FakeRecord({"uuid": "comment-2", "body": new_body}),
    )
    result = _run(
        CommentSupersedeCommand.run(
            plan="some-plan", comment_uuid=VALID_UUID_1, body="corrected", changed_by="tester"
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["body"] == "corrected"
