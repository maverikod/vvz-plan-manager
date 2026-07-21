"""Regression tests for bug 64107707: dependency repair blocked by the
pre-existing same-file ambiguity gate.

Root cause: plan_manager.views.dependency_graph.build_edges() raises
SameFileOrderAmbiguousError whenever ANY same-file writer pair (existing
OR candidate) has no derivable order, by default (strict_same_file_order=
True). The shared step_dependency_ops helpers (detect_cycle,
execution_order_paths, parallel_wave_paths) called build_edges() with that
default, so step_dependency_preview / step_dependency_apply(dry_run) /
step_dependency_add / step_dependency_set all raised on a pre-existing
(or partially-resolved) ambiguity before any candidate simulation could
run or return structured impact data — even when the requested change
was a fully curative fix.

The fix (see step_dependency_ops.same_file_admission /
render_same_file_conflicts): same-file ambiguity is evaluated
monotonically, on the candidate after-state, and is never gated by a
pre-existing before-state ambiguity. A mutation is refused only if it
introduces a NEW ambiguous pair absent from the before-state; a
pre-existing ambiguity that survives unchanged is reported, not blocked.

Two layers are tested:
  - Pure graph-level: same_file_admission()/diff_same_file_conflicts()
    directly on Step dicts (no DB), extending the style of
    tests/test_b9_step_content_and_file_order.py.
  - Command-level: step_dependency_preview/apply/add/set .execute(),
    with db_connection/resolve_plan/load_steps/persist_changes/
    head_revision_str monkeypatched onto an in-memory node store,
    following the established _fake_db pattern of
    tests/test_step_create_admission_guard.py.
"""
from __future__ import annotations

import asyncio
import dataclasses
import uuid
from contextlib import contextmanager

from plan_manager.commands import (
    step_dependency_add_command,
    step_dependency_apply_command,
    step_dependency_preview_command,
    step_dependency_set_command,
)
from plan_manager.commands.step_dependency_add_command import StepDependencyAddCommand
from plan_manager.commands.step_dependency_apply_command import StepDependencyApplyCommand
from plan_manager.commands.step_dependency_ops import (
    detect_cycle,
    render_same_file_conflicts,
    same_file_admission,
    simulate,
)
from plan_manager.commands.step_dependency_preview_command import StepDependencyPreviewCommand
from plan_manager.commands.step_dependency_set_command import StepDependencySetCommand
from plan_manager.domain.plan import Plan
from plan_manager.domain.step import Step
from plan_manager.views.dependency_graph import build_edges, topological_order
from plan_manager.views.same_file_order import diff_same_file_conflicts, same_file_order_conflicts

PLAN_UUID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Fixture: the exact live-reproduction shape — one GS with four TS siblings,
# two independent same-file AS pairs (shared_a.md, shared_b.md).
# ---------------------------------------------------------------------------


def make_step(
    level: int,
    step_id: str,
    parent: uuid.UUID | None,
    *,
    target: str | None = None,
    priority: int = 1,
    depends: list[str] | None = None,
) -> Step:
    fields = {"name": step_id}
    if level == 5:
        fields.update(
            {
                "target_file": target,
                "priority": priority,
                "operation": "modify_file",
                "prompt": "",
                "verification": "pytest tests/test_x.py",
            }
        )
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


def _build_nodes(*, t004_depends_on_t003: bool = False) -> dict[uuid.UUID, Step]:
    """T-001..T-004 siblings under one GS; A-001 under each targets a shared file.

    shared_a.md: T-001/A-001 <> T-002/A-001 (always ambiguous, no dep between
    T-001/T-002).
    shared_b.md: T-003/A-001 <> T-004/A-001 (ambiguous unless
    t004_depends_on_t003 pre-resolves it).
    """
    gs = make_step(3, "G-001", None)
    t1 = make_step(4, "T-001", gs.uuid)
    t2 = make_step(4, "T-002", gs.uuid)
    t3 = make_step(4, "T-003", gs.uuid)
    t4 = make_step(4, "T-004", gs.uuid, depends=["T-003"] if t004_depends_on_t003 else None)
    a1 = make_step(5, "A-001", t1.uuid, target="shared_a.md")
    a2 = make_step(5, "A-001", t2.uuid, target="shared_a.md")
    a3 = make_step(5, "A-001", t3.uuid, target="shared_b.md")
    a4 = make_step(5, "A-001", t4.uuid, target="shared_b.md")
    return {s.uuid: s for s in (gs, t1, t2, t3, t4, a1, a2, a3, a4)}


