"""EIG block G (todo e902db52): the three-contour gate model.

Layer 1 here is the pure partition itself
(``plan_manager.verify.gate_contours``): a gate ``Report`` splits into a
STRUCTURAL and an EXECUTION contour by check_id prefix, with no second gate
run and no database. Layer 2 is the surfacing: plan_validate, plan_status,
cascade_preview, plan_score and branch_weak all carry the same additive
``contours`` block, each composing its own SEMANTIC contour. Layer 3 is the
authoritative documentation passage in the info command's capabilities
section.

Probe wiring lives in tests/test_eig_block_g_probe_wiring.py and the
plan_prompt_chain refusal matrix in tests/test_eig_block_g_prompt_chain.py
(one concern per file, under the 400-line guideline).
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import contextmanager
from typing import Any

import pytest
from mcp_proxy_adapter.commands.result import SuccessResult

from plan_manager.commands import plan_status_command, plan_validate_command
from plan_manager.commands.info_command import InfoCommand
from plan_manager.commands.plan_status_command import PlanStatusCommand
from plan_manager.commands.plan_validate_command import PlanValidateCommand
from plan_manager.scoring.blocks import contours_block
from plan_manager.verify.finding import Finding, build_report
from plan_manager.verify.gate import CHECK_IDS
from plan_manager.verify.gate_contours import (
    EXECUTION_CONTOUR_PREFIX,
    contours_payload,
    empty_partition,
    merge_partitions,
    partition_contours,
    semantic_contour,
    structural_partition,
)
from plan_manager.verify.verdict import Verdict

STRUCTURAL_CHECK = "parse.required_fields"
EXECUTION_CHECK = "execution_integrity.object_producer_before_consumer"
EXECUTION_CHECK_2 = "execution_integrity.execution_graph_acyclic"


def _finding(check_id: str, path: str = "G-001/T-001/A-001") -> Finding:
    return Finding(
        check_id=check_id, severity="error", artifact_path=path, message="boom"
    )


def _report(*check_ids_with_findings: str, all_ids: list[str] | None = None):
    ids = all_ids or [STRUCTURAL_CHECK, EXECUTION_CHECK, EXECUTION_CHECK_2]
    return build_report(ids, [_finding(cid) for cid in check_ids_with_findings])


# ---------------------------------------------------------------------------
# Layer 1: the pure partition.
# ---------------------------------------------------------------------------


def test_green_report_yields_two_green_contours() -> None:
    assert partition_contours(_report()) == empty_partition()


def test_structural_finding_reds_only_the_structural_contour() -> None:
    contours = partition_contours(_report(STRUCTURAL_CHECK))

    assert contours["structural"] == {"green": False, "findings_count": 1}
    assert contours["execution"] == {"green": True, "findings_count": 0}


def test_execution_finding_reds_only_the_execution_contour() -> None:
    contours = partition_contours(_report(EXECUTION_CHECK))

    assert contours["structural"] == {"green": True, "findings_count": 0}
    assert contours["execution"] == {"green": False, "findings_count": 1}


def test_findings_are_counted_per_contour_not_per_check() -> None:
    report = build_report(
        [STRUCTURAL_CHECK, EXECUTION_CHECK, EXECUTION_CHECK_2],
        [
            _finding(STRUCTURAL_CHECK, "a"),
            _finding(STRUCTURAL_CHECK, "b"),
            _finding(EXECUTION_CHECK, "c"),
            _finding(EXECUTION_CHECK_2, "d"),
            _finding(EXECUTION_CHECK_2, "e"),
        ],
    )

    contours = partition_contours(report)

    assert contours["structural"]["findings_count"] == 2
    assert contours["execution"]["findings_count"] == 3


@pytest.mark.parametrize("check_id", CHECK_IDS["execution_integrity"])
def test_every_registered_execution_check_id_lands_in_the_execution_contour(
    check_id: str,
) -> None:
    """The partition is prefix-driven, so a future check joins automatically."""
    assert check_id.startswith(EXECUTION_CONTOUR_PREFIX)

    contours = partition_contours(build_report([check_id], [_finding(check_id)]))

    assert contours["execution"]["findings_count"] == 1
    assert contours["structural"]["green"] is True


@pytest.mark.parametrize(
    "group", [g for g in CHECK_IDS if g != "execution_integrity"]
)
def test_every_non_execution_group_lands_in_the_structural_contour(group: str) -> None:
    for check_id in CHECK_IDS[group]:
        contours = partition_contours(build_report([check_id], [_finding(check_id)]))
        assert contours["structural"]["findings_count"] == 1, check_id
        assert contours["execution"]["green"] is True, check_id


def test_partition_never_disagrees_with_the_reports_own_green() -> None:
    for reds in ([], [STRUCTURAL_CHECK], [EXECUTION_CHECK], [STRUCTURAL_CHECK, EXECUTION_CHECK]):
        report = _report(*reds)
        contours = partition_contours(report)
        both_green = contours["structural"]["green"] and contours["execution"]["green"]
        assert both_green == report.green, reds


def test_partition_reads_the_report_and_never_runs_a_gate(monkeypatch) -> None:
    """No database, no second gate pass: the function takes only the report."""
    import plan_manager.verify.gate as gate_module

    def _boom(*_args: Any, **_kwargs: Any):
        raise AssertionError("partition_contours must never run the gate")

    monkeypatch.setattr(gate_module, "run_gate", _boom)

    assert partition_contours(_report(EXECUTION_CHECK))["execution"]["green"] is False


def test_merge_partitions_sums_counts_per_contour() -> None:
    merged = merge_partitions(
        partition_contours(_report(STRUCTURAL_CHECK)),
        partition_contours(_report(EXECUTION_CHECK, EXECUTION_CHECK_2)),
    )

    assert merged == {
        "structural": {"green": False, "findings_count": 1},
        "execution": {"green": False, "findings_count": 2},
    }


def test_merging_two_green_partitions_stays_green() -> None:
    assert merge_partitions(empty_partition(), empty_partition()) == empty_partition()


def test_structural_partition_never_touches_the_execution_contour() -> None:
    assert structural_partition(0) == empty_partition()
    assert structural_partition(2) == {
        "structural": {"green": False, "findings_count": 2},
        "execution": {"green": True, "findings_count": 0},
    }


def test_semantic_contour_rejects_an_unknown_state() -> None:
    with pytest.raises(ValueError, match="unknown semantic contour state"):
        semantic_contour("mostly_fine")


@pytest.mark.parametrize(
    "state", ["scored", "deferred", "refused", "not_evaluated"]
)
def test_semantic_contour_shape_is_uniform_across_states(state: str) -> None:
    assert set(semantic_contour(state)) == {"state", "reason"}
    assert semantic_contour(state)["reason"] is None
    assert semantic_contour(state, "why")["reason"] == "why"


def test_contours_payload_omits_semantic_when_not_supplied() -> None:
    payload = contours_payload(partition_contours(_report(EXECUTION_CHECK)))

    assert set(payload) == {"structural", "execution"}


def test_contours_payload_defaults_a_missing_partition_to_all_green() -> None:
    payload = contours_payload(None, semantic_contour("scored"))

    assert payload["structural"] == {"green": True, "findings_count": 0}
    assert payload["execution"] == {"green": True, "findings_count": 0}
    assert payload["semantic"]["state"] == "scored"


# ---------------------------------------------------------------------------
# Layer 2: surfacing (additive keys, per-surface semantic composition).
# ---------------------------------------------------------------------------


class _FakePlan:
    uuid = uuid.UUID("00000000-0000-0000-0000-0000e902db52")
    name = "block-g-plan"
    status = "draft"
    completed = False
    comment = None
    project_ids: list[str] = []
    primary_project_id = None
    head_revision_uuid = None


@contextmanager
def _fake_db():
    yield object()


def _verdict() -> Verdict:
    return Verdict(kind="gate", scope="plan", revision_uuid=None, green=True, payload={})


def _run_plan_validate(monkeypatch, report) -> dict:
    monkeypatch.setattr(plan_validate_command, "db_connection", _fake_db)
    monkeypatch.setattr(plan_validate_command, "resolve_plan", lambda c, n: _FakePlan())
    monkeypatch.setattr(
        plan_validate_command, "run_gate", lambda *a, **k: (report, _verdict())
    )
    monkeypatch.setattr(plan_validate_command, "get_open_cascade", lambda c, p: None)
    result = asyncio.run(PlanValidateCommand().execute(plan="block-g-plan"))
    assert isinstance(result, SuccessResult)
    return result.to_dict()["data"]


def test_plan_validate_surfaces_contours_with_a_not_evaluated_semantic(monkeypatch):
    data = _run_plan_validate(monkeypatch, _report(EXECUTION_CHECK))

    assert data["contours"]["structural"] == {"green": True, "findings_count": 0}
    assert data["contours"]["execution"] == {"green": False, "findings_count": 1}
    assert data["contours"]["semantic"]["state"] == "not_evaluated"
    # Additive only: external_verification and every pre-block-G key survive.
    assert "external_verification" in data
    assert data["report"]


def _run_plan_status(monkeypatch, report) -> dict:
    monkeypatch.setattr(plan_status_command, "db_connection", _fake_db)
    monkeypatch.setattr(plan_status_command, "resolve_plan", lambda c, n: _FakePlan())
    monkeypatch.setattr(plan_status_command, "load_steps", lambda c, p: {})
    monkeypatch.setattr(
        plan_status_command,
        "resolve_external_files_for_plan",
        lambda c, p: (None, False, {"status": "skipped", "reason": "no_primary_project"}),
    )
    monkeypatch.setattr(
        plan_status_command, "run_gate", lambda *a, **k: (report, _verdict())
    )
    result = asyncio.run(PlanStatusCommand().execute(plan="block-g-plan"))
    assert isinstance(result, SuccessResult)
    return result.to_dict()["data"]


def test_plan_status_semantic_contour_is_deferred_when_the_gate_is_green(monkeypatch):
    gate = _run_plan_status(monkeypatch, _report())["gate"]

    assert gate["contours"]["semantic"]["state"] == "deferred"
    # The semantic contour restates plan_status's own scoring block verbatim.
    assert gate["contours"]["semantic"]["reason"] == (
        "SemanticIndex scoring is queue-bound and is not computed "
        "synchronously by plan_status."
    )
    assert gate["contours"]["structural"]["green"] is True
    assert gate["external_verification"] == {
        "status": "skipped",
        "reason": "no_primary_project",
    }


def test_plan_status_semantic_contour_is_refused_when_the_gate_is_red(monkeypatch):
    data = _run_plan_status(monkeypatch, _report(EXECUTION_CHECK))

    assert data["gate"]["contours"]["semantic"]["state"] == "refused"
    assert data["gate"]["contours"]["execution"]["green"] is False
    # The pre-block-G scoring block is untouched: contours restates it, it
    # does not replace it.
    assert data["scoring"] == {"refused": "GATE_RED"}


def test_scoring_commands_report_a_scored_semantic_contour() -> None:
    block = contours_block(partition_contours(_report()))

    assert block["semantic"]["state"] == "scored"
    assert block["structural"] == {"green": True, "findings_count": 0}
    assert block["execution"] == {"green": True, "findings_count": 0}


def test_cascade_preview_passes_the_contours_through_to_the_response(monkeypatch):
    from plan_manager.commands import cascade_preview_command
    from plan_manager.commands.cascade_preview_command import CascadePreviewCommand

    preview = {
        "cascade_uuid": str(uuid.uuid4()),
        "base_revision_uuid": str(uuid.uuid4()),
        "tip_revision_uuid": str(uuid.uuid4()),
        "gate_green": False,
        "entries": [],
        "gate_report_json": "{}",
        "contours": contours_payload(
            partition_contours(_report(EXECUTION_CHECK)),
            semantic_contour("not_evaluated", "gate only"),
        ),
        "external_verification": {"status": "ok", "reason": None},
    }
    monkeypatch.setattr(cascade_preview_command, "db_connection", _fake_db)
    monkeypatch.setattr(cascade_preview_command, "resolve_plan", lambda c, n: _FakePlan())
    monkeypatch.setattr(cascade_preview_command, "get_open_cascade", lambda c, p: object())
    monkeypatch.setattr(
        cascade_preview_command, "preview_cascade", lambda c, p: dict(preview)
    )

    result = asyncio.run(CascadePreviewCommand().execute(plan="block-g-plan"))
    data = result.to_dict()["data"]

    assert data["contours"]["execution"] == {"green": False, "findings_count": 1}
    assert data["contours"]["semantic"]["state"] == "not_evaluated"
    assert data["external_verification"] == {"status": "ok", "reason": None}


# ---------------------------------------------------------------------------
# Layer 3: the authoritative documentation passage.
# ---------------------------------------------------------------------------


def _execution_docs() -> dict:
    result = asyncio.run(InfoCommand().execute(section="capabilities"))
    return result.to_dict()["data"]["capabilities"]["execution_integrity"]


def test_info_capabilities_documents_the_execution_integrity_axis() -> None:
    docs = _execution_docs()

    assert set(docs) >= {
        "summary",
        "semantic_coverage_vs_execution_closure",
        "role_vocabulary",
        "inferred_edge_provenance",
        "external_verification_modes",
        "no_silent_truth_writes",
        "diagnostic_override",
        "domain_errors",
    }
    json.dumps(docs)  # info returns this over JSON-RPC


def test_docs_name_every_artifact_role_and_both_inferred_edge_types() -> None:
    docs = _execution_docs()

    assert set(docs["role_vocabulary"]["roles"]) == {
        "create", "modify", "consume", "verify", "document", "package", "deploy",
    }
    assert set(docs["inferred_edge_provenance"]["inferred"]["types"]) == {
        "object_producer", "verification_target",
    }
    assert set(docs["inferred_edge_provenance"]["explicit"]["types"]) == {
        "explicit", "file_order",
    }


def test_docs_state_every_degraded_external_verification_mode() -> None:
    modes = _execution_docs()["external_verification_modes"]["modes"]

    assert set(modes) == {
        "ok",
        "skipped/no_primary_project",
        "skipped/plan_unreadable",
        "unavailable/ca_unreachable",
    }


def test_docs_state_the_no_silent_truth_writes_rule_and_its_only_path() -> None:
    rule = _execution_docs()["no_silent_truth_writes"]

    assert "execution_dependency_suggest" in rule["only_write_path"]
    assert "execution_dependency_apply" in rule["only_write_path"]


def test_docs_state_the_full_diagnostic_override_refusal_matrix() -> None:
    override = _execution_docs()["diagnostic_override"]

    assert override["command"] == "plan_prompt_chain"
    assert set(override["refusal_matrix"]) == {
        "structural_red", "execution_red_structural_green", "both_green",
    }
    assert "GATE_RED" in override["refusal_matrix"]["structural_red"]
    assert "EXECUTION_RED" in override["refusal_matrix"]["execution_red_structural_green"]
