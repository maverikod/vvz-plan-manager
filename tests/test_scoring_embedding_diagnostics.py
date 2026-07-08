"""Regression: scoring must use embeddings when health reports ready, and
otherwise emit a precise diagnostic instead of a silent "unreachable".

Bug BUG-PLANMGR-SCORING-EMBEDDING-UNREACHABLE-WHILE-HEALTH-READY-001: the
platform ``health`` command probes only the embedding *health* endpoint
(HTTP), while ``plan_score``/``branch_weak`` additionally run the actual batch
vectorization (a distinct transport: the embed job round-trip). When the health
endpoint answered ready but the batch embed failed, scoring collapsed to
``embedding.state == "unreachable"`` and discarded the real exception, so an
operator saw health-ready-yet-scoring-unreachable with no explanation.

These tests pin two guarantees:

1. When the embedding batch resolves, the embedding estimator contributes and
   trust rises above the declared floor (embeddings are actually used).
2. When health reports ready but the batch embed fails, scoring degrades but
   surfaces the real failure reason in ``embedding_detail`` rather than an
   unexplained "unreachable".
"""

from uuid import uuid4

import pytest

from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.step import Step
from plan_manager.scoring import index
from plan_manager.scoring.embedding import (
    READINESS_NOT_READY,
    READINESS_READY,
    READINESS_UNREACHABLE,
)
from plan_manager.scoring.embedding_batch import EmbeddingUnavailable
from plan_manager.scoring.estimators import branch_text
from plan_manager.scoring.index import ScoringConfig, score_plan
from plan_manager.views.branch import Branch


PLAN_UUID = uuid4()


def _ready_health(base_url, timeout):
    return {
        "state": READINESS_READY,
        "transport_available": True,
        "model_ready": True,
        "model_status": "ready",
    }


def _fake_branch() -> Branch:
    """A one-branch plan whose deterministic estimators need no database.

    The steps carry no ``depends_on``, relations, or source labels, so
    ``reference_estimator`` resolves entirely in-memory (no cursor), and one
    concept ``C-001`` is both required (via the HRS slice label ``L1``) and
    declared (on the global step).
    """
    gs = Step(
        uuid=uuid4(), plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3,
        step_id="G-001", slug="g", fields={"description": "global goal"},
        depends_on=[], concepts=["C-001"], project_id=None, status="draft",
    )
    ts = Step(
        uuid=uuid4(), plan_uuid=PLAN_UUID, parent_step_uuid=gs.uuid, level=4,
        step_id="T-001", slug="t", fields={"description": "tactical plan"},
        depends_on=[], concepts=[], project_id=None, status="draft",
    )
    atomic = Step(
        uuid=uuid4(), plan_uuid=PLAN_UUID, parent_step_uuid=ts.uuid, level=5,
        step_id="A-001", slug="a", fields={"prompt": "atomic prompt"},
        depends_on=[], concepts=[], project_id=None, status="draft",
    )
    hrs_slice = [Paragraph(label="L1", text="binding text", position=0)]
    return Branch(plan_uuid=PLAN_UUID, gs=gs, ts=ts, atomic=atomic, hrs_slice=hrs_slice)


CONCEPT_ROWS = [("C-001", "concept one definition", ["{L1}"])]


class _GreenReport:
    green = True
    checks: list = []


def _patch_plan_flow(monkeypatch, branch: Branch) -> None:
    """Stub every database-touching hop of ``score_plan`` for one branch."""
    steps = {branch.gs.uuid: branch.gs, branch.ts.uuid: branch.ts,
             branch.atomic.uuid: branch.atomic}
    monkeypatch.setattr(index, "run_gate", lambda *a, **k: (_GreenReport(), object()))
    monkeypatch.setattr(index, "load_steps", lambda conn, plan_uuid: steps)
    monkeypatch.setattr(index, "resolve_branch", lambda *a, **k: branch)
    monkeypatch.setattr(index, "load_concept_rows", lambda conn, plan_uuid: CONCEPT_ROWS)
    monkeypatch.setattr(index, "current_head_revision", lambda conn, plan_uuid: uuid4())


def _config() -> ScoringConfig:
    return ScoringConfig(
        threshold=85.0, aggregation="minimum", concept_weight=1.0,
        trust_floor=0.2, embedding_url="https://embed.example:8001",
        embedding_timeout=30.0,
    )


def test_ready_health_uses_embedding_estimator_and_lifts_trust(monkeypatch) -> None:
    branch = _fake_branch()
    _patch_plan_flow(monkeypatch, branch)

    vectors = {
        branch_text(branch): [1.0, 0.5],
        "concept one definition": [0.9, 0.4],
    }
    monkeypatch.setattr(index, "embedding_health", _ready_health)
    monkeypatch.setattr(index, "embed_texts", lambda *a, **k: vectors)

    score = score_plan(None, PLAN_UUID, _config())

    assert score.embedding_state == READINESS_READY
    assert score.embedding_detail is None
    weakest = score.weakest[0]
    # The embedding estimator actually contributed to the ensemble...
    assert "embedding" in weakest.estimator_vector
    # ...and trust is computed from the basis geometry, above the fallback floor.
    assert weakest.trust > _config().trust_floor


def test_health_ready_but_batch_embed_fails_surfaces_reason(monkeypatch) -> None:
    branch = _fake_branch()
    _patch_plan_flow(monkeypatch, branch)

    monkeypatch.setattr(index, "embedding_health", _ready_health)

    def _boom(*a, **k):
        raise EmbeddingUnavailable("websocket /ws connection refused")

    monkeypatch.setattr(index, "embed_texts", _boom)

    score = score_plan(None, PLAN_UUID, _config())

    # Degraded, but not silently: the state is unreachable AND the real reason
    # is carried, including the fact that health had reported ready.
    assert score.embedding_state == READINESS_UNREACHABLE
    assert score.embedding_detail is not None
    assert "websocket /ws connection refused" in score.embedding_detail
    assert "ready" in score.embedding_detail
    # Deterministic estimators still degrade to the trust floor.
    assert score.weakest[0].trust == pytest.approx(_config().trust_floor)
    assert "embedding" not in score.weakest[0].estimator_vector


def test_resolve_vectors_reports_not_ready_model_status(monkeypatch) -> None:
    def _not_ready(base_url, timeout):
        return {
            "state": READINESS_NOT_READY,
            "transport_available": True,
            "model_ready": False,
            "model_status": "not_initialized",
        }

    monkeypatch.setattr(index, "embedding_health", _not_ready)

    vectors, state, detail = index._resolve_vectors(None, _config(), ["x"])

    assert vectors == {}
    assert state == READINESS_NOT_READY
    assert detail is not None
    assert "not_initialized" in detail


def test_require_embeddings_raises_with_diagnostic(monkeypatch) -> None:
    monkeypatch.setattr(index, "embedding_health", _ready_health)

    def _boom(*a, **k):
        raise EmbeddingUnavailable("job timed out")

    monkeypatch.setattr(index, "embed_texts", _boom)

    with pytest.raises(EmbeddingUnavailable, match="job timed out"):
        index._resolve_vectors(None, _config(), ["x"], require_embeddings=True)
