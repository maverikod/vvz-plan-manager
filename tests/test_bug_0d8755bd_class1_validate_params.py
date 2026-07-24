"""Regression tests for bug 0d8755bd-066d-4d42-a3d2-f71389c190df, Class 1.

A bare ``raise ValueError(...)`` (from ``uuid.UUID(x)`` on a malformed
string) inside a Command's ``validate_params`` override is invisible to the
adapter's typed-error mapping in ``mcp_proxy_adapter.commands.base.Command.run``:
that classmethod only special-cases ``ValidationError`` / ``InvalidParamsError``
/ ``NotFoundError`` / ``TimeoutError`` / ``CommandError``; anything else falls
through to the generic ``except Exception`` branch and surfaces as a raw
JSON-RPC -32603 "Unexpected error executing command ..." instead of a clean
-32602 invalid-params ``ErrorResult``.

Class 1 covers the 18 command files (plus the 19 already fixed and covered by
``test_validate_params_typed_error_mapping.py``) where ``validate_params``
called ``uuid.UUID(...)`` directly on an untrusted string without catching
``ValueError`` and re-raising as ``InvalidParamsError`` (imported from
``mcp_proxy_adapter.core.errors``). This module drives the real adapter
dispatch path (``Command.run``, the same classmethod the JSON-RPC handler
calls), not ``execute()`` directly, exactly like the sibling module for the
already-fixed files: calling ``execute()`` bypasses ``validate_params``
entirely and never touches ``run()``'s error mapping, which is precisely why
these defects went undetected.
"""
from __future__ import annotations

import asyncio

import pytest
from mcp_proxy_adapter.commands import command_registry as command_registry_module
from mcp_proxy_adapter.commands.command_registry import CommandRegistry
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.comment_delete_command import CommentDeleteCommand
from plan_manager.commands.concept_add_command import ConceptAddCommand
from plan_manager.commands.concept_remove_command import ConceptRemoveCommand
from plan_manager.commands.plan_export_command import PlanExportCommand
from plan_manager.commands.relation_add_command import RelationAddCommand
from plan_manager.commands.relation_remove_command import RelationRemoveCommand
from plan_manager.commands.relation_update_command import RelationUpdateCommand
from plan_manager.commands.runtime_link_add_command import RuntimeLinkAddCommand
from plan_manager.commands.runtime_link_remove_command import RuntimeLinkRemoveCommand
from plan_manager.commands.step_delete_command import StepDeleteCommand
from plan_manager.commands.step_dependency_add_command import StepDependencyAddCommand
from plan_manager.commands.step_dependency_apply_command import StepDependencyApplyCommand
from plan_manager.commands.step_dependency_clear_command import StepDependencyClearCommand
from plan_manager.commands.step_dependency_remove_command import StepDependencyRemoveCommand
from plan_manager.commands.step_dependency_set_command import StepDependencySetCommand
from plan_manager.commands.step_move_command import StepMoveCommand
from plan_manager.commands.step_set_status_command import StepSetStatusCommand
from plan_manager.commands.todo_delete_command import TodoDeleteCommand


@pytest.fixture()
def register_command(monkeypatch):
    """Provide a helper that swaps in a throwaway registry holding one command.

    ``Command.run`` re-imports ``registry`` from
    ``mcp_proxy_adapter.commands.command_registry`` on every call (a local
    import inside the method body), so patching the module attribute here is
    picked up live without touching the real process-wide singleton that
    other tests / the running server may depend on.

    Returns:
        A callable ``(command_cls) -> CommandRegistry`` that registers
        ``command_cls`` under its own ``name`` in a fresh registry and
        installs that registry as the adapter-visible one for the duration
        of the test.
    """

    def _register(command_cls: type) -> CommandRegistry:
        """Register ``command_cls`` in a fresh throwaway ``CommandRegistry``.

        Args:
            command_cls: The Command subclass under test.

        Returns:
            The fresh registry the command was registered into.
        """
        registry = CommandRegistry()
        registry.register(command_cls, "custom")
        monkeypatch.setattr(command_registry_module, "registry", registry)
        return registry

    return _register


