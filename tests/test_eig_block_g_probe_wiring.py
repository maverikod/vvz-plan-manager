"""EIG block G (todo e902db52): the CA external-file probe reaches EVERY gate caller.

Block F wired the live analysis-server file inventory into exactly one
``run_gate`` caller (plan_validate) and recorded the rest as a residual. This
file pins the closure of that residual, in two layers:

1. ``runtime.external_verification.resolve_external_files_for_plan`` -- the
   uuid-only entry point the non-command callers use -- honours the same
   degraded matrix as block F's plan-object form and NEVER raises.
2. Each of the six previously probe-less callers (plan_status, cascade
   preview, cascade commit, the step_transition freeze gate,
   plan_prompt_chain, and the scoring index's two entry points) threads the
   resolved probe and policy flag into its own ``run_gate`` call, and passes
   ``external_files=None, require_project_verification=False`` -- i.e. keeps
   exactly its pre-block-G behaviour -- when no probe resolves.

Every caller is exercised through its real code path with the gate itself
faked, so what is asserted is the WIRING, not the checks (those are pinned by
tests/test_eig_block_e1/e2/f).
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from typing import Any

import pytest

from plan_manager.runtime import external_verification as ev
from plan_manager.runtime.ca_files_probe import ExternalFilesProbe
from plan_manager.verify.finding import Finding, build_report
from plan_manager.verify.verdict import Verdict

PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000e902db52")
PROJECT_ID = uuid.UUID("00000000-0000-0000-0000-0000000000f6")

AVAILABLE = ExternalFilesProbe(available=True, reason=None, files=frozenset({"src/a.py"}))
UNAVAILABLE = ExternalFilesProbe(available=False, reason="ca_unreachable")

SKIPPED_NO_BINDING = {"status": "skipped", "reason": "no_primary_project"}
SKIPPED_UNREADABLE = {"status": "skipped", "reason": "plan_unreadable"}


class _Plan:
    def __init__(self, primary: Any = None) -> None:
        self.uuid = PLAN_UUID
        self.name = "block-g-plan"
        self.status = "draft"
        self.completed = False
        self.comment = None
        self.project_ids: list[str] = []
        self.primary_project_id = primary
        self.head_revision_uuid = None


class _Rec:
    """Minimal open-cascade record stand-in."""

    def __init__(self) -> None:
        self.uuid = uuid.uuid4()
        self.name = "cascade/one"
        self.base_revision_uuid = uuid.uuid4()


class _Config:
    code_analysis_url = "mtls://casmgr:15010"
    code_analysis_timeout = 1.0
    code_analysis_cert = None
    code_analysis_key = None
    code_analysis_ca = None
    require_project_verification = True


@contextmanager
def _fake_db():
    yield object()


def _green():
    return build_report([], []), Verdict(
        kind="gate", scope="plan", revision_uuid=None, green=True, payload={}
    )


def _red():
    finding = Finding(
        check_id="parse.required_fields",
        severity="error",
        artifact_path="G-001",
        message="boom",
    )
    return build_report(["parse.required_fields"], [finding]), Verdict(
        kind="gate", scope="plan", revision_uuid=None, green=False, payload={}
    )


# ---------------------------------------------------------------------------
# Layer 1: resolve_external_files_for_plan's degraded matrix.
# ---------------------------------------------------------------------------


def test_unreadable_plan_row_degrades_to_skipped_and_never_raises(monkeypatch):
    def _boom(_conn, _plan_uuid):
        raise RuntimeError("no such plan")

    monkeypatch.setattr(ev, "get_plan", _boom)

    assert ev.resolve_external_files_for_plan(object(), PLAN_UUID) == (
        None,
        False,
        SKIPPED_UNREADABLE,
    )


def test_missing_plan_row_degrades_to_skipped(monkeypatch):
    monkeypatch.setattr(ev, "get_plan", lambda _c, _p: None)

    assert ev.resolve_external_files_for_plan(object(), PLAN_UUID) == (
        None,
        False,
        SKIPPED_UNREADABLE,
    )


def test_plan_without_a_primary_binding_fetches_no_probe(monkeypatch):
    monkeypatch.setattr(ev, "get_plan", lambda _c, _p: _Plan(primary=None))
    monkeypatch.setattr(
        ev,
        "list_project_files_probe",
        lambda **_k: pytest.fail("no probe may be fetched without a binding"),
    )

    assert ev.resolve_external_files_for_plan(object(), PLAN_UUID) == (
        None,
        False,
        SKIPPED_NO_BINDING,
    )


def test_available_probe_and_policy_flag_reach_the_caller(monkeypatch):
    monkeypatch.setattr(ev, "get_plan", lambda _c, _p: _Plan(primary=str(PROJECT_ID)))
    monkeypatch.setattr(ev, "app_config", lambda: _Config())
    monkeypatch.setattr(ev, "list_project_files_probe", lambda **_k: AVAILABLE)

    probe, require, payload = ev.resolve_external_files_for_plan(object(), PLAN_UUID)

    assert probe is AVAILABLE
    assert require is True
    assert payload == {"status": "ok", "reason": None}


def test_unreachable_ca_degrades_to_unavailable(monkeypatch):
    monkeypatch.setattr(ev, "get_plan", lambda _c, _p: _Plan(primary=str(PROJECT_ID)))
    monkeypatch.setattr(ev, "app_config", lambda: _Config())
    monkeypatch.setattr(ev, "list_project_files_probe", lambda **_k: UNAVAILABLE)

    probe, require, payload = ev.resolve_external_files_for_plan(object(), PLAN_UUID)

    assert probe is UNAVAILABLE
    assert require is True
    assert payload == {"status": "unavailable", "reason": "ca_unreachable"}


# ---------------------------------------------------------------------------
# Layer 2: every caller threads the probe into its own run_gate call.
# ---------------------------------------------------------------------------


def _capture(monkeypatch, module, result_factory=_green) -> dict:
    captured: dict = {}

    def _fake_run_gate(*_args: Any, **kwargs: Any):
        captured.update(kwargs)
        return result_factory()

    monkeypatch.setattr(module, "run_gate", _fake_run_gate)
    return captured


def _wire_probe(monkeypatch, module, probe=AVAILABLE, require=True, payload=None):
    monkeypatch.setattr(
        module,
        "resolve_external_files_for_plan",
        lambda _c, _p: (probe, require, payload or {"status": "ok", "reason": None}),
    )


def _assert_threaded(captured: dict, probe, require) -> None:
    assert captured["external_files"] is probe
    assert captured["require_project_verification"] is require


def test_plan_status_threads_the_probe(monkeypatch):
    from plan_manager.commands import plan_status_command as mod
    from plan_manager.commands.plan_status_command import PlanStatusCommand

    monkeypatch.setattr(mod, "db_connection", _fake_db)
    monkeypatch.setattr(mod, "resolve_plan", lambda _c, _n: _Plan())
    monkeypatch.setattr(mod, "load_steps", lambda _c, _p: {})
    _wire_probe(monkeypatch, mod)
    captured = _capture(monkeypatch, mod)

    asyncio.run(PlanStatusCommand().execute(plan="block-g-plan"))

    _assert_threaded(captured, AVAILABLE, True)


def test_plan_status_without_a_probe_keeps_the_pre_block_g_call(monkeypatch):
    from plan_manager.commands import plan_status_command as mod
    from plan_manager.commands.plan_status_command import PlanStatusCommand

    monkeypatch.setattr(mod, "db_connection", _fake_db)
    monkeypatch.setattr(mod, "resolve_plan", lambda _c, _n: _Plan())
    monkeypatch.setattr(mod, "load_steps", lambda _c, _p: {})
    _wire_probe(monkeypatch, mod, probe=None, require=False, payload=SKIPPED_NO_BINDING)
    captured = _capture(monkeypatch, mod)

    asyncio.run(PlanStatusCommand().execute(plan="block-g-plan"))

    _assert_threaded(captured, None, False)


def test_cascade_preview_threads_the_probe(monkeypatch):
    from plan_manager.cascade import preview as mod

    monkeypatch.setattr(mod, "get_open_cascade", lambda _c, _p: _Rec())
    monkeypatch.setattr(mod, "get_ref", lambda _c, _p, _n: uuid.uuid4())
    monkeypatch.setattr(mod, "diff", lambda *_a: {"added": [], "removed": [], "changed": []})
    monkeypatch.setattr(mod, "load_steps", lambda _c, _p: {})
    _wire_probe(monkeypatch, mod)
    captured = _capture(monkeypatch, mod)

    data = mod.preview_cascade(object(), PLAN_UUID)

    _assert_threaded(captured, AVAILABLE, True)
    assert data["external_verification"] == {"status": "ok", "reason": None}
    assert data["contours"]["semantic"]["state"] == "not_evaluated"


def test_cascade_commit_threads_the_probe(monkeypatch):
    from plan_manager.cascade import close as mod

    monkeypatch.setattr(mod, "acquire_plan_lock", lambda _c, _p: None)
    monkeypatch.setattr(mod, "release_plan_lock", lambda _c, _p: None)
    monkeypatch.setattr(mod, "get_open_cascade", lambda _c, _p: _Rec())
    _wire_probe(monkeypatch, mod)
    captured = _capture(monkeypatch, mod, result_factory=_red)

    with pytest.raises(mod.CommitRefusedError):
        mod.commit_cascade(object(), PLAN_UUID)

    _assert_threaded(captured, AVAILABLE, True)


def test_freeze_gate_threads_the_probe_once_for_the_whole_scope(monkeypatch):
    from plan_manager.commands import step_transition_command as mod

    calls: list[int] = []

    def _resolve(_conn, _plan_uuid):
        calls.append(1)
        return AVAILABLE, True, {"status": "ok", "reason": None}

    monkeypatch.setattr(mod, "resolve_external_files_for_plan", _resolve)
    monkeypatch.setattr(mod, "get_open_cascade", lambda _c, _p: None)
    captured = _capture(monkeypatch, mod)

    gate = mod._run_transition_gate(object(), PLAN_UUID, {}, [], "whole_plan", None)

    _assert_threaded(captured, AVAILABLE, True)
    assert len(calls) == 1, "the CA inventory must be read once per gate run"
    assert gate["contours"] == {
        "structural": {"green": True, "findings_count": 0},
        "execution": {"green": True, "findings_count": 0},
    }


def test_scoring_score_plan_threads_the_probe(monkeypatch):
    from plan_manager.scoring import index as mod
    from plan_manager.scoring.types import ScoreRefusedError, ScoringConfig

    _wire_probe(monkeypatch, mod)
    captured = _capture(monkeypatch, mod, result_factory=_red)

    with pytest.raises(ScoreRefusedError):
        mod.score_plan(object(), PLAN_UUID, ScoringConfig())

    _assert_threaded(captured, AVAILABLE, True)


def test_scoring_score_branch_threads_the_probe(monkeypatch):
    from plan_manager.scoring import index as mod
    from plan_manager.scoring.types import ScoreRefusedError, ScoringConfig

    monkeypatch.setattr(mod, "resolve_branch_scope", lambda *_a: object())
    monkeypatch.setattr(mod, "load_steps", lambda _c, _p: {})
    _wire_probe(monkeypatch, mod)
    captured = _capture(monkeypatch, mod, result_factory=_red)

    with pytest.raises(ScoreRefusedError):
        mod.score_branch(
            object(), PLAN_UUID, "G-001", "T-001", "A-001", ScoringConfig()
        )

    _assert_threaded(captured, AVAILABLE, True)


def test_plan_prompt_chain_threads_the_probe(monkeypatch):
    from plan_manager.commands import plan_prompt_chain_command as mod
    from plan_manager.commands.plan_prompt_chain_command import PlanPromptChainCommand

    monkeypatch.setattr(mod, "db_connection", _fake_db)
    monkeypatch.setattr(mod, "resolve_plan", lambda _c, _n: _Plan())
    _wire_probe(monkeypatch, mod)
    captured = _capture(monkeypatch, mod, result_factory=_red)

    result = asyncio.run(PlanPromptChainCommand().execute(plan="block-g-plan"))

    _assert_threaded(captured, AVAILABLE, True)
    assert result.to_dict()["error"]["data"]["domain_code"] == "GATE_RED"


@pytest.mark.parametrize(
    "module_path",
    [
        "plan_manager.commands.plan_status_command",
        "plan_manager.commands.plan_prompt_chain_command",
        "plan_manager.commands.step_transition_command",
        "plan_manager.cascade.preview",
        "plan_manager.cascade.close",
        "plan_manager.scoring.index",
    ],
)
def test_no_run_gate_caller_is_left_probe_less(module_path: str) -> None:
    """The block-F residual is closed: every caller imports the resolver."""
    module = __import__(module_path, fromlist=["_"])

    assert hasattr(module, "resolve_external_files_for_plan"), module_path
    assert hasattr(module, "run_gate"), module_path
