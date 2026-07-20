from __future__ import annotations

import uuid

from plan_manager.domain.step import Step
from plan_manager.verify.gate_structure import _additional_write_targets
from plan_manager.views.dependency_graph import build_edges, waves
from plan_manager.views.same_file_order import SameFileOrderAmbiguousError, same_file_order_conflicts

PLAN = uuid.uuid4()


def make_step(level: int, step_id: str, parent: uuid.UUID | None, *, target: str | None = None, priority: int = 1, depends: list[str] | None = None, prompt: str = "") -> Step:
    fields = {"name": step_id}
    if level == 5:
        fields.update({"target_file": target, "priority": priority, "operation": "modify_file", "prompt": prompt, "verification": "pytest tests/test_x.py"})
    return Step(uuid=uuid.uuid4(), plan_uuid=PLAN, parent_step_uuid=parent, level=level, step_id=step_id, slug=step_id.lower(), fields=fields, depends_on=depends or [], concepts=[], project_id=None, status="draft")


def test_second_explicit_write_target_is_detected_but_read_reference_is_not() -> None:
    atomic = make_step(5, "A-001", uuid.uuid4(), target="src/main.py", prompt="Modify src/main.py and edit src/other.py. Read src/context.py for context.")
    assert _additional_write_targets(atomic, "src/main.py") == {"prompt": ["src/other.py"]}


def test_same_parent_same_file_is_serialized_by_priority() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    a2 = make_step(5, "A-002", ts.uuid, target="src/shared.py", priority=2)
    a1 = make_step(5, "A-001", ts.uuid, target="src/shared.py", priority=1)
    nodes = {x.uuid: x for x in (gs, ts, a1, a2)}
    edges = build_edges(nodes)
    assert (a1.uuid, a2.uuid) in edges
    assert same_file_order_conflicts(nodes, edges) == []
    atom_waves = [[u for u in wave if nodes[u].level == 5] for wave in waves(nodes, edges)]
    assert not any(a1.uuid in wave and a2.uuid in wave for wave in atom_waves)


def test_cross_branch_same_file_derives_order_from_ts_dependency() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])
    a1 = make_step(5, "A-001", ts1.uuid, target="src/shared.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/shared.py")
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    edges = build_edges(nodes)
    assert (a1.uuid, a2.uuid) in edges
    assert same_file_order_conflicts(nodes, edges) == []


def test_cross_branch_same_file_without_dependency_is_conflict() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    a1 = make_step(5, "A-001", ts1.uuid, target="src/shared.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/shared.py")
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    conflicts = same_file_order_conflicts(nodes, build_edges(nodes, strict_same_file_order=False))
    assert len(conflicts) == 1


def test_independent_files_remain_parallel() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    a1 = make_step(5, "A-001", ts1.uuid, target="src/one.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/two.py")
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    atom_waves = [[u for u in wave if nodes[u].level == 5] for wave in waves(nodes, build_edges(nodes))]
    assert any(a1.uuid in wave and a2.uuid in wave for wave in atom_waves)


def test_ambiguous_same_file_order_refuses_strict_graph_build() -> None:
    g1 = make_step(3, "G-001", None)
    g2 = make_step(3, "G-002", None)
    t1 = make_step(4, "T-001", g1.uuid)
    t2 = make_step(4, "T-001", g2.uuid)
    a1 = make_step(5, "A-001", t1.uuid, target="shared.py", priority=1)
    a2 = make_step(5, "A-001", t2.uuid, target="shared.py", priority=1)
    nodes = {s.uuid: s for s in (g1, g2, t1, t2, a1, a2)}
    try:
        build_edges(nodes)
    except SameFileOrderAmbiguousError as exc:
        assert exc.conflicts == [(a1.uuid, a2.uuid, "shared.py")]
    else:
        raise AssertionError("strict graph build must refuse ambiguous same-file writers")
