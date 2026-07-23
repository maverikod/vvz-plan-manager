"""Regression tests for todo d8849951 (reword ambiguous coverage-gate
finding wording; document per-check gate semantics; expose plan_validate
state identity).

The coverage.gs finding "concept 'X' missing" read as "missing FROM the
GS row" instead of its real meaning ("declared on the GS but not covered
by any TS child"), causing two rejected false-blocker bug reports
(3de7a081, a8c43201) against a gate that was working as designed.

Covers, per the todo's three-piece mandate:
    1. The reworded "missing"-direction messages of check_coverage_gs and
       the plan-level coverage checks (concepts/labels/relations), and
       that the old ambiguous text is gone.
    2. GATE_CHECK_SEMANTICS (single source of truth) wired into both
       plan_validate and cascade_preview command metadata.
    3. plan_validate's response now carries tip_revision_uuid/cascade_uuid
       (populated with an open cascade, null without), alongside the
       pre-existing revision_uuid (still the committed-head label).

Exercised at the repo's existing convention: real check functions against
a minimal fake connection (mirrors test_bug_3de7a081_gs_coverage_live_read.py
/ test_step_update_validation.py), and PlanValidateCommand.execute against
monkeypatched module-level collaborators (mirrors
test_anchor_confirmation_commands.py).
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Any

from plan_manager.cascade.record import CascadeRecord
from plan_manager.commands import plan_validate_command
from plan_manager.commands.cascade_preview_metadata import get_cascade_preview_metadata
from plan_manager.commands.cascade_preview_command import CascadePreviewCommand
from plan_manager.commands.plan_validate_command import PlanValidateCommand
from plan_manager.commands.plan_validate_metadata import get_plan_validate_metadata
from plan_manager.verify.finding import build_report
from plan_manager.verify.gate import (
    GATE_CHECK_SEMANTICS,
    check_coverage_concepts,
    check_coverage_gs,
    check_coverage_labels,
    check_coverage_relations,
)
from plan_manager.verify.verdict import Verdict

PLAN_UUID = uuid.uuid4()


# ---------------------------------------------------------------------------
# Piece 1: reworded coverage-check "missing" messages.
# ---------------------------------------------------------------------------


class _Rows:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def fetchall(self) -> list:
        return list(self._rows)


class _GsCoverageConn:
    """gs_coverage's two fixed queries: one GS with an uncovered concept."""

    def execute(self, query: str, _params: tuple) -> _Rows:
        if "SELECT uuid, step_id, concepts FROM step" in query:
            return _Rows([(uuid.uuid4(), "G-001", ["C-095"])])
        if "SELECT parent_step_uuid, concepts FROM step" in query:
            return _Rows([])
        raise AssertionError(query)


def test_check_coverage_gs_new_wording_states_not_covered_by_child():
    findings = check_coverage_gs(_GsCoverageConn(), PLAN_UUID)

    assert len(findings) == 1
    finding = findings[0]
    assert finding.check_id == "coverage.gs"
    assert finding.artifact_path == "G-001"
    assert finding.message == "concept 'C-095' not covered by any child (TS) step"


def test_check_coverage_gs_old_ambiguous_text_is_gone():
    findings = check_coverage_gs(_GsCoverageConn(), PLAN_UUID)

    assert "concept 'C-095' missing" not in findings[0].message


class _ConceptCoverageConn:
    """concept_coverage's two fixed queries: an MRS concept absent from
    every GS step's own concepts."""

    def execute(self, query: str, _params: tuple) -> _Rows:
        if "SELECT concepts FROM step" in query:
            return _Rows([])
        if "SELECT concept_id FROM concept" in query:
            return _Rows([("C-201",)])
        raise AssertionError(query)


def test_check_coverage_concepts_new_wording_states_not_covered_by_gs():
    findings = check_coverage_concepts(_ConceptCoverageConn(), PLAN_UUID)

    assert len(findings) == 1
    assert findings[0].message == "concept 'C-201' not covered by any GS step"
    assert "concept 'C-201' missing" not in findings[0].message


