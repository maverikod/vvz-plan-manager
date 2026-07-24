"""Regression tests for bug 0d8755bd-066d-4d42-a3d2-f71389c190df, Class 2, group B.

Class 2 covers command files where a bare ``uuid.UUID(client_param)`` call
sits inside ``execute()`` (not ``validate_params``) with no prior format
check. A malformed client-supplied UUID string reaches that unguarded call,
raises a bare stdlib ``ValueError``, is caught by the file's own
``except Exception as exc: return map_exception(exc)``, and -- because
``map_exception`` (``plan_manager.commands.errors``) has no case for a plain
``ValueError`` -- falls through to its own generic branch and surfaces as a
raw JSON-RPC -32603 "Unexpected error ..." instead of a clean -32602
invalid-params ``ErrorResult``, exactly like the sibling Class 1 defect (bare
``uuid.UUID(...)`` inside ``validate_params`` itself, see
``test_bug_0d8755bd_class1_validate_params.py``) and Class 2A (the first
batch of execute()-level sites, fixed separately).

Group B is the second batch of Class 2 files: bug_fix / bug_propagation /
execution_attempt / review_result / escalation_create / srt_diff. Each was
fixed identically to Class 1/2A: the affected command now overrides
``validate_params`` to pre-parse every pure-UUID client parameter (never a
name-or-uuid selector resolved via ``step_ref``/``resolve_step_ref``, and
only when an optional parameter is actually supplied) and re-raise a caught
``ValueError`` as ``InvalidParamsError`` (imported from
``mcp_proxy_adapter.core.errors``) -- never touching ``map_exception``.

Every test here drives the real adapter dispatch path (``Command.run``, the
same classmethod the JSON-RPC handler calls). For a malformed UUID,
``Command.run`` calls ``validate_params`` before ``execute``
(``mcp_proxy_adapter.commands.base.Command.run``), so the fixed
``InvalidParamsError`` is raised and caught by ``run``'s own typed-error
mapping before ``execute`` ever opens a database connection -- these tests
need no live database. The positive-case tests call ``validate_params``
directly on a fresh command instance with well-formed UUID strings and
assert it returns normally (no exception), proving the guard does not
false-positive on valid input; they stop short of ``execute()`` /
``Command.run()`` because that would require a live database connection
that is not part of this suite's fixtures.
"""
from __future__ import annotations

import asyncio

import pytest
from mcp_proxy_adapter.commands import command_registry as command_registry_module
from mcp_proxy_adapter.commands.command_registry import CommandRegistry
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.bug_fix_create_command import BugFixCreateCommand
from plan_manager.commands.bug_fix_list_command import BugFixListCommand
from plan_manager.commands.bug_fix_update_command import BugFixUpdateCommand
from plan_manager.commands.bug_fix_verify_command import BugFixVerifyCommand
from plan_manager.commands.bug_propagation_create_command import BugPropagationCreateCommand
from plan_manager.commands.bug_propagation_generate_todos_command import (
    BugPropagationGenerateTodosCommand,
)
from plan_manager.commands.bug_propagation_list_command import BugPropagationListCommand
from plan_manager.commands.bug_propagation_update_command import BugPropagationUpdateCommand
from plan_manager.commands.escalation_create_command import EscalationCreateCommand
from plan_manager.commands.execution_attempt_create_command import ExecutionAttemptCreateCommand
from plan_manager.commands.execution_attempt_list_command import ExecutionAttemptListCommand
from plan_manager.commands.execution_attempt_report_command import ExecutionAttemptReportCommand
from plan_manager.commands.review_result_create_command import ReviewResultCreateCommand
from plan_manager.commands.review_result_get_command import ReviewResultGetCommand
from plan_manager.commands.review_result_list_command import ReviewResultListCommand
from plan_manager.commands.srt_diff_command import SrtDiffCommand


VALID_UUID_A = "11111111-1111-1111-1111-111111111111"
VALID_UUID_B = "22222222-2222-2222-2222-222222222222"


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


# ---------------------------------------------------------------------------
# bug_fix_create
# ---------------------------------------------------------------------------

