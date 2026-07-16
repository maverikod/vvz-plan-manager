import uuid

import pytest

from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges
from plan_manager.views.dependents_closure import transitive_closure

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
G_UUID = uuid.UUID("00000000-0000-0000-0000-000000000010")

def _global_step() -> Step:
    return Step(
        uuid=G_UUID,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=None,
        level=3,
        step_id="G-001",
        slug="g-001",
        fields={},
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )

def _tactical_step(step_uuid: str, step_id: str, depends_on: list[str]) -> Step:
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=G_UUID,
        level=4,
        step_id=step_id,
        slug=step_id.lower(),
        fields={},
        depends_on=depends_on,
        concepts=[],
        project_id=None,
        status="draft",
    )

def _build_chain():
    g = _global_step()
    t1 = _tactical_step("00000000-0000-0000-0000-000000000101", "T-001", [])
    t2 = _tactical_step("00000000-0000-0000-0000-000000000102", "T-002", ["T-001"])
    t3 = _tactical_step("00000000-0000-0000-0000-000000000103", "T-003", ["T-002"])
    t4 = _tactical_step("00000000-0000-0000-0000-000000000104", "T-004", ["T-002"])
    nodes = {s.uuid: s for s in (g, t1, t2, t3, t4)}
    edges = build_edges(nodes)
    return nodes, edges, t1, t2, t3, t4

def test_dependents_direction_reaches_full_transitive_closure() -> None:
    nodes, edges, t1, t2, t3, t4 = _build_chain()

    result = transitive_closure(nodes, edges, t1.uuid, "dependents", depth_limit=10)

    assert [nodes[u].step_id for u in result] == ["T-002", "T-003", "T-004"]

def test_dependents_direction_bounded_by_depth_limit() -> None:
    nodes, edges, t1, t2, t3, t4 = _build_chain()

    result = transitive_closure(nodes, edges, t1.uuid, "dependents", depth_limit=1)

    assert [nodes[u].step_id for u in result] == ["T-002"]

def test_dependencies_direction_reaches_full_transitive_closure() -> None:
    nodes, edges, t1, t2, t3, t4 = _build_chain()

    result = transitive_closure(nodes, edges, t4.uuid, "dependencies", depth_limit=10)

    assert [nodes[u].step_id for u in result] == ["T-001", "T-002"]

def test_depth_limit_zero_or_negative_returns_empty() -> None:
    nodes, edges, t1, t2, t3, t4 = _build_chain()

    assert transitive_closure(nodes, edges, t1.uuid, "dependents", depth_limit=0) == []
    assert transitive_closure(nodes, edges, t1.uuid, "dependents", depth_limit=-1) == []

def test_invalid_direction_raises_value_error() -> None:
    nodes, edges, t1, t2, t3, t4 = _build_chain()

    with pytest.raises(ValueError):
        transitive_closure(nodes, edges, t1.uuid, "sideways", depth_limit=10)
