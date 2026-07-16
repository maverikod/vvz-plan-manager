"""Tests for CommandTimingCollection (C-005): the command_metric store and the registration.py timing hook."""

from __future__ import annotations

import asyncio
import uuid

import pytest

from plan_manager.commands import registration
from plan_manager.storage import command_metrics_store
from plan_manager.storage.command_metrics_store import (
    CommandMetricRecord,
    record_command_metric,
)


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, sql, params):
        self.calls.append((sql, params))
        return self

    def fetchall(self):
        return []


def test_record_command_metric_writes_expected_sql_and_params() -> None:
    conn = _Conn()
    record = record_command_metric(
        conn,
        command_name="step_get",
        duration_ms=12.5,
        mode="direct",
        outcome="success",
    )
    assert len(conn.calls) == 1
    sql, params = conn.calls[0]
    assert "INSERT INTO command_metric" in sql
    assert "(uuid, command_name, duration_ms, mode, outcome, created_at)" in sql
    assert params[1] == "step_get"
    assert params[2] == 12.5
    assert params[3] == "direct"
    assert params[4] == "success"
    assert record.command_name == "step_get"
    assert record.mode == "direct"
    assert record.outcome == "success"


def test_record_command_metric_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError):
        record_command_metric(
            _Conn(), command_name="x", duration_ms=1.0, mode="bogus", outcome="success"
        )


def test_record_command_metric_rejects_invalid_outcome() -> None:
    with pytest.raises(ValueError):
        record_command_metric(
            _Conn(), command_name="x", duration_ms=1.0, mode="direct", outcome="bogus"
        )


def test_list_command_metrics_filters_map_to_db_columns() -> None:
    conn = _Conn()
    command_metrics_store.list_command_metrics(
        conn, command_name="step_get", created_after="2026-01-01T00:00:00+00:00"
    )
    sql, params = conn.calls[0]
    assert "command_name = %s" in sql
    assert "created_at >= %s" in sql
    assert "step_get" in params
    assert "2026-01-01T00:00:00+00:00" in params


def test_command_metric_record_is_append_only() -> None:
    with pytest.raises(NotImplementedError):
        CommandMetricRecord.crud_update(None, uuid.uuid4(), {"outcome": "error"})


class _FakeSuccessCommand:
    use_queue = False

    async def execute(self, **kwargs):
        from mcp_proxy_adapter.commands.result import SuccessResult

        return SuccessResult(data={"ok": True})


class _FakeErrorCommand:
    use_queue = True

    async def execute(self, **kwargs):
        from mcp_proxy_adapter.commands.result import ErrorResult

        return ErrorResult(message="boom")


class _FakeRaisingCommand:
    use_queue = False

    async def execute(self, **kwargs):
        raise RuntimeError("real failure")


def test_timing_hook_records_exactly_one_metric_on_success(monkeypatch) -> None:
    recorded: list[dict] = []

    class _FakeConn:
        pass

    class _FakeCtx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, *exc_info):
            return False

    def _fake_db_connection():
        return _FakeCtx()

    def _fake_record_command_metric(conn, *, command_name, duration_ms, mode, outcome):
        recorded.append({"command_name": command_name, "mode": mode, "outcome": outcome})

    monkeypatch.setattr(registration, "db_connection", _fake_db_connection)
    monkeypatch.setattr(registration, "record_command_metric", _fake_record_command_metric)

    registration._wrap_execute_with_timing(_FakeSuccessCommand, "fake_success")
    result = asyncio.run(_FakeSuccessCommand().execute())

    assert result.data == {"ok": True}
    assert len(recorded) == 1
    assert recorded[0] == {"command_name": "fake_success", "mode": "direct", "outcome": "success"}


def test_timing_hook_tags_queued_mode_and_error_outcome(monkeypatch) -> None:
    recorded: list[dict] = []

    class _FakeConn:
        pass

    class _FakeCtx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, *exc_info):
            return False

    def _fake_db_connection():
        return _FakeCtx()

    def _fake_record_command_metric(conn, *, command_name, duration_ms, mode, outcome):
        recorded.append({"command_name": command_name, "mode": mode, "outcome": outcome})

    monkeypatch.setattr(registration, "db_connection", _fake_db_connection)
    monkeypatch.setattr(registration, "record_command_metric", _fake_record_command_metric)

    registration._wrap_execute_with_timing(_FakeErrorCommand, "fake_error")
    result = asyncio.run(_FakeErrorCommand().execute())

    assert result.message == "boom"
    assert len(recorded) == 1
    assert recorded[0] == {"command_name": "fake_error", "mode": "queued", "outcome": "error"}


def test_timing_hook_metric_write_failure_never_breaks_real_command(monkeypatch) -> None:
    def _raising_db_connection():
        raise RuntimeError("db unreachable")

    monkeypatch.setattr(registration, "db_connection", _raising_db_connection)

    registration._wrap_execute_with_timing(_FakeSuccessCommand, "fake_resilient")
    result = asyncio.run(_FakeSuccessCommand().execute())

    assert result.data == {"ok": True}


def test_timing_hook_preserves_raised_exception_and_still_records(monkeypatch) -> None:
    recorded: list[dict] = []

    class _FakeConn:
        pass

    class _FakeCtx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, *exc_info):
            return False

    def _fake_db_connection():
        return _FakeCtx()

    def _fake_record_command_metric(conn, *, command_name, duration_ms, mode, outcome):
        recorded.append({"command_name": command_name, "mode": mode, "outcome": outcome})

    monkeypatch.setattr(registration, "db_connection", _fake_db_connection)
    monkeypatch.setattr(registration, "record_command_metric", _fake_record_command_metric)

    registration._wrap_execute_with_timing(_FakeRaisingCommand, "fake_raising")
    with pytest.raises(RuntimeError, match="real failure"):
        asyncio.run(_FakeRaisingCommand().execute())

    assert len(recorded) == 1
    assert recorded[0] == {"command_name": "fake_raising", "mode": "direct", "outcome": "error"}


def test_timing_hook_is_idempotent_across_repeated_wrap_calls(monkeypatch) -> None:
    calls = {"count": 0}

    class _FakeConn:
        pass

    class _FakeCtx:
        def __enter__(self):
            return _FakeConn()

        def __exit__(self, *exc_info):
            return False

    def _fake_db_connection():
        return _FakeCtx()

    def _fake_record_command_metric(conn, *, command_name, duration_ms, mode, outcome):
        calls["count"] += 1

    monkeypatch.setattr(registration, "db_connection", _fake_db_connection)
    monkeypatch.setattr(registration, "record_command_metric", _fake_record_command_metric)

    class _FakeIdempotentCommand:
        use_queue = False

        async def execute(self, **kwargs):
            from mcp_proxy_adapter.commands.result import SuccessResult

            return SuccessResult(data={"ok": True})

    registration._wrap_execute_with_timing(_FakeIdempotentCommand, "fake_idempotent")
    registration._wrap_execute_with_timing(_FakeIdempotentCommand, "fake_idempotent")
    asyncio.run(_FakeIdempotentCommand().execute())

    assert calls["count"] == 1
