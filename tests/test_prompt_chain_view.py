import uuid

import pytest

from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges, waves
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
    depends_on: list[str] | None = None,
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
        depends_on=depends_on or [],
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


def test_wave_data_inherits_gs_level_depends_on_across_atomic_only_projection() -> None:
    # Regression bug 5d923c91: plan_prompt_chain's AS wave map lost the
    # G-002 depends_on G-001 closure because it filtered edges to
    # atomic-only endpoints before computing waves, so an AS under G-002
    # landed in wave 0 alongside G-001's AS. G-002's AS must wave strictly
    # after G-001's AS both in plan_prompt_chain's projected wave map and
    # in the raw graph_parallel_map closure (views.dependency_graph.waves)
    # driving both commands.
    g1 = _step("00000000-0000-0000-0000-0000000000e1", 3, "G-001", None)
    t1 = _step("00000000-0000-0000-0000-0000000000e2", 4, "T-001", g1.uuid)
    a1 = _atomic("00000000-0000-0000-0000-0000000000e3", "A-001", t1.uuid, "a.py")
    g2 = _step(
        "00000000-0000-0000-0000-0000000000e4",
        3,
        "G-002",
        None,
        depends_on=["G-001"],
    )
    t2 = _step("00000000-0000-0000-0000-0000000000e5", 4, "T-001", g2.uuid)
    a2 = _atomic("00000000-0000-0000-0000-0000000000e6", "A-001", t2.uuid, "b.py")
    nodes = {s.uuid: s for s in (g1, t1, a1, g2, t2, a2)}
    edges = build_edges(nodes)

    scoped = scope_atomic_steps(nodes, normalize_scope("whole_plan"))
    wave_rows, wave_index = _wave_data(scoped, edges, nodes)

    g1_key = "G-001/T-001/A-001"
    g2_key = "G-002/T-001/A-001"
    g1_wave = next(i for i, row in enumerate(wave_rows) if g1_key in row)
    g2_wave = next(i for i, row in enumerate(wave_rows) if g2_key in row)
    assert g2_wave > g1_wave

    # graph_parallel_map drives its wave partition from the same waves()
    # closure over the full node/edge set: confirm the two commands agree.
    full_rows = waves(nodes, edges)
    full_index = {node_uuid: i for i, row in enumerate(full_rows) for node_uuid in row}
    assert full_index[a2.uuid] > full_index[a1.uuid]


def test_wave_data_matches_graph_parallel_map_relative_order_for_diamond_chain() -> None:
    # Deeper regression for bug 5d923c91: a foundation GS, two parallel
    # provider GS depending on it, and a final GS depending on both
    # providers. plan_prompt_chain's projected wave map must respect the
    # full chain and its relative order must match graph_parallel_map's
    # (the shared waves() closure over the full graph).
    foundation = _step("00000000-0000-0000-0000-0000000000f1", 3, "G-001", None)
    tf = _step("00000000-0000-0000-0000-0000000000f2", 4, "T-001", foundation.uuid)
    af = _atomic("00000000-0000-0000-0000-0000000000f3", "A-001", tf.uuid, "f.py")

    provider_a = _step(
        "00000000-0000-0000-0000-0000000000f4", 3, "G-002", None, depends_on=["G-001"]
    )
    tpa = _step("00000000-0000-0000-0000-0000000000f5", 4, "T-001", provider_a.uuid)
    apa = _atomic("00000000-0000-0000-0000-0000000000f6", "A-001", tpa.uuid, "pa.py")

    provider_b = _step(
        "00000000-0000-0000-0000-0000000000f7", 3, "G-003", None, depends_on=["G-001"]
    )
    tpb = _step("00000000-0000-0000-0000-0000000000f8", 4, "T-001", provider_b.uuid)
    apb = _atomic("00000000-0000-0000-0000-0000000000f9", "A-001", tpb.uuid, "pb.py")

    final = _step(
        "00000000-0000-0000-0000-0000000000fa",
        3,
        "G-004",
        None,
        depends_on=["G-002", "G-003"],
    )
    tfin = _step("00000000-0000-0000-0000-0000000000fb", 4, "T-001", final.uuid)
    afin = _atomic("00000000-0000-0000-0000-0000000000fc", "A-001", tfin.uuid, "z.py")

    nodes = {
        s.uuid: s
        for s in (
            foundation, tf, af,
            provider_a, tpa, apa,
            provider_b, tpb, apb,
            final, tfin, afin,
        )
    }
    edges = build_edges(nodes)

    scoped = scope_atomic_steps(nodes, normalize_scope("whole_plan"))
    wave_rows, wave_index = _wave_data(scoped, edges, nodes)

    def _wave_of(rows: list[list[str]], key: str) -> int:
        return next(i for i, row in enumerate(rows) if key in row)

    foundation_wave = _wave_of(wave_rows, "G-001/T-001/A-001")
    provider_a_wave = _wave_of(wave_rows, "G-002/T-001/A-001")
    provider_b_wave = _wave_of(wave_rows, "G-003/T-001/A-001")
    final_wave = _wave_of(wave_rows, "G-004/T-001/A-001")

    assert foundation_wave < provider_a_wave
    assert foundation_wave < provider_b_wave
    assert provider_a_wave < final_wave
    assert provider_b_wave < final_wave

    # graph_parallel_map's relative order (via the shared waves() closure)
    # must agree: the two providers may share a wave, but both must be
    # strictly between the foundation and the final AS.
    full_rows = waves(nodes, edges)
    full_index = {node_uuid: i for i, row in enumerate(full_rows) for node_uuid in row}
    assert full_index[af.uuid] < full_index[apa.uuid]
    assert full_index[af.uuid] < full_index[apb.uuid]
    assert full_index[apa.uuid] < full_index[afin.uuid]
    assert full_index[apb.uuid] < full_index[afin.uuid]
