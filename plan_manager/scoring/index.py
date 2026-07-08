"""SemanticIndex (C-013) scoring: branch and plan-level ensemble measurement.

Implements the normative fold and refusal discipline of NormativeAlgorithmSet
(C-036). Results are returned to the caller and never stored.
"""

from __future__ import annotations

from plan_manager.scoring.embedding import (
    EmbeddingUnavailable,
    READINESS_READY,
    READINESS_UNCONFIGURED,
    READINESS_UNREACHABLE,
)
from plan_manager.scoring.embedding_batch import embed_texts, embedding_health
from plan_manager.scoring.estimators import (
    branch_text,
    coverage_diagnostics,
    coverage_estimator,
    declared_concepts,
    embedding_estimator,
    load_concept_rows,
    reference_estimator,
    required_concepts,
)
from plan_manager.scoring.simulation import simulation_vote
from plan_manager.scoring.trust import compute_trust
from plan_manager.scoring.types import (
    BranchScore,
    PlanScore,
    ScoreRefusedError,
    ScoringConfig,
)
from plan_manager.verify.gate import run_gate
from plan_manager.verify.verdict import current_head_revision
from plan_manager.views.branch import resolve_branch
from plan_manager.views.dependency_graph import load_steps


def _branch_required_texts(branch, concept_rows) -> list[str]:
    """Every text one branch needs vectorized: its text plus concept definitions."""
    return [branch_text(branch)] + [
        definition for _concept_id, definition, _source_labels in concept_rows
    ]


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


def _resolve_vectors(
    conn,
    config: ScoringConfig,
    texts: list[str],
    progress=None,
    require_embeddings: bool = False,
) -> tuple[dict[str, list[float]], str, str | None]:
    """Preflight the embedding model once and batch-vectorize ``texts``.

    Returns the text->vector map, the embedding readiness state, and a precise
    diagnostic string (``None`` when the model was ready and vectorization
    succeeded). The preflight uses the same ``embedding_health`` probe the
    platform ``health`` command uses, so both paths share one client and one
    readiness verdict, and it distinguishes a transport-reachable service from
    an initialized model:

    * unconfigured embedding URL -> ({}, "unconfigured", detail), always degrade;
    * model not ready / unreachable -> raise EmbeddingUnavailable when
      ``require_embeddings`` is set, otherwise ({}, state, detail) to degrade fast;
    * model ready but the batch vectorization fails -> ({}, "unreachable",
      detail) carrying the real embed exception, so health-ready-yet-scoring-
      unreachable is never reported without an explanation;
    * model ready -> one queued batch resolves every cache miss at once.
    """
    if config.embedding_url is None:
        return {}, READINESS_UNCONFIGURED, "embedding service is not configured"

    if progress is not None:
        progress(message="Проверка готовности embedding-модели")
    health = embedding_health(config.embedding_url, config.embedding_timeout)
    state = health["state"]
    if state != READINESS_READY:
        detail = _readiness_detail(health)
        if require_embeddings:
            raise EmbeddingUnavailable(detail)
        return {}, state, detail

    try:
        vectors = embed_texts(
            conn,
            config.embedding_url,
            texts,
            timeout=config.embedding_timeout,
            progress=progress,
        )
    except EmbeddingUnavailable as exc:
        if require_embeddings:
            raise
        # The health endpoint reported the model ready, yet the actual batch
        # vectorization failed (a distinct transport: the embed job round-trip,
        # not the health probe). Surface the real reason instead of collapsing
        # to an unexplained "unreachable".
        return {}, READINESS_UNREACHABLE, (
            "embedding health reported ready but batch vectorization failed: "
            f"{exc}"
        )
    return vectors, READINESS_READY, None


def _score_one(
    conn,
    plan_uuid,
    branch,
    branch_path: str,
    concept_rows,
    config: ScoringConfig,
    vectors: dict[str, list[float]],
    embedding_state: str,
    embedding_detail: str | None,
    revision_uuid,
    model_output: str | None = None,
) -> BranchScore:
    """Pure SemanticIndex fold for one already-resolved branch (no network)."""
    required = required_concepts(branch, concept_rows)
    declared = declared_concepts(branch)
    coverage = coverage_diagnostics(branch, concept_rows, required, declared)

    estimator_vector: dict[str, float] = {}
    weights: dict[str, float] = {}

    estimator_vector["coverage"] = coverage_estimator(required, declared)
    weights["coverage"] = 1.0
    estimator_vector["references"] = reference_estimator(conn, branch, concept_rows)
    weights["references"] = 1.0

    pair_values: dict[str, float] = {}

    embedding_available = embedding_state == READINESS_READY
    if embedding_available:
        pair_values["embedding"] = embedding_estimator(
            branch, concept_rows, required, config.concept_weight, vectors
        )

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
            [definition for _, definition, _source_labels in concept_rows],
            vectors,
            config.trust_floor,
        )
        trust = trust_report.trust
    else:
        trust = config.trust_floor

    return BranchScore(
        branch_path=branch_path,
        index=index,
        color=color,
        estimator_vector=estimator_vector,
        trust=trust,
        revision_uuid=revision_uuid,
        below_threshold=below_threshold,
        embedding_state=embedding_state,
        embedding_detail=embedding_detail,
        coverage=coverage,
    )


