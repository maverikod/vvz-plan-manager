"""Semantic diff: source-diff-like comparison between two semantic tree snapshots.

Each snapshot's tree_content is dataclasses.asdict of a
SemanticReproductionTreeNode (plan_manager.scoring.reproduction_tree): a nested
mapping with keys 'path' (str, a stable identifier unique within the tree),
'own_vector' (list[float] | None), 'coefficients', and 'children' (list of
same-shape mappings, defaults empty). 'coefficients' is EITHER a scored
NodeCoefficientSet mapping with float keys 'semantic_fit', 'reproduction_score',
'loss_score', 'leakage_score' and a 'child_contribution' mapping of child path
to float, OR a DegradedDiagnostic mapping with keys 'node_path', 'reason',
'embedding_state', 'model_status' (carrying no scores) when embedding
resolution degraded for that node.

A node's comparable score is coefficients.semantic_fit, the node's own closeness
to its expected scope; a degraded node has no score and is skipped by the score
diff. Loss and leakage presence is read as coefficients.loss_score /
coefficients.leakage_score being present and strictly greater than 0.0; a
degraded node carries neither. Child-contribution changes are read from
coefficients.child_contribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChildContributionChange:
    parent_path: str
    child_path: str
    base_score: float | None
    target_score: float | None


@dataclass(frozen=True)
class SemanticDiffResult:
    root_score_delta: float
    improved_nodes: list[str]
    degraded_nodes: list[str]
    new_loss: list[str]
    resolved_loss: list[str]
    new_leakage: list[str]
    resolved_leakage: list[str]
    child_contribution_changes: list[ChildContributionChange]

    def to_payload(self) -> dict[str, Any]:
        return {
            "root_score_delta": self.root_score_delta,
            "improved_nodes": list(self.improved_nodes),
            "degraded_nodes": list(self.degraded_nodes),
            "new_loss": list(self.new_loss),
            "resolved_loss": list(self.resolved_loss),
            "new_leakage": list(self.new_leakage),
            "resolved_leakage": list(self.resolved_leakage),
            "child_contribution_changes": [
                {
                    "parent_path": c.parent_path,
                    "child_path": c.child_path,
                    "base_score": c.base_score,
                    "target_score": c.target_score,
                }
                for c in self.child_contribution_changes
            ],
        }


def _index_nodes_by_path(tree_content: dict[str, Any]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}

    def _walk(node: dict[str, Any]) -> None:
        index[node["path"]] = node
        for child in node.get("children", []):
            _walk(child)

    _walk(tree_content)
    return index


def _node_semantic_fit(node: dict[str, Any]) -> float | None:
    """Return the node's own semantic_fit coefficient, or None when the node is
    degraded (its coefficients is a DegradedDiagnostic that carries no scores).
    """
    coefficients = node.get("coefficients")
    if not isinstance(coefficients, dict):
        return None
    semantic_fit = coefficients.get("semantic_fit")
    if semantic_fit is None:
        return None
    return float(semantic_fit)


def _node_loss_present(node: dict[str, Any]) -> bool:
    """Return whether the node declares scope loss: a scored coefficients set
    whose loss_score is present and strictly greater than 0.0. A degraded node
    carries no loss_score and is treated as no loss.
    """
    coefficients = node.get("coefficients")
    if not isinstance(coefficients, dict):
        return False
    loss_score = coefficients.get("loss_score")
    return loss_score is not None and float(loss_score) > 0.0


def _node_leakage_present(node: dict[str, Any]) -> bool:
    """Return whether the node declares scope leakage: a scored coefficients set
    whose leakage_score is present and strictly greater than 0.0. A degraded
    node carries no leakage_score and is treated as no leakage.
    """
    coefficients = node.get("coefficients")
    if not isinstance(coefficients, dict):
        return False
    leakage_score = coefficients.get("leakage_score")
    return leakage_score is not None and float(leakage_score) > 0.0


def _node_child_contribution(node: dict[str, Any]) -> dict[str, float]:
    """Return the node's child_contribution mapping (child path to that child's
    cosine contribution to the node's own vector), or an empty mapping when the
    node is degraded or declares no child contributions.
    """
    coefficients = node.get("coefficients")
    if not isinstance(coefficients, dict):
        return {}
    child_contribution = coefficients.get("child_contribution")
    if not isinstance(child_contribution, dict):
        return {}
    return child_contribution


def _diff_node_scores(
    base_index: dict[str, dict[str, Any]],
    target_index: dict[str, dict[str, Any]],
    root_path: str,
) -> tuple[list[str], list[str]]:
    improved_nodes: list[str] = []
    degraded_nodes: list[str] = []
    for path, target_node in target_index.items():
        # The root node's delta is dedicated to root_score_delta; the node
        # lists speak only about branches, so the root path is excluded here.
        if path == root_path:
            continue
        base_node = base_index.get(path)
        if base_node is None:
            continue
        base_score = _node_semantic_fit(base_node)
        target_score = _node_semantic_fit(target_node)
        # A node scored on one side and degraded on the other has no comparable
        # score; skip it rather than invent a semantic_fit for a degraded node.
        if base_score is None or target_score is None:
            continue
        if target_score > base_score:
            improved_nodes.append(path)
        elif target_score < base_score:
            degraded_nodes.append(path)
    return improved_nodes, degraded_nodes


def _diff_loss_leakage(
    base_index: dict[str, dict[str, Any]],
    target_index: dict[str, dict[str, Any]],
) -> tuple[list[str], list[str], list[str], list[str]]:
    new_loss: list[str] = []
    resolved_loss: list[str] = []
    new_leakage: list[str] = []
    resolved_leakage: list[str] = []
    for path in sorted(set(base_index.keys()) | set(target_index.keys())):
        base_node = base_index.get(path)
        target_node = target_index.get(path)
        base_loss = base_node is not None and _node_loss_present(base_node)
        target_loss = target_node is not None and _node_loss_present(target_node)
        if target_loss and not base_loss:
            new_loss.append(path)
        elif base_loss and not target_loss:
            resolved_loss.append(path)
        base_leakage = base_node is not None and _node_leakage_present(base_node)
        target_leakage = target_node is not None and _node_leakage_present(target_node)
        if target_leakage and not base_leakage:
            new_leakage.append(path)
        elif base_leakage and not target_leakage:
            resolved_leakage.append(path)
    return new_loss, resolved_loss, new_leakage, resolved_leakage


def _diff_child_contributions(
    base_index: dict[str, dict[str, Any]],
    target_index: dict[str, dict[str, Any]],
) -> list[ChildContributionChange]:
    changes: list[ChildContributionChange] = []
    parent_paths = set(base_index.keys()) | set(target_index.keys())
    for parent_path in sorted(parent_paths):
        base_parent = base_index.get(parent_path)
        target_parent = target_index.get(parent_path)
        base_children = _node_child_contribution(base_parent) if base_parent is not None else {}
        target_children = _node_child_contribution(target_parent) if target_parent is not None else {}
        child_paths = set(base_children.keys()) | set(target_children.keys())
        for child_path in sorted(child_paths):
            base_score = base_children.get(child_path)
            target_score = target_children.get(child_path)
            if base_score != target_score:
                changes.append(
                    ChildContributionChange(
                        parent_path=parent_path,
                        child_path=child_path,
                        base_score=base_score,
                        target_score=target_score,
                    )
                )
    return changes


def compute_semantic_diff(
    base_tree_content: dict[str, Any],
    target_tree_content: dict[str, Any],
) -> SemanticDiffResult:
    base_index = _index_nodes_by_path(base_tree_content)
    target_index = _index_nodes_by_path(target_tree_content)
    root_path = str(target_tree_content["path"])
    base_root_score = _node_semantic_fit(base_tree_content)
    target_root_score = _node_semantic_fit(target_tree_content)
    # A degraded root carries no semantic_fit; treat its score as 0.0 so the
    # delta still reports the move between an unscorable and a scored root.
    root_score_delta = (
        (target_root_score if target_root_score is not None else 0.0)
        - (base_root_score if base_root_score is not None else 0.0)
    )
    improved_nodes, degraded_nodes = _diff_node_scores(base_index, target_index, root_path)
    new_loss, resolved_loss, new_leakage, resolved_leakage = _diff_loss_leakage(base_index, target_index)
    child_contribution_changes = _diff_child_contributions(base_index, target_index)
    return SemanticDiffResult(
        root_score_delta=root_score_delta,
        improved_nodes=improved_nodes,
        degraded_nodes=degraded_nodes,
        new_loss=new_loss,
        resolved_loss=resolved_loss,
        new_leakage=new_leakage,
        resolved_leakage=resolved_leakage,
        child_contribution_changes=child_contribution_changes,
    )