def test_bug_fix_create_bad_bug_uuid_is_typed_invalid_params(register_command) -> None:
    """bug_fix_create: a malformed required 'bug' UUID must map to a clean -32602."""
    register_command(BugFixCreateCommand)
    result = asyncio.run(
        BugFixCreateCommand.run(
            bug="not-a-uuid", fix_type="code", summary="s", author="a", created_by="a"
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "bug is not a valid UUID")


def test_bug_fix_create_bad_source_project_id_is_typed_invalid_params(register_command) -> None:
    """bug_fix_create: a malformed optional 'source_project_id' must map to a clean -32602."""
    register_command(BugFixCreateCommand)
    result = asyncio.run(
        BugFixCreateCommand.run(
            bug=VALID_UUID_A,
            fix_type="code",
            summary="s",
            author="a",
            created_by="a",
            source_project_id="not-a-uuid",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "source_project_id is not a valid UUID")


def test_bug_fix_create_valid_uuids_pass_validate_params() -> None:
    """bug_fix_create: well-formed bug/source_project_id pass validate_params untouched."""
    params = BugFixCreateCommand().validate_params(
        {
            "bug": VALID_UUID_A,
            "fix_type": "code",
            "summary": "s",
            "author": "a",
            "created_by": "a",
            "source_project_id": VALID_UUID_B,
        }
    )
    assert params["bug"] == VALID_UUID_A
    assert params["source_project_id"] == VALID_UUID_B


# ---------------------------------------------------------------------------
# bug_fix_list
# ---------------------------------------------------------------------------

def test_bug_fix_list_bad_bug_uuid_is_typed_invalid_params(register_command) -> None:
    """bug_fix_list: a malformed required 'bug' UUID must map to a clean -32602."""
    register_command(BugFixListCommand)
    result = asyncio.run(BugFixListCommand.run(bug="not-a-uuid"))
    _assert_typed_invalid_params(result.to_dict(), "bug is not a valid UUID")


def test_bug_fix_list_valid_uuid_passes_validate_params() -> None:
    """bug_fix_list: a well-formed 'bug' passes validate_params untouched."""
    params = BugFixListCommand().validate_params({"bug": VALID_UUID_A})
    assert params["bug"] == VALID_UUID_A


# ---------------------------------------------------------------------------
# bug_fix_update
# ---------------------------------------------------------------------------

def test_bug_fix_update_bad_bug_fix_uuid_is_typed_invalid_params(register_command) -> None:
    """bug_fix_update: a malformed required 'bug_fix' UUID must map to a clean -32602."""
    register_command(BugFixUpdateCommand)
    result = asyncio.run(BugFixUpdateCommand.run(bug_fix="not-a-uuid", changed_by="tester"))
    _assert_typed_invalid_params(result.to_dict(), "bug_fix is not a valid UUID")


# ---------------------------------------------------------------------------
# bug_fix_verify
# ---------------------------------------------------------------------------

def test_bug_fix_verify_bad_bug_fix_uuid_is_typed_invalid_params(register_command) -> None:
    """bug_fix_verify: a malformed required 'bug_fix' UUID must map to a clean -32602."""
    register_command(BugFixVerifyCommand)
    result = asyncio.run(
        BugFixVerifyCommand.run(bug_fix="not-a-uuid", changed_by="tester", passed=True)
    )
    _assert_typed_invalid_params(result.to_dict(), "bug_fix is not a valid UUID")


# ---------------------------------------------------------------------------
# bug_propagation_create
# ---------------------------------------------------------------------------

def test_bug_propagation_create_bad_bug_fix_id_is_typed_invalid_params(register_command) -> None:
    """bug_propagation_create: a malformed required 'bug_fix_id' must map to a clean -32602."""
    register_command(BugPropagationCreateCommand)
    result = asyncio.run(
        BugPropagationCreateCommand.run(
            plan="some-plan",
            bug_fix_id="not-a-uuid",
            impact_id=VALID_UUID_B,
            action="rebuild_package",
            created_by="tester",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "bug_fix_id is not a valid UUID")


def test_bug_propagation_create_bad_impact_id_is_typed_invalid_params(register_command) -> None:
    """bug_propagation_create: a malformed required 'impact_id' must map to a clean -32602."""
    register_command(BugPropagationCreateCommand)
    result = asyncio.run(
        BugPropagationCreateCommand.run(
            plan="some-plan",
            bug_fix_id=VALID_UUID_A,
            impact_id="not-a-uuid",
            action="rebuild_package",
            created_by="tester",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "impact_id is not a valid UUID")


# ---------------------------------------------------------------------------
# bug_propagation_generate_todos
# ---------------------------------------------------------------------------

def test_bug_propagation_generate_todos_bad_bug_fix_id_is_typed_invalid_params(
    register_command,
) -> None:
    """bug_propagation_generate_todos: a malformed 'bug_fix_id' must map to a clean -32602."""
    register_command(BugPropagationGenerateTodosCommand)
    result = asyncio.run(
        BugPropagationGenerateTodosCommand.run(
            plan="some-plan", bug_fix_id="not-a-uuid", created_by="tester"
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "bug_fix_id is not a valid UUID")


# ---------------------------------------------------------------------------
# bug_propagation_list
# ---------------------------------------------------------------------------

def test_bug_propagation_list_bad_bug_fix_id_is_typed_invalid_params(register_command) -> None:
    """bug_propagation_list: a malformed optional 'bug_fix_id' filter must map to a clean -32602."""
    register_command(BugPropagationListCommand)
    result = asyncio.run(BugPropagationListCommand.run(bug_fix_id="not-a-uuid"))
    _assert_typed_invalid_params(result.to_dict(), "bug_fix_id is not a valid UUID")


def test_bug_propagation_list_bad_impact_id_is_typed_invalid_params(register_command) -> None:
    """bug_propagation_list: a malformed optional 'impact_id' filter must map to a clean -32602."""
    register_command(BugPropagationListCommand)
    result = asyncio.run(BugPropagationListCommand.run(impact_id="not-a-uuid"))
    _assert_typed_invalid_params(result.to_dict(), "impact_id is not a valid UUID")


def test_bug_propagation_list_omitted_filters_pass_validate_params() -> None:
    """bug_propagation_list: omitting both optional UUID filters passes validate_params."""
    params = BugPropagationListCommand().validate_params({})
    assert params.get("bug_fix_id") is None
    assert params.get("impact_id") is None


# ---------------------------------------------------------------------------
# bug_propagation_update
# ---------------------------------------------------------------------------

def test_bug_propagation_update_bad_propagation_id_is_typed_invalid_params(
    register_command,
) -> None:
    """bug_propagation_update: a malformed required 'propagation_id' must map to a clean -32602."""
    register_command(BugPropagationUpdateCommand)
    result = asyncio.run(
        BugPropagationUpdateCommand.run(
            plan="some-plan", propagation_id="not-a-uuid", changed_by="tester"
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "propagation_id is not a valid UUID")


def test_bug_propagation_update_bad_linked_todo_id_is_typed_invalid_params(
    register_command,
) -> None:
    """bug_propagation_update: a malformed optional 'linked_todo_id' must map to a clean -32602."""
    register_command(BugPropagationUpdateCommand)
    result = asyncio.run(
        BugPropagationUpdateCommand.run(
            plan="some-plan",
            propagation_id=VALID_UUID_A,
            changed_by="tester",
            linked_todo_id="not-a-uuid",
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "linked_todo_id is not a valid UUID")


# ---------------------------------------------------------------------------
# escalation_create
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field",
    [
        "anchor_project_id",
        "anchor_plan_uuid",
        "anchor_revision_uuid",
        "anchor_step_uuid",
        "anchor_ref_id",
    ],
)
def test_escalation_create_bad_anchor_uuid_is_typed_invalid_params(
    register_command, field: str
) -> None:
    """escalation_create: a malformed optional anchor_* UUID must map to a clean -32602."""
    register_command(EscalationCreateCommand)
    kwargs = {
        "plan": "some-plan",
        "anchor_type": "none",
        "reason": "testing",
        "created_by": "tester",
        field: "not-a-uuid",
    }
    result = asyncio.run(EscalationCreateCommand.run(**kwargs))
    _assert_typed_invalid_params(result.to_dict(), f"{field} is not a valid UUID")


def test_escalation_create_valid_anchor_ref_id_passes_validate_params() -> None:
    """escalation_create: a well-formed anchor_ref_id passes validate_params untouched."""
    params = EscalationCreateCommand().validate_params(
        {
            "plan": "some-plan",
            "anchor_type": "bug",
            "reason": "testing",
            "created_by": "tester",
            "anchor_ref_id": VALID_UUID_A,
        }
    )
    assert params["anchor_ref_id"] == VALID_UUID_A


# ---------------------------------------------------------------------------
# execution_attempt_create
# ---------------------------------------------------------------------------

def test_execution_attempt_create_bad_step_is_typed_invalid_params(register_command) -> None:
    """execution_attempt_create: a malformed required 'step' UUID must map to a clean -32602."""
    register_command(ExecutionAttemptCreateCommand)
    result = asyncio.run(
        ExecutionAttemptCreateCommand.run(
            plan="some-plan", step="not-a-uuid", status="queued", created_by="tester"
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "step is not a valid UUID")


@pytest.mark.parametrize(
    "field",
    ["revision", "todo_id", "bug_fix_id", "assigned_binding_id", "parent_attempt_id"],
)
def test_execution_attempt_create_bad_optional_uuid_is_typed_invalid_params(
    register_command, field: str
) -> None:
    """execution_attempt_create: a malformed optional UUID field must map to a clean -32602."""
    register_command(ExecutionAttemptCreateCommand)
    kwargs = {
        "plan": "some-plan",
        "step": VALID_UUID_A,
        "status": "queued",
        "created_by": "tester",
        field: "not-a-uuid",
    }
    result = asyncio.run(ExecutionAttemptCreateCommand.run(**kwargs))
    _assert_typed_invalid_params(result.to_dict(), f"{field} is not a valid UUID")


def test_execution_attempt_create_valid_uuids_pass_validate_params() -> None:
    """execution_attempt_create: well-formed step/optional UUIDs pass validate_params."""
    params = ExecutionAttemptCreateCommand().validate_params(
        {
            "plan": "some-plan",
            "step": VALID_UUID_A,
            "status": "queued",
            "created_by": "tester",
            "revision": VALID_UUID_B,
        }
    )
    assert params["step"] == VALID_UUID_A
    assert params["revision"] == VALID_UUID_B


# ---------------------------------------------------------------------------
# execution_attempt_list
# ---------------------------------------------------------------------------

def test_execution_attempt_list_bad_step_is_typed_invalid_params(register_command) -> None:
    """execution_attempt_list: a malformed optional 'step' filter must map to a clean -32602."""
    register_command(ExecutionAttemptListCommand)
    result = asyncio.run(ExecutionAttemptListCommand.run(step="not-a-uuid"))
    _assert_typed_invalid_params(result.to_dict(), "step is not a valid UUID")


def test_execution_attempt_list_bad_parent_attempt_id_is_typed_invalid_params(
    register_command,
) -> None:
    """execution_attempt_list: a malformed optional 'parent_attempt_id' filter maps to -32602."""
    register_command(ExecutionAttemptListCommand)
    result = asyncio.run(ExecutionAttemptListCommand.run(parent_attempt_id="not-a-uuid"))
    _assert_typed_invalid_params(result.to_dict(), "parent_attempt_id is not a valid UUID")


# ---------------------------------------------------------------------------
# execution_attempt_report
# ---------------------------------------------------------------------------

def test_execution_attempt_report_bad_attempt_id_is_typed_invalid_params(register_command) -> None:
    """execution_attempt_report: a malformed required 'attempt_id' must map to a clean -32602."""
    register_command(ExecutionAttemptReportCommand)
    result = asyncio.run(
        ExecutionAttemptReportCommand.run(attempt_id="not-a-uuid", changed_by="tester")
    )
    _assert_typed_invalid_params(result.to_dict(), "attempt_id is not a valid UUID")


# ---------------------------------------------------------------------------
# review_result_create
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "field",
    ["reviewed_attempt_uuid", "reviewed_revision_uuid", "escalation_target_uuid"],
)
def test_review_result_create_bad_optional_uuid_is_typed_invalid_params(
    register_command, field: str
) -> None:
    """review_result_create: a malformed optional UUID field must map to a clean -32602."""
    register_command(ReviewResultCreateCommand)
    kwargs = {
        "plan": "some-plan",
        "object_type": "execution_attempt",
        "reviewer": "tester",
        "status": "accepted",
        "created_by": "tester",
        field: "not-a-uuid",
    }
    result = asyncio.run(ReviewResultCreateCommand.run(**kwargs))
    _assert_typed_invalid_params(result.to_dict(), f"{field} is not a valid UUID")


def test_review_result_create_valid_uuids_pass_validate_params() -> None:
    """review_result_create: well-formed optional UUIDs pass validate_params untouched."""
    params = ReviewResultCreateCommand().validate_params(
        {
            "plan": "some-plan",
            "object_type": "execution_attempt",
            "reviewer": "tester",
            "status": "accepted",
            "created_by": "tester",
            "reviewed_attempt_uuid": VALID_UUID_A,
        }
    )
    assert params["reviewed_attempt_uuid"] == VALID_UUID_A


# ---------------------------------------------------------------------------
# review_result_get
# ---------------------------------------------------------------------------

def test_review_result_get_bad_review_uuid_is_typed_invalid_params(register_command) -> None:
    """review_result_get: a malformed required 'review_uuid' must map to a clean -32602."""
    register_command(ReviewResultGetCommand)
    result = asyncio.run(ReviewResultGetCommand.run(plan="some-plan", review_uuid="not-a-uuid"))
    _assert_typed_invalid_params(result.to_dict(), "review_uuid is not a valid UUID")


def test_review_result_get_valid_review_uuid_passes_validate_params() -> None:
    """review_result_get: a well-formed 'review_uuid' passes validate_params untouched."""
    params = ReviewResultGetCommand().validate_params(
        {"plan": "some-plan", "review_uuid": VALID_UUID_A}
    )
    assert params["review_uuid"] == VALID_UUID_A


# ---------------------------------------------------------------------------
# review_result_list
# ---------------------------------------------------------------------------

def test_review_result_list_bad_reviewed_attempt_uuid_is_typed_invalid_params(
    register_command,
) -> None:
    """review_result_list: a malformed optional filter must map to a clean -32602."""
    register_command(ReviewResultListCommand)
    result = asyncio.run(ReviewResultListCommand.run(reviewed_attempt_uuid="not-a-uuid"))
    _assert_typed_invalid_params(result.to_dict(), "reviewed_attempt_uuid is not a valid UUID")


# ---------------------------------------------------------------------------
# srt_diff
# ---------------------------------------------------------------------------

def test_srt_diff_bad_base_snapshot_uuid_is_typed_invalid_params(register_command) -> None:
    """srt_diff: a malformed required 'base_snapshot_uuid' must map to a clean -32602."""
    register_command(SrtDiffCommand)
    result = asyncio.run(
        SrtDiffCommand.run(
            plan="some-plan", base_snapshot_uuid="not-a-uuid", target_snapshot_uuid=VALID_UUID_B
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "base_snapshot_uuid is not a valid UUID")


def test_srt_diff_bad_target_snapshot_uuid_is_typed_invalid_params(register_command) -> None:
    """srt_diff: a malformed required 'target_snapshot_uuid' must map to a clean -32602."""
    register_command(SrtDiffCommand)
    result = asyncio.run(
        SrtDiffCommand.run(
            plan="some-plan", base_snapshot_uuid=VALID_UUID_A, target_snapshot_uuid="not-a-uuid"
        )
    )
    _assert_typed_invalid_params(result.to_dict(), "target_snapshot_uuid is not a valid UUID")


def test_srt_diff_valid_uuids_pass_validate_params() -> None:
    """srt_diff: well-formed base/target snapshot UUIDs pass validate_params untouched."""
    params = SrtDiffCommand().validate_params(
        {
            "plan": "some-plan",
            "base_snapshot_uuid": VALID_UUID_A,
            "target_snapshot_uuid": VALID_UUID_B,
        }
    )
    assert params["base_snapshot_uuid"] == VALID_UUID_A
    assert params["target_snapshot_uuid"] == VALID_UUID_B
