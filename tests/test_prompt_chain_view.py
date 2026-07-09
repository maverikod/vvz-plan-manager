import uuid

import pytest

from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges
from plan_manager.views.prompt_chain import (
    _wave_data,
    cache_key,
    eligible_atomic_steps,
    normalize_role,
    normalize_scope,
    normalize_statuses,
    scope_atomic_steps,
)
from plan_manager.commands.plan_prompt_chain_command import PlanPromptChainCommand


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _step(
    step_uuid: str,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    status: str = "frozen",
) -> Step:
    fields = {}
    if level == 5:
        fields = {"target_file": "x.py", "operation": "update", "priority": 1}
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


def test_normalize_scope_accepts_whole_global_and_tactical() -> None:
    assert normalize_scope(None).label == "whole_plan"
    assert normalize_scope("whole_plan").label == "whole_plan"
    assert normalize_scope("G-001").label == "G-001"
    assert normalize_scope("G-001/T-002").label == "G-001/T-002"


def test_normalize_scope_rejects_unknown_shape() -> None:
    with pytest.raises(ValueError):
        normalize_scope("A-001")


def test_normalize_role_accepts_default_and_rejects_unknown() -> None:
    assert normalize_role(None) == "coder"
    assert normalize_role("review") == "review"
    with pytest.raises(ValueError):
        normalize_role("executor")


def test_normalize_statuses_defaults_and_rejects_unknown_values() -> None:
    assert normalize_statuses(None) == ["frozen", "ready_for_review"]
    with pytest.raises(ValueError):
        normalize_statuses(["frozen", "bogus"])


def test_cache_key_is_canonical_and_stable() -> None:
    assert cache_key({"b": 2, "a": 1}) == cache_key({"a": 1, "b": 2})


def test_plan_prompt_chain_schema_matches_rev2_contract() -> None:
    schema = PlanPromptChainCommand.get_schema()

    assert PlanPromptChainCommand.use_queue is True
    assert schema["required"] == ["plan"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["role"]["enum"] == ["coder", "review", "conscience"]
    assert schema["properties"]["role"]["default"] == "coder"
    assert schema["properties"]["include_statuses"]["default"] == [
        "frozen",
        "ready_for_review",
    ]


def test_scope_and_status_filter_select_atomic_branch_chain() -> None:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None)
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid)
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid)
    draft_atomic = _step(
        "00000000-0000-0000-0000-000000000014",
        5,
        "A-002",
        ts.uuid,
        status="draft",
    )
    nodes = {step.uuid: step for step in (gs, ts, atomic, draft_atomic)}

    scoped = scope_atomic_steps(nodes, normalize_scope("G-001/T-001"))
    assert [step.step_id for step in scoped] == ["A-001", "A-002"]

    eligible = eligible_atomic_steps(nodes, scoped, ["frozen", "ready_for_review"])
    assert [step.step_id for step in eligible] == ["A-001"]


def _atomic(
    step_uuid: str,
    step_id: str,
    parent_step_uuid: uuid.UUID,
    target_file: str,
    priority: int = 1,
    depends_on: list[str] | None = None,
) -> Step:
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_step_uuid,
        level=5,
        step_id=step_id,
        slug=step_id.lower(),
        fields={
            "target_file": target_file,
            "operation": "create_file",
            "priority": priority,
            "prompt": "",
        },
        depends_on=depends_on or [],
        concepts=[],
        project_id=None,
        status="frozen",
    )


def _repeated_id_nodes() -> dict[uuid.UUID, Step]:
    """Two branches whose local A-001/T-001 ids repeat under different parents."""
    g1 = _step("00000000-0000-0000-0000-0000000000a1", 3, "G-001", None)
    t1 = _step("00000000-0000-0000-0000-0000000000a2", 4, "T-001", g1.uuid)
    g2 = _step("00000000-0000-0000-0000-0000000000b1", 3, "G-002", None)
    t2 = _step("00000000-0000-0000-0000-0000000000b2", 4, "T-001", g2.uuid)
    a1 = _atomic("00000000-0000-0000-0000-0000000000a3", "A-001", t1.uuid, "a.py")
    a2 = _atomic("00000000-0000-0000-0000-0000000000a4", "A-002", t1.uuid, "b.py")
    a3 = _atomic("00000000-0000-0000-0000-0000000000b3", "A-001", t2.uuid, "c.py")
    return {s.uuid: s for s in (g1, t1, g2, t2, a1, a2, a3)}


def test_wave_data_whole_plan_resolves_repeated_atomic_parents() -> None:
    # Regression: BUG-PLAN-PROMPT-CHAIN-CYCLE-FROZEN-DOC-STORE (whole_plan)
    # previously raised "parent of step A-001 not found in nodes" because the
    # atomic-only wave set could not resolve TS/GS parents.
    nodes = _repeated_id_nodes()
    scoped = scope_atomic_steps(nodes, normalize_scope("whole_plan"))
    wave_rows, wave_index = _wave_data(scoped, build_edges(nodes), nodes)
    flat = [key for row in wave_rows for key in row]
    assert "G-001/T-001/A-001" in flat
    assert "G-002/T-001/A-001" in flat
    assert "G-001/T-001/A-002" in flat
    assert len(flat) == len(scoped)
    assert len(wave_index) == len(scoped)


def test_wave_data_scoped_tactical_no_false_cycle() -> None:
    # Regression: scoped prompt-chain previously raised CYCLE_DETECTED on a
    # mechanically valid tactical scope.
    nodes = _repeated_id_nodes()
    scoped = scope_atomic_steps(nodes, normalize_scope("G-001/T-001"))
    wave_rows, _ = _wave_data(scoped, build_edges(nodes), nodes)
    flat = [key for row in wave_rows for key in row]
    assert flat == ["G-001/T-001/A-001", "G-001/T-001/A-002"]


def test_wave_data_reports_canonical_cycle_path() -> None:
    # A genuine cycle must surface a concrete canonical cycle path, not a
    # bare "cycle detected".
    g1 = _step("00000000-0000-0000-0000-0000000000c1", 3, "G-001", None)
    t1 = _step("00000000-0000-0000-0000-0000000000c2", 4, "T-001", g1.uuid)
    a1 = _atomic(
        "00000000-0000-0000-0000-0000000000c3", "A-001", t1.uuid, "a.py",
        depends_on=["A-002"],
    )
    a2 = _atomic(
        "00000000-0000-0000-0000-0000000000c4", "A-002", t1.uuid, "b.py",
        depends_on=["A-001"],
    )
    nodes = {s.uuid: s for s in (g1, t1, a1, a2)}
    scoped = scope_atomic_steps(nodes, normalize_scope("G-001/T-001"))
    with pytest.raises(ValueError) as excinfo:
        _wave_data(scoped, build_edges(nodes), nodes)
    message = str(excinfo.value)
    assert message.startswith("cycle detected:")
    assert "G-001/T-001/A-001" in message
    assert "G-001/T-001/A-002" in message
