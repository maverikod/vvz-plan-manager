from mcp_proxy_adapter.commands.command_help_info import build_command_help_payload

from plan_manager.commands.step_set_status_command import StepSetStatusCommand
from plan_manager.domain.status_model import (
    ATOMIC_ONLY_STATUSES,
    LEGAL_TRANSITIONS,
    STATUSES,
)


def test_step_set_status_help_documents_every_status_enum_value() -> None:
    payload = build_command_help_payload(
        "step_set_status", StepSetStatusCommand, "custom"
    )
    metadata = payload["ai_metadata"]

    enum_values = metadata["parameters"]["status"]["enum"]
    legal_transitions = metadata["legal_transitions"]

    assert set(legal_transitions["statuses"]) == set(enum_values)
    assert set(enum_values) == set(STATUSES | ATOMIC_ONLY_STATUSES)
    assert "needs_review" in legal_transitions["cascade_targets"]
    assert (
        legal_transitions["cascade_targets"]["needs_review"]["direct_request"]
        == "INVALID_TRANSITION"
    )


def test_step_set_status_help_matches_status_model_transition_graph() -> None:
    metadata = StepSetStatusCommand.metadata()
    statuses = metadata["legal_transitions"]["statuses"]

    for status in sorted(STATUSES | ATOMIC_ONLY_STATUSES):
        expected_targets = set(LEGAL_TRANSITIONS[status])
        if status == "frozen":
            expected_targets.add("in_progress")

        assert set(statuses[status]["direct_targets"]) == expected_targets
        if status in ATOMIC_ONLY_STATUSES:
            assert statuses[status]["scope"] == "atomic_steps_only"
        else:
            assert statuses[status]["scope"] == "all_step_artifacts"

    assert "needs_review" not in {
        target
        for entry in statuses.values()
        for target in entry["direct_targets"]
    }
