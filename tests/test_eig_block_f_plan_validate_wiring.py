"""Caller wiring for EIG block F (todo 763ae29e): plan_validate is the ONE
run_gate caller that fetches the live CA file probe, plus the end-to-end
report shape carrying all twelve execution_integrity check_ids.

Two layers:

1. ``plan_manager.commands.plan_validate_command.resolve_external_files`` and
   its use inside ``execute``: the plan's PRIMARY project binding
   (``plan.primary_project_id``, the same field plan_project_list reports)
   decides whether a probe is fetched at all, the probe result is passed down
   to ``run_gate`` unchanged, and the outcome is reported to the caller in the
   additive ``external_verification`` response key. Every other run_gate
   caller (step_transition, cascade close, plan_prompt_chain, plan_status,
   the scoring index) intentionally stays probe-less this block -- block-G
   residual -- which is pinned here by the defaults of run_gate itself.
2. A full ``run_gate`` pass over a green fixture, asserting the report lists
   all twelve execution_integrity check_ids as passing (the four block-F ones
   included) when no probe is wired.

Fake-connection convention copied from
tests/test_eig_block_e1_gate_execution.py / _e2_gate_closure.py.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from plan_manager.commands import plan_validate_command
from plan_manager.commands.plan_validate_command import (
    PlanValidateCommand,
    resolve_external_files,
)
from plan_manager.domain.paragraph import Paragraph
from plan_manager.domain.step import Step
from plan_manager.runtime.ca_files_probe import ExternalFilesProbe
from plan_manager.verify.finding import build_report
from plan_manager.verify.gate import CHECK_IDS, run_gate
from plan_manager.verify.verdict import Verdict
from plan_manager.views.branch import BranchScope

PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-0000763ae29e")


class _FakePlan:
    def __init__(self, plan_uuid: uuid.UUID, primary: Any = None) -> None:
        self.uuid = plan_uuid
        self.name = "throwaway-plan"
        if primary is not None:
            self.primary_project_id = primary


class _FakeConfig:
    code_analysis_url = "mtls://casmgr:15010"
    code_analysis_timeout = 1.0
    code_analysis_cert = None
    code_analysis_key = None
    code_analysis_ca = None

    def __init__(self, require: bool = False) -> None:
        self.require_project_verification = require


AVAILABLE = ExternalFilesProbe(available=True, reason=None, files=frozenset({"src/a.py"}))
UNAVAILABLE = ExternalFilesProbe(available=False, reason="ca_unreachable")


def _patch_probe(monkeypatch, probe: ExternalFilesProbe, *, require: bool = False) -> list[dict]:
    calls: list[dict] = []

    def _fake_probe(**kwargs: Any) -> ExternalFilesProbe:
        calls.append(kwargs)
        return probe

    monkeypatch.setattr(plan_validate_command, "list_project_files_probe", _fake_probe)
    monkeypatch.setattr(plan_validate_command, "app_config", lambda: _FakeConfig(require))
    return calls


# ---------------------------------------------------------------------------
# resolve_external_files: the four outcomes.
# ---------------------------------------------------------------------------


def test_no_primary_project_binding_skips_the_probe(monkeypatch):
    def _boom(**kwargs: Any):
        raise AssertionError("no probe may be fetched without a primary project binding")

    monkeypatch.setattr(plan_validate_command, "list_project_files_probe", _boom)

    probe, require, payload = resolve_external_files(_FakePlan(uuid.uuid4()))

    assert probe is None
    assert require is False
    assert payload == {"status": "skipped", "reason": "no_primary_project"}


def test_available_probe_is_fetched_from_the_primary_project(monkeypatch):
    calls = _patch_probe(monkeypatch, AVAILABLE, require=True)

    probe, require, payload = resolve_external_files(
        _FakePlan(uuid.uuid4(), primary=str(PROJECT_ID))
    )

    assert probe is AVAILABLE
    assert require is True
    assert payload == {"status": "ok", "reason": None}
    assert len(calls) == 1
    assert calls[0]["project_id"] == PROJECT_ID
    assert calls[0]["ca_url"] == "mtls://casmgr:15010"
    assert calls[0]["timeout"] == 1.0


def test_unavailable_probe_is_reported_as_unavailable(monkeypatch):
    _patch_probe(monkeypatch, UNAVAILABLE)

    probe, require, payload = resolve_external_files(
        _FakePlan(uuid.uuid4(), primary=str(PROJECT_ID))
    )

    assert probe is UNAVAILABLE
    assert require is False
    assert payload == {"status": "unavailable", "reason": "ca_unreachable"}


def test_non_uuid_primary_project_binding_is_skipped(monkeypatch):
    def _boom(**kwargs: Any):
        raise AssertionError("no probe may be fetched for an unparseable project binding")

    monkeypatch.setattr(plan_validate_command, "list_project_files_probe", _boom)
    monkeypatch.setattr(plan_validate_command, "app_config", lambda: _FakeConfig())

    probe, _require, payload = resolve_external_files(
        _FakePlan(uuid.uuid4(), primary="not-a-uuid")
    )

    assert probe is None
    assert payload == {"status": "skipped", "reason": "no_primary_project"}


def test_uninitialized_runtime_degrades_instead_of_raising(monkeypatch):
    def _uninitialized():
        raise RuntimeError("runtime not initialized")

    monkeypatch.setattr(plan_validate_command, "app_config", _uninitialized)

    probe, require, payload = resolve_external_files(
        _FakePlan(uuid.uuid4(), primary=str(PROJECT_ID))
    )

    assert probe is not None and probe.available is False
    assert require is False
    assert payload == {"status": "unavailable", "reason": "ca_unreachable"}


# ---------------------------------------------------------------------------
# execute(): the probe reaches run_gate and the payload key reaches the caller.
# ---------------------------------------------------------------------------


def _run_execute(monkeypatch, plan: _FakePlan) -> tuple[dict, dict]:
    captured: dict = {}

    @contextmanager
    def _fake_db():
        yield object()

    def _fake_run_gate(*_args: Any, **kwargs: Any):
        captured.update(kwargs)
        return build_report([], []), Verdict(
            kind="gate",
            scope="plan",
            revision_uuid=uuid.UUID("00000000-0000-0000-0000-0000000000aa"),
            green=True,
            payload={},
        )

    monkeypatch.setattr(plan_validate_command, "db_connection", _fake_db)
    monkeypatch.setattr(plan_validate_command, "resolve_plan", lambda conn, name: plan)
    monkeypatch.setattr(plan_validate_command, "run_gate", _fake_run_gate)
    monkeypatch.setattr(plan_validate_command, "get_open_cascade", lambda conn, p: None)

    result = asyncio.run(PlanValidateCommand().execute(plan="throwaway-plan"))
    return result.to_dict()["data"], captured


def test_execute_threads_an_available_probe_into_run_gate(monkeypatch):
    _patch_probe(monkeypatch, AVAILABLE, require=True)

    data, captured = _run_execute(monkeypatch, _FakePlan(uuid.uuid4(), primary=str(PROJECT_ID)))

    assert data["external_verification"] == {"status": "ok", "reason": None}
    assert captured["external_files"] is AVAILABLE
    assert captured["require_project_verification"] is True


def test_execute_reports_skipped_and_passes_no_probe_without_a_binding(monkeypatch):
    data, captured = _run_execute(monkeypatch, _FakePlan(uuid.uuid4()))

    assert data["external_verification"] == {"status": "skipped", "reason": "no_primary_project"}
    assert captured["external_files"] is None
    assert captured["require_project_verification"] is False


def test_execute_response_keeps_every_pre_block_f_key(monkeypatch):
    """external_verification is ADDITIVE: nothing the response promised
    before block F may disappear or change shape."""
    data, _captured = _run_execute(monkeypatch, _FakePlan(uuid.uuid4()))

    assert set(data) == {
        "green",
        "scope",
        "revision_uuid",
        "tip_revision_uuid",
        "cascade_uuid",
        "format",
        "report",
        "external_verification",
    }
    assert data["green"] is True
    assert data["revision_uuid"] == "00000000-0000-0000-0000-0000000000aa"


# ---------------------------------------------------------------------------
# End-to-end run_gate: all twelve execution_integrity check_ids in the report.
# ---------------------------------------------------------------------------

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000763ae290")
GS_UUID = uuid.UUID("00000000-0000-0000-0000-0000763ae291")
TS_UUID = uuid.UUID("00000000-0000-0000-0000-0000763ae292")
AS_UUID = uuid.UUID("00000000-0000-0000-0000-0000763ae293")
HEAD_REVISION = uuid.UUID("00000000-0000-0000-0000-0000763ae294")

GS_FIELDS = {
    "name": "G one",
    "description": "GS description.",
    "relations": [{"from_concept": "C-001", "to_concept": "C-001", "type": "supports"}],
    "source_labels": ["{aaaa}"],
}
TS_FIELDS = {
    "name": "T one",
    "description": "TS description.",
    "inputs": [{"name": "in-one", "type": "input", "description": "one input."}],
    "outputs": [{"name": "out-one", "type": "output", "description": "one output."}],
}
AS_FIELDS = {
    "name": "A one",
    "target_file": "src/one.py",
    "operation": "create_file",
    "priority": 1,
    "prompt": "do work",
    "verification": "pytest tests/test_one.py",
}

STEP_ROWS = [
    (GS_UUID, PLAN_UUID, None, 3, "G-001", "g-one", GS_FIELDS, [], ["C-001"], None, "draft"),
    (TS_UUID, PLAN_UUID, GS_UUID, 4, "T-001", "t-one", TS_FIELDS, [], ["C-001"], None, "draft"),
    (AS_UUID, PLAN_UUID, TS_UUID, 5, "A-001", "a-one", AS_FIELDS, [], [], None, "draft"),
]

CONTEXT_BLOCK_ROWS = [
    ("G-001", 4, HEAD_REVISION, None, ["C-001"], datetime(2026, 8, 1, tzinfo=timezone.utc)),
    ("G-001/T-001", 5, HEAD_REVISION, None, [], datetime(2026, 8, 1, tzinfo=timezone.utc)),
]


class _Rows:
    def __init__(self, rows: list[tuple]):
        self._rows = rows

    def fetchone(self) -> Optional[tuple]:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FullCursor:
    """Copy of test_eig_block_e1_gate_execution.py's _FullCursor."""

    def __init__(self, owner: "_FullFakeConn"):
        self._owner = owner
        self._pending: list[tuple] = []

    def __enter__(self) -> "_FullCursor":
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False

    def execute(self, query: str, params: tuple = ()) -> "_FullCursor":
        self._pending = self._owner.dispatch(query, params)
        return self

    def fetchall(self) -> list[tuple]:
        return self._pending

    def fetchone(self) -> Optional[tuple]:
        return self._pending[0] if self._pending else None