def _by_step_id(nodes: dict[uuid.UUID, Step], step_id: str) -> Step:
    matches = [s for s in nodes.values() if s.step_id == step_id and s.level == 4]
    assert len(matches) == 1, f"expected exactly one T-level {step_id}"
    return matches[0]


# ---------------------------------------------------------------------------
# Pure graph-level tests: same_file_admission / diff_same_file_conflicts.
# ---------------------------------------------------------------------------


def test_diff_same_file_conflicts_classifies_introduced_resolved_remaining() -> None:
    nodes = _build_nodes()
    before_conflicts = same_file_order_conflicts(nodes, build_edges(nodes, strict_same_file_order=False))
    assert len(before_conflicts) == 2  # shared_a.md and shared_b.md both ambiguous

    t2 = _by_step_id(nodes, "T-002")
    sim = simulate(nodes, {t2.uuid: ["T-001"]})
    after_conflicts = same_file_order_conflicts(sim, build_edges(sim, strict_same_file_order=False))
    assert len(after_conflicts) == 1  # only shared_b.md remains

    introduced, resolved, remaining = diff_same_file_conflicts(before_conflicts, after_conflicts)
    assert introduced == []
    assert len(resolved) == 1 and resolved[0][2] == "shared_a.md"
    assert len(remaining) == 1 and remaining[0][2] == "shared_b.md"


def test_same_file_admission_reports_but_does_not_flag_remaining_ambiguity() -> None:
    """Claim C shape: a single improving edge must not be flagged by 'introduced'."""
    nodes = _build_nodes()
    t2 = _by_step_id(nodes, "T-002")
    sim = simulate(nodes, {t2.uuid: ["T-001"]})
    admission = same_file_admission(nodes, sim)
    assert admission["introduced"] == []
    assert len(admission["remaining"]) == 1
    assert admission["remaining"][0][2] == "shared_b.md"


def test_same_file_admission_flags_a_newly_introduced_pair() -> None:
    """Clearing an edge that was resolving a pair introduces a NEW ambiguity.

    shared_a.md (T-001/T-002, no dep between them) stays ambiguous throughout
    and must land in 'remaining', never in 'introduced'; only shared_b.md
    (resolved by T-004 depends_on T-003 in the before-state) newly becomes
    ambiguous once that edge is cleared.
    """
    nodes = _build_nodes(t004_depends_on_t003=True)
    before_conflicts = same_file_order_conflicts(nodes, build_edges(nodes, strict_same_file_order=False))
    assert len(before_conflicts) == 1 and before_conflicts[0][2] == "shared_a.md"

    t4 = _by_step_id(nodes, "T-004")
    sim = simulate(nodes, {t4.uuid: []})  # clear the resolving edge
    admission = same_file_admission(nodes, sim)
    assert len(admission["introduced"]) == 1
    assert admission["introduced"][0][2] == "shared_b.md"
    assert len(admission["remaining"]) == 1
    assert admission["remaining"][0][2] == "shared_a.md"


def test_detect_cycle_no_longer_raises_on_unrelated_pre_existing_ambiguity() -> None:
    """Before the fix, build_edges(sim) inside detect_cycle raised
    SameFileOrderAmbiguousError for the untouched shared_b.md pair even
    though only shared_a.md's edge was being tested. Must not raise now."""
    nodes = _build_nodes()
    t2 = _by_step_id(nodes, "T-002")
    cycle = detect_cycle(nodes, {t2.uuid: ["T-001"]})
    assert cycle is None


# ---------------------------------------------------------------------------
# Command-level tests: full execute() with an in-memory node store.
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
    """In-memory node store backing load_steps/persist_changes fakes."""

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


