"""Pure-unit tests for bug source anchor validation, multiple bug impact modeling, and
project-dependency reverse-graph discovery (C-035, HRS {d118} bullets 13, 14, 15). No database
connection is created or used."""
from __future__ import annotations

import uuid

import pytest

from plan_manager.domain.runtime_validation import RuntimeValidationError
from plan_manager.domain.bug_source import (
    BugSource,
    BugSourceType,
    BUG_SOURCE_TYPES,
    ANCHOR_DELEGATED_TYPES,
    validate_bug_source,
    bug_source_to_columns,
    bug_source_from_columns,
)
from plan_manager.domain.bug_impact import (
    BugImpact,
    BugImpactTargetType,
    BugImpactType,
    BugImpactStatus,
    BUG_IMPACT_TARGET_TYPES,
    BUG_IMPACT_TYPES,
    BUG_IMPACT_STATUSES,
    validate_impact_target_type,
    validate_impact_type,
    validate_impact_status,
)
from plan_manager.domain.project_dependency import suspected_impact_targets


def test_bug_source_type_membership() -> None:
    assert BugSourceType.PROJECT.value in BUG_SOURCE_TYPES
    assert BugSourceType.PROJECT.value in ANCHOR_DELEGATED_TYPES
    assert BugSourceType.COMMAND.value in BUG_SOURCE_TYPES
    assert BugSourceType.COMMAND.value not in ANCHOR_DELEGATED_TYPES


def test_bug_source_project_anchor_is_valid_without_existence_lookup() -> None:
    source = BugSource(source_type=BugSourceType.PROJECT.value, project_id=uuid.uuid4())
    validate_bug_source(None, source)


def test_bug_source_command_type_requires_non_empty_command() -> None:
    source = BugSource(source_type=BugSourceType.COMMAND.value, command="deploy_service")
    validate_bug_source(None, source)

    with pytest.raises(RuntimeValidationError):
        validate_bug_source(None, BugSource(source_type=BugSourceType.COMMAND.value, command=None))


def test_bug_source_command_type_rejects_extra_identifier_fields() -> None:
    source = BugSource(source_type=BugSourceType.COMMAND.value, command="deploy_service", project_id=uuid.uuid4())
    with pytest.raises(RuntimeValidationError):
        validate_bug_source(None, source)


def test_bug_source_runtime_service_type_requires_non_empty_service() -> None:
    source = BugSource(source_type=BugSourceType.RUNTIME_SERVICE.value, service="scoring-service")
    validate_bug_source(None, source)

    with pytest.raises(RuntimeValidationError):
        validate_bug_source(None, BugSource(source_type=BugSourceType.RUNTIME_SERVICE.value, service=None))


def test_bug_source_unidentified_type_requires_all_identifier_fields_none() -> None:
    validate_bug_source(None, BugSource(source_type=BugSourceType.UNIDENTIFIED.value))

    with pytest.raises(RuntimeValidationError):
        validate_bug_source(None, BugSource(source_type=BugSourceType.UNIDENTIFIED.value, command="x"))


def test_bug_source_unknown_type_raises() -> None:
    with pytest.raises(RuntimeValidationError):
        validate_bug_source(None, BugSource(source_type="not_a_real_type"))


def test_bug_source_to_columns_and_from_columns_round_trip() -> None:
    source = BugSource(source_type=BugSourceType.RUNTIME_SERVICE.value, service="scoring-service")
    columns = bug_source_to_columns(source)

    assert columns == {
        "source_anchor_type": "runtime_service",
        "source_project_id": None,
        "source_file_path": None,
        "source_plan_uuid": None,
        "source_revision_uuid": None,
        "source_step_uuid": None,
        "source_step_path": None,
        "source_ref_id": None,
        "source_command": None,
        "source_service": "scoring-service",
    }
    assert bug_source_from_columns(columns) == source


def test_bug_impact_target_type_validation() -> None:
    assert validate_impact_target_type(BugImpactTargetType.PROJECT.value) == "project"
    with pytest.raises(RuntimeValidationError):
        validate_impact_target_type("not_a_real_target_type")