class _FullFakeConn:
    """Copy of test_eig_block_e1_gate_execution.py's _FullFakeConn."""

    def cursor(self) -> _FullCursor:
        return _FullCursor(self)

    def execute(self, query: str, params: tuple = ()) -> _Rows:
        return _Rows(self.dispatch(query, params))

    def dispatch(self, query: str, params: tuple) -> list[tuple]:
        if query.startswith("SELECT uuid, plan_uuid, parent_step_uuid, level, step_id, slug"):
            return list(STEP_ROWS)
        if query.startswith("SELECT concept_id FROM concept"):
            return [("C-001",)]
        if query.startswith("SELECT from_concept, to_concept, type FROM relation"):
            return []
        if query.startswith(
            "SELECT label FROM paragraph WHERE plan_uuid = %s AND binding IS TRUE ORDER BY position"
        ):
            return [("aaaa",)]
        if query.startswith("SELECT count(*) FROM paragraph"):
            return [(1,)]
        if query.startswith("SELECT uuid, step_id, concepts FROM step WHERE plan_uuid = %s AND level = 3"):
            return [(GS_UUID, "G-001", ["C-001"])]
        if query.startswith("SELECT parent_step_uuid, concepts FROM step WHERE plan_uuid = %s AND level = 4"):
            return [(GS_UUID, ["C-001"])]
        if query.startswith("SELECT uuid, step_id FROM step WHERE plan_uuid = %s AND level = 3"):
            return [(GS_UUID, "G-001")]
        if query.startswith("SELECT uuid, parent_step_uuid, step_id FROM step "):
            return [(TS_UUID, GS_UUID, "T-001")]
        if query.startswith("SELECT parent_step_uuid, step_id, fields, concepts FROM step "):
            return [(TS_UUID, "A-001", AS_FIELDS, [])]
        if query.startswith("SELECT uuid, name FROM cascade"):
            return []
        if query.startswith("SELECT revision_uuid FROM ref"):
            return []
        if query.startswith("SELECT head_revision_uuid FROM plan"):
            return [(HEAD_REVISION,)]
        if query.startswith("SELECT node_path, child_level, revision_uuid, cascade_uuid"):
            return list(CONTEXT_BLOCK_ROWS)
        raise AssertionError(f"unexpected query in _FullFakeConn: {query!r}")