class _LabelCoverageConn:
    """label_coverage's two fixed queries: a binding HRS paragraph label
    claimed by no GS step."""

    def execute(self, query: str, _params: tuple) -> _Rows:
        if "SELECT fields FROM step" in query:
            return _Rows([])
        if "SELECT label FROM paragraph" in query:
            return _Rows([("0o1l",)])
        raise AssertionError(query)


def test_check_coverage_labels_new_wording_states_not_covered_by_gs():
    findings = check_coverage_labels(_LabelCoverageConn(), PLAN_UUID)

    assert len(findings) == 1
    assert findings[0].message == "label '{0o1l}' not covered by any GS step"
    assert "label '{0o1l}' missing" not in findings[0].message


class _RelationCoverageConn:
    """relation_coverage's two fixed queries: an MRS relation implemented
    by no GS step."""

    def execute(self, query: str, _params: tuple) -> _Rows:
        if "SELECT fields FROM step" in query:
            return _Rows([])
        if "SELECT from_concept, to_concept, type FROM relation" in query:
            return _Rows([("C-014", "C-095", "produces")])
        raise AssertionError(query)


def test_check_coverage_relations_new_wording_states_not_covered_by_gs():
    findings = check_coverage_relations(_RelationCoverageConn(), PLAN_UUID)

    assert len(findings) == 1
    assert findings[0].message == "relation 'C-014|C-095|produces' not covered by any GS step"
    assert "relation 'C-014|C-095|produces' missing" not in findings[0].message


def test_no_reworded_check_message_contains_the_old_bare_missing_suffix():
    """Cross-check: none of the four reworded checks' "missing"-direction
    findings end in the old ambiguous '... missing' wording."""
    gs_findings = check_coverage_gs(_GsCoverageConn(), PLAN_UUID)
    concept_findings = check_coverage_concepts(_ConceptCoverageConn(), PLAN_UUID)
    label_findings = check_coverage_labels(_LabelCoverageConn(), PLAN_UUID)
    relation_findings = check_coverage_relations(_RelationCoverageConn(), PLAN_UUID)

    for finding in gs_findings + concept_findings + label_findings + relation_findings:
        assert not finding.message.endswith("missing"), finding.message
        assert "not covered by any" in finding.message


# ---------------------------------------------------------------------------
# Piece 2: GATE_CHECK_SEMANTICS documented in both commands' metadata.
# ---------------------------------------------------------------------------

_REQUIRED_GLOSS_CHECK_IDS = {
    "coverage.gs",
    "coverage.relations",
    "coverage.labels",
    "coverage.concepts",
    "references.depends_on",
    "references.concepts",
    "references.relations",
    "references.source_labels",
}


def test_gate_check_semantics_covers_the_mandated_checks():
    assert _REQUIRED_GLOSS_CHECK_IDS <= set(GATE_CHECK_SEMANTICS)
    for check_id in _REQUIRED_GLOSS_CHECK_IDS:
        gloss = GATE_CHECK_SEMANTICS[check_id]
        assert isinstance(gloss, str)
        assert len(gloss) > 0


def test_gate_check_semantics_coverage_gs_gloss_explains_child_not_row():
    gloss = GATE_CHECK_SEMANTICS["coverage.gs"]
    assert "child" in gloss
    assert "TS" in gloss
    assert "is missing from the GS row" in gloss


def test_plan_validate_metadata_carries_gate_check_semantics():
    metadata = get_plan_validate_metadata(PlanValidateCommand)

    assert metadata["gate_check_semantics"] == dict(GATE_CHECK_SEMANTICS)
    assert _REQUIRED_GLOSS_CHECK_IDS <= set(metadata["gate_check_semantics"])


def test_cascade_preview_metadata_carries_gate_check_semantics():
    metadata = get_cascade_preview_metadata(CascadePreviewCommand)

    assert metadata["gate_check_semantics"] == dict(GATE_CHECK_SEMANTICS)
    assert _REQUIRED_GLOSS_CHECK_IDS <= set(metadata["gate_check_semantics"])


