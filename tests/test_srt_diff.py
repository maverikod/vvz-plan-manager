"""SRT semantic diff: the root node is excluded from the node lists.

The root's score change is reported solely through summary field
root_score_delta; improved_nodes and degraded_nodes speak only about branch
nodes. These tests pin that contract and the surrounding diff behaviour.
"""

from __future__ import annotations

from typing import Any

import pytest

from plan_manager.scoring.srt_diff import compute_semantic_diff


def _tree(root_score: float, branch_score: float) -> dict[str, Any]:
    """One PLAN root with a single G-001 branch child."""
    return {
        "path": "PLAN",
        "score": root_score,
        "children": [
            {"path": "G-001", "score": branch_score, "children": []},
        ],
    }


def test_root_score_change_is_reported_only_as_root_score_delta() -> None:
    base = _tree(root_score=0.40, branch_score=0.50)
    target = _tree(root_score=0.70, branch_score=0.50)

    result = compute_semantic_diff(base, target)

    # The root moved up by 0.30; that lives in root_score_delta alone.
    assert result.root_score_delta == pytest.approx(0.30)
    # The root path never appears in the branch-only node lists.
    assert "PLAN" not in result.improved_nodes
    assert "PLAN" not in result.degraded_nodes
    # No branch changed, so both lists stay empty.
    assert result.improved_nodes == []
    assert result.degraded_nodes == []


def test_degraded_root_still_absent_from_node_lists() -> None:
    base = _tree(root_score=0.80, branch_score=0.50)
    target = _tree(root_score=0.55, branch_score=0.50)

    result = compute_semantic_diff(base, target)

    assert result.root_score_delta == pytest.approx(-0.25)
    assert "PLAN" not in result.improved_nodes
    assert "PLAN" not in result.degraded_nodes


def test_branch_node_change_still_lands_in_the_lists() -> None:
    base = _tree(root_score=0.60, branch_score=0.40)
    target = _tree(root_score=0.60, branch_score=0.75)

    result = compute_semantic_diff(base, target)

    # The root is unchanged; only the branch moved.
    assert result.root_score_delta == 0.0
    assert result.improved_nodes == ["G-001"]
    assert result.degraded_nodes == []
    assert "PLAN" not in result.improved_nodes


def test_branch_degradation_lands_in_degraded_nodes_without_root() -> None:
    # Root improves while its branch degrades: the two are reported separately.
    base = _tree(root_score=0.50, branch_score=0.90)
    target = _tree(root_score=0.65, branch_score=0.30)

    result = compute_semantic_diff(base, target)

    assert result.root_score_delta == pytest.approx(0.15)
    assert result.degraded_nodes == ["G-001"]
    assert result.improved_nodes == []
    assert "PLAN" not in result.degraded_nodes


def test_identical_trees_self_diff_is_empty_and_zero() -> None:
    tree = _tree(root_score=0.60, branch_score=0.40)

    result = compute_semantic_diff(tree, tree)

    assert result.root_score_delta == 0.0
    assert result.improved_nodes == []
    assert result.degraded_nodes == []
    assert result.new_loss == []
    assert result.resolved_loss == []
    assert result.new_leakage == []
    assert result.resolved_leakage == []
    assert result.child_contribution_changes == []
