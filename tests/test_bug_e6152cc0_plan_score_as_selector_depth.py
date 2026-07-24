"""Regression for bug e6152cc0: plan_score crashes on AS selectors because
Branch.depth is missing.

Root cause: ``score_branch`` (plan_manager/scoring/index.py) resolved its
branch via ``plan_manager.views.branch.resolve_branch``, which returns a
plain ``Branch`` (plan_uuid, gs, ts, atomic, hrs_slice -- no ``depth``
field). That object was then handed to ``run_gate(conn, plan_uuid,
branch=branch)`` (plan_manager/verify/gate.py), whose very first scoping
step -- ``scope_steps(tree, branch)`` in plan_manager/verify/gate_data.py
line 117 -- dereferences ``branch.depth`` to decide which steps the
hierarchical gate covers (bug e197b94a's depth dispatch: "gs" / "ts" /
"as"). A plain ``Branch`` has no such attribute, so any ``plan_score`` (or
``branch_weak``) call with scope="branch" (an AS-level selector: gs_step_id
+ ts_step_id + as_step_id all supplied) raised
``AttributeError: 'Branch' object has no attribute 'depth'``.

``score_plan`` never hit this: its own ``run_gate`` call always passes
``branch=None`` (whole-plan gate), and the per-triple ``Branch`` objects it
builds via ``resolve_branch`` for text/estimator purposes are never handed
to ``run_gate``.

The fix threads ``resolve_branch_scope`` (which returns ``BranchScope`` --
same fields plus ``depth``) through ``score_branch`` instead of
``resolve_branch``. With all three selectors supplied, ``resolve_branch_scope``
always resolves ``depth="as"`` with ``gs``/``ts``/``atomic`` all populated,
so it is a structural drop-in for every downstream consumer
(``_branch_required_texts``, ``_score_one``, and the estimators in
plan_manager/scoring/estimators.py, which only ever read
``.gs``/``.ts``/``.atomic``/``.hrs_slice``/``.plan_uuid``).

Test A pins the exact root-cause line directly: ``scope_steps`` must reject
a depth-less ``Branch`` and accept a ``BranchScope``. Test B exercises the
real public entry point, ``plan_manager.scoring.index.score_branch``,
through the actual (unstubbed) ``run_gate``/``scope_steps`` call chain, with
only the DB-touching hops stubbed -- mirroring the stubbing style already
used by tests/test_scoring_embedding_diagnostics.py.
"""

from uuid import uuid4

import pytest

from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.step import Step
from plan_manager.scoring import index
from plan_manager.scoring.index import ScoringConfig, score_branch
from plan_manager.scoring.types import BranchScore
from plan_manager.verify import gate
from plan_manager.verify.gate_data import GateTree, scope_steps
from plan_manager.views.branch import Branch, BranchScope

PLAN_UUID = uuid4()


def _steps() -> tuple[Step, Step, Step]:
    gs = Step(
        uuid=uuid4(), plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3,
        step_id="G-001", slug="g", fields={"description": "global goal"},
        depends_on=[], concepts=["C-001"], project_id=None, status="draft",
    )
    ts = Step(
        uuid=uuid4(), plan_uuid=PLAN_UUID, parent_step_uuid=gs.uuid, level=4,
        step_id="T-001", slug="t", fields={"description": "tactical plan"},
        depends_on=[], concepts=[], project_id=None, status="draft",
    )
    atomic = Step(
        uuid=uuid4(), plan_uuid=PLAN_UUID, parent_step_uuid=ts.uuid, level=5,
        step_id="A-001", slug="a", fields={"prompt": "atomic prompt"},
        depends_on=[], concepts=[], project_id=None, status="draft",
    )
    return gs, ts, atomic


def test_scope_steps_rejects_plain_branch_missing_depth() -> None:
    """Pins the exact root-cause line: gate_data.scope_steps dereferences
    branch.depth, which plain Branch (the pre-fix resolve_branch result)
    does not carry."""
    gs, ts, atomic = _steps()
    tree = GateTree(
        steps={gs.uuid: gs, ts.uuid: ts, atomic.uuid: atomic},
        concept_ids=["C-001"], relations=[], labels=[], counts={},
    )
    plain_branch = Branch(plan_uuid=PLAN_UUID, gs=gs, ts=ts, atomic=atomic, hrs_slice=[])

    with pytest.raises(AttributeError, match="depth"):
        scope_steps(tree, plain_branch)  # type: ignore[arg-type]

    scoped_branch = BranchScope(
        plan_uuid=PLAN_UUID, depth="as", gs=gs, ts=ts, atomic=atomic, hrs_slice=[]
    )
    assert scope_steps(tree, scoped_branch) == [gs, ts, atomic]


