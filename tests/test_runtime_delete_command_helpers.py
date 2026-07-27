"""Unit coverage for the shared runtime delete-command helper."""

from __future__ import annotations

from contextlib import contextmanager
import uuid

from plan_manager.commands import runtime_delete_command_helpers as helpers
from plan_manager.domain.entity import EntityReferencedError


@contextmanager
def _fake_db():
    yield object()


class _FakeRecord:
    def __init__(self, *, plan_uuid: str | None = None) -> None:
        self.plan_uuid = plan_uuid

    def to_payload(self) -> dict[str, str | None]:
        return {"uuid": "record-1", "plan_uuid": self.plan_uuid}


class _FakeEntity:
    hard_deleted: list[uuid.UUID] = []

    @classmethod
    def entity_type(cls) -> str:
        return "fake_entity"

    @classmethod
    def crud_reference_counts(cls, conn, entity_id):  # noqa: ANN001
        return {}

    @classmethod
    def crud_hard_delete(cls, conn, entity_id, **kwargs):  # noqa: ANN001
        cls.hard_deleted.append(entity_id)


class _BlockedFakeEntity(_FakeEntity):
    @classmethod
    def crud_reference_counts(cls, conn, entity_id):  # noqa: ANN001
        return {"other_table.fake_uuid": 2}


def test_perform_runtime_delete_dry_run_returns_preview(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_runtime_delete(
        raw_entity_id="11111111-1111-1111-1111-111111111111",
        changed_by="owner",
        hard=False,
        dry_run=True,
        entity_cls=_BlockedFakeEntity,
        get_record=lambda conn, entity_id: _FakeRecord(),
        soft_delete=lambda conn, entity_id, *, changed_by: _FakeRecord(),
        not_found_code="FAKE_NOT_FOUND",
        not_found_message="missing",
        payload_key="fake_entity",
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {
        "dry_run": True,
        "would_delete": "11111111-1111-1111-1111-111111111111",
        "mode": "soft",
        "blocked": True,
        "references": {"other_table.fake_uuid": 2},
    }


def test_perform_runtime_delete_hard_delete_records_audit(monkeypatch) -> None:
    audit_calls: list[dict[str, object]] = []
    _FakeEntity.hard_deleted = []

    monkeypatch.setattr(helpers, "db_connection", _fake_db)
    monkeypatch.setattr(helpers, "record_runtime_change", lambda conn, **kwargs: audit_calls.append(kwargs))

    result = helpers.perform_runtime_delete(
        raw_entity_id="22222222-2222-2222-2222-222222222222",
        changed_by="owner",
        hard=True,
        dry_run=False,
        entity_cls=_FakeEntity,
        get_record=lambda conn, entity_id: _FakeRecord(plan_uuid="plan-1"),
        soft_delete=lambda conn, entity_id, *, changed_by: _FakeRecord(),
        not_found_code="FAKE_NOT_FOUND",
        not_found_message="missing",
        payload_key="fake_entity",
        audit_plan_uuid=lambda record: record.plan_uuid,
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {
        "dry_run": False,
        "mode": "hard",
        "deleted_uuid": "22222222-2222-2222-2222-222222222222",
    }
    assert _FakeEntity.hard_deleted == [uuid.UUID("22222222-2222-2222-2222-222222222222")]
    assert audit_calls == [
        {
            "plan_uuid": "plan-1",
            "entity_type": "fake_entity",
            "entity_id": uuid.UUID("22222222-2222-2222-2222-222222222222"),
            "action": "hard_delete",
            "changed_by": "owner",
        }
    ]


def test_perform_runtime_delete_live_references_block_non_dry_run(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    try:
        helpers.perform_runtime_delete(
            raw_entity_id="44444444-4444-4444-4444-444444444444",
            changed_by="owner",
            hard=False,
            dry_run=False,
            entity_cls=_BlockedFakeEntity,
            get_record=lambda conn, entity_id: _FakeRecord(),
            soft_delete=lambda conn, entity_id, *, changed_by: _FakeRecord(),
            not_found_code="FAKE_NOT_FOUND",
            not_found_message="missing",
            payload_key="fake_entity",
            entity_label="fake_entity",
        )
        assert False, "expected EntityReferencedError"
    except EntityReferencedError as exc:
        assert exc.entity_type == "fake_entity"
        assert exc.references == {"other_table.fake_uuid": 2}


def test_perform_runtime_delete_uses_custom_hard_delete_and_pre_delete(monkeypatch) -> None:
    hard_delete_calls: list[dict[str, object]] = []
    pre_delete_calls: list[tuple[object, object]] = []

    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_runtime_delete(
        raw_entity_id="55555555-5555-5555-5555-555555555555",
        changed_by="owner",
        hard=True,
        dry_run=False,
        entity_cls=_FakeEntity,
        get_record=lambda conn, entity_id: _FakeRecord(),
        soft_delete=lambda conn, entity_id, *, changed_by: _FakeRecord(),
        not_found_code="FAKE_NOT_FOUND",
        not_found_message="missing",
        payload_key="fake_entity",
        pre_delete=lambda conn, record: pre_delete_calls.append((conn, record)),
        hard_delete=lambda conn, entity_id, *, changed_by: hard_delete_calls.append(
            {"entity_id": entity_id, "changed_by": changed_by}
        ),
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {
        "dry_run": False,
        "mode": "hard",
        "deleted_uuid": "55555555-5555-5555-5555-555555555555",
    }
    assert len(pre_delete_calls) == 1
    assert hard_delete_calls == [
        {
            "entity_id": uuid.UUID("55555555-5555-5555-5555-555555555555"),
            "changed_by": "owner",
        }
    ]


def test_perform_runtime_delete_soft_delete_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_runtime_delete(
        raw_entity_id="33333333-3333-3333-3333-333333333333",
        changed_by="owner",
        hard=False,
        dry_run=False,
        entity_cls=_FakeEntity,
        get_record=lambda conn, entity_id: _FakeRecord(),
        soft_delete=lambda conn, entity_id, *, changed_by: _FakeRecord(),
        not_found_code="FAKE_NOT_FOUND",
        not_found_message="missing",
        payload_key="fake_entity",
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {
        "dry_run": False,
        "mode": "soft",
        "fake_entity": {"uuid": "record-1", "plan_uuid": None},
    }
