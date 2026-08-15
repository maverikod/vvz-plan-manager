"""Tests for EIG block B (todo 16853f27): the extended execution graph view
(plan_manager.views.execution_graph.build_execution_graph) and its read-only
command (plan_manager.commands.execution_graph_command.ExecutionGraphCommand).

Mirrors this suite's established conventions: view-level tests build Step
objects in-memory (as tests/test_b9_step_content_and_file_order.py does,
never a live Postgres), and the command-level test drives execute() against
a minimal fake connection (as tests/test_bug_4f7fbd43_prompt_chain_scoped_
gate.py does), covering only the queries the real command path issues:
resolve_plan's plan-by-uuid select (domain.plan.get_plan) and load_steps's
step select.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from typing import Optional

from plan_manager.commands import execution_graph_command
from plan_manager.commands.execution_graph_command import ExecutionGraphCommand
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges
from plan_manager.views.execution_graph import build_execution_graph

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


# ---------------------------------------------------------------------------
# explicit / file_order decomposition matches build_edges semantics
# ---------------------------------------------------------------------------


def test_explicit_and_file_order_decomposition_matches_build_edges() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])
    a1 = make_step(5, "A-001", ts1.uuid, target="src/one.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/shared.py", priority=2)
    a3 = make_step(5, "A-002", ts2.uuid, target="src/shared.py", priority=1)
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2, a3)}

    reference_edges = build_edges(nodes)
    graph = build_execution_graph(nodes)

    explicit_uuid_edges = set()
    file_order_uuid_edges = set()
    path_to_uuid = {_path(nodes, s): s.uuid for s in nodes.values()}
    for edge in graph["explicit_edges"]:
        pair = (path_to_uuid[edge["from"]], path_to_uuid[edge["to"]])
        if edge["type"] == "explicit":
            explicit_uuid_edges.add(pair)
        elif edge["type"] == "file_order":
            file_order_uuid_edges.add(pair)
        else:
            raise AssertionError(f"unexpected explicit-family type {edge['type']!r}")
        assert edge["provenance"] == "explicit"

    assert explicit_uuid_edges | file_order_uuid_edges == reference_edges
    # ts2 declares T-001 explicitly; the a3->a2 pair is same-file priority order.
    assert (ts1.uuid, ts2.uuid) in explicit_uuid_edges
    assert (a3.uuid, a2.uuid) in file_order_uuid_edges


# ---------------------------------------------------------------------------
# object_producer edges from block-A roles
# ---------------------------------------------------------------------------


def test_object_producer_edge_from_creator_to_consumer() -> None:
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
    graph = build_execution_graph(nodes)

    producer_path = _path(nodes, producer)
    consumer_path = _path(nodes, consumer)
    matches = [
        e for e in graph["inferred_edges"]
        if e["type"] == "object_producer" and e["from"] == producer_path and e["to"] == consumer_path
    ]
    assert len(matches) == 1
    edge = matches[0]
    assert edge["provenance"] == "inferred"
    assert edge["evidence"] == {
        "object": "widget_schema",
        "producer_role": "create",
        "consumer_role": "consume",
    }
    assert graph["missing_producers"] == []
    assert graph["ambiguous_dependencies"] == []


def test_object_producer_role_less_declaration_yields_no_inferred_edge() -> None:
    """A legacy objects entry with no 'role' key contributes zero inferred edges (block-A back-compat)."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    a1 = make_step(
        5, "A-001", ts.uuid, target="src/schema.py",
        objects=[{"name": "widget_schema", "concepts": []}],
    )
    a2 = make_step(
        5, "A-002", ts.uuid, target="src/consumer.py", priority=2,
        objects=[{"name": "widget_schema", "concepts": []}],
    )
    nodes = {x.uuid: x for x in (gs, ts, a1, a2)}
    graph = build_execution_graph(nodes)
    assert graph["inferred_edges"] == []
    assert graph["missing_producers"] == []
    assert graph["ambiguous_dependencies"] == []


# ---------------------------------------------------------------------------
# verification_target edge
# ---------------------------------------------------------------------------


def test_verification_target_edge_from_creator_to_verifier() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    creator = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="create_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification={"type": "tests", "target": "  src/widget.py  ", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, creator, verifier)}
    graph = build_execution_graph(nodes)

    creator_path = _path(nodes, creator)
    verifier_path = _path(nodes, verifier)
    matches = [
        e for e in graph["inferred_edges"]
        if e["type"] == "verification_target" and e["from"] == creator_path and e["to"] == verifier_path
    ]
    assert len(matches) == 1
    assert matches[0]["evidence"] == {"target": "src/widget.py"}


