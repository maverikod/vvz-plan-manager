"""Semantic diff: source-diff-like comparison between two semantic tree snapshots.

Each snapshot's tree_content is a nested mapping representing one tree node
with keys: 'path' (str, stable identifier unique within the tree), 'score'
(float, the node's semantic coefficient), 'loss' (bool, optional, defaults
False), 'leakage' (bool, optional, defaults False), and 'children' (list of
same-shape mappings, optional, defaults empty).
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
        base_score = base_node.get("score")
        target_score = target_node.get("score")
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
    for path, target_node in target_index.items():
        base_node = base_index.get(path)
        base_loss = bool(base_node.get("loss")) if base_node is not None else False
        target_loss = bool(target_node.get("loss"))
        if target_loss and not base_loss:
            new_loss.append(path)
        base_leakage = bool(base_node.get("leakage")) if base_node is not None else False
        target_leakage = bool(target_node.get("leakage"))
        if target_leakage and not base_leakage:
            new_leakage.append(path)
    for path, base_node in base_index.items():
        target_node = target_index.get(path)
        target_loss = bool(target_node.get("loss")) if target_node is not None else False
        if bool(base_node.get("loss")) and not target_loss:
            resolved_loss.append(path)
        target_leakage = bool(target_node.get("leakage")) if target_node is not None else False
        if bool(base_node.get("leakage")) and not target_leakage:
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
        base_children = {c["path"]: c.get("score") for c in (base_parent.get("children", []) if base_parent else [])}
        target_children = {c["path"]: c.get("score") for c in (target_parent.get("children", []) if target_parent else [])}
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
    root_score_delta = float(target_tree_content.get("score", 0.0)) - float(base_tree_content.get("score", 0.0))
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
