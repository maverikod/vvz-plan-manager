"""Pure-unit tests for bug fix propagation and bug closure discipline: a source fix that leaves
downstream impacts open does not close the bug, per-impact propagation modeling, bug reopening
that preserves fix/verification history, and TODO generation from impacts (C-035, HRS {d118}
bullets 16, 17, 18, 19). No database connection is created or used."""
from __future__ import annotations

import dataclasses
import uuid

import pytest

from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.bug_report import BugReport, BugStatus
from plan_manager.domain.bug_fix import (
    BugFixType,
    BugFixStatus,
    validate_fix_type,
    validate_fix_status,
)
from plan_manager.domain.bug_fix_propagation import (
    BugFixPropagation,
    PropagationAction,
    PropagationStatus,
    validate_propagation_action,
    validate_propagation_status,
)
from plan_manager.domain.bug_closure_discipline import (
    ImpactState,
    PropagationState,
    evaluate_closure,
    guard_close,
    status_after_source_fix,
    reopen_status,
    STATUS_FIXED_SOURCE,
    STATUS_PROPAGATING,
    STATUS_REOPENED,
)


def _bug_report(*, status: str, confirmed_at, closed_at, reopened_at) -> BugReport:
    return BugReport(
        bug_uuid=uuid.uuid4(),
        title="adapter breaks on null response",
        short_description="short",
        detailed_description="detailed",
        expected_behavior=None,
        actual_behavior=None,
        reproduction=None,
        evidence=None,
        environment=None,
        kind="functional",
        severity="major",
        priority_nice=0,
        status=status,
        reporter="tester",
        owner=None,
        duplicate_of_uuid=None,
        parent_bug_uuid=None,
        source_anchor_type="project",
        source_project_id=uuid.uuid4(),
        source_file_path=None,
        source_plan_uuid=None,
        source_revision_uuid=None,
        source_step_uuid=None,
        source_step_path=None,
        source_ref_id=None,
        source_command=None,
        source_service=None,
        confirmed_at=confirmed_at,
        closed_at=closed_at,
        reopened_at=reopened_at,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
        deleted_at=None,
    )


def test_status_after_source_fix_stays_propagating_when_downstream_open() -> None:
    assert status_after_source_fix(has_open_downstream=True) == STATUS_PROPAGATING
    assert BugStatus.PROPAGATING.value == STATUS_PROPAGATING


def test_status_after_source_fix_becomes_fixed_source_when_no_downstream_open() -> None:
    assert status_after_source_fix(has_open_downstream=False) == STATUS_FIXED_SOURCE
    assert BugStatus.FIXED_SOURCE.value == STATUS_FIXED_SOURCE


def test_closure_blocked_when_source_fixed_but_impact_and_propagation_still_open() -> None:
    decision = evaluate_closure(
        source_fix_verified=True,
        impacts=[ImpactState(status="confirmed")],
        propagations=[PropagationState(status="pending")],
    )

    assert decision.can_close is False
    assert "impact not resolved and verified (status=confirmed)" in decision.blocking_reasons
    assert "propagation action not finished (status=pending)" in decision.blocking_reasons


def test_guard_close_raises_when_source_fix_not_verified() -> None:
    with pytest.raises(RuntimeValidationError):
        guard_close(source_fix_verified=False, impacts=[], propagations=[])


def test_propagation_action_and_status_validation() -> None:
    assert validate_propagation_action(PropagationAction.RERUN_TESTS.value) == "rerun_tests"
    with pytest.raises(RuntimeValidationError):
        validate_propagation_action("not_a_real_action")

    assert validate_propagation_status(PropagationStatus.DONE.value) == "done"
    with pytest.raises(RuntimeValidationError):
        validate_propagation_status("not_a_real_status")


def test_bug_fix_type_and_status_validation() -> None:
    assert validate_fix_type(BugFixType.CODE.value) == "code"
    with pytest.raises(RuntimeValidationError):
        validate_fix_type("not_a_real_fix_type")

    assert validate_fix_status(BugFixStatus.VERIFIED.value) == "verified"
    with pytest.raises(RuntimeValidationError):
        validate_fix_status("not_a_real_fix_status")


