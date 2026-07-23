"""Regression tests for bug e197b94a (plan_validate scope='branch' wrongly
required gs_step_id, ts_step_id, AND as_step_id, making GS-only and GS+TS
branch validation impossible and any branch with zero AS descendants
mechanically unverifiable).

Covers, per the bug's own required-fix test list:
    - GS-only selector on a GS with TS children but no AS descendants
    - GS+TS selector
    - full GS+TS+AS selector
    - missing gs_step_id with scope='branch'
    - skipped-level selector (as_step_id without ts_step_id)
    - nonexistent child step_id
    - parent-child mismatch (ts not under the addressed gs)
    - a branch with zero AS descendants validates and produces a report

Exercised at three layers, mirroring this test suite's existing convention
(each verify/gate_* module is tested against hand-built GateTree/Step
objects or a minimal fake connection, never a live Postgres):

    1. plan_manager.views.branch.resolve_branch_scope -- the DB-facing
       hierarchical resolver, against a minimal fake connection supporting
       only the two read-only queries it issues (load_steps, list_paragraphs).
    2. plan_manager.verify.gate_data.scope_steps -- the pure subtree-selection
       function the mechanical gate uses to decide what is checked at each
       depth.
    3. plan_manager.commands.plan_validate_command.PlanValidateCommand
       .validate_params -- the selector-syntax guard enforced before any DB
       call is made.
    4. An end-to-end plan_manager.verify.gate.run_gate call (bug's own
       "produces a mechanical report" requirement) against a comprehensive
       fake connection, for exactly the reported shape: one GS with one TS
       child and zero AS descendants, validated at depth "gs".
"""
from __future__ import annotations

import uuid
from typing import Any, Optional

import pytest
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.plan_validate_command import PlanValidateCommand
from plan_manager.domain.step import Step
from plan_manager.verify.gate import run_gate
from plan_manager.verify.gate_data import GateTree, scope_steps
from plan_manager.views.branch import (
    Branch,
    BranchResolutionError,
    BranchScope,
    resolve_branch_scope,
)

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000e1")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000e2")
TS1_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000e3")
TS2_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000e4")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000e5")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-0000000000e6")


# ---------------------------------------------------------------------------
# Layer 1: resolve_branch_scope against a minimal fake connection.
# ---------------------------------------------------------------------------


def _step_row(
    step_uuid: uuid.UUID,
    parent_uuid: Optional[uuid.UUID],
    level: int,
    step_id: str,
    fields: Optional[dict[str, Any]] = None,
) -> tuple:
    """Build one raw step row tuple in the exact column order load_steps expects."""
    return (
        step_uuid,
        PLAN_UUID,
        parent_uuid,
        level,
        step_id,
        step_id.lower(),
        fields or {},
        [],
        [],
        None,
        "draft",
    )


class _FakeCursor:
    """Minimal fake psycopg cursor dispatching by query prefix, supporting
    the context-manager idiom (``with conn.cursor() as cur``) used by
    load_steps and list_paragraphs."""

    def __init__(self, step_rows: list[tuple], paragraph_rows: list[tuple]):
        self._step_rows = step_rows
        self._paragraph_rows = paragraph_rows
        self._pending: list[tuple] = []

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> "_FakeCursor":
        if query.startswith("SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug"):
            self._pending = list(self._step_rows)
        elif query.startswith("SELECT uuid, plan_uuid, label, text, position"):
            self._pending = list(self._paragraph_rows)
        else:
            raise AssertionError(f"unexpected query in _FakeCursor: {query!r}")
        return self

    def fetchall(self) -> list[tuple]:
        return self._pending


class _FakeConnForBranch:
    """Minimal fake connection: only .cursor() is used by
    resolve_branch_scope's dependencies (load_steps, list_paragraphs)."""

    def __init__(self, step_rows: list[tuple], paragraph_rows: list[tuple] = ()):
        self._step_rows = step_rows
        self._paragraph_rows = list(paragraph_rows)

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._step_rows, self._paragraph_rows)


