"""Regression test for bug 85a9d14b: wave partitioning must inherit ancestor
depends_on constraints, because step_dependency cannot express them below the
target sibling level.
"""

from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges, waves
from plan_manager.verify.gate_data import artifact_path_of


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000851")


def _step(
    step_uuid: str,
    *,
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    depends_on: list[str] | None = None,
) -> Step:
    return Step(
        uuid=uuid.UUID(step_uuid),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields={},
        depends_on=list(depends_on or []),
        concepts=[],
        project_id=None,
        status="frozen",
    )


def _wave_index(nodes: dict[uuid.UUID, Step], rows: list[list[uuid.UUID]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, row in enumerate(rows):
        for node_uuid in row:
            result[artifact_path_of(nodes, nodes[node_uuid])] = index
    return result


def test_waves_inherit_ancestor_depends_on_constraints() -> None:
    g1 = _step("00000000-0000-0000-0000-000000000111", level=3, step_id="G-001", parent_step_uuid=None)
    t1 = _step("00000000-0000-0000-0000-000000000112", level=4, step_id="T-001", parent_step_uuid=g1.uuid)
    a1 = _step("00000000-0000-0000-0000-000000000113", level=5, step_id="A-001", parent_step_uuid=t1.uuid)

    g2 = _step(
        "00000000-0000-0000-0000-000000000121",
        level=3,
        step_id="G-002",
        parent_step_uuid=None,
        depends_on=["G-001"],
    )
    t2 = _step("00000000-0000-0000-0000-000000000122", level=4, step_id="T-001", parent_step_uuid=g2.uuid)
    a2 = _step("00000000-0000-0000-0000-000000000123", level=5, step_id="A-001", parent_step_uuid=t2.uuid)
    nodes = {step.uuid: step for step in (g1, t1, a1, g2, t2, a2)}

    wave_index = _wave_index(nodes, waves(nodes, build_edges(nodes)))

    assert wave_index["G-001"] < wave_index["G-002"]
    assert wave_index["G-002/T-001"] >= wave_index["G-002"]
    assert wave_index["G-002/T-001/A-001"] >= wave_index["G-002"]