def test_bug_impact_type_validation() -> None:
    assert validate_impact_type(BugImpactType.NEEDS_REBUILD.value) == "needs_rebuild"
    with pytest.raises(RuntimeValidationError):
        validate_impact_type("not_a_real_impact_type")


def test_bug_impact_status_validation() -> None:
    assert validate_impact_status(BugImpactStatus.SUSPECTED.value) == "suspected"
    with pytest.raises(RuntimeValidationError):
        validate_impact_status("not_a_real_status")


def test_multiple_bug_impacts_model_distinct_affected_targets() -> None:
    bug_uuid = uuid.uuid4()
    project_target = uuid.uuid4()

    impact_on_project = BugImpact(
        impact_uuid=uuid.uuid4(),
        bug_uuid=bug_uuid,
        target_type=BugImpactTargetType.PROJECT.value,
        target_project_id=project_target,
        target_file_path=None,
        target_plan_uuid=None,
        target_revision_uuid=None,
        target_step_uuid=None,
        target_step_path=None,
        target_ref_id=None,
        target_identifier=None,
        impact_type=BugImpactType.NEEDS_DEPENDENCY_UPDATE.value,
        status=BugImpactStatus.SUSPECTED.value,
        reason=None,
        skip_decided_by=None,
        discovery_method="project_dependency_graph",
        resolution_evidence=None,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
        resolved_at=None,
        deleted_at=None,
    )
    impact_on_file = BugImpact(
        impact_uuid=uuid.uuid4(),
        bug_uuid=bug_uuid,
        target_type=BugImpactTargetType.FILE.value,
        target_project_id=project_target,
        target_file_path="src/adapter/client.py",
        target_plan_uuid=None,
        target_revision_uuid=None,
        target_step_uuid=None,
        target_step_path=None,
        target_ref_id=None,
        target_identifier=None,
        impact_type=BugImpactType.USES_BROKEN_API.value,
        status=BugImpactStatus.CONFIRMED.value,
        reason=None,
        skip_decided_by=None,
        discovery_method="manual",
        resolution_evidence=None,
        created_by="tester",
        created_at="2026-07-10T00:00:00+00:00",
        updated_at="2026-07-10T00:00:00+00:00",
        resolved_at=None,
        deleted_at=None,
    )

    assert impact_on_project.bug_uuid == impact_on_file.bug_uuid
    assert impact_on_project.impact_uuid != impact_on_file.impact_uuid
    assert impact_on_project.target_type != impact_on_file.target_type
    assert impact_on_file.target_file_path == "src/adapter/client.py"


def test_bug_impact_skipped_status_is_a_recognized_status() -> None:
    assert BugImpactStatus.SKIPPED.value in BUG_IMPACT_STATUSES


def test_suspected_impact_targets_returns_transitive_reverse_dependents() -> None:
    source_project = uuid.UUID("00000000-0000-0000-0000-000000000001")
    direct_dependent = uuid.UUID("00000000-0000-0000-0000-000000000002")
    transitive_dependent = uuid.UUID("00000000-0000-0000-0000-000000000003")

    edges = [
        (str(direct_dependent), str(source_project)),
        (str(transitive_dependent), str(direct_dependent)),
    ]

    result = suspected_impact_targets(edges, source_project)

    assert result == [direct_dependent, transitive_dependent]
    assert source_project not in result


def test_suspected_impact_targets_excludes_unrelated_projects() -> None:
    source_project = uuid.UUID("00000000-0000-0000-0000-000000000001")
    dependent = uuid.UUID("00000000-0000-0000-0000-000000000002")
    unrelated_a = uuid.UUID("00000000-0000-0000-0000-000000000004")
    unrelated_b = uuid.UUID("00000000-0000-0000-0000-000000000005")

    edges = [
        (str(dependent), str(source_project)),
        (str(unrelated_a), str(unrelated_b)),
    ]

    result = suspected_impact_targets(edges, source_project)

    assert result == [dependent]


def test_suspected_impact_targets_empty_when_no_dependents() -> None:
    source_project = uuid.UUID("00000000-0000-0000-0000-000000000001")
    other_project = uuid.UUID("00000000-0000-0000-0000-000000000002")

    edges = [(str(source_project), str(other_project))]

    result = suspected_impact_targets(edges, source_project)

    assert result == []
