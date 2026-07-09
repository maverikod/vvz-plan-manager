"""Node coefficient computation for SemanticReproductionTree (C-001).

Pure, deterministic functions that turn already-resolved embedding vectors
and scope-aware concept sets (ScopeAwareCoverageFoundation, C-002) into the
NodeCoefficientSet (C-006) of one plan tree node: semantic_fit,
reproduction_score, loss_score, leakage_score, and child_contribution.

This module performs no I/O and raises nothing: embedding vectors must
already be resolved by the caller (see plan_manager.scoring.diagnostics for
the degraded-diagnostics-aware fetch wrapper used by the tree builder).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class NodeCoefficientSet:
    """The five semantic coefficients computed for one plan tree node.

    Parameters
    ----------
    semantic_fit:
        Closeness of the node's own embedding vector to its expected-scope
        embedding vector, in [0.0, 1.0].
    reproduction_score:
        How well the mean of the node's children's own vectors reproduces
        the node's own vector, in [0.0, 1.0].
    loss_score:
        Fraction of the node's required concepts (ScopeAwareCoverageFoundation,
        C-002) that are absent from its declared concepts, in [0.0, 1.0].
    leakage_score:
        Fraction of the node's declared concepts that are not part of its
        required concepts, in [0.0, 1.0].
    child_contribution:
        Mapping of child path to that child's own-vector cosine similarity
        to the node's own vector, each in [0.0, 1.0].
    """

    semantic_fit: float
    reproduction_score: float
    loss_score: float
    leakage_score: float
    child_contribution: dict[str, float]


def _cosine(a: list[float], b: list[float]) -> float:
    """Return the cosine similarity of a and b, clamped to [0.0, 1.0].

    Returns 0.0 when either vector has zero norm.
    """
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return max(0.0, dot / (norm_a * norm_b))


def compute_semantic_fit(own_vector: list[float], expected_vector: list[float]) -> float:
    """Return the semantic_fit coefficient: closeness of own_vector to
    expected_vector (the node's ExpectedScope, C-005), as their cosine
    similarity clamped to [0.0, 1.0].
    """
    return _cosine(own_vector, expected_vector)


def compute_loss_score(required_concepts: set[str], declared_concepts: set[str]) -> float:
    """Return the loss_score coefficient: the fraction of required_concepts
    (from ScopeAwareCoverageFoundation, C-002) that is absent from
    declared_concepts. Returns 0.0 when required_concepts is empty.
    """
    if not required_concepts:
        return 0.0
    missing = required_concepts - declared_concepts
    return len(missing) / len(required_concepts)


def compute_leakage_score(required_concepts: set[str], declared_concepts: set[str]) -> float:
    """Return the leakage_score coefficient: the fraction of declared_concepts
    (from ScopeAwareCoverageFoundation, C-002) that is not part of
    required_concepts. Returns 0.0 when declared_concepts is empty.
    """
    if not declared_concepts:
        return 0.0
    extra = declared_concepts - required_concepts
    return len(extra) / len(declared_concepts)


def compute_reproduction_score(
    children_vectors: list[list[float]], own_vector: list[float]
) -> float:
    """Return the reproduction_score coefficient: how well the mean of
    children_vectors reproduces own_vector, as their cosine similarity
    clamped to [0.0, 1.0]. Returns 1.0 when children_vectors is empty (a
    leaf node has no children whose absence can cause reproduction loss).
    """
    if not children_vectors:
        return 1.0
    dim = len(own_vector)
    mean_vector = [
        sum(vector[i] for vector in children_vectors) / len(children_vectors)
        for i in range(dim)
    ]
    return _cosine(mean_vector, own_vector)


def compute_child_contribution(
    children_vectors: dict[str, list[float]], own_vector: list[float]
) -> dict[str, float]:
    """Return the child_contribution coefficient: for every entry of
    children_vectors (child path to child own-vector), that child's own
    vector's cosine similarity to own_vector, clamped to [0.0, 1.0].
    """
    return {
        child_path: _cosine(child_vector, own_vector)
        for child_path, child_vector in children_vectors.items()
    }


def compute_node_coefficients(
    own_vector: list[float],
    expected_vector: list[float],
    required_concepts: set[str],
    declared_concepts: set[str],
    children_vectors: dict[str, list[float]],
) -> NodeCoefficientSet:
    """Assemble the full NodeCoefficientSet (C-006) for one node.

    Parameters
    ----------
    own_vector:
        The node's own reconstructed-summary embedding vector
        (ReconstructedSummary, C-004).
    expected_vector:
        The node's expected-scope embedding vector (ExpectedScope, C-005).
    required_concepts, declared_concepts:
        The node's scope-aware concept sets (ScopeAwareCoverageFoundation,
        C-002), as produced by
        plan_manager.scoring.estimators.coverage_diagnostics.
    children_vectors:
        Mapping of child path to that child's own reconstructed-summary
        embedding vector, for every child whose own vector was successfully
        resolved.

    Returns
    -------
    NodeCoefficientSet
        The five coefficients for this node.
    """
    return NodeCoefficientSet(
        semantic_fit=compute_semantic_fit(own_vector, expected_vector),
        reproduction_score=compute_reproduction_score(
            list(children_vectors.values()), own_vector
        ),
        loss_score=compute_loss_score(required_concepts, declared_concepts),
        leakage_score=compute_leakage_score(required_concepts, declared_concepts),
        child_contribution=compute_child_contribution(children_vectors, own_vector),
    )
