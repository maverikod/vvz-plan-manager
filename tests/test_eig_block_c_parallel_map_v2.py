"""Tests for EIG block C (todo 12fd8a80): graph_parallel_map v2.

Covers plan_manager.views.parallel_map_ext (extended_edges, placement
reasons, critical path, conflict groups) and
plan_manager.commands.graph_parallel_map_command.GraphParallelMapCommand's
mode="explicit"/"extended" split. Mirrors this suite's established
conventions (see tests/test_eig_block_b_execution_graph.py): view-level
tests build Step objects in-memory, never a live Postgres; the command-level
tests drive execute() against a minimal fake connection covering exactly the
two read-only queries the command issues (resolve_plan's plan-by-uuid
select, load_steps's step select).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from typing import Optional

import pytest

from plan_manager.commands import graph_parallel_map_command
from plan_manager.commands.graph_parallel_map_command import GraphParallelMapCommand
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges, tie_break_key, waves
from plan_manager.views.execution_graph import build_execution_graph
from plan_manager.views.parallel_map_ext import (
    MODE_EXPLICIT,
    MODE_EXTENDED,
    build_conflict_groups,
    build_critical_path,
    build_placement_reasons,
    extended_edges,
)

PLAN = uuid.uuid4()


def make_step(
    level: int,
    step_id: str,
    parent: uuid.UUID | None,
    *,
    target: str | None = None,
    priority: int = 1,
    depends: list[str] | None = None,
    operation: str = "modify_file",
    verification: object = "pytest tests/test_x.py",
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
                "verification": verification,
            }
        )
        if objects is not None:
            fields["objects"] = objects
    return Step(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN,
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


def _wave_index(nodes: dict[uuid.UUID, Step], waves_rows: list[list[uuid.UUID]]) -> dict[str, int]:
    result: dict[str, int] = {}
    for index, row in enumerate(waves_rows):
        for node_uuid in row:
            result[_path(nodes, nodes[node_uuid])] = index
    return result


# ---------------------------------------------------------------------------
# extended_edges: combined edge set matches build_execution_graph exactly
# ---------------------------------------------------------------------------


def test_extended_edges_combined_set_matches_execution_graph() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2,
        objects=[{"name": "widget", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}

    uuid_edges, edge_dicts, graph = extended_edges(nodes)

    assert edge_dicts == graph["explicit_edges"] + graph["inferred_edges"]
    path_to_uuid = {_path(nodes, s): s.uuid for s in nodes.values()}
    rebuilt = {(path_to_uuid[e["from"]], path_to_uuid[e["to"]]) for e in edge_dicts}
    assert uuid_edges == rebuilt
    assert (producer.uuid, consumer.uuid) in uuid_edges


# ---------------------------------------------------------------------------
# contract-producer scenario: producer/consumer AS without explicit deps
# land in strictly later waves; independent consumers share one wave.
# ---------------------------------------------------------------------------


def test_producer_and_independent_consumers_without_explicit_deps() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget", "concepts": [], "role": "create"}],
    )
    consumer1 = make_step(
        5, "A-002", ts.uuid, target="src/c1.py", priority=2,
        objects=[{"name": "widget", "concepts": [], "role": "consume"}],
    )
    consumer2 = make_step(
        5, "A-003", ts.uuid, target="src/c2.py", priority=3,
        objects=[{"name": "widget", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer1, consumer2)}

    uuid_edges, _edge_dicts, _graph = extended_edges(nodes)
    w = waves(nodes, uuid_edges)
    index = _wave_index(nodes, w)

    assert index[_path(nodes, producer)] < index[_path(nodes, consumer1)]
    assert index[_path(nodes, producer)] < index[_path(nodes, consumer2)]
    assert index[_path(nodes, consumer1)] == index[_path(nodes, consumer2)]


# ---------------------------------------------------------------------------
# verification_target edge affects placement
# ---------------------------------------------------------------------------


def test_verification_target_edge_affects_placement() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    creator = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="create_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification={"type": "tests", "target": "src/widget.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, creator, verifier)}

    uuid_edges, _edge_dicts, _graph = extended_edges(nodes)
    w = waves(nodes, uuid_edges)
    index = _wave_index(nodes, w)

    assert index[_path(nodes, creator)] < index[_path(nodes, verifier)]


# ---------------------------------------------------------------------------
# placement_reasons name the pinning edges
# ---------------------------------------------------------------------------


def test_placement_reasons_name_pinning_edges() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2,
        objects=[{"name": "widget", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}

    uuid_edges, edge_dicts, _graph = extended_edges(nodes)
    reasons = build_placement_reasons(nodes, edge_dicts)

    producer_path = _path(nodes, producer)
    consumer_path = _path(nodes, consumer)
    assert reasons[producer_path] == []
    assert reasons[consumer_path] == [{"from": producer_path, "type": "object_producer"}]
    # wave-0 steps (gs, ts): no edge targets them or any ancestor.
    assert reasons[_path(nodes, gs)] == []
    assert reasons[_path(nodes, ts)] == []


def test_placement_reasons_are_empty_for_every_wave_zero_step() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget", "concepts": [], "role": "create"}],
    )
    consumer = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2,
        objects=[{"name": "widget", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer)}
    uuid_edges, edge_dicts, _graph = extended_edges(nodes)
    w = waves(nodes, uuid_edges)
    reasons = build_placement_reasons(nodes, edge_dicts)
    for node_uuid in w[0]:
        assert reasons[_path(nodes, nodes[node_uuid])] == []


# ---------------------------------------------------------------------------
# critical_path correctness on a known chain
# ---------------------------------------------------------------------------


def test_critical_path_on_a_known_three_step_chain() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    ts3 = make_step(4, "T-003", gs.uuid)
    a1 = make_step(
        5, "A-001", ts1.uuid, target="src/one.py", operation="create_file",
        objects=[{"name": "obj_a", "concepts": [], "role": "create"}],
    )
    a2 = make_step(
        5, "A-001", ts2.uuid, target="src/two.py",
        objects=[
            {"name": "obj_a", "concepts": [], "role": "consume"},
            {"name": "obj_b", "concepts": [], "role": "create"},
        ],
    )
    a3 = make_step(
        5, "A-001", ts3.uuid, target="src/three.py",
        objects=[{"name": "obj_b", "concepts": [], "role": "consume"}],
    )
    # An isolated singleton that must NOT win over the length-3 chain.
    isolated = make_step(5, "A-002", ts3.uuid, target="src/isolated.py", priority=2)
    nodes = {x.uuid: x for x in (gs, ts1, ts2, ts3, a1, a2, a3, isolated)}

    uuid_edges, _edge_dicts, _graph = extended_edges(nodes)
    chain = build_critical_path(nodes, uuid_edges)

    assert chain == [_path(nodes, a1), _path(nodes, a2), _path(nodes, a3)]


def test_critical_path_empty_for_empty_nodes() -> None:
    assert build_critical_path({}, set()) == []


# ---------------------------------------------------------------------------
# wave_parallelism (command-level; trivial derivation, see below)
# conflict_groups: same-file writers and same-object multi-producers
# ---------------------------------------------------------------------------


def test_conflict_groups_same_file_writers() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    a1 = make_step(5, "A-001", ts.uuid, target="src/shared.py", priority=1)
    a2 = make_step(5, "A-002", ts.uuid, target="src/shared.py", priority=2)
    nodes = {x.uuid: x for x in (gs, ts, a1, a2)}
    _uuid_edges, _edge_dicts, graph = extended_edges(nodes)

    groups = build_conflict_groups(nodes, graph)

    members = sorted([_path(nodes, a1), _path(nodes, a2)])
    assert {"type": "same_file_writers", "key": "src/shared.py", "members": members} in groups


def test_conflict_groups_same_object_producers() -> None:
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
    nodes = {x.uuid: x for x in (gs, ts, p1, p2)}
    _uuid_edges, _edge_dicts, graph = extended_edges(nodes)

    groups = build_conflict_groups(nodes, graph)

    p1_path, p2_path = sorted([_path(nodes, p1), _path(nodes, p2)])
    assert {
        "type": "same_object_producers",
        "key": "shared_object",
        "members": [p1_path, p2_path],
    } in groups


def test_conflict_groups_empty_when_no_conflicts() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    a1 = make_step(5, "A-001", ts.uuid, target="src/one.py")
    nodes = {x.uuid: x for x in (gs, ts, a1)}
    _uuid_edges, _edge_dicts, graph = extended_edges(nodes)
    assert build_conflict_groups(nodes, graph) == []


# ---------------------------------------------------------------------------
# determinism: two independent computations are byte-identical
# ---------------------------------------------------------------------------


def test_extended_payload_sections_are_deterministic_across_two_runs() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    producer = make_step(
        5, "A-001", ts.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget", "concepts": [], "role": "create"}],
    )
    consumer1 = make_step(
        5, "A-002", ts.uuid, target="src/c1.py", priority=2,
        objects=[{"name": "widget", "concepts": [], "role": "consume"}],
    )
    consumer2 = make_step(
        5, "A-003", ts.uuid, target="src/c2.py", priority=3,
        objects=[{"name": "widget", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, producer, consumer1, consumer2)}

    def _compute() -> dict:
        uuid_edges, edge_dicts, graph = extended_edges(nodes)
        w = waves(nodes, uuid_edges)
        return {
            "waves": [[_path(nodes, nodes[u]) for u in wave] for wave in w],
            "placement_reasons": build_placement_reasons(nodes, edge_dicts),
            "critical_path": build_critical_path(nodes, uuid_edges),
            "wave_parallelism": [len(wave) for wave in w],
            "conflict_groups": build_conflict_groups(nodes, graph),
        }

    first = _compute()
    second = _compute()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


# ---------------------------------------------------------------------------
# cycle over extended edges raises the same "cycle detected" ValueError
# waves() raises for explicit-mode cycles.
# ---------------------------------------------------------------------------


def test_cycle_over_extended_edges_raises_cycle_detected() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    ts3 = make_step(4, "T-003", gs.uuid)
    a1 = make_step(
        5, "A-001", ts1.uuid, target="src/one.py",
        objects=[
            {"name": "obj_a", "concepts": [], "role": "consume"},
            {"name": "obj_b", "concepts": [], "role": "create"},
        ],
    )
    a2 = make_step(
        5, "A-001", ts2.uuid, target="src/two.py",
        objects=[
            {"name": "obj_b", "concepts": [], "role": "consume"},
            {"name": "obj_c", "concepts": [], "role": "create"},
        ],
    )
    a3 = make_step(
        5, "A-001", ts3.uuid, target="src/three.py",
        objects=[
            {"name": "obj_c", "concepts": [], "role": "consume"},
            {"name": "obj_a", "concepts": [], "role": "create"},
        ],
    )
    nodes = {x.uuid: x for x in (gs, ts1, ts2, ts3, a1, a2, a3)}

    # No explicit depends_on: the cycle exists only once inferred edges fold in.
    assert waves(nodes, build_edges(nodes))  # explicit-only mode: no cycle

    uuid_edges, _edge_dicts, _graph = extended_edges(nodes)
    with pytest.raises(ValueError, match="cycle detected"):
        waves(nodes, uuid_edges)


# ---------------------------------------------------------------------------
# command payload shape: explicit-mode byte compat, extended-mode additive
# sections, pagination, invalid mode.
# ---------------------------------------------------------------------------

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000012fd8a0")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-0000012fd8a1")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-0000012fd8a2")
PRODUCER_UUID = uuid.UUID("00000000-0000-0000-0000-0000012fd8a3")
CONSUMER_UUID = uuid.UUID("00000000-0000-0000-0000-0000012fd8a4")

GS_FIELDS = {"name": "G one"}
TS_FIELDS = {"name": "T one"}
PRODUCER_FIELDS = {
    "name": "producer",
    "target_file": "src/schema.py",
    "operation": "create_file",
    "priority": 1,
    "prompt": "",
    "verification": "pytest tests/test_x.py",
    "objects": [{"name": "widget", "concepts": [], "role": "create"}],
}
CONSUMER_FIELDS = {
    "name": "consumer",
    "target_file": "src/consumer.py",
    "operation": "modify_file",
    "priority": 1,
    "prompt": "",
    "verification": "pytest tests/test_y.py",
    "objects": [{"name": "widget", "concepts": [], "role": "consume"}],
}

STEP_ROWS = [
    (GS_UUID, PLAN_UUID, None, 3, "G-001", "g-one", GS_FIELDS, [], [], None, "draft"),
    (TS_UUID, PLAN_UUID, GS_UUID, 4, "T-001", "t-one", TS_FIELDS, [], [], None, "draft"),
    (PRODUCER_UUID, PLAN_UUID, TS_UUID, 5, "A-001", "a-one", PRODUCER_FIELDS, [], [], None, "draft"),
    (CONSUMER_UUID, PLAN_UUID, TS_UUID, 5, "A-002", "a-two", CONSUMER_FIELDS, [], [], None, "draft"),
]

PLAN_ROW = (
    PLAN_UUID,
    "plan-12fd8a80",
    "draft",
    None,
    uuid.UUID("00000000-0000-0000-0000-0000012fd8a5"),
    [],
    None,
    None,
    False,
    None,
)


class _Cursor:
    def __init__(self, owner: "_FakeConn") -> None:
        self._owner = owner
        self._pending: list[tuple] = []

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> "_Cursor":
        self._pending = self._owner.dispatch(query, params)
        return self

    def fetchall(self) -> list[tuple]:
        return self._pending

    def fetchone(self) -> Optional[tuple]:
        return self._pending[0] if self._pending else None


class _FakeConn:
    """Fake connection covering exactly the two read-only queries
    graph_parallel_map_command's execute() issues: resolve_plan/get_plan's
    plan-by-uuid select, and load_steps's step select."""

    def __init__(self, step_rows: list[tuple], plan_row: tuple) -> None:
        self._step_rows = step_rows
        self._plan_row = plan_row

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def execute(self, query: str, params: tuple = ()) -> _Cursor:
        cur = _Cursor(self)
        cur._pending = self.dispatch(query, params)
        return cur

    def dispatch(self, query: str, params: tuple) -> list[tuple]:
        if query.startswith("SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug"):
            return list(self._step_rows)
        if query.startswith("SELECT uuid, name, status, context_budget, head_revision_uuid"):
            return [self._plan_row]
        raise AssertionError(f"unexpected query in _FakeConn: {query!r}")


