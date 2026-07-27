"""Regression coverage for explicit cross-branch atomic dependencies.

The legacy step_dependency surface only persisted bare sibling step_ids, so an
atomic step could not depend explicitly on an atomic step under a different
tactical parent. The fix keeps sibling bare ids intact and stores cross-branch
atomic targets as canonical step paths, which the graph, gate, and command
surfaces must all resolve consistently.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from contextlib import contextmanager

from plan_manager.commands import (
    step_dependency_add_command,
    step_dependency_list_command,
    step_dependency_remove_command,
)
from plan_manager.commands.step_dependency_add_command import StepDependencyAddCommand
from plan_manager.commands.step_dependency_list_command import StepDependencyListCommand
from plan_manager.commands.step_dependency_remove_command import StepDependencyRemoveCommand
from plan_manager.domain.plan import Plan
from plan_manager.domain.step import Step, validate_step
from plan_manager.scoring.estimators import reference_estimator
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_refs import check_references_depends_on
from plan_manager.views.branch import Branch
from plan_manager.views.dependency_graph import build_edges


PLAN_UUID = uuid.uuid4()


def _step(
    level: int,
    step_id: str,
    parent_step_uuid: uuid.UUID | None,
    *,
    depends_on: list[str] | None = None,
) -> Step:
    fields = {}
    if level == 5:
        fields = {
            "target_file": f"{step_id.lower()}.py",
            "priority": 1,
            "operation": "modify_file",
            "prompt": step_id,
        }
    return Step(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_step_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields,
        depends_on=depends_on or [],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _nodes() -> dict[uuid.UUID, Step]:
    gs = _step(3, "G-001", None)
    ts_left = _step(4, "T-001", gs.uuid)
    ts_right = _step(4, "T-002", gs.uuid)
    atomic_left = _step(5, "A-001", ts_left.uuid)
    atomic_right = _step(
        5,
        "A-002",
        ts_right.uuid,
        depends_on=["G-001/T-001/A-001"],
    )
    return {
        step.uuid: step
        for step in (gs, ts_left, ts_right, atomic_left, atomic_right)
    }


def _tree(nodes: dict[uuid.UUID, Step]) -> GateTree:
    return GateTree(steps=nodes, concept_ids=[], relations=[], labels=[], counts={})


def test_validate_step_accepts_canonical_path_dependency_ref() -> None:
    nodes = _nodes()
    atomic_right = next(step for step in nodes.values() if step.step_id == "A-002")
    validate_step(atomic_right)


def test_build_edges_resolves_cross_branch_atomic_canonical_path() -> None:
    nodes = _nodes()
    edges = build_edges(nodes, strict_same_file_order=False)
    atomic_left = next(step for step in nodes.values() if step.step_id == "A-001")
    atomic_right = next(step for step in nodes.values() if step.step_id == "A-002")
    assert (atomic_left.uuid, atomic_right.uuid) in edges


def test_gate_references_accept_cross_branch_atomic_canonical_path() -> None:
    nodes = _nodes()
    atomic_right = next(step for step in nodes.values() if step.step_id == "A-002")
    findings = check_references_depends_on(_tree(nodes), [atomic_right])
    assert findings == []


def test_reference_estimator_counts_cross_branch_atomic_dependency_as_resolved() -> None:
    nodes = _nodes()
    gs = next(step for step in nodes.values() if step.level == 3)
    ts_right = next(step for step in nodes.values() if step.step_id == "T-002")
    atomic_right = next(step for step in nodes.values() if step.step_id == "A-002")
    branch = Branch(plan_uuid=PLAN_UUID, gs=gs, ts=ts_right, atomic=atomic_right, hrs_slice=[])
    assert reference_estimator(None, branch, [], nodes) == 1.0


@contextmanager
def _fake_db():
    yield object()


def _plan() -> Plan:
    return Plan(
        uuid=PLAN_UUID,
        name="throwaway",
        status="draft",
        context_budget=4000,
        head_revision_uuid=uuid.uuid4(),
        project_ids=[],
        primary_project_id=None,
    )


class _Store:
    def __init__(self, nodes: dict[uuid.UUID, Step]) -> None:
        self.nodes = dict(nodes)

    def load(self, conn, plan_uuid):
        return dict(self.nodes)

    def persist(self, conn, plan, new_by_uuid, cascade_uuid, message):
        for target_uuid, deps in new_by_uuid.items():
            self.nodes[target_uuid] = dataclasses.replace(
                self.nodes[target_uuid], depends_on=list(deps)
            )
        return uuid.uuid4()


def _wire(monkeypatch, module, store: _Store, *, mutating: bool) -> None:
    monkeypatch.setattr(module, "db_connection", _fake_db)
    monkeypatch.setattr(module, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(module, "load_steps", store.load)
    monkeypatch.setattr(module, "head_revision_str", lambda conn, plan: "head-rev")
    if mutating:
        monkeypatch.setattr(module, "persist_changes", store.persist)


def test_add_list_and_remove_cross_branch_atomic_dependency(monkeypatch) -> None:
    nodes = _nodes()
    atomic_right = next(step for step in nodes.values() if step.step_id == "A-002")
    nodes[atomic_right.uuid] = dataclasses.replace(atomic_right, depends_on=[])
    store = _Store(nodes)
    _wire(monkeypatch, step_dependency_add_command, store, mutating=True)
    _wire(monkeypatch, step_dependency_list_command, store, mutating=False)
    _wire(monkeypatch, step_dependency_remove_command, store, mutating=True)

    add_result = asyncio.run(
        StepDependencyAddCommand().execute(
            plan="p",
            step_id="G-001/T-002/A-002",
            depends_on="G-001/T-001/A-001",
        )
    ).to_dict()
    assert add_result["success"] is True
    assert add_result["data"]["depends_on"] == ["G-001/T-001/A-001"]
    assert add_result["data"]["added"] == "G-001/T-001/A-001"

    target_list = asyncio.run(
        StepDependencyListCommand().execute(
            plan="p",
            step_id="G-001/T-002/A-002",
        )
    ).to_dict()
    assert target_list["success"] is True
    assert target_list["data"]["depends_on"] == ["G-001/T-001/A-001"]

    source_list = asyncio.run(
        StepDependencyListCommand().execute(
            plan="p",
            step_id="G-001/T-001/A-001",
        )
    ).to_dict()
    assert source_list["success"] is True
    assert source_list["data"]["dependents"] == ["G-001/T-002/A-002"]

    remove_result = asyncio.run(
        StepDependencyRemoveCommand().execute(
            plan="p",
            step_id="G-001/T-002/A-002",
            depends_on="G-001/T-001/A-001",
        )
    ).to_dict()
    assert remove_result["success"] is True
    assert remove_result["data"]["depends_on"] == []
    assert remove_result["data"]["removed"] == "G-001/T-001/A-001"
