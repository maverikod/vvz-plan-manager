"""Behavioral tests for the audit_list command (C-009, C-010, C-011): filter pass-through, envelope shape, and rejection behavior. No accompanying test coverage was authored by the sibling branch that implements this command, so this test binds directly to it."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import audit_list_command
from plan_manager.commands.audit_list_command import AuditListCommand
from plan_manager.storage.runtime_audit_store import RuntimeAuditRecord


def _fake_db():
    @contextmanager
    def _cm():
        yield object()
    return _cm()


def _record() -> RuntimeAuditRecord:
    return RuntimeAuditRecord(
        audit_uuid=uuid.uuid4(),
        plan_uuid=None,
        target_type="step",
        target_id=uuid.uuid4(),
        action="update",
        changed_by="tester",
        change_reason=None,
        changed_fields=None,
        linked_attempt_id=None,
        linked_review_id=None,
        created_at="2026-07-16T00:00:00+00:00",
    )


def test_execute_passes_actor_action_entity_and_plan_filters_through(monkeypatch) -> None:
    captured_list: dict = {}
    captured_count: dict = {}
    plan_uuid = uuid.uuid4()
    entity_uuid = uuid.uuid4()

    def _fake_list(conn, **kwargs):
        captured_list.update(kwargs)
        return []

    def _fake_count(conn, **kwargs):
        captured_count.update(kwargs)
        return 0

    monkeypatch.setattr(audit_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(audit_list_command, "list_runtime_audit", _fake_list)
    monkeypatch.setattr(audit_list_command, "count_runtime_audit", _fake_count)

    asyncio.run(
        AuditListCommand().execute(
            actor="tester",
            action="update",
            entity_type="step",
            entity_id=str(entity_uuid),
            plan=str(plan_uuid),
            created_after="2026-01-01T00:00:00+00:00",
            created_before="2026-12-31T00:00:00+00:00",
        )
    )

    assert captured_list["changed_by"] == "tester"
    assert captured_list["action"] == "update"
    assert captured_list["entity_type"] == "step"
    assert captured_list["entity_id"] == entity_uuid
    assert captured_list["plan_uuid"] == plan_uuid
    assert captured_list["created_after"] == "2026-01-01T00:00:00+00:00"
    assert captured_list["created_before"] == "2026-12-31T00:00:00+00:00"
    assert captured_count["changed_by"] == "tester"
    assert captured_count["plan_uuid"] == plan_uuid


def test_execute_returns_uniform_items_total_limit_offset_envelope(monkeypatch) -> None:
    record = _record()
    monkeypatch.setattr(audit_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(audit_list_command, "list_runtime_audit", lambda conn, **kwargs: [record])
    monkeypatch.setattr(audit_list_command, "count_runtime_audit", lambda conn, **kwargs: 1)

    result = asyncio.run(AuditListCommand().execute(limit=50, offset=0))
    payload = result.to_dict()

    assert payload["success"] is True
    data = payload["data"]
    assert set(data.keys()) == {"items", "total", "limit", "offset"}
    assert data["total"] == 1
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["items"][0]["uuid"] == str(record.audit_uuid)
    assert data["items"][0]["action"] == "update"


def test_execute_rejects_out_of_vocabulary_action(monkeypatch) -> None:
    monkeypatch.setattr(audit_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(audit_list_command, "list_runtime_audit", lambda conn, **kwargs: [])
    monkeypatch.setattr(audit_list_command, "count_runtime_audit", lambda conn, **kwargs: 0)

    result = asyncio.run(AuditListCommand().execute(action="not_a_real_action"))
    payload = result.to_dict()

    assert payload["success"] is False


def test_execute_rejects_out_of_range_pagination(monkeypatch) -> None:
    monkeypatch.setattr(audit_list_command, "db_connection", _fake_db)
    monkeypatch.setattr(audit_list_command, "list_runtime_audit", lambda conn, **kwargs: [])
    monkeypatch.setattr(audit_list_command, "count_runtime_audit", lambda conn, **kwargs: 0)

    result = asyncio.run(AuditListCommand().execute(limit=0))
    payload = result.to_dict()

    assert payload["success"] is False
