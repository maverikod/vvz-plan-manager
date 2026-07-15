"""RuntimeAuditRecord re-seated on DataclassEntity: identity, boundary mapping, append-only."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from plan_manager.domain.entity import DataclassEntity
from plan_manager.storage import runtime_audit_store
from plan_manager.storage.runtime_audit_store import (
    RuntimeAuditRecord,
    _row_to_record,
    record_runtime_change,
)


def _record() -> RuntimeAuditRecord:
    return RuntimeAuditRecord(
        audit_uuid=uuid.uuid4(),
        plan_uuid=uuid.uuid4(),
        target_type="plan",
        target_id=uuid.uuid4(),
        action="update",
        changed_by="orchestrator",
        change_reason="why",
        changed_fields={"a": 1},
        linked_attempt_id=None,
        linked_review_id=None,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


def test_is_dataclass_entity_subclass() -> None:
    assert issubclass(RuntimeAuditRecord, DataclassEntity)
    assert RuntimeAuditRecord.ENTITY_TYPE == "runtime_audit"
    assert RuntimeAuditRecord.TABLE_NAME == "runtime_audit_log"


def test_base_identity_methods_resolve_without_collision() -> None:
    rec = _record()
    # classmethod from the base, not shadowed by any data field
    assert RuntimeAuditRecord.entity_type() == "runtime_audit"
    # instance method returns THIS record's id (audit_uuid), not the target
    assert rec.entity_id() == rec.audit_uuid
    assert rec.entity_id() != rec.target_id


def test_payload_keeps_external_contract_keys() -> None:
    rec = _record()
    payload = rec.to_payload()
    # outward keys unchanged: entity_type/entity_id map from target_type/target_id
    assert payload["entity_type"] == rec.target_type
    assert payload["entity_id"] == str(rec.target_id)
    assert payload["uuid"] == str(rec.audit_uuid)
    assert "target_type" not in payload and "target_id" not in payload


def test_row_round_trip_preserves_contract() -> None:
    src = _record()
    created = datetime.now(timezone.utc)
    row = (
        src.audit_uuid,
        src.plan_uuid,
        "plan",           # DB column entity_type
        src.target_id,    # DB column entity_id
        "update",
        "orchestrator",
        "why",
        {"a": 1},
        None,
        None,
        created,
    )
    rec = _row_to_record(row)
    assert rec.target_type == "plan"
    assert rec.target_id == src.target_id
    assert rec.to_payload()["entity_type"] == "plan"
    assert rec.to_payload()["entity_id"] == str(src.target_id)


def test_record_runtime_change_writes_unchanged_columns_and_params() -> None:
    captured: dict = {}

    class _Conn:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

    entity_id = uuid.uuid4()
    plan_uuid = uuid.uuid4()
    rec = record_runtime_change(
        _Conn(),
        plan_uuid=plan_uuid,
        entity_type="plan",
        entity_id=entity_id,
        action="update",
        changed_by="orchestrator",
        change_reason="reopen",
        changed_fields={"k": "v"},
    )
    # DB columns unchanged
    assert "(uuid, plan_uuid, entity_type, entity_id, action, changed_by, change_reason" in captured["sql"]
    assert "INSERT INTO runtime_audit_log" in captured["sql"]
    # param positions: entity_type at index 2, entity_id at index 3 (unchanged)
    assert captured["params"][2] == "plan"
    assert captured["params"][3] == entity_id
    # returned record maps into the renamed fields but preserves outward contract
    assert rec.target_type == "plan"
    assert rec.target_id == entity_id
    assert rec.to_payload()["entity_type"] == "plan"
    assert rec.to_payload()["entity_id"] == str(entity_id)


def test_append_only_mutations_refused() -> None:
    # crud_update explicitly forbidden
    with pytest.raises(NotImplementedError):
        RuntimeAuditRecord.crud_update(None, uuid.uuid4(), {"action": "x"})
    # no soft-delete column -> base soft_delete/delete/purge refuse to mutate
    with pytest.raises(NotImplementedError):
        RuntimeAuditRecord.crud_soft_delete(None, uuid.uuid4())
    with pytest.raises(NotImplementedError):
        RuntimeAuditRecord.crud_delete(None, uuid.uuid4())
    with pytest.raises(NotImplementedError):
        RuntimeAuditRecord.crud_purge_soft_deleted_batch(None)


def test_list_runtime_audit_filters_map_to_db_columns() -> None:
    captured: dict = {}

    class _Cur:
        def fetchall(self):
            return []

    class _Conn:
        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params
            return _Cur()

    et_id = uuid.uuid4()
    runtime_audit_store.list_runtime_audit(_Conn(), entity_type="plan", entity_id=et_id)
    # query still filters on the unchanged DB column names
    assert "entity_type = %s" in captured["sql"]
    assert "entity_id = %s" in captured["sql"]
    assert "plan" in captured["params"] and et_id in captured["params"]