def _gs_ts_ts_as_rows() -> list[tuple]:
    """One GS (G-001) with two TS children (T-001, T-002); only T-001 has
    one AS child (A-001). T-002 has zero AS descendants -- the exact shape
    the bug's reproduction (doc-store G-007: TS children, no AS) reported."""
    return [
        _step_row(GS_UUID, None, 3, "G-001", {"source_labels": ["{aaaa}"]}),
        _step_row(TS1_UUID, GS_UUID, 4, "T-001"),
        _step_row(TS2_UUID, GS_UUID, 4, "T-002"),
        _step_row(AS_UUID, TS1_UUID, 5, "A-001"),
    ]


def test_resolve_branch_scope_gs_only_on_ts_with_zero_as():
    """GS-only selector resolves even though the addressed TS (T-002) has
    zero AS descendants: depth 'gs', ts and atomic both None."""
    conn = _FakeConnForBranch(_gs_ts_ts_as_rows())

    scope = resolve_branch_scope(conn, PLAN_UUID, "G-001")

    assert scope.depth == "gs"
    assert scope.gs.step_id == "G-001"
    assert scope.ts is None
    assert scope.atomic is None


def test_resolve_branch_scope_gs_plus_ts_narrows_to_ts_with_zero_as():
    """GS+TS selector resolves the TS subtree even when that TS (T-002) has
    zero AS descendants: depth 'ts', atomic still None."""
    conn = _FakeConnForBranch(_gs_ts_ts_as_rows())

    scope = resolve_branch_scope(conn, PLAN_UUID, "G-001", ts_step_id="T-002")

    assert scope.depth == "ts"
    assert scope.gs.step_id == "G-001"
    assert scope.ts is not None
    assert scope.ts.step_id == "T-002"
    assert scope.atomic is None


def test_resolve_branch_scope_full_triple_resolves_one_atomic_branch():
    """GS+TS+AS selector resolves exactly one atomic branch: depth 'as'."""
    conn = _FakeConnForBranch(_gs_ts_ts_as_rows())

    scope = resolve_branch_scope(conn, PLAN_UUID, "G-001", ts_step_id="T-001", as_step_id="A-001")

    assert scope.depth == "as"
    assert scope.gs.step_id == "G-001"
    assert scope.ts is not None and scope.ts.step_id == "T-001"
    assert scope.atomic is not None and scope.atomic.step_id == "A-001"


def test_resolve_branch_scope_missing_gs_raises():
    """A gs_step_id that does not resolve at level 3 raises BranchResolutionError."""
    conn = _FakeConnForBranch(_gs_ts_ts_as_rows())

    with pytest.raises(BranchResolutionError, match="level 3"):
        resolve_branch_scope(conn, PLAN_UUID, "G-999")


def test_resolve_branch_scope_skipped_level_as_without_ts_raises():
    """as_step_id without ts_step_id (skipped level) raises defensively even
    if the command layer's validate_params guard were ever bypassed."""
    conn = _FakeConnForBranch(_gs_ts_ts_as_rows())

    with pytest.raises(BranchResolutionError, match="skipped level"):
        resolve_branch_scope(conn, PLAN_UUID, "G-001", as_step_id="A-001")


def test_resolve_branch_scope_nonexistent_child_id_raises():
    """A ts_step_id that names no step at all (not just a wrong parent) raises."""
    conn = _FakeConnForBranch(_gs_ts_ts_as_rows())

    with pytest.raises(BranchResolutionError, match="does not belong to addressed parent"):
        resolve_branch_scope(conn, PLAN_UUID, "G-001", ts_step_id="T-999")


def test_resolve_branch_scope_parent_child_mismatch_raises():
    """A ts_step_id that exists but under a DIFFERENT gs than addressed raises."""
    other_gs_uuid = uuid.uuid4()
    rows = _gs_ts_ts_as_rows() + [_step_row(uuid.uuid4(), other_gs_uuid, 4, "T-777")]
    conn = _FakeConnForBranch(rows)

    with pytest.raises(BranchResolutionError, match="does not belong to addressed parent 'G-001'"):
        resolve_branch_scope(conn, PLAN_UUID, "G-001", ts_step_id="T-777")


def test_resolve_branch_scope_as_parent_mismatch_raises():
    """An as_step_id that exists but under a DIFFERENT ts than addressed raises."""
    conn = _FakeConnForBranch(_gs_ts_ts_as_rows())

    with pytest.raises(BranchResolutionError, match="does not belong to addressed parent 'T-002'"):
        resolve_branch_scope(conn, PLAN_UUID, "G-001", ts_step_id="T-002", as_step_id="A-001")


