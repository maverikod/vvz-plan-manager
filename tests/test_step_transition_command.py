import uuid

import pytest

from mcp_proxy_adapter.commands.command_help_info import build_command_help_payload

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.info_command import InfoCommand
from plan_manager.commands.info_reference import step_lifecycle_capabilities
from plan_manager.commands.step_transition_command import (
    StepTransitionCommand,
    _plan_transitions,
    _select_steps,
)
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _step(
    step_uuid: str,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    status: str = "draft",
) -> Step:
    fields = {}
    if level == 5:
        fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1}
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields,
        depends_on=[],
        concepts=[],
        project_id=None,
        status=status,
    )


def _tree() -> dict[uuid.UUID, Step]:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None)
    other_gs = _step("00000000-0000-0000-0000-000000000021", 3, "G-002", None)
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid)
    other_ts = _step("00000000-0000-0000-0000-000000000023", 4, "T-001", other_gs.uuid)
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid)
    other_atomic = _step(
        "00000000-0000-0000-0000-000000000022", 5, "A-001", other_ts.uuid
    )
    return {step.uuid: step for step in (gs, other_gs, ts, other_ts, atomic, other_atomic)}


def test_step_transition_schema_and_metadata_are_help_ready() -> None:
    schema = StepTransitionCommand.get_schema()
    payload = build_command_help_payload(
        "step_transition", StepTransitionCommand, "custom"
    )

    assert StepTransitionCommand.use_queue is False
    assert schema["required"] == ["plan", "to_status"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["to_status"]["enum"] == [
        "draft",
        "ready_for_review",
        "frozen",
    ]
    assert payload["ai_metadata"]["parameters"]["scope"]["required"] is False
    assert payload["ai_metadata"]["error_cases"]["GATE_RED"]
    assert "fields.status" in payload["ai_metadata"]["detailed_description"]


def test_select_steps_supports_whole_plan_and_scoped_subtree() -> None:
    nodes = _tree()

    whole, whole_label = _select_steps(nodes, None, None)
    scoped, scoped_label = _select_steps(nodes, None, "G-001/T-001")

    assert whole_label == "whole_plan"
    assert [step.step_id for step in whole] == [
        "G-001",
        "G-002",
        "T-001",
        "T-001",
        "A-001",
        "A-001",
    ]
    assert scoped_label == "G-001/T-001"
    assert [step.step_id for step in scoped] == ["T-001", "A-001"]


def test_select_steps_rejects_missing_scope() -> None:
    with pytest.raises(DomainCommandError) as excinfo:
        _select_steps(_tree(), None, "G-009")

    assert excinfo.value.code == "STEP_NOT_FOUND"


def test_plan_transitions_allows_bulk_draft_to_frozen_and_skips_idempotent() -> None:
    nodes = _tree()
    selected = list(nodes.values())
    selected[0].status = "frozen"

    transitioned, skipped = _plan_transitions(nodes, selected, "frozen")

    assert len(transitioned) == 5
    assert transitioned[0]["from"] == "draft"
    assert transitioned[0]["to"] == "frozen"
    assert skipped == [
        {
            "uuid": str(selected[0].uuid),
            "step_id": "G-001",
            "path": "G-001",
            "from": "frozen",
            "reason": "already_at_target",
        }
    ]


def test_plan_transitions_rejects_illegal_reopen_to_ready() -> None:
    nodes = _tree()
    frozen = next(iter(nodes.values()))
    frozen.status = "frozen"

    with pytest.raises(DomainCommandError) as excinfo:
        _plan_transitions(nodes, [frozen], "ready_for_review")

    assert excinfo.value.code == "INVALID_TRANSITION"
    assert excinfo.value.details["illegal"][0]["from"] == "frozen"


def test_info_capabilities_include_step_transition() -> None:
    capabilities = step_lifecycle_capabilities()

    assert "step_transition" in capabilities["commands"]
    assert capabilities["read_surfaces"]["plan_prompt_chain"]


def test_info_metadata_documents_step_lifecycle_capability() -> None:
    metadata = InfoCommand.metadata()

    assert "step_lifecycle" in metadata["return_value"]["success"]["example"]["capabilities"]
    assert "step lifecycle transitions" in metadata["detailed_description"]
    assert "step lifecycle transitions" in metadata["best_practices"][2]
