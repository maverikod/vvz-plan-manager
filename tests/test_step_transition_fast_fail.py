"""Regression tests for bug 96329ae5: step_transition must reject an all-illegal transition
synchronously and immediately (no queue, no gate run) with INVALID_TRANSITION + legal_targets,
while a legal request still flows through."""
from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import step_transition_command
from plan_manager.commands.step_transition_command import StepTransitionCommand
from plan_manager.domain.step import Step


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _step(step_uuid: str, level: int, step_id: str, parent, status: str) -> Step:
    fields = {"target_file": "x.py", "operation": "modify_file", "priority": 1} if level == 5 else {}
    return Step(
        uuid=uuid.UUID(step_uuid), plan_uuid=PLAN_UUID, parent_step_uuid=parent,
        level=level, step_id=step_id, slug=step_id.lower(), fields=fields,
        depends_on=[], concepts=[], project_id=None, status=status,
    )


class _DummyPlan:
    uuid = PLAN_UUID
    head_revision_uuid = None


@contextmanager
def _fake_db():
    yield object()


def _tree(atomic_status: str) -> dict[uuid.UUID, Step]:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None, "frozen")
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid, "frozen")
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid, atomic_status)
    return {s.uuid: s for s in (gs, ts, atomic)}


def test_all_illegal_returns_invalid_transition_without_running_gate(monkeypatch) -> None:
    nodes = _tree(atomic_status="in_progress")  # in_progress -> frozen is illegal

    monkeypatch.setattr(step_transition_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_transition_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_transition_command, "load_steps", lambda conn, plan_uuid: nodes)

    def _gate_must_not_run(*args, **kwargs):
        raise AssertionError("gate must not run for an illegal transition")

    monkeypatch.setattr(step_transition_command, "run_gate", _gate_must_not_run)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p", to_status="frozen", step_id="A-001", require_green=True
        )
    )

    payload = result.to_dict()
    assert payload["error"]["data"]["domain_code"] == "INVALID_TRANSITION"
    illegal = payload["error"]["data"]["illegal"]
    assert illegal[0]["from"] == "in_progress"
    assert "legal_targets" in illegal[0]


def test_legal_dry_run_transition_still_reports_transitioned(monkeypatch) -> None:
    gs = _step("00000000-0000-0000-0000-000000000011", 3, "G-001", None, "draft")
    ts = _step("00000000-0000-0000-0000-000000000012", 4, "T-001", gs.uuid, "draft")
    atomic = _step("00000000-0000-0000-0000-000000000013", 5, "A-001", ts.uuid, "draft")
    nodes = {s.uuid: s for s in (gs, ts, atomic)}

    monkeypatch.setattr(step_transition_command, "db_connection", _fake_db)
    monkeypatch.setattr(step_transition_command, "resolve_plan", lambda conn, plan: _DummyPlan())
    monkeypatch.setattr(step_transition_command, "load_steps", lambda conn, plan_uuid: nodes)

    result = asyncio.run(
        StepTransitionCommand().execute(
            plan="p", to_status="ready_for_review", step_id="A-001", dry_run=True
        )
    )

    payload = result.to_dict()
    assert payload["success"] is True
    assert payload["data"]["dry_run"] is True
    assert payload["data"]["transitioned"][0]["to"] == "ready_for_review"


def test_step_transition_is_not_queued() -> None:
    assert StepTransitionCommand.use_queue is False