def _assert_typed_invalid_params(payload: dict, expected_message_fragment: str) -> None:
    """Assert a ``Command.run`` result payload is a clean typed -32602 error.

    Args:
        payload: The ``.to_dict()`` output of the ``CommandResult`` returned
            by ``Command.run``.
        expected_message_fragment: A substring that must appear in the
            error message (the field-specific complaint from the fixed
            ``except ValueError as exc: raise InvalidParamsError(...)``
            idiom).

    Raises:
        AssertionError: If the payload does not match the expected typed
            -32602 shape, or the bug's raw -32603 symptom is still present.
    """
    assert payload["success"] is False
    error = payload["error"]
    assert error["code"] == InvalidParamsError().code == -32602
    assert "Unexpected error" not in error["message"]
    assert expected_message_fragment in error["message"]
    # The bug's symptom: the original ValueError text demoted to a details
    # blob instead of being the actual typed error message.
    assert "original_error" not in payload["error"].get("data", {})


def test_comment_delete_bad_comment_uuid_is_typed_invalid_params(register_command) -> None:
    """comment_delete: a malformed 'comment' UUID must map to a clean -32602."""
    register_command(CommentDeleteCommand)
    result = asyncio.run(CommentDeleteCommand.run(comment="not-a-uuid", changed_by="tester"))
    _assert_typed_invalid_params(result.to_dict(), "comment is not a valid UUID")


