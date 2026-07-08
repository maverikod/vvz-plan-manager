"""Scoring value types (C-013/C-014): config, refusal, and score records.

Split out of :mod:`plan_manager.scoring.index` to keep that module within the
file-size limit; ``index`` re-exports these names so existing imports of
``plan_manager.scoring.index.ScoringConfig`` etc. keep working.
"""

from __future__ import annotations

import dataclasses
import uuid

from plan_manager.scoring.embedding import READINESS_UNCONFIGURED


@dataclasses.dataclass
class ScoringConfig:
    """Published-default configuration consumed by the SemanticIndex fold.

    Attributes:
        threshold: branch/plan index threshold, published default 85.0.
        aggregation: plan-level aggregation mode, "minimum" or
            "fraction_above_threshold". Published default "minimum".
        concept_weight: per-concept weight applied to required concepts in
            embedding_estimator. Published default 1.0.
        trust_floor: declared trust floor used when the embedding service
            is unavailable. Published default 0.2.
        embedding_url: the embedding service base URL, or None when the
            embedding service is not configured.
        embedding_timeout: per-request embedding timeout in seconds,
            published default 60.0.

    Raises:
        ValueError: raised by __post_init__ when aggregation is not
            "minimum" or "fraction_above_threshold".
    """

    threshold: float = 85.0
    aggregation: str = "minimum"
    concept_weight: float = 1.0
    trust_floor: float = 0.2
    embedding_url: str | None = None
    embedding_timeout: float = 60.0

    def __post_init__(self) -> None:
        if self.aggregation not in ("minimum", "fraction_above_threshold"):
            raise ValueError(
                "aggregation must be 'minimum' or 'fraction_above_threshold', "
                f"got {self.aggregation!r}"
            )


class ScoreRefusedError(Exception):
    """Raised when a branch or plan scope's mechanical gate is not green.

    A scope whose gate is not green at the current revision is never
    measured (C-012 precedes C-013): score_branch and score_plan raise
    this error instead of computing an index.
    """


@dataclasses.dataclass
class BranchScore:
    """The 0..100 completeness index of one branch (C-008) with its color.

    Attributes:
        branch_path: the branch's path, e.g. "G-001/T-002/A-003".
        index: the 0..100 ensemble index.
        color: "green" iff index >= threshold, else "red".
        estimator_vector: mapping of estimator name to its vote value.
        trust: the TrustEstimate (C-014) value accompanying this score.
        revision_uuid: the plan revision the score was computed on.
        below_threshold: True iff color == "red".
        embedding_state: the embedding model readiness at scoring time —
            "ready" when the embedding estimator contributed, otherwise one
            of "unconfigured", "not_ready", or "unreachable" (score degraded
            to the deterministic estimators with trust at the floor).
        embedding_detail: a precise diagnostic explaining why the embedding
            estimator did not contribute when ``embedding_state`` is not
            "ready"; ``None`` when the embedding estimator contributed. This
            carries the real reason a batch vectorization failed even though
            the embedding health endpoint reported ready, so scoring never
            collapses to an unexplained "unreachable".
    """

    branch_path: str
    index: float
    color: str
    estimator_vector: dict[str, float]
    trust: float
    revision_uuid: uuid.UUID | None
    below_threshold: bool
    embedding_state: str = READINESS_UNCONFIGURED
    embedding_detail: str | None = None


@dataclasses.dataclass
class PlanScore:
    """The conservative plan-level aggregation of every branch's index.

    Attributes:
        index: the aggregated 0..100 plan index.
        color: "green" iff index >= threshold, else "red".
        aggregation: the aggregation mode used, "minimum" or
            "fraction_above_threshold".
        weakest: up to 3 BranchScore entries, ascending by index.
        revision_uuid: the plan revision the score was computed on.
        embedding_state: the embedding model readiness used for the whole
            plan aggregation (one preflight, one batch), "ready" when the
            embedding estimator contributed to every branch.
        embedding_detail: a precise diagnostic explaining why the embedding
            estimator did not contribute when ``embedding_state`` is not
            "ready"; ``None`` when the embedding estimator contributed.
    """

    index: float
    color: str
    aggregation: str
    weakest: list[BranchScore]
    revision_uuid: uuid.UUID | None
    embedding_state: str = READINESS_UNCONFIGURED
    embedding_detail: str | None = None
