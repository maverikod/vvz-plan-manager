"""Tests for the ops_status command (C-002/C-003): version, health, and the
applied schema_migration ledger returned together in one read-only call."""

import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone

from plan_manager.commands import ops_status_command as osc
from plan_manager.commands.inventory import INVENTORY
from plan_manager.commands.registration import check_inventory, register_all


class FakeRegistry:
    def __init__(self) -> None:
        self.commands = {}
        self._command_types = {}

    def register(self, command_class, command_type: str = "custom") -> None:
        self.commands[command_class.name] = command_class
        self._command_types[command_class.name] = command_type

    def get_all_commands(self) -> dict:
        return dict(self.commands)


_BUILD_INFO = {
    "product": "plan_manager",
    "package_version": "0.1.36",
    "adapter_version": "8.10.20",
    "build_date": "2026-07-15",
    "image_tag": "0.1.36",
}


def _detail(state: str) -> dict:
    ready = state == "ready"
    reachable = state in ("ready", "not_ready")
    return {
        "state": state,
        "transport_available": reachable,
        "model_ready": ready,
        "model_status": ("ready" if ready else ("not_initialized" if reachable else None)),
    }


class _FakeCursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def execute(self, query: str) -> None:
        assert "schema_migration" in query
        assert "ORDER BY applied_at DESC" in query

    def fetchall(self) -> list[tuple]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self._rows)


def _fake_db_connection(rows: list[tuple]):
    @contextmanager
    def _factory():
        yield _FakeConnection(rows)
    return _factory


def test_ops_status_metadata_is_complete() -> None:
    required = {
        "name", "version", "description", "category", "author", "email",
        "detailed_description", "parameters", "return_value",
        "usage_examples", "error_cases", "best_practices",
    }
    meta = osc.OpsStatusCommand.metadata()
    assert required <= set(meta)
    assert meta["name"] == "ops_status"
    assert meta["description"] == osc.OpsStatusCommand.descr
    assert osc.OpsStatusCommand.descr.strip()


def test_ops_status_schema_takes_no_parameters() -> None:
    schema = osc.OpsStatusCommand.get_schema()
    assert schema["type"] == "object"
    assert schema["properties"] == {}
    assert schema["required"] == []
    assert schema["additionalProperties"] is False


def test_ops_status_registered_in_normative_inventory() -> None:
    assert "ops_status" in INVENTORY
    registry = FakeRegistry()
    register_all(registry)
    check_inventory(registry)
    assert registry.commands["ops_status"] is osc.OpsStatusCommand


def test_version_health_and_migrations_returned_together(monkeypatch) -> None:
    monkeypatch.setattr(osc, "build_info", lambda: _BUILD_INFO)
    monkeypatch.setattr(osc, "probe_database", lambda: True)
    monkeypatch.setattr(osc, "probe_embedding_detail", lambda: _detail("ready"))
    rows = [
        ("0016_add_metrics_store.sql", datetime(2026, 7, 16, 9, 0, 0, tzinfo=timezone.utc)),
        ("0009_runtime_audit_log.sql", datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)),
    ]
    monkeypatch.setattr(osc, "db_connection", _fake_db_connection(rows))

    result = asyncio.run(osc.OpsStatusCommand().execute())
    data = result.data

    assert data["version"] == {"image_tag": "0.1.36", "build_date": "2026-07-15"}
    assert data["health"]["status"] == "ok"
    assert data["health"]["services"]["database"] == {"required": True, "available": True}
    assert data["health"]["services"]["embedding"]["available"] is True
    assert data["schema_migration"]["count"] == 2
    assert data["schema_migration"]["rows"][0] == {
        "filename": "0016_add_metrics_store.sql",
        "applied_at": "2026-07-16T09:00:00+00:00",
    }
    assert data["schema_migration"]["rows"][1]["filename"] == "0009_runtime_audit_log.sql"


def test_database_unavailable_skips_migration_read_and_reports_error(monkeypatch) -> None:
    monkeypatch.setattr(osc, "build_info", lambda: _BUILD_INFO)
    monkeypatch.setattr(osc, "probe_database", lambda: False)
    monkeypatch.setattr(osc, "probe_embedding_detail", lambda: _detail("unreachable"))

    def _explode():
        raise AssertionError("db_connection must not be called when the database is unavailable")

    monkeypatch.setattr(osc, "db_connection", _explode)

    result = asyncio.run(osc.OpsStatusCommand().execute())
    data = result.data

    assert data["health"]["status"] == "error"
    assert data["health"]["services"]["database"] == {"required": True, "available": False}
    assert data["schema_migration"] == {
        "count": 0,
        "rows": [],
        "note": "database unavailable; schema_migration not read",
    }