def test_verification_target_falls_back_to_plain_owner_without_creator() -> None:
    """No target_file owner carries operation 'create_file': every owner is used."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    owner = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="modify_file")
    verifier = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification={"type": "tests", "target": "src/widget.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts, owner, verifier)}
    graph = build_execution_graph(nodes)
    owner_path = _path(nodes, owner)
    verifier_path = _path(nodes, verifier)
    matches = [
        e for e in graph["inferred_edges"]
        if e["type"] == "verification_target" and e["from"] == owner_path and e["to"] == verifier_path
    ]
    assert len(matches) == 1


def test_verification_string_field_yields_no_verification_target_edge() -> None:
    """Legacy string-shaped verification (no .target) never produces this edge type."""
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    a1 = make_step(5, "A-001", ts.uuid, target="src/widget.py", operation="create_file")
    a2 = make_step(
        5, "A-002", ts.uuid, target="tests/test_widget.py", priority=2,
        verification="pytest tests/test_widget.py",
    )
    nodes = {x.uuid: x for x in (gs, ts, a1, a2)}
    graph = build_execution_graph(nodes)
    assert [e for e in graph["inferred_edges"] if e["type"] == "verification_target"] == []


# ---------------------------------------------------------------------------
# missing_producers / ambiguous_dependencies
# ---------------------------------------------------------------------------


def test_missing_producer_object_consumed_with_no_producer() -> None:
    gs = make_step(3, "G-001", None)
    ts = make_step(4, "T-001", gs.uuid)
    consumer = make_step(
        5, "A-001", ts.uuid, target="src/consumer.py",
        objects=[{"name": "orphan_object", "concepts": [], "role": "consume"}],
    )
    nodes = {x.uuid: x for x in (gs, ts, consumer)}
    graph = build_execution_graph(nodes)
    consumer_path = _path(nodes, consumer)
    assert graph["missing_producers"] == [{"object": "orphan_object", "consumers": [consumer_path]}]
    assert graph["ambiguous_dependencies"] == []
    assert graph["inferred_edges"] == []


def test_ambiguous_dependency_object_with_two_producers() -> None:
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
    graph = build_execution_graph(nodes)
    p1_path, p2_path = sorted([_path(nodes, p1), _path(nodes, p2)])
    assert graph["ambiguous_dependencies"] == [
        {"object": "shared_object", "producers": [p1_path, p2_path]}
    ]
    assert graph["missing_producers"] == []


# ---------------------------------------------------------------------------
# cycle report with full path
# ---------------------------------------------------------------------------


def test_cycle_reported_as_full_ordered_path() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid)
    ts3 = make_step(4, "T-003", gs.uuid)
    # Build a 3-node cycle purely through object_producer inferred edges
    # (ts1 -> ts2 -> ts3 -> ts1), avoiding build_edges/depends_on entirely
    # so the cycle only exists once inferred edges are folded in.
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
    graph = build_execution_graph(nodes)

    assert len(graph["cycles"]) == 1
    cycle = graph["cycles"][0]
    assert len(cycle) == 3
    assert set(cycle) == {_path(nodes, a1), _path(nodes, a2), _path(nodes, a3)}
    # The path is a genuine walk: consecutive entries (wrapping around) are
    # connected by a real object_producer edge in the reported direction.
    edge_pairs = {
        (e["from"], e["to"]) for e in graph["inferred_edges"] if e["type"] == "object_producer"
    }
    for i in range(len(cycle)):
        assert (cycle[i], cycle[(i + 1) % len(cycle)]) in edge_pairs


def test_no_cycle_over_pure_dag() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])
    a1 = make_step(5, "A-001", ts1.uuid, target="src/one.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/two.py")
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}
    graph = build_execution_graph(nodes)
    assert graph["cycles"] == []


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------


def test_two_builds_over_same_fixture_are_byte_identical() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])
    p = make_step(
        5, "A-001", ts1.uuid, target="src/schema.py", operation="create_file",
        objects=[{"name": "widget_schema", "concepts": [], "role": "create"}],
    )
    c = make_step(
        5, "A-001", ts2.uuid, target="src/consumer.py",
        objects=[{"name": "widget_schema", "concepts": [], "role": "consume"}],
    )
    v = make_step(
        5, "A-002", ts2.uuid, target="tests/test_schema.py", priority=2,
        verification={"type": "tests", "target": "src/schema.py", "expected": ""},
    )
    nodes = {x.uuid: x for x in (gs, ts1, ts2, p, c, v)}

    first = build_execution_graph(nodes)
    second = build_execution_graph(nodes)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    # sanity: the fixture actually exercises both inferred edge types.
    types = {e["type"] for e in first["inferred_edges"]}
    assert types == {"object_producer", "verification_target"}


# ---------------------------------------------------------------------------
# role-less legacy plan: zero inferred edges, explicit edges identical to
# the graph machinery graph_deps/graph_order/graph_parallel_map use.
# ---------------------------------------------------------------------------


def test_legacy_plan_without_roles_has_zero_inferred_edges() -> None:
    gs = make_step(3, "G-001", None)
    ts1 = make_step(4, "T-001", gs.uuid)
    ts2 = make_step(4, "T-002", gs.uuid, depends=["T-001"])
    a1 = make_step(5, "A-001", ts1.uuid, target="src/one.py")
    a2 = make_step(5, "A-001", ts2.uuid, target="src/two.py")
    nodes = {x.uuid: x for x in (gs, ts1, ts2, a1, a2)}

    reference_edges = build_edges(nodes)
    graph = build_execution_graph(nodes)

    assert graph["inferred_edges"] == []
    assert graph["missing_producers"] == []
    assert graph["ambiguous_dependencies"] == []
    assert graph["cycles"] == []

    path_to_uuid = {_path(nodes, s): s.uuid for s in nodes.values()}
    rebuilt = {
        (path_to_uuid[e["from"]], path_to_uuid[e["to"]]) for e in graph["explicit_edges"]
    }
    assert rebuilt == reference_edges


# ---------------------------------------------------------------------------
# command payload shape + pagination
# ---------------------------------------------------------------------------

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000016853f2")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-0000016853f3")
TS1_UUID = uuid.UUID("00000000-0000-0000-0000-0000016853f4")
TS2_UUID = uuid.UUID("00000000-0000-0000-0000-0000016853f5")
AS1_UUID = uuid.UUID("00000000-0000-0000-0000-0000016853f6")
AS2_UUID = uuid.UUID("00000000-0000-0000-0000-0000016853f7")

GS_FIELDS = {"name": "G one"}
TS1_FIELDS = {"name": "T one"}
TS2_FIELDS = {"name": "T two"}
AS1_FIELDS = {
    "name": "A one",
    "target_file": "src/one.py",
    "operation": "create_file",
    "priority": 1,
    "prompt": "",
    "verification": "pytest tests/test_x.py",
    "objects": [{"name": "widget", "concepts": [], "role": "create"}],
}
AS2_FIELDS = {
    "name": "A two",
    "target_file": "src/two.py",
    "operation": "modify_file",
    "priority": 1,
    "prompt": "",
    "verification": "pytest tests/test_y.py",
    "objects": [{"name": "widget", "concepts": [], "role": "consume"}],
}

STEP_ROWS = [
    (GS_UUID, PLAN_UUID, None, 3, "G-001", "g-one", GS_FIELDS, [], [], None, "draft"),
    (TS1_UUID, PLAN_UUID, GS_UUID, 4, "T-001", "t-one", TS1_FIELDS, [], [], None, "draft"),
    (TS2_UUID, PLAN_UUID, GS_UUID, 4, "T-002", "t-two", TS2_FIELDS, ["T-001"], [], None, "draft"),
    (AS1_UUID, PLAN_UUID, TS1_UUID, 5, "A-001", "a-one", AS1_FIELDS, [], [], None, "draft"),
    (AS2_UUID, PLAN_UUID, TS2_UUID, 5, "A-001", "a-two", AS2_FIELDS, [], [], None, "draft"),
]

PLAN_ROW = (
    PLAN_UUID,
    "plan-16853f27",
    "draft",
    None,
    uuid.UUID("00000000-0000-0000-0000-0000016853f8"),
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
    execution_graph_command's execute() issues: resolve_plan/get_plan's
    plan-by-uuid select, and load_steps's step select."""

    def cursor(self) -> _Cursor:
        return _Cursor(self)

    def execute(self, query: str, params: tuple = ()) -> _Cursor:
        cur = _Cursor(self)
        cur._pending = self.dispatch(query, params)
        return cur

    def dispatch(self, query: str, params: tuple) -> list[tuple]:
        if query.startswith("SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug"):
            return list(STEP_ROWS)
        if query.startswith("SELECT uuid, name, status, context_budget, head_revision_uuid"):
            return [PLAN_ROW]
        raise AssertionError(f"unexpected query in _FakeConn: {query!r}")


