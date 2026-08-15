"""EIG block G (todo e902db52): plan_prompt_chain's refusal semantics and the view split.

Three layers:

1. THE REFUSAL MATRIX. A red STRUCTURAL contour always refuses with GATE_RED
   and is never overridable. A red EXECUTION contour with a green structural
   one refuses with the NEW domain code EXECUTION_RED, unless the caller
   passes diagnostic_override=true -- in which case the chain is assembled and
   the payload says so out loud.
2. SURFACING. Every successful payload carries the additive ``contours`` key
   with a "not_evaluated" semantic contour; the override keys appear ONLY when
   the override actually admitted a red execution contour.
3. THE SPLIT. views/prompt_chain.py was over the 400-line cap, so scope
   normalization/selection moved to views/prompt_chain_scope.py. The names are
   re-exported as the SAME objects and the assembled artifact's canonical
   bytes are pinned, so the split is provably behaviour-neutral.

The fake connection is the one from
tests/test_bug_4f7fbd43_prompt_chain_scoped_gate.py (a complete read-only
plan_prompt_chain pass), imported rather than copied.
"""

from __future__ import annotations

import asyncio
import hashlib

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands import plan_prompt_chain_command
from plan_manager.commands.errors import DOMAIN_CODES
from plan_manager.commands.plan_prompt_chain_command import PlanPromptChainCommand
from plan_manager.storage.canonical import canonical_json
from plan_manager.verify.finding import Finding, build_report
from plan_manager.verify.verdict import Verdict
from plan_manager.views import prompt_chain, prompt_chain_scope

from tests.test_bug_4f7fbd43_prompt_chain_scoped_gate import (
    PLAN_UUID,
    _FakeConn,
    _patch,
)

STRUCTURAL_CHECK = "parse.required_fields"
EXECUTION_CHECK = "execution_integrity.object_producer_before_consumer"
ALL_CHECKS = [STRUCTURAL_CHECK, EXECUTION_CHECK]


def _report(*red_checks: str):
    findings = [
        Finding(
            check_id=check_id,
            severity="error",
            artifact_path="G-001/T-001/A-001",
            message=f"{check_id} violated",
        )
        for check_id in red_checks
    ]
    return build_report(ALL_CHECKS, findings)


def _patch_gate(monkeypatch, *red_checks: str) -> None:
    report = _report(*red_checks)
    verdict = Verdict(
        kind="gate",
        scope="plan",
        revision_uuid=None,
        green=report.green,
        payload={},
    )
    monkeypatch.setattr(
        plan_prompt_chain_command, "run_gate", lambda *a, **k: (report, verdict)
    )


def _execute(monkeypatch, *red_checks: str, override: bool = False):
    _patch(monkeypatch)
    _patch_gate(monkeypatch, *red_checks)
    return asyncio.run(
        PlanPromptChainCommand().execute(
            plan=str(PLAN_UUID), diagnostic_override=override
        )
    )


def _error(result) -> dict:
    assert isinstance(result, ErrorResult), result
    return result.to_dict()["error"]


def _data(result) -> dict:
    assert isinstance(result, SuccessResult), result
    return result.to_dict()["data"]


# ---------------------------------------------------------------------------
# Layer 1: the refusal matrix.
# ---------------------------------------------------------------------------


def test_execution_red_is_a_registered_domain_code() -> None:
    assert "EXECUTION_RED" in DOMAIN_CODES


def test_both_contours_green_assembles_normally(monkeypatch) -> None:
    data = _data(_execute(monkeypatch))

    assert data["scope"] == "whole_plan"
    assert data["contours"]["structural"]["green"] is True
    assert data["contours"]["execution"]["green"] is True
    assert "diagnostic_override" not in data
    assert "execution_findings" not in data


def test_structural_red_refuses_with_gate_red(monkeypatch) -> None:
    error = _error(_execute(monkeypatch, STRUCTURAL_CHECK))

    assert error["data"]["domain_code"] == "GATE_RED"
    assert error["data"]["scope"] == "whole_plan"
    assert error["data"]["findings_count"] == 1
    assert error["data"]["contours"]["structural"]["green"] is False


def test_structural_red_is_never_overridable(monkeypatch) -> None:
    error = _error(_execute(monkeypatch, STRUCTURAL_CHECK, override=True))

    assert error["data"]["domain_code"] == "GATE_RED"


def test_structural_red_wins_when_both_contours_are_red(monkeypatch) -> None:
    error = _error(_execute(monkeypatch, STRUCTURAL_CHECK, EXECUTION_CHECK, override=True))

    assert error["data"]["domain_code"] == "GATE_RED"
    # GATE_RED counts the WHOLE report, not one contour.
    assert error["data"]["findings_count"] == 2
    assert error["data"]["contours"]["execution"]["green"] is False


def test_execution_red_alone_refuses_with_the_distinct_code(monkeypatch) -> None:
    error = _error(_execute(monkeypatch, EXECUTION_CHECK))

    assert error["data"]["domain_code"] == "EXECUTION_RED"
    assert error["data"]["scope"] == "whole_plan"
    # findings_count is the EXECUTION contour's count, not the report's.
    assert error["data"]["findings_count"] == 1
    assert error["data"]["contours"]["structural"]["green"] is True
    assert error["data"]["contours"]["execution"]["green"] is False
    assert error["data"]["top_findings"][0]["code"] == EXECUTION_CHECK


def test_execution_red_refusal_omits_the_semantic_contour(monkeypatch) -> None:
    """A refused call never consulted scoring; inventing a state would lie."""
    error = _error(_execute(monkeypatch, EXECUTION_CHECK))

    assert set(error["data"]["contours"]) == {"structural", "execution"}


