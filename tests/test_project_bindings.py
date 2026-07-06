import uuid

import pytest

from plan_manager.commands.errors import DomainCommandError
from plan_manager.commands.info_command import InfoCommand
from plan_manager.commands.info_reference import planning_standards_reference
from plan_manager.commands.step_update_command import StepUpdateCommand
from plan_manager.domain.plan import Plan
from plan_manager.domain.project_binding import (
    attach_project,
    clear_primary_project,
    detach_project,
    normalize_project_id,
    require_project_bound,
    set_primary_project,
    validate_plan_projects,
)
from plan_manager.domain.step import Step


PROJECT_1 = "4acd4be1-d166-417d-81c6-76bf77b4a392"
PROJECT_2 = "28d6b6dc-391d-4f49-9c87-d7c88fcadf1a"


def _plan(project_ids: list[str] | None = None, primary_project_id: str | None = None) -> Plan:
    return Plan(
        uuid=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        name="workmgr",
        status="draft",
        context_budget=4000,
        head_revision_uuid=None,
        project_ids=project_ids or [],
        primary_project_id=primary_project_id,
    )


def _domain_code(excinfo) -> str:
    return excinfo.value.code


class FakeConn:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []

    def execute(self, sql: str, params: tuple) -> None:
        self.statements.append((sql, params))


def _step(
    step_uuid: str,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    project_id: str | None,
) -> Step:
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields={},
        depends_on=[],
        concepts=[],
        project_id=project_id,
        status="draft",
    )


def test_plan_without_projects_is_valid() -> None:
    validate_plan_projects([], None)


def test_attach_project_uuid_normalizes() -> None:
    assert normalize_project_id(PROJECT_1.upper()) == PROJECT_1


def test_duplicate_project_binding_rejected() -> None:
    with pytest.raises(DomainCommandError) as excinfo:
        validate_plan_projects([PROJECT_1, PROJECT_1], None)
    assert _domain_code(excinfo) == "DUPLICATE_PROJECT_BINDING"


def test_primary_project_must_be_bound() -> None:
    with pytest.raises(DomainCommandError) as excinfo:
        validate_plan_projects([PROJECT_1], PROJECT_2)
    assert _domain_code(excinfo) == "PRIMARY_PROJECT_NOT_BOUND"


def test_invalid_project_id_rejected() -> None:
    with pytest.raises(DomainCommandError) as excinfo:
        normalize_project_id("not-a-uuid")
    assert _domain_code(excinfo) == "INVALID_PROJECT_ID"


def test_step_project_must_be_bound_to_plan() -> None:
    with pytest.raises(DomainCommandError) as excinfo:
        require_project_bound(_plan([PROJECT_1]), PROJECT_2)
    assert _domain_code(excinfo) == "PROJECT_NOT_BOUND_TO_PLAN"


def test_step_project_bound_to_plan_is_accepted() -> None:
    assert require_project_bound(_plan([PROJECT_1]), PROJECT_1) == PROJECT_1


def test_step_update_schema_preserves_explicit_null_project_id() -> None:
    command = StepUpdateCommand()
    params = command.validate_params(
        {"plan": "workmgr", "step_id": "G-001", "project_id": None}
    )
    assert "project_id" in params
    assert params["project_id"] is None


def test_step_update_accepts_project_id_as_only_patch() -> None:
    command = StepUpdateCommand()
    params = command.validate_params(
        {"plan": "workmgr", "step_id": "G-001", "project_id": PROJECT_1}
    )
    assert params["project_id"] == PROJECT_1


def test_plan_project_attach_adds_project_without_primary() -> None:
    conn = FakeConn()
    updated, already_exists = attach_project(conn, _plan(), PROJECT_1)
    assert already_exists is False
    assert updated.project_ids == [PROJECT_1]
    assert updated.primary_project_id is None


def test_plan_project_attach_primary_sets_primary() -> None:
    conn = FakeConn()
    updated, already_exists = attach_project(conn, _plan(), PROJECT_1, primary=True)
    assert already_exists is False
    assert updated.project_ids == [PROJECT_1]
    assert updated.primary_project_id == PROJECT_1


def test_plan_project_attach_is_idempotent() -> None:
    conn = FakeConn()
    updated, already_exists = attach_project(conn, _plan([PROJECT_1]), PROJECT_1)
    assert already_exists is True
    assert updated.project_ids == [PROJECT_1]


def test_plan_project_set_primary_requires_existing_binding() -> None:
    conn = FakeConn()
    updated = set_primary_project(conn, _plan([PROJECT_1, PROJECT_2]), PROJECT_2)
    assert updated.primary_project_id == PROJECT_2


def test_plan_project_clear_primary_keeps_project_ids() -> None:
    conn = FakeConn()
    updated = clear_primary_project(conn, _plan([PROJECT_1], PROJECT_1))
    assert updated.project_ids == [PROJECT_1]
    assert updated.primary_project_id is None


def test_plan_project_detach_clears_matching_step_bindings(monkeypatch) -> None:
    conn = FakeConn()
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None, PROJECT_1)
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid, PROJECT_1)
    other = _step("00000000-0000-0000-0000-000000000013", 3, "G-002", None, PROJECT_2)
    monkeypatch.setattr(
        "plan_manager.domain.project_binding.load_steps",
        lambda _conn, _plan_uuid: {step.uuid: step for step in (gs, ts, other)},
    )

    result = detach_project(conn, _plan([PROJECT_1, PROJECT_2], PROJECT_1), PROJECT_1)

    assert result["project_ids"] == [PROJECT_2]
    assert result["cleared_primary"] is True
    assert result["affected_steps"] == ["G-001", "G-001/T-001"]
    assert conn.statements[-1][0].startswith("UPDATE step SET project_id = NULL")


def test_plan_project_detach_rejects_unattached_project() -> None:
    conn = FakeConn()
    with pytest.raises(DomainCommandError) as excinfo:
        detach_project(conn, _plan([PROJECT_1]), PROJECT_2)
    assert _domain_code(excinfo) == "PROJECT_NOT_ATTACHED_TO_PLAN"


def test_info_exposes_planning_standards_glossary_section() -> None:
    schema = InfoCommand.get_schema()
    metadata = InfoCommand.metadata()
    enum = schema["properties"]["section"]["enum"]

    assert "planning_standards" in enum
    assert metadata["parameters"]["section"]["enum"] == enum

    glossary = planning_standards_reference()
    assert set(glossary["artifact_levels"]) == {"HRS", "MRS", "GS", "TS", "AS"}
    assert "concept_axis" in glossary["coverage_axes"]
    assert "owner" in glossary["execution_delegation"]
    assert "get_schema" in glossary["command_metadata_standard"]
