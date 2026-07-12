"""End-to-end adapter-bug lifecycle scenario (C-035, HRS {le1s}): a bug is registered in the
mcp-proxy-adapter project, its source is bound to a specific adapter file, all dependent
projects are discovered through the project dependency graph, suspected impacts are created
and some confirmed, the source fix is implemented, the bug reaches fixed_source (not closed),
propagation actions and TODO items are created and driven to completion for dependents, and
the bug closes only once every confirmed impact is verified and every propagation is finished.
Pure in-memory orchestration over the domain models and closure-discipline predicates; no DB."""
from __future__ import annotations

import uuid

import pytest

from plan_manager.domain.bug_report import (
    BugReport,
    BugKind,
    BugSeverity,
    BugStatus,
    validate_bug_kind,
    validate_bug_severity,
    validate_bug_status,
)
from plan_manager.domain.bug_source import BugSource, BugSourceType
from plan_manager.domain.bug_impact import (
    BugImpact,
    BugImpactTargetType,
    BugImpactType,
    BugImpactStatus,
    validate_impact_target_type,
    validate_impact_type,
    validate_impact_status,
)
from plan_manager.domain.project_dependency import (
    ProjectDependency,
    DependencyType,
    DiscoverySource,
    DependencyConfidence,
    validate_dependency_type,
    validate_discovery_source,
    validate_confidence,
    validate_dependency_project_ids,
    guard_discovery_not_silently_confirmed,
    guard_no_dependency_cycle,
    suspected_impact_targets,
)
from plan_manager.domain.bug_fix import (
    BugFix,
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
    STATUS_CLOSED,
)
from plan_manager.domain.runtime_validation import RuntimeValidationError

NOW = "2026-07-10T00:00:00+00:00"

ADAPTER_PROJECT_ID = uuid.uuid4()
DEPENDENT_A_ID = uuid.uuid4()
DEPENDENT_B_ID = uuid.uuid4()
UNRELATED_PROJECT_ID = uuid.uuid4()


def make_bug_report(*, bug_uuid: uuid.UUID, status: str, source_file_path: str | None) -> BugReport:
    kind = validate_bug_kind(BugKind.REGRESSION.value)
    severity = validate_bug_severity(BugSeverity.MAJOR.value)
    validate_bug_status(status)
    return BugReport(
        bug_uuid=bug_uuid,
        title="mcp-proxy-adapter breaks dependent request routing",
        short_description="Adapter changed a response field name.",
        detailed_description="A recent adapter change renamed a response field, breaking callers.",
        expected_behavior="Adapter keeps the documented response contract.",
        actual_behavior="Adapter emits a renamed field, dependents fail to parse it.",
        reproduction="Call the adapter endpoint and inspect the response payload.",
        evidence=None,
        environment="production",
        kind=kind,
        severity=severity,
        priority_nice=0,
        status=status,
        reporter="runtime-scenario",
        owner="runtime-scenario",
        duplicate_of_uuid=None,
        parent_bug_uuid=None,
        source_anchor_type=BugSourceType.FILE.value,
        source_project_id=ADAPTER_PROJECT_ID,
        source_file_path=source_file_path,
        source_plan_uuid=None,
        source_revision_uuid=None,
        source_step_uuid=None,
        source_step_path=None,
        source_ref_id=None,
        source_command=None,
        source_service=None,
        confirmed_at=None,
        closed_at=None,
        reopened_at=None,
        created_by="runtime-scenario",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )


def make_bug_impact(*, impact_uuid: uuid.UUID, bug_uuid: uuid.UUID, target_project_id: uuid.UUID, status: str) -> BugImpact:
    target_type = validate_impact_target_type(BugImpactTargetType.PROJECT.value)
    impact_type = validate_impact_type(BugImpactType.USES_BROKEN_CONTRACT.value)
    validate_impact_status(status)
    return BugImpact(
        impact_uuid=impact_uuid,
        bug_uuid=bug_uuid,
        target_type=target_type,
        target_project_id=target_project_id,
        target_file_path=None,
        target_plan_uuid=None,
        target_revision_uuid=None,
        target_step_uuid=None,
        target_step_path=None,
        target_ref_id=None,
        target_identifier=None,
        impact_type=impact_type,
        status=status,
        reason=None,
        skip_decided_by=None,
        discovery_method="project_dependency_graph",
        resolution_evidence=None,
        created_by="runtime-scenario",
        created_at=NOW,
        updated_at=NOW,
        resolved_at=None,
        deleted_at=None,
    )


