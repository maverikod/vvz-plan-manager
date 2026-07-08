"""Regression: branch coverage must use declared branch scope before labels."""

from uuid import uuid4

from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.step import Step
from plan_manager.scoring.estimators import (
    concepts_from_hrs_slice,
    coverage_diagnostics,
    coverage_estimator,
    declared_concepts,
    required_concepts,
)
from plan_manager.scoring.index import branch_summary
from plan_manager.scoring.types import BranchScore
from plan_manager.views.branch import Branch


def _step(level: int, step_id: str, concepts: list[str], parent=None) -> Step:
    return Step(
        uuid=uuid4(),
        plan_uuid=parent.plan_uuid if parent is not None else uuid4(),
        parent_step_uuid=parent.uuid if parent is not None else None,
        level=level,
        step_id=step_id,
        slug=step_id.lower(),
        fields={},
        depends_on=[],
        concepts=concepts,
        project_id=None,
        status="draft",
    )


def test_required_concepts_prefers_declared_as_scope_over_label_expansion() -> None:
    gs = _step(3, "G-001", [])
    ts = _step(4, "T-001", [], gs)
    atomic = _step(5, "A-001", ["C-013"], ts)
    branch = Branch(
        plan_uuid=gs.plan_uuid,
        gs=gs,
        ts=ts,
        atomic=atomic,
        hrs_slice=[Paragraph(label="e5f6", text="shared source", position=0)],
    )
    concept_rows = [
        ("C-001", "broad system concept", ["{e5f6}"]),
        ("C-013", "branch storage concept", ["{e5f6}"]),
    ]

    assert concepts_from_hrs_slice(branch, concept_rows) == {"C-001", "C-013"}

    required = required_concepts(branch, concept_rows)
    declared = declared_concepts(branch)
    diagnostics = coverage_diagnostics(branch, concept_rows, required, declared)

    assert required == {"C-013"}
    assert coverage_estimator(required, declared) == 1.0
    assert diagnostics["missing_concepts"] == []
    assert diagnostics["extra_declared_concepts"] == []
    assert diagnostics["scope_source"] == "as_or_ts_declared_scope"
    assert diagnostics["source_labels_used"] == ["e5f6"]
    assert diagnostics["formula"] == "1 / 1"


def test_required_concepts_falls_back_to_legacy_labels_without_declared_scope() -> None:
    gs = _step(3, "G-001", [])
    ts = _step(4, "T-001", [], gs)
    atomic = _step(5, "A-001", [], ts)
    branch = Branch(
        plan_uuid=gs.plan_uuid,
        gs=gs,
        ts=ts,
        atomic=atomic,
        hrs_slice=[Paragraph(label="e5f6", text="shared source", position=0)],
    )
    concept_rows = [
        ("C-001", "broad system concept", ["{e5f6}"]),
        ("C-013", "branch storage concept", ["{e5f6}"]),
    ]

    required = required_concepts(branch, concept_rows)
    diagnostics = coverage_diagnostics(
        branch, concept_rows, required, declared_concepts(branch)
    )

    assert required == {"C-001", "C-013"}
    assert diagnostics["scope_source"] == "legacy_gs_source_labels"


def test_branch_summary_verbose_includes_coverage_diagnostics() -> None:
    score = BranchScore(
        branch_path="G-005/T-002/A-002",
        index=100.0,
        color="green",
        estimator_vector={"coverage": 1.0, "references": 1.0},
        trust=0.8,
        revision_uuid=None,
        below_threshold=False,
        coverage={
            "required_concepts": ["C-013"],
            "declared_concepts": ["C-013"],
            "missing_concepts": [],
            "extra_declared_concepts": [],
            "source_labels_used": ["e5f6"],
            "scope_source": "as_or_ts_declared_scope",
            "formula": "1 / 1",
        },
    )

    summary = branch_summary(score, verbose=True)

    assert summary["coverage"] == {
        "value": 1.0,
        "required_concepts": ["C-013"],
        "declared_concepts": ["C-013"],
        "missing_concepts": [],
        "extra_declared_concepts": [],
        "source_labels_used": ["e5f6"],
        "scope_source": "as_or_ts_declared_scope",
        "formula": "1 / 1",
    }
