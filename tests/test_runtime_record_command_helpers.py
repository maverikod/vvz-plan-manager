"""Unit coverage for runtime record get/update helpers and guarded-update hooks."""

from __future__ import annotations

from contextlib import contextmanager

from plan_manager.commands import runtime_record_command_helpers as helpers
from plan_manager.commands.errors import DomainCommandError


@contextmanager
def _fake_db():
    yield object()


class _FakeRecord:
    def __init__(self, payload: dict[str, object] | None = None, **attrs: object) -> None:
        self._payload = payload or {"uuid": "record-1"}
        for key, value in attrs.items():
            setattr(self, key, value)

    def to_payload(self) -> dict[str, object]:
        return dict(self._payload)


def test_perform_runtime_get_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_runtime_get(
        raw_entity_id="11111111-1111-1111-1111-111111111111",
        get_record=lambda conn, entity_id: _FakeRecord({"uuid": str(entity_id), "status": "ok"}),
        not_found_code="FAKE_NOT_FOUND",
        not_found_message="missing",
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["status"] == "ok"


def test_perform_runtime_create_returns_payload(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_runtime_create(
        create_record=lambda conn, **kwargs: _FakeRecord({"uuid": "created-1", "name": kwargs["name"]}),
        create_fields={"name": "tool-a"},
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {"uuid": "created-1", "name": "tool-a"}


def test_perform_runtime_create_supports_prepare_fields(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)
    calls: list[object] = []

    result = helpers.perform_runtime_create(
        create_record=lambda conn, **kwargs: _FakeRecord({"uuid": "created-2", "name": kwargs["name"]}),
        prepare_create_fields=lambda conn: calls.append("prepare") or {"name": "tool-b"},
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {"uuid": "created-2", "name": "tool-b"}
    assert calls == ["prepare"]


def test_perform_guarded_runtime_update_runs_hooks_in_order(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)
    calls: list[object] = []
    existing = _FakeRecord(status="pending", bug_fix_uuid="fix-1")

    def _get_record(conn, entity_id):
        calls.append("get")
        return existing

    def _resolve_scope(conn):
        calls.append("resolve")

    def _pre_update(conn, record, update_fields):
        calls.append(("pre", record.status, update_fields["status"]))

    def _before_store(conn, entity_id, record, update_fields):
        calls.append(("before", str(entity_id), update_fields["status"]))

    def _update_record(conn, entity_id, *, changed_by, **update_fields):
        calls.append(("update", changed_by, update_fields["status"]))
        return _FakeRecord({"uuid": str(entity_id), "status": update_fields["status"]})

    def _post_update(conn, entity_id, record, updated, update_fields):
        calls.append(("post", updated.to_payload()["status"]))

    result = helpers.perform_guarded_runtime_update(
        raw_entity_id="22222222-2222-2222-2222-222222222222",
        get_record=_get_record,
        update_record=_update_record,
        changed_by="owner",
        not_found_code="FAKE_NOT_FOUND",
        not_found_message="missing",
        update_fields={"status": "done"},
        resolve_scope=_resolve_scope,
        pre_update=_pre_update,
        before_store_update=_before_store,
        post_update=_post_update,
    ).to_dict()

    assert result["success"] is True
    assert result["data"]["status"] == "done"
    assert calls == [
        "resolve",
        "get",
        ("pre", "pending", "done"),
        ("before", "22222222-2222-2222-2222-222222222222", "done"),
        ("update", "owner", "done"),
        ("post", "done"),
    ]


def test_perform_guarded_runtime_update_supports_custom_result_shape(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    result = helpers.perform_guarded_runtime_update(
        raw_entity_id="44444444-4444-4444-4444-444444444444",
        get_record=lambda conn, entity_id: _FakeRecord(status="pending"),
        update_record=lambda conn, entity_id, *, changed_by, **update_fields: _FakeRecord(
            {"uuid": str(entity_id), "status": update_fields["status"]}
        ),
        changed_by="owner",
        not_found_code="FAKE_NOT_FOUND",
        not_found_message="missing",
        update_fields={"status": "done"},
        build_result_data=lambda record: {"wrapped": record.to_payload()},
    ).to_dict()

    assert result["success"] is True
    assert result["data"] == {
        "wrapped": {
            "uuid": "44444444-4444-4444-4444-444444444444",
            "status": "done",
        }
    }


def test_perform_guarded_runtime_update_raises_not_found(monkeypatch) -> None:
    monkeypatch.setattr(helpers, "db_connection", _fake_db)

    try:
        helpers.perform_guarded_runtime_update(
            raw_entity_id="33333333-3333-3333-3333-333333333333",
            get_record=lambda conn, entity_id: None,
            update_record=lambda conn, entity_id, *, changed_by, **update_fields: _FakeRecord(),
            changed_by="owner",
            not_found_code="TODO_NOT_FOUND",
            not_found_message="missing",
            update_fields={},
        )
        assert False, "expected DomainCommandError"
    except DomainCommandError as exc:
        assert exc.code == "TODO_NOT_FOUND"
