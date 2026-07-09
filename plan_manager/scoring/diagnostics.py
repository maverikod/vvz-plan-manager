"""Explicit degraded diagnostics for EmbeddingDegradedDiagnostics (C-010).

When the embedding service required by SemanticReproductionTree (C-001)
coefficient computation is unavailable, this module makes the mechanism
return an explicit DegradedDiagnostic instead of silently lowering or
hiding a node's coefficients, per EmbeddingDegradedDiagnostics (C-010).

Builds on plan_manager.scoring.embedding.EmbeddingUnavailable and
plan_manager.scoring.embedding_batch.embedding_health.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, TypeVar

from plan_manager.scoring.embedding import EmbeddingUnavailable
from plan_manager.scoring.embedding_batch import embedding_health

T = TypeVar("T")


@dataclass(frozen=True)
class DegradedDiagnostic:
    """An explicit degraded-diagnostics result for one plan tree node.

    Parameters
    ----------
    node_path:
        The step path of the node whose coefficient computation degraded.
    reason:
        The str argument carried by the EmbeddingUnavailable exception
        that triggered this diagnostic.
    embedding_state:
        The coarse embedding readiness state at the time of the failure, one
        of "unconfigured", "ready", "not_ready", "unreachable"
        (plan_manager.scoring.embedding_batch.embedding_health's "state").
    model_status:
        The raw embedding model status string reported by the embedding
        service's health payload, or None when unavailable.
    """

    node_path: str
    reason: str
    embedding_state: str
    model_status: str | None


def build_degraded_diagnostic(
    node_path: str, error: EmbeddingUnavailable, base_url: str | None
) -> DegradedDiagnostic:
    """Build the explicit DegradedDiagnostic for node_path from error.

    Calls embedding_health(base_url) to attach the current embedding
    readiness state and model status to the diagnostic, so the diagnostic
    distinguishes an unconfigured, unreachable, or not-yet-ready embedding
    service.
    """
    health = embedding_health(base_url)
    return DegradedDiagnostic(
        node_path=node_path,
        reason=str(error),
        embedding_state=health["state"],
        model_status=health["model_status"],
    )


def safe_fetch(
    node_path: str, base_url: str | None, fetch_fn: Callable[[], T]
) -> tuple[T | None, DegradedDiagnostic | None]:
    """Call fetch_fn() and turn an EmbeddingUnavailable failure into an
    explicit DegradedDiagnostic instead of letting the failure propagate or
    silently lowering the caller's score.

    Returns
    -------
    tuple[T | None, DegradedDiagnostic | None]
        (result, None) when fetch_fn() succeeds, or (None, diagnostic) when
        it raises EmbeddingUnavailable. The caller must check which of the
        two is not None; there is no silent default.
    """
    try:
        return fetch_fn(), None
    except EmbeddingUnavailable as exc:
        return None, build_degraded_diagnostic(node_path, exc, base_url)