def _patch(monkeypatch) -> None:
    conn = _FakeConn()

    @contextmanager
    def fake_db_connection():
        yield conn

    monkeypatch.setattr(execution_graph_command, "db_connection", fake_db_connection)


def test_command_payload_shape_and_pagination(monkeypatch) -> None:
    _patch(monkeypatch)
    result = asyncio.run(ExecutionGraphCommand().execute(plan=str(PLAN_UUID), limit=1, offset=0))
    data = result.data
    assert set(data) == {
        "edges", "total_edges", "limit", "offset", "summary",
        "missing_producers", "ambiguous_dependencies", "cycles",
    }
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert len(data["edges"]) == 1
    assert data["total_edges"] == data["summary"]["explicit_edge_count"] + data["summary"]["inferred_edge_count"]
    assert data["missing_producers"] == []
    assert data["ambiguous_dependencies"] == []
    assert data["cycles"] == []
    for edge in data["edges"]:
        assert set(edge) == {"from", "to", "type", "provenance", "evidence"}


def test_command_second_page_is_disjoint_from_first(monkeypatch) -> None:
    _patch(monkeypatch)
    first = asyncio.run(ExecutionGraphCommand().execute(plan=str(PLAN_UUID), limit=1, offset=0))
    second = asyncio.run(ExecutionGraphCommand().execute(plan=str(PLAN_UUID), limit=1, offset=1))
    assert first.data["edges"] != second.data["edges"]
    assert first.data["total_edges"] == second.data["total_edges"]