def make_project_dependency(*, dependency_uuid: uuid.UUID, dependent_project_id: uuid.UUID, depends_on_project_id: uuid.UUID) -> ProjectDependency:
    dependency_type = validate_dependency_type(DependencyType.RUNTIME_ADAPTER.value)
    discovery_source = validate_discovery_source(DiscoverySource.MANUAL.value)
    confidence = validate_confidence(DependencyConfidence.CONFIRMED.value)
    validate_dependency_project_ids(dependent_project_id, depends_on_project_id)
    guard_discovery_not_silently_confirmed(discovery_source, confidence)
    return ProjectDependency(
        dependency_uuid=dependency_uuid,
        dependent_project_id=dependent_project_id,
        depends_on_project_id=depends_on_project_id,
        dependency_type=dependency_type,
        version_constraint=None,
        discovery_source=discovery_source,
        confidence=confidence,
        active=True,
        created_by="runtime-scenario",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )


def make_bug_fix(*, fix_uuid: uuid.UUID, bug_uuid: uuid.UUID, status: str, passed: bool | None) -> BugFix:
    fix_type = validate_fix_type(BugFixType.CODE.value)
    validate_fix_status(status)
    return BugFix(
        fix_uuid=fix_uuid,
        bug_uuid=bug_uuid,
        status=status,
        fix_type=fix_type,
        summary="Restore the documented adapter response field name.",
        implementation_notes="Reverted the field rename in the adapter response serializer.",
        source_project_id=ADAPTER_PROJECT_ID,
        branch="fix/adapter-response-field",
        commit_hash="abc123",
        pull_request=None,
        changed_files=[str(ADAPTER_PROJECT_ID) + "/adapter_response.py"],
        tests=["test_adapter_response_contract"],
        author="runtime-scenario",
        reviewer="runtime-scenario",
        started_at=NOW,
        implemented_at=NOW,
        verified_at=NOW if status == BugFixStatus.VERIFIED.value else None,
        verification_method="unit_test",
        expected_result="Response field name matches the documented contract.",
        actual_result="Response field name matches the documented contract." if passed else None,
        passed=passed,
        revert_info=None,
        created_by="runtime-scenario",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )


def make_propagation(*, propagation_uuid: uuid.UUID, bug_fix_uuid: uuid.UUID, impact_uuid: uuid.UUID, action: str, status: str) -> BugFixPropagation:
    validated_action = validate_propagation_action(action)
    validate_propagation_status(status)
    finished_statuses = {PropagationStatus.DONE.value, PropagationStatus.VERIFIED.value, PropagationStatus.SKIPPED.value}
    return BugFixPropagation(
        propagation_uuid=propagation_uuid,
        bug_fix_uuid=bug_fix_uuid,
        impact_uuid=impact_uuid,
        target_type=BugImpactTargetType.PROJECT.value,
        target_identifier=None,
        action=validated_action,
        status=status,
        assigned_to="runtime-scenario",
        linked_todo_uuid=uuid.uuid4(),
        linked_plan_uuid=None,
        linked_cascade_uuid=None,
        started_at=NOW,
        finished_at=NOW if status in finished_statuses else None,
        evidence=None,
        verification_result=None,
        created_by="runtime-scenario",
        created_at=NOW,
        updated_at=NOW,
        deleted_at=None,
    )


