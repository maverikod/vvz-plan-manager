"""Semantic reproduction tree assembly for SemanticReproductionTree (C-001).

Refactors the existing plan_score/scoring mechanism (plan_manager.scoring.index)
into a tree builder that walks a plan's full global/tactical/atomic hierarchy
bottom-up on the scope-aware coverage foundation (ScopeAwareCoverageFoundation,
C-002) and attaches a NodeCoefficientSet (C-006) — or, when the embedding
service is unavailable, an explicit DegradedDiagnostic (C-010) — at every
node, producing a diagnostic tree rather than a single flat score. Does not
change the external behavior of the plan_score, branch_weak, or plan_validate
commands.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from plan_manager.scoring.coefficients import NodeCoefficientSet, compute_node_coefficients
from plan_manager.scoring.diagnostics import DegradedDiagnostic, safe_fetch


@dataclass(frozen=True)
class ScopedNode:
    """One node of the plan hierarchy, scoped for reproduction-tree assembly.

    Parameters
    ----------
    path:
        The node's step path (for example "G-002/T-101/A-001").
    own_text:
        The node's own reconstructed-summary text (ReconstructedSummary,
        C-004): its own description plus the summaries of its children.
    expected_text:
        The node's expected-scope text (ExpectedScope, C-005): the
        concept-aware HRS/MRS slice the node is compared against.
    required_concepts, declared_concepts:
        The node's scope-aware concept sets (ScopeAwareCoverageFoundation,
        C-002), as produced by
        plan_manager.scoring.estimators.coverage_diagnostics.
    children:
        The node's direct children, each a ScopedNode, in the order they
        contribute to this node's ReconstructedSummary.
    """

    path: str
    own_text: str
    expected_text: str
    required_concepts: set[str]
    declared_concepts: set[str]
    children: list["ScopedNode"]


@dataclass(frozen=True)
class SemanticReproductionTreeNode:
    """One node of the assembled SemanticReproductionTree (C-001).

    Parameters
    ----------
    path:
        The node's step path, copied from the source ScopedNode.
    own_vector:
        The node's own resolved embedding vector, or None when embedding
        resolution degraded for this node.
    coefficients:
        The node's NodeCoefficientSet (C-006) when embedding resolution
        succeeded, or its DegradedDiagnostic (C-010) when it did not.
    children:
        The node's already-built child SemanticReproductionTreeNode
        entries.
    """

    path: str
    own_vector: list[float] | None
    coefficients: NodeCoefficientSet | DegradedDiagnostic
    children: list["SemanticReproductionTreeNode"]


def build_node(
    node: ScopedNode,
    base_url: str | None,
    embed_fn: Callable[[str], list[float]],
) -> SemanticReproductionTreeNode:
    """Recursively build the SemanticReproductionTreeNode for node.

    Builds every child of node first (bottom-up), then resolves node's own
    and expected embedding vectors through embed_fn via
    plan_manager.scoring.diagnostics.safe_fetch. When either resolution
    degrades, this node's coefficients is the resulting DegradedDiagnostic
    and no coefficient computation is attempted for this node. Otherwise
    coefficients is the NodeCoefficientSet computed by
    plan_manager.scoring.coefficients.compute_node_coefficients from this
    node's own and expected vectors, its required_concepts and
    declared_concepts, and the own vectors of the children whose own
    resolution succeeded (children with a degraded own vector are excluded
    from children_vectors without themselves degrading this node).
    """
    children_results = [build_node(child, base_url, embed_fn) for child in node.children]

    own_vector, own_diag = safe_fetch(
        node.path, base_url, lambda: embed_fn(node.own_text)
    )
    if own_vector is None:
        return SemanticReproductionTreeNode(
            path=node.path, own_vector=None, coefficients=own_diag, children=children_results
        )

    expected_vector, expected_diag = safe_fetch(
        node.path, base_url, lambda: embed_fn(node.expected_text)
    )
    if expected_vector is None:
        return SemanticReproductionTreeNode(
            path=node.path,
            own_vector=own_vector,
            coefficients=expected_diag,
            children=children_results,
        )

    children_vectors = {
        child_result.path: child_result.own_vector
        for child_result in children_results
        if child_result.own_vector is not None
    }
    coefficients = compute_node_coefficients(
        own_vector,
        expected_vector,
        node.required_concepts,
        node.declared_concepts,
        children_vectors,
    )
    return SemanticReproductionTreeNode(
        path=node.path,
        own_vector=own_vector,
        coefficients=coefficients,
        children=children_results,
    )


def build_tree(
    root: ScopedNode,
    base_url: str | None,
    embed_fn: Callable[[str], list[float]],
) -> SemanticReproductionTreeNode:
    """Build the full SemanticReproductionTree (C-001) rooted at root.

    Public entry point of the tree builder: delegates to build_node on
    root, so the whole global/tactical/atomic hierarchy under root is
    walked bottom-up and annotated with coefficients or degraded
    diagnostics at every node.
    """
    return build_node(root, base_url, embed_fn)
