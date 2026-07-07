"""Regression tests for the mechanical-gate reference resolver (C-012).

A ``depends_on`` entry is an ordering edge between sibling atomic steps
(same level, same parent tactical step). Its resolution universe must be
the full plan tree, so a branch-scoped gate run yields the same verdict
for one revision as a plan-scoped run. Resolving against the scoped
subset instead makes a branch run falsely report a sibling target as
unresolved, which previously blocked plan_score with GATE_RED for any
correct plan whose atomic steps carry ordering dependencies.
"""

from uuid import uuid4

from plan_manager.domain.step import Step
from plan_manager.verify.gate_data import GateTree
from plan_manager.verify.gate_refs import check_references_depends_on


def _atomic(uuid, parent_uuid, step_id, depends_on):
    return Step(
        uuid=uuid,
        plan_uuid=uuid4(),
        parent_step_uuid=parent_uuid,
        level=5,
        step_id=step_id,
        slug=step_id.lower(),
        fields={},
        depends_on=depends_on,
        concepts=[],
        project_id=None,
        status="draft",
    )


def _tree(steps):
    return GateTree(
        steps={step.uuid: step for step in steps},
        concept_ids=[],
        relations=[],
        labels=[],
        counts={},
    )


def test_sibling_depends_on_resolves_in_both_scopes():
    """A-002 -> A-001 (siblings) must resolve in plan and branch scope alike."""
    ts_uuid = uuid4()
    a1 = _atomic(uuid4(), ts_uuid, "A-001", [])
    a2 = _atomic(uuid4(), ts_uuid, "A-002", ["A-001"])
    tree = _tree([a1, a2])

    # Plan scope: both steps are reported over.
    plan_findings = check_references_depends_on(tree, [a1, a2])
    assert plan_findings == []

    # Branch scope: only A-002 is reported over, but A-001 still resolves
    # because the resolution universe is the full tree, not the subset.
    branch_findings = check_references_depends_on(tree, [a2])
    assert branch_findings == []


def test_unresolved_depends_on_still_flagged():
    """A genuinely missing target is reported in both scopes."""
    ts_uuid = uuid4()
    a2 = _atomic(uuid4(), ts_uuid, "A-002", ["A-001"])
    tree = _tree([a2])  # A-001 does not exist anywhere in the plan.

    findings = check_references_depends_on(tree, [a2])
    assert len(findings) == 1
    assert findings[0].check_id == "references.depends_on"
    assert "A-001" in findings[0].message


def test_cross_parent_sibling_not_resolved():
    """A-001 under a different tactical step must not resolve A-002's dep."""
    ts_a = uuid4()
    ts_b = uuid4()
    other = _atomic(uuid4(), ts_b, "A-001", [])
    a2 = _atomic(uuid4(), ts_a, "A-002", ["A-001"])
    tree = _tree([other, a2])

    findings = check_references_depends_on(tree, [a2])
    assert len(findings) == 1
    assert "A-001" in findings[0].message
