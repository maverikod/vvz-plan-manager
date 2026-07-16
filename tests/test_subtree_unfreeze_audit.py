"""Tests for G-003/T-001 (C-006 SubtreeUnfreezeAudit): a scoped frozen->draft
step_transition must write an immutable runtime audit record equivalent in
rigor to the plan_unfreeze audit, and the audit action vocabulary must gain
the additive 'subtree_unfreeze' value.

Unit-style, no real database: monkeypatch module-level names on
step_transition_command directly, matching the established pattern of
tests/test_plan_unfreeze.py and tests/test_step_transition_fast_fail.py.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import step_transition_command
from plan_manager.commands.step_transition_command import StepTransitionCommand
from plan_manager.domain.step import Step
from plan_manager.storage import runtime_audit_store


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000bb")


class _DummyPlan:
    uuid = PLAN_UUID
    head_revision_uuid = HEAD_REV


class _FakeCascadeRec:
    def __init__(self) -> None:
        self.uuid = uuid.uuid4()
        self.name = "cascade/x"


class _AuditRecord:
    def __init__(self) -> None:
        self.audit_uuid = uuid.uuid4()


@contextmanager
def _fake_db():
    yield _Conn()


class _Conn:
    def execute(self, sql, params=()):
        return None


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


def _draft_tree() -> dict[uuid.UUID, Step]:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None, "draft")
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid, "draft")
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid, "draft")
    return {s.uuid: s for s in (gs, ts, atomic)}


def _patch_common(monkeypatch, nodes) -> dict:
    calls: dict = {}
    monkeypatch.setattr(step_transition_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_transition_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_transition_command, "load_steps", lambda conn, plan_uuid: nodes)
    monkeypatch.setattr(
        step_transition_command,
        "check_admission",
        lambda conn, plan_uuid, kind, target_uuid, cascade_uuid: _FakeCascadeRec(),
    )
    monkeypatch.setattr(step_transition_command, "get_ref", lambda conn, plan_uuid, name: HEAD_REV)

    def _rev(conn, plan_uuid, actor, message, changes, parent, ref_name=None):
        calls["revision"] = {
            "changes": changes, "parent": parent, "ref_name": ref_name, "message": message,
        }
        return uuid.uuid4()

    monkeypatch.setattr(step_transition_command, "record_revision", _rev)

    def _audit(conn, **kwargs):
        calls.setdefault("audit_calls", []).append(kwargs)
        return _AuditRecord()

    monkeypatch.setattr(step_transition_command, "record_runtime_change", _audit)
    return calls


# --------------------------------------------------------------------- vocabulary


def test_allowed_actions_gains_subtree_unfreeze() -> None:
    assert "subtree_unfreeze" in runtime_audit_store.ALLOWED_ACTIONS
    # plan_unfreeze stays present: this is an additive change only.
    assert "plan_unfreeze" in runtime_audit_store.ALLOWED_ACTIONS


# --------------------------------------------------------------------- happy path


def test_scoped_unfreeze_writes_one_subtree_unfreeze_audit_record(monkeypatch) -> None:
    nodes = _frozen_tree()
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p",
            to_status="draft",
            scope="G-001",
            cascade_uuid=str(uuid.uuid4()),
            changed_by="orchestrator",
            reason="reopen G-001 to fix a defect",
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True
    audit_calls = calls["audit_calls"]
    assert len(audit_calls) == 1
    audit = audit_calls[0]
    assert audit["action"] == "subtree_unfreeze"
    assert audit["entity_type"] == "plan"
    assert audit["entity_id"] == PLAN_UUID
    assert audit["changed_by"] == "orchestrator"
    assert audit["change_reason"] == "reopen G-001 to fix a defect"
    assert audit["changed_fields"]["scope"] == "G-001"
    assert set(audit["changed_fields"]["unfrozen_steps"]) == {"G-001", "T-001", "A-001"}
    assert audit["changed_fields"]["head_revision_uuid"] == str(HEAD_REV)


# --------------------------------------------------------------------- validation


def test_scoped_unfreeze_without_changed_by_is_refused(monkeypatch) -> None:
    nodes = _frozen_tree()
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p",
            to_status="draft",
            scope="G-001",
            cascade_uuid=str(uuid.uuid4()),
            reason="reopen G-001 to fix a defect",
        )
    )

    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "RUNTIME_VALIDATION_ERROR"
    assert "audit_calls" not in calls
    assert "revision" not in calls


def test_scoped_unfreeze_without_reason_is_refused(monkeypatch) -> None:
    nodes = _frozen_tree()
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p",
            to_status="draft",
            scope="G-001",
            cascade_uuid=str(uuid.uuid4()),
            changed_by="orchestrator",
            reason="   ",
        )
    )

    payload = result.to_dict()
    assert payload["success"] is False
    assert payload["error"]["data"]["domain_code"] == "RUNTIME_VALIDATION_ERROR"
    assert "audit_calls" not in calls
    assert "revision" not in calls


# --------------------------------------------------------------------- non-unfreeze paths write no audit


def test_dry_run_unfreeze_writes_no_audit_record(monkeypatch) -> None:
    nodes = _frozen_tree()
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p",
            to_status="draft",
            scope="G-001",
            cascade_uuid=str(uuid.uuid4()),
            dry_run=True,
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["dry_run"] is True
    assert "audit_calls" not in calls
    assert "revision" not in calls


def test_draft_to_ready_for_review_writes_no_audit_record(monkeypatch) -> None:
    nodes = _draft_tree()
    calls = _patch_common(monkeypatch, nodes)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p",
            to_status="ready_for_review",
            scope="G-001",
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert "audit_calls" not in calls
    assert calls["revision"]["changes"]