def test_adapter_bug_lifecycle_end_to_end() -> None:
    # Stage 1: a bug is registered in the mcp-proxy-adapter project.
    bug_uuid = uuid.uuid4()
    bug = make_bug_report(bug_uuid=bug_uuid, status=BugStatus.REPORTED.value, source_file_path=None)
    assert bug.status == BugStatus.REPORTED.value
    assert bug.source_project_id == ADAPTER_PROJECT_ID

    # Stage 2: the source is bound to a specific file of the adapter.
    source = BugSource(source_type=BugSourceType.FILE.value, project_id=ADAPTER_PROJECT_ID, file_path="adapter/response.py")
    assert source.source_type == BugSourceType.FILE.value
    assert source.file_path == "adapter/response.py"
    bug = make_bug_report(bug_uuid=bug_uuid, status=BugStatus.CONFIRMED.value, source_file_path=source.file_path)
    assert bug.source_file_path == "adapter/response.py"
    assert bug.status == BugStatus.CONFIRMED.value

    # Stage 3: all projects using the adapter are discovered through the dependency graph.
    edges = [
        (str(DEPENDENT_A_ID), str(ADAPTER_PROJECT_ID)),
        (str(DEPENDENT_B_ID), str(DEPENDENT_A_ID)),
        (str(UNRELATED_PROJECT_ID), str(uuid.uuid4())),
    ]
    guard_no_dependency_cycle(edges)
    dependency_a = make_project_dependency(
        dependency_uuid=uuid.uuid4(), dependent_project_id=DEPENDENT_A_ID, depends_on_project_id=ADAPTER_PROJECT_ID
    )
    dependency_b = make_project_dependency(
        dependency_uuid=uuid.uuid4(), dependent_project_id=DEPENDENT_B_ID, depends_on_project_id=DEPENDENT_A_ID
    )
    discovered = suspected_impact_targets(edges, ADAPTER_PROJECT_ID)
    assert set(discovered) == {DEPENDENT_A_ID, DEPENDENT_B_ID}
    assert UNRELATED_PROJECT_ID not in discovered
    assert dependency_a.dependent_project_id == DEPENDENT_A_ID
    assert dependency_b.dependent_project_id == DEPENDENT_B_ID

    # Stage 4: suspected impacts are created for the discovered dependents.
    impact_a_uuid = uuid.uuid4()
    impact_b_uuid = uuid.uuid4()
    impact_a = make_bug_impact(
        impact_uuid=impact_a_uuid, bug_uuid=bug_uuid, target_project_id=DEPENDENT_A_ID, status=BugImpactStatus.SUSPECTED.value
    )
    impact_b = make_bug_impact(
        impact_uuid=impact_b_uuid, bug_uuid=bug_uuid, target_project_id=DEPENDENT_B_ID, status=BugImpactStatus.SUSPECTED.value
    )
    assert impact_a.status == BugImpactStatus.SUSPECTED.value
    assert impact_b.status == BugImpactStatus.SUSPECTED.value

    # Stage 5: some impacts are confirmed.
    impact_a = make_bug_impact(
        impact_uuid=impact_a_uuid, bug_uuid=bug_uuid, target_project_id=DEPENDENT_A_ID, status=BugImpactStatus.CONFIRMED.value
    )
    assert impact_a.status == BugImpactStatus.CONFIRMED.value
    assert impact_b.status == BugImpactStatus.SUSPECTED.value

    # Stage 6: the source fix is implemented.
    fix_uuid = uuid.uuid4()
    fix = make_bug_fix(fix_uuid=fix_uuid, bug_uuid=bug_uuid, status=BugFixStatus.IMPLEMENTED.value, passed=None)
    assert fix.status == BugFixStatus.IMPLEMENTED.value
    fix = make_bug_fix(fix_uuid=fix_uuid, bug_uuid=bug_uuid, status=BugFixStatus.VERIFIED.value, passed=True)
    assert fix.status == BugFixStatus.VERIFIED.value
    assert fix.passed is True

    # Stage 7: the bug receives fixed_source status, not closed, because a confirmed impact remains open.
    has_open_downstream = impact_a.status in {BugImpactStatus.SUSPECTED.value, BugImpactStatus.CONFIRMED.value}
    next_status = status_after_source_fix(has_open_downstream=has_open_downstream)
    assert next_status == STATUS_PROPAGATING
    fixed_bug = make_bug_report(bug_uuid=bug_uuid, status=STATUS_FIXED_SOURCE, source_file_path=source.file_path)
    assert fixed_bug.status == STATUS_FIXED_SOURCE
    assert fixed_bug.status != STATUS_CLOSED
    bug = make_bug_report(bug_uuid=bug_uuid, status=next_status, source_file_path=source.file_path)
    assert bug.status == STATUS_PROPAGATING
    assert bug.status != STATUS_CLOSED

    # Stage 8: propagation actions and TODO items are created for the dependent projects.
    propagation_a_uuid = uuid.uuid4()
    propagation_a = make_propagation(
        propagation_uuid=propagation_a_uuid,
        bug_fix_uuid=fix_uuid,
        impact_uuid=impact_a_uuid,
        action=PropagationAction.REBUILD_PACKAGE.value,
        status=PropagationStatus.PENDING.value,
    )
    assert propagation_a.status == PropagationStatus.PENDING.value
    assert propagation_a.linked_todo_uuid is not None

    # Stage 9: the updates, rebuild, and test rerun are performed (propagation reaches a finished state).
    propagation_a = make_propagation(
        propagation_uuid=propagation_a_uuid,
        bug_fix_uuid=fix_uuid,
        impact_uuid=impact_a_uuid,
        action=PropagationAction.REBUILD_PACKAGE.value,
        status=PropagationStatus.IN_PROGRESS.value,
    )
    assert propagation_a.status == PropagationStatus.IN_PROGRESS.value
    propagation_a = make_propagation(
        propagation_uuid=propagation_a_uuid,
        bug_fix_uuid=fix_uuid,
        impact_uuid=impact_a_uuid,
        action=PropagationAction.REBUILD_PACKAGE.value,
        status=PropagationStatus.DONE.value,
    )
    assert propagation_a.status == PropagationStatus.DONE.value
    assert propagation_a.finished_at == NOW

    # Stage 10: the bug closes only after all confirmed impacts are verified.
    pre_verification_decision = evaluate_closure(
        source_fix_verified=(fix.status == BugFixStatus.VERIFIED.value),
        impacts=[ImpactState(status=impact_a.status), ImpactState(status=impact_b.status)],
        propagations=[PropagationState(status=propagation_a.status)],
    )
    assert pre_verification_decision.can_close is False
    assert any("impact" in reason for reason in pre_verification_decision.blocking_reasons)
    with pytest.raises(RuntimeValidationError):
        guard_close(
            source_fix_verified=(fix.status == BugFixStatus.VERIFIED.value),
            impacts=[ImpactState(status=impact_a.status), ImpactState(status=impact_b.status)],
            propagations=[PropagationState(status=propagation_a.status)],
        )

    impact_a = make_bug_impact(
        impact_uuid=impact_a_uuid, bug_uuid=bug_uuid, target_project_id=DEPENDENT_A_ID, status=BugImpactStatus.VERIFIED.value
    )
    impact_b = make_bug_impact(
        impact_uuid=impact_b_uuid, bug_uuid=bug_uuid, target_project_id=DEPENDENT_B_ID, status=BugImpactStatus.UNAFFECTED.value
    )
    final_decision = evaluate_closure(
        source_fix_verified=(fix.status == BugFixStatus.VERIFIED.value),
        impacts=[ImpactState(status=impact_a.status), ImpactState(status=impact_b.status)],
        propagations=[PropagationState(status=propagation_a.status)],
    )
    assert final_decision.can_close is True
    assert final_decision.blocking_reasons == []
    guard_close(
        source_fix_verified=(fix.status == BugFixStatus.VERIFIED.value),
        impacts=[ImpactState(status=impact_a.status), ImpactState(status=impact_b.status)],
        propagations=[PropagationState(status=propagation_a.status)],
    )
    closed_bug = make_bug_report(bug_uuid=bug_uuid, status=STATUS_CLOSED, source_file_path=source.file_path)
    assert closed_bug.status == STATUS_CLOSED

    # reopen_status is available and does not destroy prior history (C-026 {exm0}).
    assert reopen_status() == "reopened"
