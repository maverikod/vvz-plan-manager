"""Regression tests for defect d01b3bc6: a fully-frozen plan must be
un-unfreezable through the new plan_unfreeze command, without weakening the
public cascade_begin frozen-truth guard.

All tests are unit-style with the established monkeypatch _fake_db / fake-conn
pattern (no real database), matching test_step_transition_fast_fail.py and
test_hotfix_cascade_all_steps_frozen.py.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone

import pytest

from plan_manager.cascade import begin as begin_mod
from plan_manager.cascade.record import CascadeRecord
from plan_manager.commands import plan_unfreeze_command, step_transition_command
from plan_manager.commands.plan_unfreeze_command import PlanUnfreezeCommand
from plan_manager.commands.step_transition_command import StepTransitionCommand
from plan_manager.domain.plan import Plan
from plan_manager.domain.runtime_validation import FrozenTruthMutationError
from plan_manager.domain.step import Step
from plan_manager.storage import runtime_audit_store


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000bb")


# --------------------------------------------------------------------------- helpers


@contextmanager
def _fake_db():
    yield object()


def _plan(name: str = "throwaway") -> Plan:
    return Plan(
        uuid=PLAN_UUID,
        name=name,
        status="draft",
        context_budget=4000,
        head_revision_uuid=HEAD_REV,
        project_ids=[],
        primary_project_id=None,
    )


def _step(step_uuid: str, level: int, step_id: str, parent, status: str) -> Step:
    fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1} if level == 5 else {}
    return Step(
        uuid=uuid.UUID(step_uuid), plan_uuid=PLAN_UUID, parent_step_uuid=parent,
        level=level, step_id=step_id, slug=step_id.lower(), fields=fields,
        depends_on=[], concepts=[], project_id=None, status=status,
    )


def _frozen_tree() -> dict[uuid.UUID, Step]:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None, "frozen")
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid, "frozen")
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid, "frozen")
    return {s.uuid: s for s in (gs, ts, atomic)}


class _AuditRecord:
    def __init__(self) -> None:
        self.audit_uuid = uuid.uuid4()


class _FakeCascade:
    def __init__(self) -> None:
        self.uuid = uuid.uuid4()
        self.name = f"cascade/{self.uuid}"


def _cascade_record() -> CascadeRecord:
    return CascadeRecord(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN_UUID,
        name="cascade/x",
        base_revision_uuid=HEAD_REV,
        status="open",
        created_at=datetime.now(timezone.utc),
    )


# ------------------------------------------------------- begin.py: internal bypass


class _StepConn:
    """Fake connection answering the two EXISTS probes of _all_steps_frozen."""

    def __init__(self, has_steps: bool, has_non_frozen: bool) -> None:
        self._has_steps = has_steps
        self._has_non_frozen = has_non_frozen

    def execute(self, sql, params=()):
        value = self._has_non_frozen if "status != 'frozen'" in sql else self._has_steps

        class _Cur:
            def fetchone(self_inner):
                return (value,)

        return _Cur()


def _patch_begin(monkeypatch, plan: Plan) -> dict:
    calls: dict = {}
    monkeypatch.setattr(begin_mod, "acquire_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "release_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_open_cascade", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_plan", lambda conn, pu: plan)
    monkeypatch.setattr(begin_mod, "create_ref", lambda conn, pu, name, rev: calls.setdefault("ref", name))
    monkeypatch.setattr(begin_mod, "insert_cascade", lambda conn, rec: calls.setdefault("rec", rec))
    return calls


def test_public_begin_cascade_still_refuses_fully_frozen(monkeypatch) -> None:
    plan = _plan()
    _patch_begin(monkeypatch, plan)
    conn = _StepConn(has_steps=True, has_non_frozen=False)
    with pytest.raises(FrozenTruthMutationError):
        begin_mod.begin_cascade(conn, plan.uuid)


def test_internal_bypass_opens_cascade_on_fully_frozen(monkeypatch) -> None:
    plan = _plan()
    calls = _patch_begin(monkeypatch, plan)
    conn = _StepConn(has_steps=True, has_non_frozen=False)
    rec = begin_mod.begin_cascade(conn, plan.uuid, allow_all_frozen=True)
    assert rec.status == "open"
    assert "rec" in calls


def test_internal_bypass_still_refuses_plan_status_frozen(monkeypatch) -> None:
    plan = _plan()
    object.__setattr__(plan, "status", "frozen")
    _patch_begin(monkeypatch, plan)
    conn = _StepConn(has_steps=True, has_non_frozen=False)
    with pytest.raises(FrozenTruthMutationError):
        begin_mod.begin_cascade(conn, plan.uuid, allow_all_frozen=True)


# ------------------------------------------------------- audit store accepts action


def test_runtime_audit_store_accepts_plan_unfreeze_action() -> None:
    assert "plan_unfreeze" in runtime_audit_store.ALLOWED_ACTIONS

    captured: dict = {}

    class _Conn:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

    rec = runtime_audit_store.record_runtime_change(
        _Conn(),
        plan_uuid=PLAN_UUID,
        entity_type="plan",
        entity_id=PLAN_UUID,
        action="plan_unfreeze",
        changed_by="orchestrator",
        change_reason="reopen",
        changed_fields={"head_revision_uuid": str(HEAD_REV)},
    )
    assert rec.action == "plan_unfreeze"
    assert "INSERT INTO runtime_audit_log" in captured["sql"]


# ------------------------------------------------------- plan_unfreeze command


def _patch_unfreeze(monkeypatch, *, all_frozen: bool, open_cascade, plan: Plan) -> dict:
    calls: dict = {}
    monkeypatch.setattr(plan_unfreeze_command, "db_connection", _fake_db)
    monkeypatch.setattr(plan_unfreeze_command, "resolve_plan", lambda conn, p: plan)
    monkeypatch.setattr(plan_unfreeze_command, "_all_steps_frozen", lambda conn, pu: all_frozen)
    monkeypatch.setattr(plan_unfreeze_command, "get_open_cascade", lambda conn, pu: open_cascade)

    def _audit(conn, **kwargs):
        calls["audit"] = kwargs
        return _AuditRecord()

    monkeypatch.setattr(plan_unfreeze_command, "record_runtime_change", _audit)

    def _begin(conn, pu, allow_all_frozen=False):
        calls["begin_allow_all_frozen"] = allow_all_frozen
        rec = _cascade_record()
        calls["cascade"] = rec
        return rec

    monkeypatch.setattr(plan_unfreeze_command, "begin_cascade", _begin)
    # get_open_cascade is called twice: pre-check and post-open re-read verify.
    if open_cascade is None:
        state = {"opened": None}

        def _get_open(conn, pu):
            return state["opened"]

        def _begin2(conn, pu, allow_all_frozen=False):
            calls["begin_allow_all_frozen"] = allow_all_frozen
            rec = _cascade_record()
            calls["cascade"] = rec
            state["opened"] = rec
            return rec

        monkeypatch.setattr(plan_unfreeze_command, "get_open_cascade", _get_open)
        monkeypatch.setattr(plan_unfreeze_command, "begin_cascade", _begin2)
    return calls


def test_plan_unfreeze_opens_audited_cascade_on_fully_frozen(monkeypatch) -> None:
    plan = _plan()
    calls = _patch_unfreeze(monkeypatch, all_frozen=True, open_cascade=None, plan=plan)

    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="orchestrator", reason="reopen for fix")
    )
    payload = result.to_dict()
    assert payload["success"] is True
    data = payload["data"]
    assert data["cascade_uuid"] == str(calls["cascade"].uuid)
    assert data["plan_uuid"] == str(PLAN_UUID)
    assert "audit_uuid" in data
    assert "step_transition" in data["next_steps"]
    # audited with the mandated fields, bypass flag set only for this door.
    assert calls["audit"]["action"] == "plan_unfreeze"
    assert calls["audit"]["changed_by"] == "orchestrator"
    assert calls["audit"]["change_reason"] == "reopen for fix"
    assert calls["audit"]["entity_type"] == "plan"
    assert calls["audit"]["changed_fields"] == {"head_revision_uuid": str(HEAD_REV)}
    assert calls["begin_allow_all_frozen"] is True


def test_plan_unfreeze_refuses_not_fully_frozen(monkeypatch) -> None:
    plan = _plan()
    calls = _patch_unfreeze(monkeypatch, all_frozen=False, open_cascade=None, plan=plan)
    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="o", reason="r")
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "PLAN_NOT_FULLY_FROZEN"
    assert "audit" not in calls  # no audit, no cascade opened on refusal


def test_plan_unfreeze_refuses_open_cascade(monkeypatch) -> None:
    plan = _plan()
    calls = _patch_unfreeze(monkeypatch, all_frozen=True, open_cascade=_cascade_record(), plan=plan)
    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by="o", reason="r")
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "CASCADE_CONFLICT"
    assert "audit" not in calls


@pytest.mark.parametrize(
    "changed_by,reason",
    [("", "r"), ("   ", "r"), ("o", ""), ("o", "   ")],
)
def test_plan_unfreeze_refuses_empty_actor_or_reason(monkeypatch, changed_by, reason) -> None:
    plan = _plan()
    _patch_unfreeze(monkeypatch, all_frozen=True, open_cascade=None, plan=plan)
    result = asyncio.run(
        PlanUnfreezeCommand().execute(plan="p", changed_by=changed_by, reason=reason)
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "RUNTIME_VALIDATION_ERROR"


# --------------------------------- end-to-end former-deadlock, then reopen succeeds


def test_step_transition_frozen_to_draft_refused_without_cascade(monkeypatch) -> None:
    """The deadlock's first wall: reopening a frozen step needs a cascade."""
    nodes = _frozen_tree()
    monkeypatch.setattr(step_transition_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_transition_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_transition_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(
        StepTransitionCommand().execute(plan="p", to_status="draft", step_id="A-001")
    )
    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "CASCADE_REQUIRED"


def test_scoped_frozen_to_draft_succeeds_under_cascade(monkeypatch) -> None:
    """After plan_unfreeze opens the cascade, the scoped reopen is admitted."""
    nodes = _frozen_tree()
    cascade = _FakeCascade()
    monkeypatch.setattr(step_transition_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_transition_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(step_transition_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(
        step_transition_command, "check_admission",
        lambda conn, plan_uuid, kind, step_uuid, cid: cascade,
    )

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p", to_status="draft", step_id="A-001",
            cascade_uuid=str(cascade.uuid), dry_run=True,
        )
    )
    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["transitioned"][0]["from"] == "frozen"
    assert payload["data"]["transitioned"][0]["to"] == "draft"