def test_gate_red_message_is_unchanged_from_before_block_g(monkeypatch) -> None:
    error = _error(_execute(monkeypatch, STRUCTURAL_CHECK))

    assert error["message"] == (
        "scope whole_plan refused: mechanical gate not green (1 findings)"
    )


def test_execution_red_message_names_the_execution_contour(monkeypatch) -> None:
    error = _error(_execute(monkeypatch, EXECUTION_CHECK))

    assert "execution-integrity contour not green" in error["message"]
    assert "structurally valid" in error["message"]


# ---------------------------------------------------------------------------
# Layer 2: the override proceeds, loudly.
# ---------------------------------------------------------------------------


def test_override_admits_a_red_execution_contour(monkeypatch) -> None:
    data = _data(_execute(monkeypatch, EXECUTION_CHECK, override=True))

    assert data["diagnostic_override"] is True
    assert data["execution_findings"]["findings_count"] == 1
    assert data["execution_findings"]["top_findings"][0]["code"] == EXECUTION_CHECK
    assert data["contours"]["execution"] == {"green": False, "findings_count": 1}
    # The artifact itself is a real one, not a stub.
    assert data["assembly"]


def test_override_on_a_green_plan_adds_no_diagnostic_keys(monkeypatch) -> None:
    data = _data(_execute(monkeypatch, override=True))

    assert "diagnostic_override" not in data
    assert "execution_findings" not in data


def test_successful_payload_semantic_contour_is_not_evaluated(monkeypatch) -> None:
    data = _data(_execute(monkeypatch))

    assert data["contours"]["semantic"]["state"] == "not_evaluated"
    assert "plan_score" in data["contours"]["semantic"]["reason"]


def test_contours_are_additive_to_the_pre_block_g_payload(monkeypatch) -> None:
    data = _data(_execute(monkeypatch))

    for key in (
        "plan", "revision", "scope", "role", "waves", "assembly",
        "used_block_keys", "total", "limit", "offset", "meta",
    ):
        assert key in data, key


def test_diagnostic_override_is_declared_in_schema_and_metadata() -> None:
    schema = PlanPromptChainCommand.get_schema()
    metadata = PlanPromptChainCommand.metadata()

    assert schema["properties"]["diagnostic_override"]["type"] == "boolean"
    assert schema["properties"]["diagnostic_override"]["default"] is False
    assert metadata["parameters"]["diagnostic_override"]["required"] is False
    assert "EXECUTION_RED" in metadata["error_cases"]
    assert "diagnostic_override" in metadata["error_cases"]["EXECUTION_RED"]["solution"]


def test_diagnostic_override_defaults_to_false_when_omitted() -> None:
    normalized = PlanPromptChainCommand().validate_params({"plan": "x"})

    assert normalized["diagnostic_override"] is False


# ---------------------------------------------------------------------------
# Layer 3: the views/prompt_chain split is behaviour-neutral.
# ---------------------------------------------------------------------------

_SPLIT_NAMES = [
    "DEFAULT_INCLUDE_STATUSES",
    "ROLES",
    "PromptScope",
    "normalize_scope",
    "normalize_role",
    "normalize_statuses",
    "scope_atomic_steps",
    "eligible_atomic_steps",
    "hrs_slice_for",
    "branch_for_atomic",
]


def test_every_split_name_is_re_exported_as_the_same_object() -> None:
    for name in _SPLIT_NAMES:
        assert hasattr(prompt_chain, name), name
        assert getattr(prompt_chain, name) is getattr(prompt_chain_scope, name), name


def test_both_halves_of_the_split_are_under_the_line_cap() -> None:
    import pathlib

    for module in (prompt_chain, prompt_chain_scope):
        path = pathlib.Path(module.__file__)
        assert sum(1 for _ in path.open()) <= 400, path


def _assemble() -> dict:
    conn = _FakeConn()
    return prompt_chain.assemble_prompt_chain(
        conn,
        PLAN_UUID,
        "plan-4f7fbd43",
        None,
        prompt_chain.normalize_scope("whole_plan"),
        list(prompt_chain.DEFAULT_INCLUDE_STATUSES),
        "coder",
    )


def test_assembly_is_byte_identical_across_runs() -> None:
    assert canonical_json(_assemble()) == canonical_json(_assemble())


PINNED_ASSEMBLY_DIGEST = (
    "32c73c6eed96be063d54cd156c88fabbc652b1047b67e95641fa0d1771a83d59"
)


def test_assembled_artifact_matches_its_pinned_canonical_bytes() -> None:
    """Byte-identity pin for the split (and for any later refactor of it).

    The digest was taken from the assembled artifact of the fixture plan
    immediately after the mechanical move, with the full pre-existing
    prompt-chain suite (tests/test_prompt_chain_view.py,
    tests/test_bug_4f7fbd43_prompt_chain_scoped_gate.py) green and unchanged
    -- so it pins the post-split output to the behaviour those tests already
    proved was the pre-split behaviour.
    """
    digest = hashlib.sha256(canonical_json(_assemble())).hexdigest()

    assert digest == PINNED_ASSEMBLY_DIGEST


def test_split_module_carries_no_assembly_logic() -> None:
    """The seam is scope-selection vs corpus-assembly; it must not blur."""
    assert not hasattr(prompt_chain_scope, "assemble_prompt_chain")
    assert not hasattr(prompt_chain_scope, "cache_key")
    assert hasattr(prompt_chain, "assemble_prompt_chain")
