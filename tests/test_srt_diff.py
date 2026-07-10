"""SRT semantic diff over the REAL snapshot node schema.

Each snapshot's tree_content is dataclasses.asdict of a
SemanticReproductionTreeNode: a node dict carries 'path', 'own_vector',
'coefficients', and 'children'. 'coefficients' is either a scored
NodeCoefficientSet mapping (semantic_fit, reproduction_score, loss_score,
leakage_score, child_contribution) or a DegradedDiagnostic mapping (node_path,
reason, embedding_state, model_status) with no scores. These tests pin the diff
against that real shape: node improvement/degradation via semantic_fit, root
exclusion from the node lists, loss/leakage threshold transitions,
child-contribution changes, degraded<->scored transitions, and self-diff.
"""

from __future__ import annotations

from typing import Any

import pytest

from plan_manager.scoring.srt_diff import compute_semantic_diff


def _scored(
    path: str,
    semantic_fit: float,
    *,
    loss_score: float = 0.0,
    leakage_score: float = 0.0,
    child_contribution: dict[str, float] | None = None,
    children: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """A scored SemanticReproductionTreeNode as stored (asdict) in a snapshot."""
    return {
        "path": path,
        "own_vector": [1.0, 0.0],
        "coefficients": {
            "semantic_fit": semantic_fit,
            "reproduction_score": 1.0,
            "loss_score": loss_score,
            "leakage_score": leakage_score,
            "child_contribution": dict(child_contribution or {}),
        },
        "children": list(children or []),
    }


def _degraded(path: str, *, children: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """A degraded SemanticReproductionTreeNode as stored (asdict) in a snapshot."""
    return {
        "path": path,
        "own_vector": None,
        "coefficients": {
            "node_path": path,
            "reason": "embedding service unavailable",
            "embedding_state": "unreachable",
            "model_status": None,
        },
        "children": list(children or []),
    }


def _tree(root_fit: float, branch_fit: float) -> dict[str, Any]:
    """One PLAN root with a single G-001 branch child, both scored."""
    return _scored(
        "PLAN",
        root_fit,
        child_contribution={"G-001": branch_fit},
        children=[_scored("G-001", branch_fit)],
    )


def test_root_score_change_is_reported_only_as_root_score_delta() -> None:
    base = _tree(root_fit=0.40, branch_fit=0.50)
    target = _tree(root_fit=0.70, branch_fit=0.50)

    result = compute_semantic_diff(base, target)

    assert result.root_score_delta == pytest.approx(0.30)
    assert "PLAN" not in result.improved_nodes
    assert "PLAN" not in result.degraded_nodes
    assert result.improved_nodes == []
    assert result.degraded_nodes == []


def test_branch_improvement_lands_in_improved_nodes_without_root() -> None:
    base = _tree(root_fit=0.60, branch_fit=0.40)
    target = _tree(root_fit=0.60, branch_fit=0.75)

    result = compute_semantic_diff(base, target)

    assert result.root_score_delta == pytest.approx(0.0)
    assert result.improved_nodes == ["G-001"]
    assert result.degraded_nodes == []
    assert "PLAN" not in result.improved_nodes


def test_branch_degradation_lands_in_degraded_nodes_without_root() -> None:
    # Root improves while its branch degrades: the two are reported separately.
    base = _tree(root_fit=0.50, branch_fit=0.90)
    target = _tree(root_fit=0.65, branch_fit=0.30)

    result = compute_semantic_diff(base, target)

    assert result.root_score_delta == pytest.approx(0.15)
    assert result.degraded_nodes == ["G-001"]
    assert result.improved_nodes == []
    assert "PLAN" not in result.degraded_nodes


def test_degraded_to_scored_transition_does_not_crash_and_is_skipped() -> None:
    # Base root+branch degraded (no scores); target fully scored. The node lists
    # only carry nodes with a comparable score on both sides, so G-001 is absent.
    base = _degraded("PLAN", children=[_degraded("G-001")])
    target = _tree(root_fit=0.72, branch_fit=0.55)

    result = compute_semantic_diff(base, target)

    # Degraded root treated as score 0.0 -> delta is the target root fit.
    assert result.root_score_delta == pytest.approx(0.72)
    assert result.improved_nodes == []
    assert result.degraded_nodes == []
    # New loss/leakage do not fire: the degraded base had none and the target
    # branch declares none either.
    assert result.new_loss == []
    assert result.new_leakage == []


def test_loss_and_leakage_threshold_transitions() -> None:
    base = _scored(
        "PLAN",
        0.6,
        children=[
            _scored("G-001", 0.5, loss_score=0.0, leakage_score=0.4),
            _scored("G-002", 0.5, loss_score=0.3, leakage_score=0.0),
        ],
    )
    target = _scored(
        "PLAN",
        0.6,
        children=[
            _scored("G-001", 0.5, loss_score=0.5, leakage_score=0.0),
            _scored("G-002", 0.5, loss_score=0.0, leakage_score=0.0),
        ],
    )

    result = compute_semantic_diff(base, target)

    assert result.new_loss == ["G-001"]
    assert result.resolved_loss == ["G-002"]
    assert result.resolved_leakage == ["G-001"]
    assert result.new_leakage == []


def test_child_contribution_changes_are_reported() -> None:
    base = _scored("PLAN", 0.6, child_contribution={"G-001": 0.40, "G-002": 0.70})
    target = _scored("PLAN", 0.6, child_contribution={"G-001": 0.55, "G-002": 0.70})

    result = compute_semantic_diff(base, target)

    changes = result.child_contribution_changes
    assert len(changes) == 1
    change = changes[0]
    assert change.parent_path == "PLAN"
    assert change.child_path == "G-001"
    assert change.base_score == pytest.approx(0.40)
    assert change.target_score == pytest.approx(0.55)


def test_identical_trees_self_diff_is_empty_and_zero() -> None:
    tree = _scored(
        "PLAN",
        0.6,
        loss_score=0.2,
        leakage_score=0.1,
        child_contribution={"G-001": 0.4},
        children=[_scored("G-001", 0.4, loss_score=0.3)],
    )

    result = compute_semantic_diff(tree, tree)

    assert result.root_score_delta == pytest.approx(0.0)
    assert result.improved_nodes == []
    assert result.degraded_nodes == []
    assert result.new_loss == []
    assert result.resolved_loss == []
    assert result.new_leakage == []
    assert result.resolved_leakage == []
    assert result.child_contribution_changes == []