CONCEPT_ROWS = [("C-001", "concept one definition", ["{L1}"])]


# Every per-group check function run_gate calls (plan_manager/verify/gate.py
# GROUP_ORDER). This test targets ONLY the depth-dispatch bug (scope_steps +
# the tail scope_label branch in run_gate), not the content of each check, so
# every one of these is stubbed to report no findings -- the real, unstubbed
# code under test is run_gate's own control flow: load_tree -> scope_steps
# (bug e6152cc0's crash site) -> the group loop -> the branch.depth-keyed
# scope_label tail (bug e197b94a's crash site, same missing-depth failure
# mode). The two conn-driven coverage/context checks are stubbed for the same
# reason load_tree is: this test supplies no real database connection.
_NO_FINDINGS_CHECKS = [
    "check_parse_required_fields",
    "check_parse_inputs_outputs",
    "check_parse_target_file",
    "check_parse_atomic_single_code_file",
    "check_parse_sanity_counts",
    "check_identity_step_id",
    "check_identity_slug",
    "check_identity_concept_id",
    "check_identity_label",
    "check_uniqueness_step_id",
    "check_uniqueness_concept_id",
    "check_uniqueness_label",
    "check_uniqueness_priority",
    "check_references_depends_on",
    "check_references_concepts",
    "check_references_relations",
    "check_references_source_labels",
    "check_dependencies_same_file_order",
    "check_coverage_gs",
    "check_embedded_code_parses",
    "check_context_coverage_common_current",
    "check_context_coverage_specific_subset",
]


def _patch_branch_flow(monkeypatch, gs: Step, ts: Step, atomic: Step) -> None:
    """Stub only the DB-touching hops and per-check content of score_branch ->
    run_gate, keeping the real (unstubbed) run_gate / scope_steps depth-
    dispatch code -- the code path this bug lives in -- in the loop."""
    steps = {gs.uuid: gs, ts.uuid: ts, atomic.uuid: atomic}
    tree = GateTree(
        steps=steps, concept_ids=["C-001"], relations=[], labels=[], counts={},
    )
    monkeypatch.setattr(gate, "load_tree", lambda conn, plan_uuid: tree)
    for name in _NO_FINDINGS_CHECKS:
        monkeypatch.setattr(gate, name, lambda *a, **k: [])
    monkeypatch.setattr(gate, "current_head_revision", lambda conn, plan_uuid: uuid4())
    monkeypatch.setattr(index, "load_concept_rows", lambda conn, plan_uuid: CONCEPT_ROWS)
    monkeypatch.setattr(index, "current_head_revision", lambda conn, plan_uuid: uuid4())


def _config() -> ScoringConfig:
    # embedding_url=None -> _resolve_vectors degrades without any network call.
    return ScoringConfig(
        threshold=85.0, aggregation="minimum", concept_weight=1.0,
        trust_floor=0.2, embedding_url=None, embedding_timeout=30.0,
    )


def test_score_branch_as_selector_does_not_crash_on_missing_depth(monkeypatch) -> None:
    """End-to-end regression at the plan_score entry point: score_branch with
    an AS-level selector (scope="branch", all three ids supplied) must not
    raise AttributeError('depth') and must return a real BranchScore.

    Both resolver doubles below are wired so this single test reproduces the
    pre-fix crash (score_branch called ``resolve_branch``, whose plain
    ``Branch`` has no ``depth``) and pins the post-fix behavior (score_branch
    calls ``resolve_branch_scope``, whose ``BranchScope`` carries
    ``depth="as"``) without editing the test between the two states -- only
    whichever resolver score_branch actually calls is exercised.
    """
    gs, ts, atomic = _steps()
    hrs_slice = [Paragraph(label="L1", text="binding text", position=0)]
    monkeypatch.setattr(
        index, "resolve_branch",
        lambda conn, plan_uuid, gs_id, ts_id, as_id: Branch(
            plan_uuid=PLAN_UUID, gs=gs, ts=ts, atomic=atomic, hrs_slice=hrs_slice
        ),
    )
    monkeypatch.setattr(
        index, "resolve_branch_scope",
        lambda conn, plan_uuid, gs_id, ts_id, as_id: BranchScope(
            plan_uuid=PLAN_UUID, depth="as", gs=gs, ts=ts, atomic=atomic,
            hrs_slice=hrs_slice,
        ),
        raising=False,
    )
    _patch_branch_flow(monkeypatch, gs, ts, atomic)

    score = score_branch(
        conn=None,
        plan_uuid=PLAN_UUID,
        gs_step_id="G-001",
        ts_step_id="T-001",
        as_step_id="A-001",
        config=_config(),
    )

    assert isinstance(score, BranchScore)
    assert score.branch_path == "G-001/T-001/A-001"