# ---------------------------------------------------------------------------
# Layer 2: scope_steps -- the pure hierarchical subtree selector.
# ---------------------------------------------------------------------------


def _step(step_uuid: uuid.UUID, parent_uuid: Optional[uuid.UUID], level: int, step_id: str) -> Step:
    return Step(
        uuid=step_uuid,
        plan_uuid=PLAN_UUID,
        parent_step_uuid=parent_uuid,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields={},
        depends_on=[],
        concepts=[],
        project_id=None,
        status="draft",
    )


def _tree() -> tuple[GateTree, Step, Step, Step, Step]:
    gs = _step(GS_UUID, None, 3, "G-001")
    ts1 = _step(TS1_UUID, GS_UUID, 4, "T-001")
    ts2 = _step(TS2_UUID, GS_UUID, 4, "T-002")
    atomic = _step(AS_UUID, TS1_UUID, 5, "A-001")
    tree = GateTree(
        steps={s.uuid: s for s in (gs, ts1, ts2, atomic)},
        concept_ids=[],
        relations=[],
        labels=[],
        counts={},
    )
    return tree, gs, ts1, ts2, atomic


def test_scope_steps_depth_gs_covers_whole_subtree():
    tree, gs, ts1, ts2, atomic = _tree()
    branch = BranchScope(plan_uuid=PLAN_UUID, depth="gs", gs=gs, ts=None, atomic=None, hrs_slice=[])

    steps = scope_steps(tree, branch)

    assert set(s.uuid for s in steps) == {gs.uuid, ts1.uuid, ts2.uuid, atomic.uuid}


def test_scope_steps_depth_ts_covers_ts_subtree_only():
    tree, gs, ts1, ts2, atomic = _tree()
    branch = BranchScope(plan_uuid=PLAN_UUID, depth="ts", gs=gs, ts=ts2, atomic=None, hrs_slice=[])

    steps = scope_steps(tree, branch)

    # T-002 has zero AS descendants: the scoped list is exactly [gs, ts2].
    assert set(s.uuid for s in steps) == {gs.uuid, ts2.uuid}
    assert atomic.uuid not in {s.uuid for s in steps}
    assert ts1.uuid not in {s.uuid for s in steps}


def test_scope_steps_depth_ts_with_as_descendant():
    tree, gs, ts1, ts2, atomic = _tree()
    branch = BranchScope(plan_uuid=PLAN_UUID, depth="ts", gs=gs, ts=ts1, atomic=None, hrs_slice=[])

    steps = scope_steps(tree, branch)

    assert set(s.uuid for s in steps) == {gs.uuid, ts1.uuid, atomic.uuid}


def test_scope_steps_depth_as_covers_exactly_the_triple():
    tree, gs, ts1, ts2, atomic = _tree()
    branch = BranchScope(plan_uuid=PLAN_UUID, depth="as", gs=gs, ts=ts1, atomic=atomic, hrs_slice=[])

    steps = scope_steps(tree, branch)

    assert [s.uuid for s in steps] == [gs.uuid, ts1.uuid, atomic.uuid]


def test_scope_steps_plan_scope_unaffected():
    """scope=plan (branch=None) still returns every step, unaffected by BranchScope."""
    tree, gs, ts1, ts2, atomic = _tree()

    steps = scope_steps(tree, None)

    assert set(s.uuid for s in steps) == {gs.uuid, ts1.uuid, ts2.uuid, atomic.uuid}


# ---------------------------------------------------------------------------
# Layer 3: PlanValidateCommand.validate_params -- selector-syntax guard.
# ---------------------------------------------------------------------------


def test_validate_params_gs_only_is_accepted():
    params = PlanValidateCommand().validate_params({"plan": "some-plan", "scope": "branch", "gs_step_id": "G-001"})
    assert params["gs_step_id"] == "G-001"
    assert params.get("ts_step_id") is None
    assert params.get("as_step_id") is None


def test_validate_params_gs_plus_ts_is_accepted():
    params = PlanValidateCommand().validate_params(
        {"plan": "some-plan", "scope": "branch", "gs_step_id": "G-001", "ts_step_id": "T-001"}
    )
    assert params["gs_step_id"] == "G-001"
    assert params["ts_step_id"] == "T-001"