def _wire(monkeypatch, module, store: _Store, *, mutating: bool) -> None:
    monkeypatch.setattr(module, "db_connection", _fake_db)
    monkeypatch.setattr(module, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(module, "load_steps", store.load)
    if mutating:
        monkeypatch.setattr(module, "persist_changes", store.persist)
        monkeypatch.setattr(module, "head_revision_str", lambda conn, plan: "head-rev-stub")


def _graph_order_is_clean(nodes: dict[uuid.UUID, Step]) -> bool:
    edges = build_edges(nodes)  # strict default: raises if still ambiguous
    _order, residual = topological_order(nodes, edges)
    return not residual


# (a) preview on ambiguous graph simulates the curative batch cleanly.
def test_preview_curative_batch_on_ambiguous_graph_reports_clean_after(monkeypatch) -> None:
    store = _Store(_build_nodes())
    _wire(monkeypatch, step_dependency_preview_command, store, mutating=False)

    changes = [
        {"op": "set", "step_id": "T-002", "depends_on": ["T-001"]},
        {"op": "set", "step_id": "T-004", "depends_on": ["T-003"]},
    ]
    result = asyncio.run(StepDependencyPreviewCommand().execute(plan="p", changes=changes))
    data = result.to_dict()["data"]

    assert data["valid"] is True
    assert data["would_create_cycle"] is False
    assert len(data["same_file_order"]["before_findings"]) == 2
    assert data["same_file_order"]["after_findings"] == []
    assert len(data["same_file_order"]["resolved_pairs"]) == 2
    assert data["same_file_order"]["introduced_pairs"] == []
    assert data["findings"] == []


# (b) apply dry_run=true, same batch: no mutation, same report as preview.
def test_apply_dry_run_curative_batch_reports_clean_no_mutation(monkeypatch) -> None:
    store = _Store(_build_nodes())
    _wire(monkeypatch, step_dependency_apply_command, store, mutating=True)
    original_snapshot = dict(store.nodes)

    changes = [
        {"op": "set", "step_id": "T-002", "depends_on": ["T-001"]},
        {"op": "set", "step_id": "T-004", "depends_on": ["T-003"]},
    ]
    result = asyncio.run(
        StepDependencyApplyCommand().execute(plan="p", changes=changes, dry_run=True)
    )
    data = result.to_dict()["data"]

    assert data["applied"] is False
    assert data["dry_run"] is True
    assert data["valid"] is True
    assert data["same_file_order"]["after_findings"] == []
    assert data["same_file_order"]["introduced_pairs"] == []
    # non-mutating guarantee: the store is byte-identical to before the call
    for u, step in store.nodes.items():
        assert step.depends_on == original_snapshot[u].depends_on
    assert store.revisions == []


# (c) apply real: atomic commit of the curative batch; graph_order clean after.
def test_apply_real_curative_batch_commits_and_graph_order_is_clean(monkeypatch) -> None:
    store = _Store(_build_nodes())
    _wire(monkeypatch, step_dependency_apply_command, store, mutating=True)

    changes = [
        {"op": "set", "step_id": "T-002", "depends_on": ["T-001"]},
        {"op": "set", "step_id": "T-004", "depends_on": ["T-003"]},
    ]
    result = asyncio.run(
        StepDependencyApplyCommand().execute(plan="p", changes=changes, dry_run=False)
    )
    data = result.to_dict()["data"]

    assert data["applied"] is True
    assert len(store.revisions) == 1
    assert _by_step_id(store.nodes, "T-002").depends_on == ["T-001"]
    assert _by_step_id(store.nodes, "T-004").depends_on == ["T-003"]
    assert _graph_order_is_clean(store.nodes)


# (d) single improving edge (claim C) persists via step_dependency_add.
def test_add_single_improving_edge_persists_leaving_unrelated_ambiguity(monkeypatch) -> None:
    store = _Store(_build_nodes())
    _wire(monkeypatch, step_dependency_add_command, store, mutating=True)

    t2 = _by_step_id(store.nodes, "T-002")
    result = asyncio.run(
        StepDependencyAddCommand().execute(plan="p", step_id=str(t2.uuid), depends_on="T-001")
    )
    data = result.to_dict()["data"]

    assert data["already_present"] is False
    assert _by_step_id(store.nodes, "T-002").depends_on == ["T-001"]
    # shared_b.md pair is untouched and still ambiguous — this must NOT have
    # blocked the add (this was exactly claim C's live-reproduction failure).
    remaining = same_file_order_conflicts(store.nodes, build_edges(store.nodes, strict_same_file_order=False))
    assert len(remaining) == 1 and remaining[0][2] == "shared_b.md"


# (e) an edge wholly unrelated to any same-file pair persists on an ambiguous graph.
def test_set_unrelated_edge_persists_on_already_ambiguous_graph(monkeypatch) -> None:
    nodes = _build_nodes()
    # Give T-003 and T-004 an unrelated file-free sibling to depend on, distinct
    # from the shared_a.md/shared_b.md pairs, so the edit touches neither pair.
    extra = make_step(4, "T-005", _by_step_id(nodes, "T-001").parent_step_uuid)
    nodes[extra.uuid] = extra
    store = _Store(nodes)
    _wire(monkeypatch, step_dependency_set_command, store, mutating=True)

    t5 = _by_step_id(store.nodes, "T-005")
    result = asyncio.run(
        StepDependencySetCommand().execute(plan="p", step_id=str(t5.uuid), depends_on=["T-001"])
    )
    data = result.to_dict()["data"]

    assert data["depends_on"] == ["G-001/T-001"]
    assert _by_step_id(store.nodes, "T-005").depends_on == ["T-001"]
    # both pre-existing same-file pairs remain ambiguous and untouched by rejection
    remaining = same_file_order_conflicts(store.nodes, build_edges(store.nodes, strict_same_file_order=False))
    assert len(remaining) == 2


# (f) an edge that introduces a NEW same-file ambiguity is rejected, state unchanged.
def test_set_clear_that_introduces_new_ambiguity_is_rejected_and_state_unchanged(monkeypatch) -> None:
    store = _Store(_build_nodes(t004_depends_on_t003=True))  # shared_b.md pre-resolved
    _wire(monkeypatch, step_dependency_set_command, store, mutating=True)
    original_snapshot = dict(store.nodes)

    t4 = _by_step_id(store.nodes, "T-004")
    result = asyncio.run(
        StepDependencySetCommand().execute(plan="p", step_id=str(t4.uuid), depends_on=[])
    )
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "AS_SAME_FILE_ORDER_AMBIGUOUS"
    introduced = payload["error"]["data"]["introduced_pairs"]
    assert len(introduced) == 1 and introduced[0]["target_file"] == "shared_b.md"
    # non-mutating guarantee
    for u, step in store.nodes.items():
        assert step.depends_on == original_snapshot[u].depends_on
    assert store.revisions == []


# (f2) a plain cycle is still rejected exactly as before (unaffected by this fix).
def test_add_edge_that_would_create_a_cycle_is_still_rejected(monkeypatch) -> None:
    nodes = _build_nodes()
    t1 = _by_step_id(nodes, "T-001")
    t2 = _by_step_id(nodes, "T-002")
    nodes[t2.uuid] = dataclasses.replace(t2, depends_on=[t1.step_id])  # T-002 depends_on T-001
    store = _Store(nodes)
    _wire(monkeypatch, step_dependency_add_command, store, mutating=True)

    result = asyncio.run(
        StepDependencyAddCommand().execute(plan="p", step_id=str(t1.uuid), depends_on="T-002")
    )
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "DEPENDENCY_CYCLE"
    assert _by_step_id(store.nodes, "T-001").depends_on == []


# (g) rejection atomicity: a batch whose LAST change introduces new ambiguity
# leaves the WHOLE batch unapplied, including the earlier, otherwise-good change.
def test_apply_batch_rejected_atomically_when_last_change_introduces_ambiguity(monkeypatch) -> None:
    store = _Store(_build_nodes(t004_depends_on_t003=True))  # shared_b.md pre-resolved
    _wire(monkeypatch, step_dependency_apply_command, store, mutating=True)
    original_snapshot = dict(store.nodes)

    changes = [
        {"op": "set", "step_id": "T-002", "depends_on": ["T-001"]},  # good: resolves shared_a.md
        {"op": "clear", "step_id": "T-004"},  # bad: un-resolves shared_b.md (last in batch)
    ]
    result = asyncio.run(
        StepDependencyApplyCommand().execute(plan="p", changes=changes, dry_run=False)
    )
    payload = result.to_dict()

    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "AS_SAME_FILE_ORDER_AMBIGUOUS"
    # atomicity: the good T-002 change must NOT have landed either.
    for u, step in store.nodes.items():
        assert step.depends_on == original_snapshot[u].depends_on
    assert store.revisions == []
