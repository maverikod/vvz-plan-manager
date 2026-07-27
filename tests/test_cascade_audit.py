"""Regression tests for cascade lifecycle audit provenance.

The cascade lifecycle commands previously changed plan state without appending
runtime audit records, leaving no immutable provenance for begin/commit/abort.
These tests pin the audit vocabulary additions and the command-level writes.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone

from plan_manager.cascade.record import CascadeRecord
from plan_manager.commands import (
    cascade_abort_command,
    cascade_begin_command,
    cascade_commit_command,
)
from plan_manager.commands.cascade_abort_command import CascadeAbortCommand
from plan_manager.commands.cascade_begin_command import CascadeBeginCommand
from plan_manager.commands.cascade_commit_command import CascadeCommitCommand
from plan_manager.domain.plan import Plan
from plan_manager.storage import runtime_audit_store


PLAN_UUID = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000bb")
NEW_HEAD_REV = uuid.UUID("00000000-0000-0000-0000-0000000000cc")


@contextmanager
def _fake_db():
    yield object()


def _plan() -> Plan:
    return Plan(
        uuid=PLAN_UUID,
        name="throwaway",
        status="draft",
        context_budget=4000,
        head_revision_uuid=HEAD_REV,
        project_ids=[],
        primary_project_id=None,
    )


def _open_cascade() -> CascadeRecord:
    return CascadeRecord(
        uuid=uuid.uuid4(),
        plan_uuid=PLAN_UUID,
        name="cascade/x",
        base_revision_uuid=HEAD_REV,
        status="open",
        created_at=datetime.now(timezone.utc),
    )


class _AuditRecord:
    def __init__(self) -> None:
        self.audit_uuid = uuid.uuid4()


@dataclass
class _Verdict:
    green: bool = True
    scope: str = "plan"


def test_allowed_actions_gain_cascade_lifecycle_entries() -> None:
    assert "cascade_begin" in runtime_audit_store.ALLOWED_ACTIONS
    assert "cascade_commit" in runtime_audit_store.ALLOWED_ACTIONS
    assert "cascade_abort" in runtime_audit_store.ALLOWED_ACTIONS


def test_cascade_begin_writes_runtime_audit_record(monkeypatch) -> None:
    calls: dict = {}
    rec = _open_cascade()

    monkeypatch.setattr(cascade_begin_command, "db_connection", _fake_db)
    monkeypatch.setattr(cascade_begin_command, "resolve_plan", lambda conn, plan: _plan())
    monkeypatch.setattr(cascade_begin_command, "begin_cascade", lambda conn, plan_uuid: rec)
    monkeypatch.setattr(cascade_begin_command, "get_open_cascade", lambda conn, plan_uuid: rec)

    def _audit(conn, **kwargs):
        calls["audit"] = kwargs
        return _AuditRecord()

    monkeypatch.setattr(cascade_begin_command, "record_runtime_change", _audit)

    payload = asyncio.run(CascadeBeginCommand().execute(plan="p")).to_dict()
    assert payload["success"] is True
    assert calls["audit"]["action"] == "cascade_begin"
    assert calls["audit"]["entity_type"] == "plan"
    assert calls["audit"]["entity_id"] == PLAN_UUID
    assert calls["audit"]["changed_by"] == "api"
    assert calls["audit"]["changed_fields"] == {
        "cascade_uuid": str(rec.uuid),
        "base_revision_uuid": str(rec.base_revision_uuid),
        "ref_name": rec.name,
    }


def test_cascade_commit_writes_runtime_audit_record(monkeypatch) -> None:
    calls: dict = {}
    rec = _open_cascade()
    refreshed = _plan()
    object.__setattr__(refreshed, "head_revision_uuid", NEW_HEAD_REV)
    open_state = {"count": 0}

    monkeypatch.setattr(cascade_commit_command, "db_connection", _fake_db)
    monkeypatch.setattr(cascade_commit_command, "resolve_plan", lambda conn, plan: _plan())

    def _get_open(conn, plan_uuid):
        open_state["count"] += 1
        return rec if open_state["count"] == 1 else None

    monkeypatch.setattr(cascade_commit_command, "get_open_cascade", _get_open)
    monkeypatch.setattr(cascade_commit_command, "commit_cascade", lambda conn, plan_uuid: _Verdict())
    monkeypatch.setattr(cascade_commit_command, "get_plan", lambda conn, plan_uuid: refreshed)

    def _audit(conn, **kwargs):
        calls["audit"] = kwargs
        return _AuditRecord()

    monkeypatch.setattr(cascade_commit_command, "record_runtime_change", _audit)

    payload = asyncio.run(CascadeCommitCommand().execute(plan="p")).to_dict()
    assert payload["success"] is True
    assert calls["audit"]["action"] == "cascade_commit"
    assert calls["audit"]["entity_type"] == "plan"
    assert calls["audit"]["entity_id"] == PLAN_UUID
    assert calls["audit"]["changed_by"] == "api"
    assert calls["audit"]["changed_fields"] == {
        "cascade_uuid": str(rec.uuid),
        "base_revision_uuid": str(rec.base_revision_uuid),
        "head_revision_uuid": str(NEW_HEAD_REV),
    }


def test_cascade_abort_writes_runtime_audit_record(monkeypatch) -> None:
    calls: dict = {}
    rec = _open_cascade()
    open_state = {"count": 0}

    monkeypatch.setattr(cascade_abort_command, "db_connection", _fake_db)
    monkeypatch.setattr(cascade_abort_command, "resolve_plan", lambda conn, plan: _plan())

    def _get_open(conn, plan_uuid):
        open_state["count"] += 1
        return rec if open_state["count"] == 1 else None

    monkeypatch.setattr(cascade_abort_command, "get_open_cascade", _get_open)
    monkeypatch.setattr(cascade_abort_command, "abort_cascade", lambda conn, plan_uuid: None)
    monkeypatch.setattr(cascade_abort_command, "get_plan", lambda conn, plan_uuid: _plan())

    def _audit(conn, **kwargs):
        calls["audit"] = kwargs
        return _AuditRecord()

    monkeypatch.setattr(cascade_abort_command, "record_runtime_change", _audit)

    payload = asyncio.run(CascadeAbortCommand().execute(plan="p")).to_dict()
    assert payload["success"] is True
    assert calls["audit"]["action"] == "cascade_abort"
    assert calls["audit"]["entity_type"] == "plan"
    assert calls["audit"]["entity_id"] == PLAN_UUID
    assert calls["audit"]["changed_by"] == "api"
    assert calls["audit"]["changed_fields"] == {
        "cascade_uuid": str(rec.uuid),
        "base_revision_uuid": str(rec.base_revision_uuid),
        "restored_head_revision_uuid": str(HEAD_REV),
    }
