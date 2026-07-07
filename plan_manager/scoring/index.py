"""SemanticIndex (C-013) scoring: branch and plan-level ensemble measurement.

Implements the normative fold and refusal discipline of NormativeAlgorithmSet
(C-036). Results are returned to the caller and never stored.
"""

from __future__ import annotations

import dataclasses
import uuid

from plan_manager.scoring.embedding import EmbeddingUnavailable
from plan_manager.scoring.estimators import (
    coverage_estimator,
    declared_concepts,
    embedding_estimator,
    load_concept_rows,
    reference_estimator,
    required_concepts,
)
from plan_manager.scoring.simulation import simulation_vote
from plan_manager.scoring.trust import compute_trust
from plan_manager.verify.gate import run_gate
from plan_manager.verify.verdict import current_head_revision
from plan_manager.views.branch import resolve_branch
from plan_manager.views.dependency_graph import load_steps


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
    """

    branch_path: str
    index: float
    color: str
    estimator_vector: dict[str, float]
    trust: float
    revision_uuid: uuid.UUID | None
    below_threshold: bool


def score_branch(
    conn,
    plan_uuid,
    gs_step_id: str,
    ts_step_id: str,
    as_step_id: str,
    config: ScoringConfig,
    model_output: str | None = None,
) -> BranchScore:
    """Compute the 0..100 SemanticIndex (C-013) score of one branch."""
    branch = resolve_branch(conn, plan_uuid, gs_step_id, ts_step_id, as_step_id)
    branch_path = f"{gs_step_id}/{ts_step_id}/{as_step_id}"

    report, _verdict = run_gate(conn, plan_uuid, branch=branch)
    if not report.green:
        raise ScoreRefusedError(
            f"{branch_path} refused: mechanical gate not green "
            f"({sum(len(c.findings) for c in report.checks)} findings)"
        )

    concept_rows = load_concept_rows(conn, plan_uuid)
    required = required_concepts(branch, concept_rows)
    declared = declared_concepts(branch)

    estimator_vector: dict[str, float] = {}
    weights: dict[str, float] = {}

    estimator_vector["coverage"] = coverage_estimator(required, declared)
    weights["coverage"] = 1.0
    estimator_vector["references"] = reference_estimator(conn, branch, concept_rows)
    weights["references"] = 1.0

    pair_values: dict[str, float] = {}

    if config.embedding_url is not None:
        try:
            pair_values["embedding"] = embedding_estimator(
                conn,
                config.embedding_url,
                branch,
                concept_rows,
                required,
                config.concept_weight,
                config.embedding_timeout,
            )
        except EmbeddingUnavailable:
            pair_values.pop("embedding", None)

    sim_vote = simulation_vote(model_output, branch.atomic.fields.get("prompt", ""))
    if sim_vote is not None:
        pair_values["simulation"] = sim_vote

    if pair_values:
        pair_weight = 1.0 / len(pair_values)
        for name, value in pair_values.items():
            estimator_vector[name] = value
            weights[name] = pair_weight

    index = 100.0 * sum(
        weights[name] * estimator_vector[name] for name in estimator_vector
    ) / sum(weights.values())

    color = "green" if index >= config.threshold else "red"
    below_threshold = color == "red"

    if "embedding" in pair_values:
        trust_report = compute_trust(
            conn,
            config.embedding_url,
            [definition for _, definition, _source_labels in concept_rows],
            config.trust_floor,
            config.embedding_timeout,
        )
        trust = trust_report.trust
    else:
        trust = config.trust_floor

    revision_uuid = current_head_revision(conn, plan_uuid)

    return BranchScore(
        branch_path=branch_path,
        index=index,
        color=color,
        estimator_vector=estimator_vector,
        trust=trust,
        revision_uuid=revision_uuid,
        below_threshold=below_threshold,
    )


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
    """

    index: float
    color: str
    aggregation: str
    weakest: list[BranchScore]
    revision_uuid: uuid.UUID | None


def score_plan(conn, plan_uuid, config: ScoringConfig) -> PlanScore:
    """Compute the plan-level SemanticIndex (C-013) aggregation."""
    report, _verdict = run_gate(conn, plan_uuid, branch=None)
    if not report.green:
        raise ScoreRefusedError(
            f"plan {plan_uuid} refused: mechanical gate not green "
            f"({sum(len(c.findings) for c in report.checks)} findings)"
        )

    steps = load_steps(conn, plan_uuid)

    gs_steps = [s for s in steps.values() if s.level == 3]
    triples: list[tuple] = []
    for gs in gs_steps:
        ts_steps = [
            s for s in steps.values() if s.level == 4 and s.parent_step_uuid == gs.uuid
        ]
        for ts in ts_steps:
            as_steps = [
                s
                for s in steps.values()
                if s.level == 5 and s.parent_step_uuid == ts.uuid
            ]
            for as_step in as_steps:
                triples.append((gs, ts, as_step))

    triples.sort(key=lambda t: (t[0].step_id, t[1].step_id, t[2].step_id))

    branch_scores = [
        score_branch(
            conn, plan_uuid, gs.step_id, ts.step_id, as_step.step_id, config, None
        )
        for gs, ts, as_step in triples
    ]

    if not branch_scores:
        index = 100.0
    elif config.aggregation == "minimum":
        index = min(score.index for score in branch_scores)
    else:
        above = sum(1 for score in branch_scores if score.index >= config.threshold)
        index = 100.0 * above / len(branch_scores)

    color = "green" if index >= config.threshold else "red"
    weakest = sorted(branch_scores, key=lambda score: score.index)[:3]
    revision_uuid = current_head_revision(conn, plan_uuid)

    return PlanScore(
        index=index,
        color=color,
        aggregation=config.aggregation,
        weakest=weakest,
        revision_uuid=revision_uuid,
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
    return summary
