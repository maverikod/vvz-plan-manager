"""Behavioral tests for the step_prompt_verify comparison support module (C-006, C-007): match, mismatch-with-diff, and the field/block selector. No accompanying test coverage was authored by the sibling branch that implements this module, so this test binds directly to it."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass

import pytest

from plan_manager.storage.canonical import content_hash
from plan_manager.views.step_fingerprint import step_field_hash
from plan_manager.views.step_prompt_verify import (
    compare_verdict,
    extract_fenced_block,
    resolve_candidate_bytes,
    resolve_target_content,
)


@dataclass
class _FakeStep:
    step_id: str
    level: int
    depends_on: list
    concepts: list
    project_id: object
    status: str
    fields: dict


def _make_step(fields: dict) -> _FakeStep:
    return _FakeStep(
        step_id="G-003/T-001/A-001",
        level=5,
        depends_on=[],
        concepts=["C-006"],
        project_id=None,
        status="draft",
        fields=fields,
    )


def test_resolve_candidate_bytes_from_base64_decodes_and_hashes() -> None:
    raw = b"hello world"
    encoded = base64.b64encode(raw).decode("ascii")
    candidate_bytes, digest = resolve_candidate_bytes(encoded, None)
    assert candidate_bytes == raw
    assert digest == hashlib.sha256(raw).hexdigest()


def test_resolve_candidate_bytes_from_sha256_passes_through() -> None:
    digest_in = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    candidate_bytes, digest_out = resolve_candidate_bytes(None, digest_in)
    assert candidate_bytes is None
    assert digest_out == digest_in


def test_resolve_candidate_bytes_requires_exactly_one_of_base64_or_sha256() -> None:
    with pytest.raises(ValueError):
        resolve_candidate_bytes(None, None)
    with pytest.raises(ValueError):
        resolve_candidate_bytes(
            base64.b64encode(b"x").decode("ascii"),
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )


_TWO_BLOCK_TEXT = "intro\n```python\nfirst block\n```\nmiddle\n```sql\nSELECT 1\n```\ntail"


def test_extract_fenced_block_returns_the_requested_block() -> None:
    assert extract_fenced_block(_TWO_BLOCK_TEXT, 0) == "first block\n"
    assert extract_fenced_block(_TWO_BLOCK_TEXT, 1) == "SELECT 1\n"


def test_extract_fenced_block_out_of_range_raises_value_error() -> None:
    with pytest.raises(ValueError):
        extract_fenced_block(_TWO_BLOCK_TEXT, 2)


def test_resolve_target_content_field_selector_matches_step_field_hash() -> None:
    step = _make_step({"description": "the field text"})
    content, digest = resolve_target_content(step, "description", None)
    assert content == "the field text"
    assert digest == step_field_hash(step, "description")


def test_resolve_target_content_field_and_block_selector_matches_content_hash() -> None:
    step = _make_step({"prompt": _TWO_BLOCK_TEXT})
    content, digest = resolve_target_content(step, "prompt", 1)
    assert content == "SELECT 1\n"
    assert digest == content_hash("SELECT 1\n")


def test_resolve_target_content_block_index_without_field_raises_value_error() -> None:
    step = _make_step({"prompt": _TWO_BLOCK_TEXT})
    with pytest.raises(ValueError):
        resolve_target_content(step, None, 0)


def test_resolve_target_content_unknown_field_raises_key_error() -> None:
    step = _make_step({"prompt": _TWO_BLOCK_TEXT})
    with pytest.raises(KeyError):
        resolve_target_content(step, "does_not_exist", None)


def test_compare_verdict_exact_match() -> None:
    target = "line one\nline two\n"
    target_bytes = target.encode("utf-8")
    digest = hashlib.sha256(target_bytes).hexdigest()
    verdict = compare_verdict(target, target_bytes, digest, "canonical-hash-value")
    assert verdict["match"] is True
    assert verdict["canonical_content_hash"] == "canonical-hash-value"
    assert "unified_diff" not in verdict
    assert "first_divergence_offset" not in verdict


def test_compare_verdict_mismatch_reports_diff_and_first_divergence_offset() -> None:
    target = "line one\nline two\n"
    candidate = "line one\nline TWO\n"
    candidate_bytes = candidate.encode("utf-8")
    wrong_digest = hashlib.sha256(candidate_bytes).hexdigest()
    verdict = compare_verdict(target, candidate_bytes, wrong_digest, "canonical-hash-value")
    assert verdict["match"] is False
    assert verdict["canonical_content_hash"] == "canonical-hash-value"
    assert "line one" in verdict["unified_diff"]
    assert "-line two" in verdict["unified_diff"]
    assert "+line TWO" in verdict["unified_diff"]
    assert verdict["first_divergence_offset"] == 14


def test_compare_verdict_mismatch_without_candidate_bytes_omits_diff_fields() -> None:
    target = "line one\n"
    verdict = compare_verdict(target, None, "0" * 64, "canonical-hash-value")
    assert verdict["match"] is False
    assert "unified_diff" not in verdict
    assert "first_divergence_offset" not in verdict
