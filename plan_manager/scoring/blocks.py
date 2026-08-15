"""Presentation helpers for the scoring layer (readiness diagnostic + response blocks).

Split out of :mod:`plan_manager.scoring.index` for the same reason
:mod:`plan_manager.scoring.types` was: EIG block G's ``contours`` block
pushed that module past the repository's hard 400-line-per-file cap, and the
cheapest thing to lift out is the layer that only FORMATS an already computed
score. ``index`` re-exports every name here, so existing imports of
``plan_manager.scoring.index.embedding_block`` / ``branch_summary`` keep
working unchanged.
"""

from __future__ import annotations

from plan_manager.scoring.embedding import (
    READINESS_READY,
    READINESS_UNCONFIGURED,
    READINESS_UNREACHABLE,
)
from plan_manager.scoring.types import BranchScore
from plan_manager.verify.gate_contours import contours_payload, semantic_contour


def _readiness_detail(health: dict) -> str:
    """Explain, for a not-ready health verdict, why scoring cannot embed.

    ``health`` is the detail dict returned by ``embedding_health`` (the same
    probe the platform ``health`` command uses), so the scoring diagnostic and
    the health surface always agree on why the model is unusable.
    """
    state = health.get("state")
    if state == READINESS_UNCONFIGURED:
        return "embedding service is not configured"
    if state == READINESS_UNREACHABLE:
        return "embedding health endpoint did not answer within the configured timeout"
    status = health.get("model_status")
    return (
        "embedding transport reachable but model is not ready "
        f"(model_status={status!r})"
    )


def embedding_block(embedding_state: str, embedding_detail: str | None) -> dict:
    """Build the scoring commands' ``embedding`` status block."""
    block: dict = {
        "available": embedding_state == READINESS_READY,
        "state": embedding_state,
    }
    if embedding_detail is not None:
        block["detail"] = embedding_detail
    return block


def contours_block(contours: dict | None) -> dict:
    """Build the scoring commands' ``contours`` block (EIG block G).

    A score exists only past a GREEN mechanical gate, so the semantic
    contour is always "scored" here and a missing partition (``None``,
    e.g. a BranchScore constructed outside score_branch) reads as both
    gate contours green.
    """
    return contours_payload(
        contours,
        semantic_contour(
            "scored",
            "SemanticIndex was computed for this scope at the reported revision.",
        ),
    )


def branch_summary(score: BranchScore, verbose: bool = False) -> dict:
    """Build the output-discipline summary dict for one BranchScore."""
    summary: dict = {
        "branch_path": score.branch_path,
        "index": score.index,
        "color": score.color,
    }
    if score.below_threshold or verbose:
        summary["estimator_vector"] = score.estimator_vector
        summary["trust"] = score.trust
        if score.coverage is not None:
            summary["coverage"] = {
                "value": score.estimator_vector.get("coverage"),
                **score.coverage,
            }
    return summary
