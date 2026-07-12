from __future__ import annotations

import pytest

from plan_manager.domain.execution_attempt import (
    ExecutionAttemptStatus,
    ATTEMPT_STATUSES,
    TERMINAL_ATTEMPT_STATUSES,
    validate_attempt_status,
    is_terminal_status,
)
from plan_manager.domain.owner_review_ladder import (
    LADDER_LEVELS,
    VERIFICATION_MAP,
    PRODUCER_MAP,
    verifier_of,
    producer_of,
    subordinate_levels,
    escalation_target,
    is_self_certification,
    guard_no_self_certification,
    guard_valid_reviewer,
)
from plan_manager.domain.escalation import (
    EscalationStatus,
    ESCALATION_STATUSES,
    validate_escalation_status,
)
from plan_manager.domain.review_result import (
    ReviewStatus,
    REVIEW_STATUSES,
    validate_review_status,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError


# Execution Attempts ({d118} bullet 10)


def test_validate_attempt_status_accepts_known_statuses():
    """validate_attempt_status accepts every status in ATTEMPT_STATUSES."""
    for status in ATTEMPT_STATUSES:
        assert validate_attempt_status(status) == status


def test_validate_attempt_status_rejects_unknown_status():
    """validate_attempt_status rejects unknown statuses."""
    with pytest.raises(RuntimeValidationError):
        validate_attempt_status("not_a_real_status")


def test_is_terminal_status_true_for_terminal_statuses():
    """is_terminal_status returns True for all terminal statuses."""
    assert TERMINAL_ATTEMPT_STATUSES == {"succeeded", "failed", "cancelled", "timed_out"}
    for status in TERMINAL_ATTEMPT_STATUSES:
        assert is_terminal_status(status) is True


def test_is_terminal_status_false_for_non_terminal_statuses():
    """is_terminal_status returns False for non-terminal statuses."""
    assert is_terminal_status("queued") is False
    assert is_terminal_status("running") is False
    assert is_terminal_status("needs_review") is False
    assert is_terminal_status("needs_escalation") is False


def test_is_terminal_status_rejects_unknown_status():
    """is_terminal_status rejects unknown statuses."""
    with pytest.raises(RuntimeValidationError):
        is_terminal_status("bogus")


# Owner Review ({d118} bullet 11)


def test_verifier_of_maps_each_produced_level():
    """verifier_of correctly maps each produced level to its verifying owner."""
    assert verifier_of("gs") == "hrs_mrs"
    assert verifier_of("ts") == "gs"
    assert verifier_of("as") == "ts"
    assert verifier_of("as_execution") == "ts"


def test_verifier_of_rejects_unknown_level():
    """verifier_of rejects unknown produced levels."""
    with pytest.raises(RuntimeValidationError):
        verifier_of("not_a_level")


def test_producer_of_maps_each_produced_level():
    """producer_of correctly maps each produced level to its producer."""
    assert producer_of("gs") == "gs"
    assert producer_of("ts") == "ts"
    assert producer_of("as") == "as"
    assert producer_of("as_execution") == "code_execution"


def test_producer_of_rejects_unknown_level():
    """producer_of rejects unknown produced levels."""
    with pytest.raises(RuntimeValidationError):
        producer_of("not_a_level")


def test_escalation_target_next_level_up():
    """escalation_target returns the next level up in the hierarchy."""
    assert escalation_target("as") == "ts"
    assert escalation_target("ts") == "gs"
    assert escalation_target("gs") == "hrs_mrs"
    assert escalation_target("hrs_mrs") is None


def test_no_self_certification_the_code_executor_cannot_certify_its_own_result():
    """The code executor cannot certify its own as_execution result."""
    # The code executor reviewing its own as_execution would be self-certification.
    assert is_self_certification("code_execution", "as_execution") is True

    # guard_no_self_certification must reject this.
    with pytest.raises(RuntimeValidationError):
        guard_no_self_certification("code_execution", "as_execution")

    # But the TS owner (the designated verifier) may certify the as_execution result.
    guard_no_self_certification("ts", "as_execution")


def test_guard_valid_reviewer_accepts_the_designated_owner():
    """guard_valid_reviewer accepts the designated verifier for a produced level."""
    guard_valid_reviewer("ts", "as")


def test_guard_valid_reviewer_rejects_wrong_level():
    """guard_valid_reviewer rejects a reviewer that is not the designated verifier."""
    with pytest.raises(RuntimeValidationError):
        guard_valid_reviewer("gs", "as")


# Escalation ({d118} bullet 12)


def test_validate_escalation_status_accepts_known_statuses():
    """validate_escalation_status accepts every status in ESCALATION_STATUSES."""
    assert ESCALATION_STATUSES == {"open", "resolved"}
    for status in ESCALATION_STATUSES:
        assert validate_escalation_status(status) == status


def test_validate_escalation_status_rejects_unknown_status():
    """validate_escalation_status rejects unknown statuses."""
    with pytest.raises(RuntimeValidationError):
        validate_escalation_status("not_a_real_status")
