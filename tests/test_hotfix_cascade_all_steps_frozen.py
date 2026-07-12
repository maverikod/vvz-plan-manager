"""Regression tests for 0.1.27 hotfix defect 2b: cascade_begin must refuse a plan whose
non-empty step set is entirely frozen, even when plan.status is still 'draft' (no command
surface ever sets plan-level status to frozen; step_transition freezes only step.status)."""
from __future__ import annotations

import uuid

import pytest

from plan_manager.cascade import begin as begin_mod
from plan_manager.domain.plan import Plan
from plan_manager.domain.runtime_validation import FrozenTruthMutationError


class _Cursor:
    def __init__(self, value: bool) -> None:
        self._value = value

    def fetchone(self):
        return (self._value,)


class _StepConn:
    """Fake connection answering the two EXISTS probes of _all_steps_frozen."""

    def __init__(self, has_steps: bool, has_non_frozen: bool) -> None:
        self._has_steps = has_steps
        self._has_non_frozen = has_non_frozen

    def execute(self, sql, params=()):
        if "status != 'frozen'" in sql:
            return _Cursor(self._has_non_frozen)
        return _Cursor(self._has_steps)


def _plan(status: str = "draft") -> Plan:
    return Plan(
        uuid=uuid.uuid4(),
        name="p",
        status=status,
        context_budget=4000,
        head_revision_uuid=uuid.uuid4(),
        project_ids=[],
        primary_project_id=None,
    )


def _patch_common(monkeypatch, plan: Plan) -> dict:
    calls: dict = {}
    monkeypatch.setattr(begin_mod, "acquire_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "release_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_open_cascade", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_plan", lambda conn, pu: plan)
    monkeypatch.setattr(
        begin_mod, "create_ref", lambda conn, pu, name, rev: calls.setdefault("ref", name)
    )
    monkeypatch.setattr(begin_mod, "insert_cascade", lambda conn, rec: calls.setdefault("rec", rec))
    return calls


def test_draft_plan_with_all_steps_frozen_is_refused(monkeypatch) -> None:
    plan = _plan("draft")
    _patch_common(monkeypatch, plan)
    conn = _StepConn(has_steps=True, has_non_frozen=False)
    with pytest.raises(FrozenTruthMutationError):
        begin_mod.begin_cascade(conn, plan.uuid)


def test_plan_with_a_non_frozen_step_is_allowed(monkeypatch) -> None:
    plan = _plan("draft")
    calls = _patch_common(monkeypatch, plan)
    conn = _StepConn(has_steps=True, has_non_frozen=True)
    rec = begin_mod.begin_cascade(conn, plan.uuid)
    assert rec.status == "open"
    assert "rec" in calls


def test_plan_with_zero_steps_is_allowed(monkeypatch) -> None:
    plan = _plan("draft")
    calls = _patch_common(monkeypatch, plan)
    conn = _StepConn(has_steps=False, has_non_frozen=False)
    rec = begin_mod.begin_cascade(conn, plan.uuid)
    assert rec.status == "open"
    assert "rec" in calls