def _patch(monkeypatch, conn: _FakeConn) -> None:
    @contextmanager
    def fake_db_connection():
        yield conn

    monkeypatch.setattr(graph_parallel_map_command, "db_connection", fake_db_connection)


def test_explicit_mode_default_payload_is_byte_compatible(monkeypatch) -> None:
    """mode omitted keeps the pre-existing payload shape and values exactly."""
    _patch(monkeypatch, _FakeConn(STEP_ROWS, PLAN_ROW))
    result = asyncio.run(GraphParallelMapCommand().execute(plan=str(PLAN_UUID), limit=200, offset=0))
    data = result.data
    assert set(data) == {"waves", "total", "limit", "offset"}
    # No explicit/file_order edges exist among this fixture's steps (only
    # the inferred object_producer edge, invisible to explicit mode): every
    # step lands in one single wave.
    assert data["total"] == 1
    assert len(data["waves"][0]) == 4


def test_explicit_mode_is_identical_whether_mode_is_omitted_or_spelled_out(monkeypatch) -> None:
    conn = _FakeConn(STEP_ROWS, PLAN_ROW)
    _patch(monkeypatch, conn)
    omitted = asyncio.run(GraphParallelMapCommand().execute(plan=str(PLAN_UUID), limit=200, offset=0))
    _patch(monkeypatch, conn)
    explicit = asyncio.run(
        GraphParallelMapCommand().execute(plan=str(PLAN_UUID), limit=200, offset=0, mode=MODE_EXPLICIT)
    )
    assert omitted.data == explicit.data