def test_validate_params_full_triple_is_accepted():
    params = PlanValidateCommand().validate_params(
        {
            "plan": "some-plan",
            "scope": "branch",
            "gs_step_id": "G-001",
            "ts_step_id": "T-001",
            "as_step_id": "A-001",
        }
    )
    assert params["as_step_id"] == "A-001"


def test_validate_params_missing_gs_step_id_with_branch_scope_raises():
    with pytest.raises(InvalidParamsError, match="gs_step_id is required"):
        PlanValidateCommand().validate_params({"plan": "some-plan", "scope": "branch"})


def test_validate_params_skipped_level_as_without_ts_raises():
    with pytest.raises(InvalidParamsError, match="as_step_id requires ts_step_id"):
        PlanValidateCommand().validate_params(
            {"plan": "some-plan", "scope": "branch", "gs_step_id": "G-001", "as_step_id": "A-001"}
        )


def test_validate_params_plan_scope_with_step_id_still_rejected():
    """Unchanged pre-existing behavior: scope='plan' rejects any of the three ids."""
    with pytest.raises(InvalidParamsError, match="must be absent"):
        PlanValidateCommand().validate_params({"plan": "some-plan", "scope": "plan", "gs_step_id": "G-001"})


# ---------------------------------------------------------------------------
# Layer 4: end-to-end run_gate over a branch with zero AS descendants.
# ---------------------------------------------------------------------------


class _Rows:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self) -> Optional[tuple]:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FullCursor:
    """Fake cursor for the context-manager idiom used by load_tree,
    load_steps, list_paragraphs, and current_head_revision."""

    def __init__(self, owner: "_FullFakeConn"):
        self._owner = owner
        self._pending: list[tuple] = []

    def __enter__(self) -> "_FullCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> "_FullCursor":
        self._pending = self._owner.dispatch(query, params)
        return self

    def fetchall(self) -> list[tuple]:
        return self._pending

    def fetchone(self) -> Optional[tuple]:
        return self._pending[0] if self._pending else None


class _FullFakeConn:
    """Comprehensive fake connection covering every read-only query issued
    by a full run_gate() pass over one hierarchical branch scope: the
    step/concept/relation/paragraph selects of load_tree, the two
    level-scoped step selects of coverage.gs_coverage (via conn.execute),
    the context_block/cascade/plan selects of gate_context (via
    conn.execute), and current_head_revision's plan select (via
    conn.cursor())."""

    def __init__(
        self,
        step_rows: list[tuple],
        concept_rows: list[tuple],
        paragraph_label_rows: list[tuple],
        paragraph_full_rows: list[tuple],
        context_block_rows: list[tuple],
        head_revision: uuid.UUID,
    ):
        self._step_rows = step_rows
        self._concept_rows = concept_rows
        self._paragraph_label_rows = paragraph_label_rows
        self._paragraph_full_rows = paragraph_full_rows
        self._context_block_rows = context_block_rows
        self._head_revision = head_revision

    def cursor(self) -> _FullCursor:
        return _FullCursor(self)

    def execute(self, query: str, params: tuple = ()) -> _Rows:
        return _Rows(self.dispatch(query, params))

    def dispatch(self, query: str, params: tuple) -> list[tuple]:
        if query.startswith("SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug"):
            return list(self._step_rows)
        if query.startswith("SELECT concept_id FROM concept"):
            return list(self._concept_rows)
        if query.startswith("SELECT from_concept, to_concept, type FROM relation"):
            return []
        if query.startswith("SELECT label FROM paragraph WHERE plan_uuid = %s AND binding IS TRUE ORDER BY position"):
            return list(self._paragraph_label_rows)
        if query.startswith("SELECT count(*) FROM paragraph"):
            return [(len(self._paragraph_full_rows),)]
        if query.startswith("SELECT uuid, plan_uuid, label, text, position"):
            return list(self._paragraph_full_rows)
        if query.startswith("SELECT uuid, step_id, concepts FROM step WHERE plan_uuid = %s AND level = 3"):
            return [row for row in self._step_rows if row[3] == 3 for row in [(row[0], row[4], row[8])]]
        if query.startswith("SELECT parent_step_uuid, concepts FROM step WHERE plan_uuid = %s AND level = 4"):
            return [row for row in self._step_rows if row[3] == 4 for row in [(row[2], row[8])]]
        if query.startswith("SELECT uuid, name FROM cascade"):
            return []
        if query.startswith("SELECT revision_uuid FROM ref"):
            return []
        if query.startswith("SELECT head_revision_uuid FROM plan"):
            return [(self._head_revision,)]
        if query.startswith("SELECT node_path, child_level, revision_uuid, cascade_uuid"):
            return list(self._context_block_rows)
        raise AssertionError(f"unexpected query in _FullFakeConn: {query!r}")