def test_multiple_propagations_model_distinct_downstream_actions_for_one_fix() -> None:
    fix_uuid = uuid.uuid4()
    impact_a = uuid.uuid4()
    impact_b = uuid.uuid4()

    propagation_rebuild = BugFixPropagation(
        propagation_uuid=uuid.uuid4(),
        bug_fix_uuid=fix_uuid,
        impact_uuid=impact_a,
        target_type="project",
        target_identifier="dependent-service-a",
        action=PropagationAction.REBUILD_IMAGE.value,
        status=PropagationStatus.IN_PROGRESS.value,
        assigned_to="ops-team",
        linked_todo_uuid=None,
        linked_plan_uuid=None,
        linked_cascade_uuid=None,
        started_at="2026-07-10T00:00:00+00:00",
        finished_at=None,
        evidence=None,
        verification_result=None,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
        deleted_at=None,
    )
    propagation_rerun_tests = BugFixPropagation(
        propagation_uuid=uuid.uuid4(),
        bug_fix_uuid=fix_uuid,
        impact_uuid=impact_b,
        target_type="project",
        target_identifier="dependent-service-b",
        action=PropagationAction.RERUN_TESTS.value,
        status=PropagationStatus.DONE.value,
        assigned_to="ops-team",
        linked_todo_uuid=None,
        linked_plan_uuid=None,
        linked_cascade_uuid=None,
        started_at="2026-07-10T00:00:00+00:00",
        finished_at="2026-07-10T01:00:00+00:00",
        evidence=None,
        verification_result=None,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T01:00:00+00:00",
        deleted_at=None,
    )

    assert propagation_rebuild.bug_fix_uuid == propagation_rerun_tests.bug_fix_uuid
    assert propagation_rebuild.impact_uuid != propagation_rerun_tests.impact_uuid
    assert propagation_rebuild.action != propagation_rerun_tests.action


def test_closure_permitted_when_fix_verified_impacts_cleared_and_propagations_finished() -> None:
    decision = evaluate_closure(
        source_fix_verified=True,
        impacts=[ImpactState(status="verified"), ImpactState(status="unaffected")],
        propagations=[PropagationState(status="done"), PropagationState(status="skipped")],
    )

    assert decision.can_close is True
    assert decision.blocking_reasons == []


def test_reopen_status_is_reopened() -> None:
    assert reopen_status() == STATUS_REOPENED
    assert BugStatus.REOPENED.value == STATUS_REOPENED


def test_reopening_preserves_history_representing_fields() -> None:
    closed_bug = _bug_report(
        status="closed",
        confirmed_at="2026-06-01T00:00:00+00:00",
        closed_at="2026-06-15T00:00:00+00:00",
        reopened_at=None,
    )

    reopened_bug = dataclasses.replace(
        closed_bug,
        status=reopen_status(),
        reopened_at="2026-07-10T00:00:00+00:00",
    )

    assert reopened_bug.status == "reopened"
    assert reopened_bug.confirmed_at == closed_bug.confirmed_at
    assert reopened_bug.closed_at == closed_bug.closed_at
    assert reopened_bug.reopened_at == "2026-07-10T00:00:00+00:00"


def test_propagation_carries_a_generated_todo_link_for_an_open_impact() -> None:
    todo_uuid = uuid.uuid4()

    propagation = BugFixPropagation(
        propagation_uuid=uuid.uuid4(),
        bug_fix_uuid=uuid.uuid4(),
        impact_uuid=uuid.uuid4(),
        target_type="project",
        target_identifier="dependent-service-a",
        action=PropagationAction.UPDATE_DEPENDENCY_VERSION.value,
        status=PropagationStatus.PENDING.value,
        assigned_to=None,
        linked_todo_uuid=todo_uuid,
        linked_plan_uuid=None,
        linked_cascade_uuid=None,
        started_at=None,
        finished_at=None,
        evidence=None,
        verification_result=None,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
        deleted_at=None,
    )

    assert propagation.linked_todo_uuid == todo_uuid


def test_propagation_without_a_generated_todo_has_no_linked_todo() -> None:
    propagation = BugFixPropagation(
        propagation_uuid=uuid.uuid4(),
        bug_fix_uuid=uuid.uuid4(),
        impact_uuid=uuid.uuid4(),
        target_type=None,
        target_identifier=None,
        action=PropagationAction.NO_ACTION_REQUIRED.value,
        status=PropagationStatus.SKIPPED.value,
        assigned_to=None,
        linked_todo_uuid=None,
        linked_plan_uuid=None,
        linked_cascade_uuid=None,
        started_at=None,
        finished_at="2026-07-10T00:00:00+00:00",
        evidence=None,
        verification_result=None,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
        deleted_at=None,
    )

    assert propagation.linked_todo_uuid is None