def test_extended_mode_adds_the_four_sections_and_reorders_waves(monkeypatch) -> None:
    _patch(monkeypatch, _FakeConn(STEP_ROWS, PLAN_ROW))
    result = asyncio.run(
        GraphParallelMapCommand().execute(plan=str(PLAN_UUID), limit=200, offset=0, mode=MODE_EXTENDED)
    )
    data = result.data
    assert set(data) == {
        "waves", "total", "limit", "offset",
        "placement_reasons", "critical_path", "wave_parallelism", "conflict_groups",
    }
    # The object_producer edge (invisible to explicit mode) now splits the
    # steps into two waves: producer's wave, then consumer's wave.
    assert data["total"] == 2
    assert data["wave_parallelism"] == [len(wave) for wave in data["waves"]]
    consumer_path = "G-001/T-001/A-002"
    producer_path = "G-001/T-001/A-001"
    assert data["placement_reasons"][consumer_path] == [
        {"from": producer_path, "type": "object_producer"}
    ]
    assert data["placement_reasons"][producer_path] == []
    assert data["critical_path"] == [producer_path, consumer_path]
    assert data["conflict_groups"] == []


def test_extended_mode_pagination_applies_to_waves_only(monkeypatch) -> None:
    _patch(monkeypatch, _FakeConn(STEP_ROWS, PLAN_ROW))
    result = asyncio.run(
        GraphParallelMapCommand().execute(plan=str(PLAN_UUID), limit=1, offset=0, mode=MODE_EXTENDED)
    )
    data = result.data
    assert len(data["waves"]) == 1
    assert data["total"] == 2
    # The additive sections ride outside the paginated window: full, not
    # limited to the one wave on this page.
    assert len(data["wave_parallelism"]) == 2
    assert len(data["critical_path"]) == 2