def test_plan_validate_metadata_documents_revision_uuid_as_committed_label():
    metadata = get_plan_validate_metadata(PlanValidateCommand)
    revision_doc = metadata["return_value"]["success"]["data"]["revision_uuid"]

    assert "committed" in revision_doc.lower()
    assert "does NOT identify which rows" in revision_doc


def test_plan_validate_metadata_documents_tip_revision_uuid_and_cascade_uuid_fields():
    metadata = get_plan_validate_metadata(PlanValidateCommand)
    data_doc = metadata["return_value"]["success"]["data"]

    assert "tip_revision_uuid" in data_doc
    assert "cascade_uuid" in data_doc
    assert "tip_revision_uuid" in metadata["return_value"]["success"]["example"]
    assert "cascade_uuid" in metadata["return_value"]["success"]["example"]


# ---------------------------------------------------------------------------
# Piece 3: plan_validate response carries tip_revision_uuid/cascade_uuid.
# ---------------------------------------------------------------------------


class _FakePlan:
    def __init__(self, plan_uuid: uuid.UUID) -> None:
        self.uuid = plan_uuid
        self.name = "throwaway-plan"


def _fake_db_ctx():
    @contextmanager
    def _cm():
        yield object()

    return _cm


def _fake_run_gate(*_args: Any, **_kwargs: Any):
    report = build_report([], [])
    verdict = Verdict(
        kind="gate",
        scope="plan",
        revision_uuid=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
        green=True,
        payload={},
    )
    return report, verdict


def test_plan_validate_response_carries_open_cascade_identity(monkeypatch):
    cascade_uuid = uuid.UUID("00000000-0000-0000-0000-0000000000cc")
    tip_uuid = uuid.UUID("00000000-0000-0000-0000-0000000000dd")
    plan_uuid = uuid.uuid4()

    monkeypatch.setattr(plan_validate_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(plan_validate_command, "resolve_plan", lambda conn, plan: _FakePlan(plan_uuid))
    monkeypatch.setattr(plan_validate_command, "run_gate", _fake_run_gate)
    monkeypatch.setattr(
        plan_validate_command,
        "get_open_cascade",
        lambda conn, p_uuid: CascadeRecord(
            uuid=cascade_uuid,
            plan_uuid=p_uuid,
            name="cascade/" + str(cascade_uuid),
            base_revision_uuid=None,
            status="open",
            created_at=None,
        ),
    )
    monkeypatch.setattr(plan_validate_command, "get_ref", lambda conn, p_uuid, name: tip_uuid)

    result = asyncio.run(PlanValidateCommand().execute(plan="throwaway-plan"))

    data = result.to_dict()["data"]
    assert data["cascade_uuid"] == str(cascade_uuid)
    assert data["tip_revision_uuid"] == str(tip_uuid)
    assert data["revision_uuid"] == "00000000-0000-0000-0000-0000000000aa"


def test_plan_validate_response_nulls_identity_fields_without_open_cascade(monkeypatch):
    plan_uuid = uuid.uuid4()

    monkeypatch.setattr(plan_validate_command, "db_connection", _fake_db_ctx())
    monkeypatch.setattr(plan_validate_command, "resolve_plan", lambda conn, plan: _FakePlan(plan_uuid))
    monkeypatch.setattr(plan_validate_command, "run_gate", _fake_run_gate)
    monkeypatch.setattr(plan_validate_command, "get_open_cascade", lambda conn, p_uuid: None)

    def _get_ref_should_not_be_called(*_args: Any, **_kwargs: Any):
        raise AssertionError("get_ref must not be called without an open cascade")

    monkeypatch.setattr(plan_validate_command, "get_ref", _get_ref_should_not_be_called)

    result = asyncio.run(PlanValidateCommand().execute(plan="throwaway-plan"))

    data = result.to_dict()["data"]
    assert data["cascade_uuid"] is None
    assert data["tip_revision_uuid"] is None
    assert data["revision_uuid"] == "00000000-0000-0000-0000-0000000000aa"
