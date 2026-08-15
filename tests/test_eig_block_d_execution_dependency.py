"""Tests for EIG block D (todo 004cd507): execution_dependency_suggest /
execution_dependency_apply.

Mirrors this suite's established conventions: view/ops-level tests build Step
objects in-memory (as tests/test_eig_block_b_execution_graph.py does, never a
live Postgres), and command-level tests drive execute() against an in-memory
node store with db_connection/resolve_plan/load_steps/persist_changes/
head_revision_str monkeypatched (the _Store/_wire pattern of
tests/test_step_dependency_same_file_admission.py).
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import uuid
from contextlib import contextmanager
from typing import Optional

from plan_manager.commands import (
    execution_dependency_apply_command,
    execution_dependency_suggest_command,
)
from plan_manager.commands.execution_dependency_apply_command import (
    ExecutionDependencyApplyCommand,
)
from plan_manager.commands.execution_dependency_ops import compute_suggested_changes
from plan_manager.commands.execution_dependency_suggest_command import (
    ExecutionDependencySuggestCommand,
)
from plan_manager.domain.plan import Plan
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges, waves

PLAN_UUID = uuid.uuid4()


def make_step(
    level: int,
    step_id: str,
    parent: uuid.UUID | None,
    *,
    target: str | None = None,
    priority: int = 1,
    depends: list[str] | None = None,
    operation: str = "modify_file",
    objects: list[dict] | None = None,
) -> Step:
    fields: dict = {"name": step_id}
    if level == 5:
        fields.update(
            {
                "target_file": target,
                "priority": priority,
                "operation": operation,
                "prompt": "",
                "verification": "pytest tests/test_x.py",
            }
        )
        if objects is not None:
            fields["objects"] = objects
    return Step(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields=fields,
        depends_on=depends or [],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _path(nodes: dict[uuid.UUID, Step], step: Step) -> str:
    from plan_manager.views.step_paths import parent_path

    if step.level == 3:
        return step.step_id
    return f"{parent_path(nodes, step)}/{step.step_id}"


# ---------------------------------------------------------------------------
# compute_suggested_changes: pure ops-level coverage
# ---------------------------------------------------------------------------


def test_suggest_returns_unambiguous_edge_as_applicable_proposal() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2,
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}
    proposal = compute_suggested_changes(nodes)

    producer_path = _path(nodes, producer)
    consumer_path = _path(nodes, consumer)
    assert proposal["proposed_changes"] == [
        {"op": "add", "step_id": consumer_path, "depends_on": [producer_path]}
    ]
    assert len(proposal["proposed_edges"]) == 1
    edge = proposal["proposed_edges"][0]
    assert edge["from"] == producer_path and edge["to"] == consumer_path
    assert edge["type"] == "object_producer"
    assert edge["provenance"] == "inferred"
    assert edge["evidence"] == {
        "object": "widget_schema",
        "producer_role": "create",
        "consumer_role": "consume",
    }
    assert proposal["ambiguous_dependencies"] == []


def test_suggest_cross_branch_edge_uses_full_canonical_paths_directly() -> None:
    """The cross-branch ancestor rule: no GS/TS depends_on lifting.

    Producer and consumer sit under different TS parents of the same GS, with
    no ancestor-level depends_on establishing branch order. The proposal must
    still name the edge directly at the atomic (level-5) step's own level,
    using full canonical paths on both sides, per
    step_dependency_ops.resolve_dependency_bare's level-5-to-level-5
    cross-branch exception (see tests/test_cross_branch_step_dependencies.py)
    -- never lifted to a GS/TS-level depends_on the way same-file ordering
    needs derive_cross_branch_edges/waves() inheritance for.
    """
    gs = make_step(3, "G-001", None)
    ts_left = make_step(4, "T-001", gs.uuid)
    ts_right = make_step(4, "T-002", gs.uuid)
    producer = make_step(
        5, "A-001", ts_left.uuid, target="src/schema.py",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-001", ts_right.uuid, target="src/consumer.py",
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts_left, ts_right, producer, consumer)}
    proposal = compute_suggested_changes(nodes)

    producer_path = _path(nodes, producer)  # "G-001/T-001/A-001"
    consumer_path = _path(nodes, consumer)  # "G-001/T-002/A-001"
    assert "/" in producer_path and "/" in consumer_path
    change = proposal["proposed_changes"]
    assert change == [{"op": "add", "step_id": consumer_path, "depends_on": [producer_path]}]

    # The proposal is directly applicable: step_dependency_ops resolves the
    # canonical-path cross-branch reference and build_edges honors it.
    from plan_manager.commands.step_dependency_ops import persist_changes, plan_changes

    new_by_uuid = plan_changes(nodes, change)
    sim = dict(nodes)
    for target_uuid, deps in new_by_uuid.items():
        sim[target_uuid] = dataclasses.replace(nodes[target_uuid], depends_on=list(deps))
    edges = build_edges(sim, strict_same_file_order=False)
    assert (producer.uuid, consumer.uuid) in edges
    assert persist_changes  # imported to document the real mutation path exists; not invoked here


def test_ambiguous_object_edges_excluded_and_reported() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    p1 = make_step(
        5, "A-001", ts.uuid, target="src/one.py",
        objects=[{"name": "shared_object", "concepts": [], "role": "create"}],
    )
    p2 = make_step(
        5, "A-002", ts.uuid, target="src/two.py", priority=2,
        objects=[{"name": "shared_object", "concepts": [], "role": "modify"}],
    )
    consumer = make_step(
        5, "A-003", ts.uuid, target="src/three.py", priority=3,
        objects=[{"name": "shared_object", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, p1, p2, consumer)}
    proposal = compute_suggested_changes(nodes)

    assert proposal["proposed_changes"] == []
    assert proposal["proposed_edges"] == []
    p1_path, p2_path = sorted([_path(nodes, p1), _path(nodes, p2)])
    assert proposal["ambiguous_dependencies"] == [
        {"object": "shared_object", "producers": [p1_path, p2_path]}
    ]


def test_already_explicit_edge_is_excluded() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2,
        depends=["A-001"],
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}
    proposal = compute_suggested_changes(nodes)
    assert proposal["proposed_changes"] == []
    assert proposal["proposed_edges"] == []


def test_transitively_implied_edge_is_excluded() -> None:
    """A1 -> A2 -> A3 explicit chain already orders A1 before A3; the
    object_producer edge A1->A3 is redundant even though never declared
    directly, and must be excluded (reachable(), not just direct presence)."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    a1 = make_step(
        5, "A-001", ts.uuid, target="src/one.py",
        objects=[{"name": "obj", "concepts": [], "role": "create"}],
    )
    a2 = make_step(5, "A-002", ts.uuid, target="src/two.py", priority=2, depends=["A-001"])
    a3 = make_step(
        5, "A-003", ts.uuid, target="src/three.py", priority=3, depends=["A-002"],
        objects=[{"name": "obj", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, a1, a2, a3)}
    proposal = compute_suggested_changes(nodes)
    assert proposal["proposed_changes"] == []
    assert proposal["proposed_edges"] == []


def test_determinism_of_suggest_output() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    p = make_step(
        5, "A-001", ts1.uuid, target="src/schema.py",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    c = make_step(
        5, "A-001", ts2.uuid, target="src/consumer.py",
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts1, ts2, p, c)}
    first = compute_suggested_changes(nodes)
    second = compute_suggested_changes(nodes)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# Command-level: in-memory node store, execute()
# ---------------------------------------------------------------------------


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
        self.revisions: list[tuple[uuid.UUID, str]] = []

    def load(self, conn, plan_uuid):
        return dict(self.nodes)

    def persist(self, conn, plan, new_by_uuid, cascade_uuid, message):
        for target_uuid, deps in new_by_uuid.items():
            self.nodes[target_uuid] = dataclasses.replace(self.nodes[target_uuid], depends_on=list(deps))
        rev = uuid.uuid4()
        self.revisions.append((rev, message))
        return rev


def _wire_suggest(monkeypatch, store: _Store) -> None:
    monkeypatch.setattr(execution_dependency_suggest_command, "db_connection", _fake_db)
    monkeypatch.setattr(execution_dependency_suggest_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(execution_dependency_suggest_command, "load_steps", store.load)


def _wire_apply(monkeypatch, store: _Store) -> None:
    monkeypatch.setattr(execution_dependency_apply_command, "db_connection", _fake_db)
    monkeypatch.setattr(execution_dependency_apply_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(execution_dependency_apply_command, "load_steps", store.load)
    monkeypatch.setattr(execution_dependency_apply_command, "persist_changes", store.persist)
    monkeypatch.setattr(execution_dependency_apply_command, "head_revision_str", lambda conn, plan: "head-rev-stub")


def _one_edge_nodes() -> tuple[dict[uuid.UUID, Step], Step, Step]:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2,
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}
    return nodes, producer, consumer


def test_suggest_command_payload_shape(monkeypatch) -> None:
    nodes, producer, consumer = _one_edge_nodes()
    store = _Store(nodes)
    _wire_suggest(monkeypatch, store)

    result = asyncio.run(ExecutionDependencySuggestCommand().execute(plan="p"))
    data = result.to_dict()["data"]
    producer_path = _path(nodes, producer)
    consumer_path = _path(nodes, consumer)
    assert data["proposed_changes"] == [
        {"op": "add", "step_id": consumer_path, "depends_on": [producer_path]}
    ]
    assert data["total_proposed_edges"] == 1
    assert len(data["proposed_edges"]) == 1
    assert data["summary"]["proposed_step_count"] == 1
    assert data["ambiguous_dependencies"] == []
    assert data["missing_producers"] == []


def test_apply_dry_run_default_mutates_nothing(monkeypatch) -> None:
    nodes, producer, consumer = _one_edge_nodes()
    store = _Store(nodes)
    _wire_apply(monkeypatch, store)
    original_snapshot = dict(store.nodes)
    consumer_path = _path(nodes, consumer)
    producer_path = _path(nodes, producer)

    result = asyncio.run(
        ExecutionDependencyApplyCommand().execute(
            plan="p",
            changes=[{"op": "add", "step_id": consumer_path, "depends_on": [producer_path]}],
        )
    )
    data = result.to_dict()["data"]
    assert data["dry_run"] is True
    assert data["applied"] is False
    for u, step in store.nodes.items():
        assert step.depends_on == original_snapshot[u].depends_on
    assert store.revisions == []


def test_apply_real_persists_one_revision_and_waves_shift(monkeypatch) -> None:
    nodes, producer, consumer = _one_edge_nodes()
    store = _Store(nodes)
    _wire_apply(monkeypatch, store)
    consumer_path = _path(nodes, consumer)
    producer_path = _path(nodes, producer)

    edges_before = build_edges(nodes, strict_same_file_order=False)
    waves_before = waves(nodes, edges_before)
    same_wave_before = any(
        producer.uuid in wave and consumer.uuid in wave for wave in waves_before
    )
    assert same_wave_before  # no ordering between them yet

    result = asyncio.run(
        ExecutionDependencyApplyCommand().execute(
            plan="p",
            changes=[{"op": "add", "step_id": consumer_path, "depends_on": [producer_path]}],
            dry_run=False,
        )
    )
    data = result.to_dict()["data"]
    assert data["applied"] is True
    assert len(store.revisions) == 1
    assert data["changes_applied"] == [
        {"op": "add", "step_id": consumer_path, "depends_on": [producer_path]}
    ]

    edges_after = build_edges(store.nodes, strict_same_file_order=False)
    waves_after = waves(store.nodes, edges_after)
    producer_wave = next(i for i, wave in enumerate(waves_after) if producer.uuid in wave)
    consumer_wave = next(i for i, wave in enumerate(waves_after) if consumer.uuid in wave)
    assert consumer_wave > producer_wave


def test_apply_confirm_true_recomputes_and_applies_current_proposal(monkeypatch) -> None:
    nodes, producer, consumer = _one_edge_nodes()
    store = _Store(nodes)
    _wire_apply(monkeypatch, store)
    consumer_path = _path(nodes, consumer)
    producer_path = _path(nodes, producer)

    result = asyncio.run(
        ExecutionDependencyApplyCommand().execute(plan="p", confirm=True, dry_run=False)
    )
    data = result.to_dict()["data"]
    assert data["applied"] is True
    assert data["changes_applied"] == [
        {"op": "add", "step_id": consumer_path, "depends_on": [producer_path]}
    ]
    # producer/consumer are siblings here, so the stored form is the bare
    # sibling step_id (resolve_dependency_bare), not the full canonical path.
    assert store.nodes[consumer.uuid].depends_on == ["A-001"]


def test_apply_without_changes_or_confirm_is_invalid_params() -> None:
    from mcp_proxy_adapter.core.errors import InvalidParamsError

    try:
        ExecutionDependencyApplyCommand().validate_params({"plan": "p"})
        raise AssertionError("expected InvalidParamsError")
    except InvalidParamsError as exc:
        assert "confirm" in str(exc)


def test_apply_cycle_refusal_matches_step_dependency_apply(monkeypatch) -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    a1 = make_step(5, "A-001", ts.uuid, target="src/one.py")
    a2 = make_step(5, "A-002", ts.uuid, target="src/two.py", priority=2, depends=["A-001"])
    nodes = {x.uuid: x for x in (gs, ts, a1, a2)}
    store = _Store(nodes)
    _wire_apply(monkeypatch, store)
    original_snapshot = dict(store.nodes)

    result = asyncio.run(
        ExecutionDependencyApplyCommand().execute(
            plan="p",
            changes=[{"op": "add", "step_id": "A-001", "depends_on": ["A-002"]}],
            dry_run=False,
        )
    )
    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "DEPENDENCY_CYCLE"
    for u, step in store.nodes.items():
        assert step.depends_on == original_snapshot[u].depends_on
    assert store.revisions == []


def test_apply_same_file_ambiguity_refusal_matches_step_dependency_apply(monkeypatch) -> None:
    gs = make_step(3, "G-001", None)
    t1 = make_step(4, "T-001", gs.uuid)
    t2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])  # resolves the same-file pair
    a1 = make_step(5, "A-001", t1.uuid, target="shared.md")
    a2 = make_step(5, "A-001", t2.uuid, target="shared.md")
    nodes = {x.uuid: x for x in (gs, t1, t2, a1, a2)}
    store = _Store(nodes)
    _wire_apply(monkeypatch, store)
    original_snapshot = dict(store.nodes)

    result = asyncio.run(
        ExecutionDependencyApplyCommand().execute(
            plan="p",
            changes=[{"op": "clear", "step_id": "T-002"}],  # un-resolves the same-file pair
            dry_run=False,
        )
    )
    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "AS_SAME_FILE_ORDER_AMBIGUOUS"
    for u, step in store.nodes.items():
        assert step.depends_on == original_snapshot[u].depends_on
    assert store.revisions == []