def test_run_gate_branch_with_zero_as_descendants_validates_green():
    """Bug e197b94a's core assertion: a branch scope resolved at depth 'gs'
    over a GS whose one TS child has ZERO AS descendants runs the gate to
    completion and produces a green mechanical report -- it is valid
    input, not a validation failure."""
    from datetime import datetime, timezone

    gs_fields = {
        "name": "G one",
        "description": "GS description.",
        "relations": [{"from_concept": "C-001", "to_concept": "C-001", "type": "supports"}],
        "source_labels": ["{aaaa}"],
    }
    ts_fields = {
        "name": "T one",
        "description": "TS description.",
        "inputs": [{"name": "in-one", "type": "input", "description": "one input."}],
        "outputs": [{"name": "out-one", "type": "output", "description": "one output."}],
    }
    step_rows = [
        (GS_UUID, PLAN_UUID, None, 3, "G-001", "g", gs_fields, [], ["C-001"], None, "draft"),
        (TS1_UUID, PLAN_UUID, GS_UUID, 4, "T-001", "t-001", ts_fields, [], ["C-001"], None, "draft"),
    ]
    conn = _FullFakeConn(
        step_rows=step_rows,
        concept_rows=[("C-001",)],
        paragraph_label_rows=[("aaaa",)],
        paragraph_full_rows=[(uuid.uuid4(), PLAN_UUID, "aaaa", "Paragraph text.", 0)],
        context_block_rows=[
            ("G-001", 4, HEAD_REVISION, None, ["C-001"], datetime(2026, 7, 20, tzinfo=timezone.utc)),
        ],
        head_revision=HEAD_REVISION,
    )
    branch = BranchScope(
        plan_uuid=PLAN_UUID,
        depth="gs",
        gs=Step(
            uuid=GS_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3, step_id="G-001",
            slug="g", fields=gs_fields, depends_on=[], concepts=["C-001"], project_id=None, status="draft",
        ),
        ts=None,
        atomic=None,
        hrs_slice=[],
    )
    # hrs_slice must be non-empty for parse.sanity_counts; build it from the
    # real Paragraph-shaped object the way resolve_branch_scope would.
    from plan_manager.domain.paragraph import Paragraph

    branch.hrs_slice = [Paragraph(label="aaaa", text="Paragraph text.", position=0)]

    report, verdict = run_gate(conn, PLAN_UUID, branch=branch, fail_fast=False)

    assert verdict.scope == "G-001"
    assert report.green is True, report.checks
    assert len(report.checks) > 0


def test_run_gate_branch_scope_label_names_deepest_selector():
    """The verdict's scope label names the deepest selector the caller
    supplied: 'G-001' at depth gs, 'G-001/T-001' at depth ts."""
    tree_gs = Step(
        uuid=GS_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3, step_id="G-001",
        slug="g", fields={"source_labels": []}, depends_on=[], concepts=[], project_id=None, status="draft",
    )
    tree_ts = Step(
        uuid=TS1_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=GS_UUID, level=4, step_id="T-001",
        slug="t-001", fields={}, depends_on=[], concepts=[], project_id=None, status="draft",
    )
    step_rows = [
        (GS_UUID, PLAN_UUID, None, 3, "G-001", "g", {"source_labels": []}, [], [], None, "draft"),
        (TS1_UUID, PLAN_UUID, GS_UUID, 4, "T-001", "t-001", {}, [], [], None, "draft"),
    ]
    conn = _FullFakeConn(
        step_rows=step_rows,
        concept_rows=[],
        paragraph_label_rows=[],
        paragraph_full_rows=[],
        context_block_rows=[],
        head_revision=HEAD_REVISION,
    )
    branch = BranchScope(plan_uuid=PLAN_UUID, depth="ts", gs=tree_gs, ts=tree_ts, atomic=None, hrs_slice=[])

    _, verdict = run_gate(conn, PLAN_UUID, branch=branch, fail_fast=True)

    assert verdict.scope == "G-001/T-001"