def _branch() -> BranchScope:
    return BranchScope(
        plan_uuid=PLAN_UUID,
        depth="gs",
        gs=Step(
            uuid=GS_UUID, plan_uuid=PLAN_UUID, parent_step_uuid=None, level=3,
            step_id="G-001", slug="g-one", fields=GS_FIELDS, depends_on=[],
            concepts=["C-001"], project_id=None, status="draft",
        ),
        ts=None,
        atomic=None,
        hrs_slice=[Paragraph(label="aaaa", text="unused.", position=0)],
    )


def test_report_lists_all_twelve_execution_integrity_check_ids_when_passing():
    report, _verdict = run_gate(_FullFakeConn(), PLAN_UUID, branch=_branch(), fail_fast=False)

    assert report.green is True, report.checks
    expected = set(CHECK_IDS["execution_integrity"])
    assert len(expected) == 12
    present = {check.check_id for check in report.checks}
    assert expected <= present
    for check in report.checks:
        if check.check_id in expected:
            assert check.passed is True
            assert check.findings == []


def test_probe_less_run_gate_defaults_keep_block_f_silent():
    """Block-G residual: every caller that does not wire a probe gets the
    pre-block-F report, which is what makes the four new check_ids safe to
    register and the orphan switch safe to flip."""
    report, _verdict = run_gate(_FullFakeConn(), PLAN_UUID, branch=_branch())

    assert report.green is True
    block_f = {
        "execution_integrity.artifact_producer_exists",
        "execution_integrity.verification_target_resolvable",
        "execution_integrity.modify_file_context_available",
        "execution_integrity.external_project_unverified",
        "execution_integrity.no_orphan_verification",
    }
    for check in report.checks:
        if check.check_id in block_f:
            assert check.findings == []