def test_invalid_mode_returns_invalid_execution_mode(monkeypatch) -> None:
    _patch(monkeypatch, _FakeConn(STEP_ROWS, PLAN_ROW))
    result = asyncio.run(
        GraphParallelMapCommand().execute(plan=str(PLAN_UUID), mode="bogus")
    )
    assert result.details["domain_code"] == "INVALID_EXECUTION_MODE"


def test_extended_mode_cycle_returns_cycle_detected(monkeypatch) -> None:
    gs_uuid = uuid.UUID("00000000-0000-0000-0000-0000012fd8b0")
    ts1_uuid = uuid.UUID("00000000-0000-0000-0000-0000012fd8b1")
    ts2_uuid = uuid.UUID("00000000-0000-0000-0000-0000012fd8b2")
    ts3_uuid = uuid.UUID("00000000-0000-0000-0000-0000012fd8b3")
    a1_uuid = uuid.UUID("00000000-0000-0000-0000-0000012fd8b4")
    a2_uuid = uuid.UUID("00000000-0000-0000-0000-0000012fd8b5")
    a3_uuid = uuid.UUID("00000000-0000-0000-0000-0000012fd8b6")

    cycle_plan_uuid = uuid.UUID("00000000-0000-0000-0000-0000012fd8bf")
    a1_fields = {
        "name": "a1", "target_file": "src/one.py", "operation": "modify_file",
        "priority": 1, "prompt": "", "verification": "pytest tests/test_x.py",
        "objects": [
            {"name": "obj_a", "concepts": [], "role": "consume"},
            {"name": "obj_b", "concepts": [], "role": "create"},
        ],
    }
    a2_fields = {
        "name": "a2", "target_file": "src/two.py", "operation": "modify_file",
        "priority": 1, "prompt": "", "verification": "pytest tests/test_x.py",
        "objects": [
            {"name": "obj_b", "concepts": [], "role": "consume"},
            {"name": "obj_c", "concepts": [], "role": "create"},
        ],
    }
    a3_fields = {
        "name": "a3", "target_file": "src/three.py", "operation": "modify_file",
        "priority": 1, "prompt": "", "verification": "pytest tests/test_x.py",
        "objects": [
            {"name": "obj_c", "concepts": [], "role": "consume"},
            {"name": "obj_a", "concepts": [], "role": "create"},
        ],
    }
    cycle_rows = [
        (gs_uuid, cycle_plan_uuid, None, 3, "G-001", "g-one", {"name": "g"}, [], [], None, "draft"),
        (ts1_uuid, cycle_plan_uuid, gs_uuid, 4, "T-001", "t-one", {"name": "t1"}, [], [], None, "draft"),
        (ts2_uuid, cycle_plan_uuid, gs_uuid, 4, "T-002", "t-two", {"name": "t2"}, [], [], None, "draft"),
        (ts3_uuid, cycle_plan_uuid, gs_uuid, 4, "T-003", "t-three", {"name": "t3"}, [], [], None, "draft"),
        (a1_uuid, cycle_plan_uuid, ts1_uuid, 5, "A-001", "a-one", a1_fields, [], [], None, "draft"),
        (a2_uuid, cycle_plan_uuid, ts2_uuid, 5, "A-001", "a-two", a2_fields, [], [], None, "draft"),
        (a3_uuid, cycle_plan_uuid, ts3_uuid, 5, "A-001", "a-three", a3_fields, [], [], None, "draft"),
    ]
    cycle_plan_row = (
        cycle_plan_uuid, "plan-12fd8a80-cycle", "draft", None,
        uuid.UUID("00000000-0000-0000-0000-0000012fd8bd"), [], None, None, False, None,
    )

    _patch(monkeypatch, _FakeConn(cycle_rows, cycle_plan_row))
    explicit_result = asyncio.run(
        GraphParallelMapCommand().execute(plan=str(cycle_plan_uuid), mode=MODE_EXPLICIT)
    )
    # No depends_on and no same-file writers among this fixture's steps:
    # explicit mode is entirely edge-free, so every step lands in one wave.
    assert explicit_result.data["total"] == 1
    assert len(explicit_result.data["waves"][0]) == 7

    _patch(monkeypatch, _FakeConn(cycle_rows, cycle_plan_row))
    extended_result = asyncio.run(
        GraphParallelMapCommand().execute(plan=str(cycle_plan_uuid), mode=MODE_EXTENDED)
    )
    assert extended_result.details["domain_code"] == "CYCLE_DETECTED"
