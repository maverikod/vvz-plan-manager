"""Regression test for 0.1.26 hotfix defect 2: cascade_begin must refuse a frozen plan.

Opening a cascade on a frozen plan would corrupt frozen plan truth (read-only), so begin_cascade
must raise FrozenTruthMutationError (mapped to the FROZEN_TRUTH_WRITE domain code)."""
from __future__ import annotations

import uuid

import pytest

from plan_manager.cascade import begin as begin_mod
from plan_manager.domain.plan import Plan
from plan_manager.domain.runtime_validation import FrozenTruthMutationError


def _plan(status: str) -> Plan:
    return Plan(
        uuid=uuid.uuid4(),
        name="p",
        status=status,
        context_budget=4000,
        head_revision_uuid=uuid.uuid4(),
        project_ids=[],
        primary_project_id=None,
    )


def test_begin_cascade_refuses_frozen_plan(monkeypatch) -> None:
    frozen = _plan("frozen")
    monkeypatch.setattr(begin_mod, "acquire_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "release_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_open_cascade", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_plan", lambda conn, pu: frozen)

    with pytest.raises(FrozenTruthMutationError):
        begin_mod.begin_cascade(object(), frozen.uuid)


def test_begin_cascade_allows_non_frozen_plan(monkeypatch) -> None:
    draft = _plan("draft")
    calls: dict = {}
    monkeypatch.setattr(begin_mod, "acquire_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "release_plan_lock", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_open_cascade", lambda conn, pu: None)
    monkeypatch.setattr(begin_mod, "get_plan", lambda conn, pu: draft)
    monkeypatch.setattr(begin_mod, "_all_steps_frozen", lambda conn, pu: False)
    monkeypatch.setattr(
        begin_mod, "create_ref", lambda conn, pu, name, rev: calls.setdefault("ref", (name, rev))
    )
    monkeypatch.setattr(begin_mod, "insert_cascade", lambda conn, rec: calls.setdefault("rec", rec))

    rec = begin_mod.begin_cascade(object(), draft.uuid)
    assert rec.status == "open"
    assert rec.base_revision_uuid == draft.head_revision_uuid
    assert "rec" in calls and "ref" in calls
