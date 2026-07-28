"""Regression tests for bug 13cae630: plan_score must be quality-discriminating.

The published index was 100 * mean(coverage, references, embedding-cosine).
On real plans coverage and references saturate at 1.0 and the raw
concept-basis cosine tops out around 0.39, so the index collapsed to
66.67 + 33.33 * cosine, capping at ~79.8 — the green band (threshold 85)
was arithmetically unreachable, and controlled pairs showed skeleton steps
outscoring complete, correctly-verified siblings.

The fix has two parts:
1. calibrate_cosine: an affine, monotone map of the realistic cosine range
   onto [0, 1] (config band embedding_cal_floor..embedding_cal_ceiling).
2. completeness_estimator: a deterministic operational-completeness signal
   (automated verification type, targeted verification, declared objects)
   joining coverage/references in the deterministic estimator family.
"""

from __future__ import annotations

import uuid

import pytest

import plan_manager.scoring.index as index_mod
from plan_manager.scoring.estimators import calibrate_cosine, completeness_estimator
from plan_manager.scoring.index import _score_one
from plan_manager.scoring.types import ScoringConfig


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000013cae")


class _Atomic:
    def __init__(self, fields: dict) -> None:
        self.fields = fields


class _Branch:
    def __init__(self, fields: dict) -> None:
        self.atomic = _Atomic(fields)


SKELETON_FIELDS = {
    "prompt": "p",
    "verification": {"type": "manual", "target": "", "expected": ""},
}

COMPLETE_FIELDS = {
    "prompt": "p",
    "verification": {
        "type": "static_analysis",
        "target": "lmrs/release.py",
        "expected": "pipeline builds and signs the artifact",
    },
    "objects": [{"name": "run_release", "kind": "function"}],
}


# ---------------------------------------------------------------- calibration


def test_calibrate_cosine_maps_band_onto_unit_interval() -> None:
    assert calibrate_cosine(0.05, 0.05, 0.45) == 0.0
    assert calibrate_cosine(0.0, 0.05, 0.45) == 0.0
    assert calibrate_cosine(0.45, 0.05, 0.45) == 1.0
    assert calibrate_cosine(0.9, 0.05, 0.45) == 1.0
    assert calibrate_cosine(0.25, 0.05, 0.45) == pytest.approx(0.5)


def test_calibrate_cosine_is_monotone() -> None:
    values = [calibrate_cosine(v / 100, 0.05, 0.45) for v in range(0, 100)]
    assert values == sorted(values)


def test_config_rejects_inverted_calibration_band() -> None:
    with pytest.raises(ValueError):
        ScoringConfig(embedding_cal_floor=0.5, embedding_cal_ceiling=0.4)


# -------------------------------------------------------------- completeness


def test_completeness_zero_for_skeleton_defaults() -> None:
    assert completeness_estimator(_Branch(SKELETON_FIELDS)) == 0.0


def test_completeness_full_for_specified_verified_step() -> None:
    assert completeness_estimator(_Branch(COMPLETE_FIELDS)) == 1.0


def test_completeness_partial_signals() -> None:
    only_type = {
        "prompt": "p",
        "verification": {"type": "tests", "target": "", "expected": ""},
    }
    assert completeness_estimator(_Branch(only_type)) == pytest.approx(1 / 3)
    no_objects = {
        "prompt": "p",
        "verification": {"type": "tests", "target": "t", "expected": "e"},
    }
    assert completeness_estimator(_Branch(no_objects)) == pytest.approx(2 / 3)


# ------------------------------------------------------- index integration


def _score(monkeypatch, fields: dict, raw_cosine: float):
    """Run _score_one with saturated deterministic estimators and a fixed
    raw embedding cosine, keeping calibrate_cosine and
    completeness_estimator REAL."""
    monkeypatch.setattr(index_mod, "required_concepts", lambda b, rows: {"C-001"})
    monkeypatch.setattr(index_mod, "declared_concepts", lambda b: {"C-001"})
    monkeypatch.setattr(index_mod, "coverage_diagnostics", lambda b, rows, req, dec: {})
    monkeypatch.setattr(index_mod, "coverage_estimator", lambda req, dec: 1.0)
    monkeypatch.setattr(index_mod, "reference_estimator", lambda conn, b, rows, nodes: 1.0)
    monkeypatch.setattr(index_mod, "embedding_estimator", lambda b, rows, req, w, v: raw_cosine)

    class _TrustReport:
        trust = 0.9

    monkeypatch.setattr(index_mod, "compute_trust", lambda defs, vectors, floor: _TrustReport())

    return _score_one(
        conn=None,
        plan_uuid=PLAN_UUID,
        branch=_Branch(fields),
        branch_path="G-001/T-001/A-001",
        concept_rows=[],
        plan_nodes={},
        config=ScoringConfig(),
        vectors={},
        embedding_state="ready",
        embedding_detail=None,
        revision_uuid=None,
        model_output=None,
    )


def test_green_band_reachable_for_complete_step_at_observed_best_cosine(monkeypatch) -> None:
    """The bug's best observed cosine (0.3946) capped the OLD index at
    ~79.8 — permanently red. A complete step at that cosine must now be
    green."""
    score = _score(monkeypatch, COMPLETE_FIELDS, raw_cosine=0.3946)
    assert score.index >= 85.0
    assert score.color == "green"


def test_skeleton_scores_strictly_below_complete_at_same_cosine(monkeypatch) -> None:
    """The reporter's controlled pair, reversed: at IDENTICAL embedding
    cosine the self-declared skeleton must rank strictly below the
    complete, correctly-verified step — and stay red."""
    skeleton = _score(monkeypatch, SKELETON_FIELDS, raw_cosine=0.3946)
    complete = _score(monkeypatch, COMPLETE_FIELDS, raw_cosine=0.3946)
    assert skeleton.index < complete.index
    assert skeleton.color == "red"


def test_lexical_echo_alone_cannot_outscore_operational_completeness(monkeypatch) -> None:
    """A skeleton with a PERFECT cosine (pure lexical echo) must not
    outscore a complete step with the bug's merely-good observed cosine."""
    echo_skeleton = _score(monkeypatch, SKELETON_FIELDS, raw_cosine=0.99)
    complete = _score(monkeypatch, COMPLETE_FIELDS, raw_cosine=0.3946)
    assert echo_skeleton.index < complete.index