def score_branch(
    conn,
    plan_uuid,
    gs_step_id: str,
    ts_step_id: str,
    as_step_id: str,
    config: ScoringConfig,
    model_output: str | None = None,
    progress=None,
    require_embeddings: bool = False,
) -> BranchScore:
    """Compute the 0..100 SemanticIndex (C-013) score of one branch."""
    branch = resolve_branch(conn, plan_uuid, gs_step_id, ts_step_id, as_step_id)
    branch_path = f"{gs_step_id}/{ts_step_id}/{as_step_id}"

    if progress is not None:
        progress(pct=0, message=f"Scoring branch {branch_path}")

    report, _verdict = run_gate(conn, plan_uuid, branch=branch)
    if not report.green:
        raise ScoreRefusedError(
            f"{branch_path} refused: mechanical gate not green "
            f"({sum(len(c.findings) for c in report.checks)} findings)"
        )
    if progress is not None:
        progress(pct=10, message="Mechanical gate green")

    concept_rows = load_concept_rows(conn, plan_uuid)
    texts = _branch_required_texts(branch, concept_rows)
    vectors, embedding_state, embedding_detail = _resolve_vectors(
        conn, config, texts, progress, require_embeddings
    )
    if progress is not None:
        progress(pct=70, message="Estimators")

    revision_uuid = current_head_revision(conn, plan_uuid)
    score = _score_one(
        conn,
        plan_uuid,
        branch,
        branch_path,
        concept_rows,
        config,
        vectors,
        embedding_state,
        embedding_detail,
        revision_uuid,
        model_output,
    )
    if progress is not None:
        progress(pct=100, message="Done")
    return score


def score_plan(
    conn,
    plan_uuid,
    config: ScoringConfig,
    progress=None,
    require_embeddings: bool = False,
) -> PlanScore:
    """Compute the plan-level SemanticIndex (C-013) aggregation.

    Vectorizes the whole plan once: a single embedding readiness preflight
    and a single queued batch resolve every branch text and concept
    definition, then each branch is folded from the in-memory vector map
    with no further network calls. Progress is reported through ``progress``
    (pct/message) so the queued job shows what it is doing instead of
    sitting at 0.
    """
    if progress is not None:
        progress(pct=0, message="Semantic scoring started")

    report, _verdict = run_gate(conn, plan_uuid, branch=None)
    if not report.green:
        raise ScoreRefusedError(
            f"plan {plan_uuid} refused: mechanical gate not green "
            f"({sum(len(c.findings) for c in report.checks)} findings)"
        )
    if progress is not None:
        progress(pct=5, message="Mechanical gate green")

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

    branches = [
        resolve_branch(conn, plan_uuid, gs.step_id, ts.step_id, as_step.step_id)
        for gs, ts, as_step in triples
    ]
    total = len(branches)
    if progress is not None:
        progress(pct=10, message=f"{total} branches enumerated")

    concept_rows = load_concept_rows(conn, plan_uuid)
    texts = [branch_text(b) for b in branches] + [
        definition for _concept_id, definition, _source_labels in concept_rows
    ]
    vectors, embedding_state, embedding_detail = _resolve_vectors(
        conn, config, texts, progress, require_embeddings
    )

    revision_uuid = current_head_revision(conn, plan_uuid)

    branch_scores: list[BranchScore] = []
    for i, ((gs, ts, as_step), branch) in enumerate(zip(triples, branches)):
        branch_path = f"{gs.step_id}/{ts.step_id}/{as_step.step_id}"
        branch_scores.append(
            _score_one(
                conn,
                plan_uuid,
                branch,
                branch_path,
                concept_rows,
                config,
                vectors,
                embedding_state,
                embedding_detail,
                revision_uuid,
                None,
            )
        )
        if progress is not None and total:
            progress(
                pct=10 + int(80 * (i + 1) / total),
                message=f"Scored branch {i + 1}/{total}",
            )

    if not branch_scores:
        index = 100.0
    elif config.aggregation == "minimum":
        index = min(score.index for score in branch_scores)
    else:
        above = sum(1 for score in branch_scores if score.index >= config.threshold)
        index = 100.0 * above / len(branch_scores)

    color = "green" if index >= config.threshold else "red"
    weakest = sorted(branch_scores, key=lambda score: score.index)[:3]
    if progress is not None:
        progress(pct=95, message="Aggregation complete")

    return PlanScore(
        index=index,
        color=color,
        aggregation=config.aggregation,
        weakest=weakest,
        revision_uuid=revision_uuid,
        embedding_state=embedding_state,
        embedding_detail=embedding_detail,
    )


def embedding_block(embedding_state: str, embedding_detail: str | None) -> dict:
    """Build the ``embedding`` block reported by the scoring commands.

    Always carries ``available`` and ``state``; adds ``detail`` with the
    precise reason whenever the embedding estimator did not contribute, so a
    degraded score is never reported without an explanation of why — in
    particular the real batch-vectorization failure when the health endpoint
    reported the model ready.
    """
    block: dict = {
        "available": embedding_state == READINESS_READY,
        "state": embedding_state,
    }
    if embedding_detail is not None:
        block["detail"] = embedding_detail
    return block


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