def test_concept_add_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """concept_add: a malformed 'cascade_uuid' must map to a clean -32602."""
    register_command(ConceptAddCommand)
    result = asyncio.run(
        ConceptAddCommand.run(
            plan="some-plan",
            cascade_uuid="not-a-uuid",
            concept_id="C-001",
            name="Concept",
            definition="A definition.",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_concept_remove_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """concept_remove: a malformed 'cascade_uuid' must map to a clean -32602."""
    register_command(ConceptRemoveCommand)
    result = asyncio.run(
        ConceptRemoveCommand.run(plan="some-plan", cascade_uuid="not-a-uuid", concept_id="C-001")
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_plan_export_bad_revision_uuid_is_typed_invalid_params(register_command) -> None:
    """plan_export: a malformed optional 'revision' must map to a clean -32602."""
    register_command(PlanExportCommand)
    result = asyncio.run(PlanExportCommand.run(plan="some-plan", revision="not-a-uuid"))
    _assert_typed_invalid_params(result.to_dict(), "revision is not a valid UUID")


def test_relation_add_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """relation_add: a malformed 'cascade_uuid' must map to a clean -32602."""
    register_command(RelationAddCommand)
    result = asyncio.run(
        RelationAddCommand.run(
            plan="some-plan",
            cascade_uuid="not-a-uuid",
            from_concept="C-001",
            to_concept="C-002",
            type="uses",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_relation_remove_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """relation_remove: a malformed 'cascade_uuid' must map to a clean -32602."""
    register_command(RelationRemoveCommand)
    result = asyncio.run(
        RelationRemoveCommand.run(
            plan="some-plan",
            cascade_uuid="not-a-uuid",
            from_concept="C-001",
            to_concept="C-002",
            type="uses",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_relation_update_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """relation_update: a malformed 'cascade_uuid' must map to a clean -32602."""
    register_command(RelationUpdateCommand)
    result = asyncio.run(
        RelationUpdateCommand.run(
            plan="some-plan",
            cascade_uuid="not-a-uuid",
            from_concept="C-001",
            to_concept="C-002",
            type="uses",
            new_type="depends_on",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_runtime_link_add_bad_from_entity_uuid_is_typed_invalid_params(register_command) -> None:
    """runtime_link_add: a malformed 'from_entity_uuid' must map to a clean -32602."""
    register_command(RuntimeLinkAddCommand)
    result = asyncio.run(
        RuntimeLinkAddCommand.run(
            from_entity_type="bug",
            from_entity_uuid="not-a-uuid",
            to_entity_type="todo",
            to_entity_uuid="12345678-1234-1234-1234-123456789012",
            link_type="relates_to",
            created_by="tester",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "from_entity_uuid is not a valid UUID")


def test_runtime_link_add_bad_to_entity_uuid_is_typed_invalid_params(register_command) -> None:
    """runtime_link_add: a malformed 'to_entity_uuid' must map to a clean -32602."""
    register_command(RuntimeLinkAddCommand)
    result = asyncio.run(
        RuntimeLinkAddCommand.run(
            from_entity_type="bug",
            from_entity_uuid="12345678-1234-1234-1234-123456789012",
            to_entity_type="todo",
            to_entity_uuid="not-a-uuid",
            link_type="relates_to",
            created_by="tester",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "to_entity_uuid is not a valid UUID")


def test_runtime_link_add_same_endpoint_is_typed_invalid_params(register_command) -> None:
    """runtime_link_add: identical source/target endpoints must map to a clean -32602.

    This is the second half of the file's fix: a direct
    ``raise RuntimeValidationError(...)`` for the "same record on both ends"
    semantic check also escaped untyped as a raw -32603. It is now raised as
    ``InvalidParamsError``, consistent with the ``plan_validate`` precedent
    for semantic checks performed inside ``validate_params``.
    """
    register_command(RuntimeLinkAddCommand)
    same_uuid = "12345678-1234-1234-1234-123456789012"
    result = asyncio.run(
        RuntimeLinkAddCommand.run(
            from_entity_type="bug",
            from_entity_uuid=same_uuid,
            to_entity_type="bug",
            to_entity_uuid=same_uuid,
            link_type="relates_to",
            created_by="tester",
        )
    )
    _assert_typed_invalid_params(
        result.to_dict(), "may not reference the same record as both source and target"
    )


def test_runtime_link_remove_bad_link_uuid_is_typed_invalid_params(register_command) -> None:
    """runtime_link_remove: a malformed 'link' UUID must map to a clean -32602."""
    register_command(RuntimeLinkRemoveCommand)
    result = asyncio.run(RuntimeLinkRemoveCommand.run(link="not-a-uuid", changed_by="tester"))
    _assert_typed_invalid_params(result.to_dict(), "link is not a valid UUID")


def test_step_delete_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """step_delete: a malformed optional 'cascade_uuid' must map to a clean -32602."""
    register_command(StepDeleteCommand)
    result = asyncio.run(
        StepDeleteCommand.run(plan="some-plan", step_id="G-001", cascade_uuid="not-a-uuid")
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_step_dependency_add_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """step_dependency_add: a malformed optional 'cascade_uuid' must map to a clean -32602."""
    register_command(StepDependencyAddCommand)
    result = asyncio.run(
        StepDependencyAddCommand.run(
            plan="some-plan",
            step_id="G-001",
            depends_on="G-002",
            cascade_uuid="not-a-uuid",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_step_dependency_apply_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """step_dependency_apply: a malformed optional 'cascade_uuid' must map to a clean -32602."""
    register_command(StepDependencyApplyCommand)
    result = asyncio.run(
        StepDependencyApplyCommand.run(
            plan="some-plan",
            changes=[{"op": "clear", "step_id": "G-001"}],
            cascade_uuid="not-a-uuid",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_step_dependency_clear_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """step_dependency_clear: a malformed optional 'cascade_uuid' must map to a clean -32602."""
    register_command(StepDependencyClearCommand)
    result = asyncio.run(
        StepDependencyClearCommand.run(plan="some-plan", step_id="G-001", cascade_uuid="not-a-uuid")
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_step_dependency_remove_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """step_dependency_remove: a malformed optional 'cascade_uuid' must map to a clean -32602."""
    register_command(StepDependencyRemoveCommand)
    result = asyncio.run(
        StepDependencyRemoveCommand.run(
            plan="some-plan",
            step_id="G-001",
            depends_on="G-002",
            cascade_uuid="not-a-uuid",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_step_dependency_set_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """step_dependency_set: a malformed optional 'cascade_uuid' must map to a clean -32602."""
    register_command(StepDependencySetCommand)
    result = asyncio.run(
        StepDependencySetCommand.run(
            plan="some-plan",
            step_id="G-001",
            depends_on=["G-002"],
            cascade_uuid="not-a-uuid",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_step_move_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """step_move: a malformed optional 'cascade_uuid' must map to a clean -32602."""
    register_command(StepMoveCommand)
    result = asyncio.run(
        StepMoveCommand.run(
            plan="some-plan",
            step_id="G-001",
            new_parent_step_id="G-002",
            cascade_uuid="not-a-uuid",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_step_set_status_bad_cascade_uuid_is_typed_invalid_params(register_command) -> None:
    """step_set_status: a malformed optional 'cascade_uuid' must map to a clean -32602."""
    register_command(StepSetStatusCommand)
    result = asyncio.run(
        StepSetStatusCommand.run(
            plan="some-plan",
            step_id="G-001",
            status="draft",
            cascade_uuid="not-a-uuid",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "cascade_uuid is not a valid UUID")


def test_todo_delete_bad_todo_uuid_is_typed_invalid_params(register_command) -> None:
    """todo_delete: a malformed 'todo' UUID must map to a clean -32602."""
    register_command(TodoDeleteCommand)
    result = asyncio.run(TodoDeleteCommand.run(todo="not-a-uuid", changed_by="tester"))
    _assert_typed_invalid_params(result.to_dict(), "todo is not a valid UUID")
