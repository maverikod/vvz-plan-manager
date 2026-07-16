"""Unit tests for CommandTimingStatsCommand (C-004): grouping, percentile computation, and direct/queued split."""

from __future__ import annotations

import asyncio
import uuid
from contextlib import contextmanager

from plan_manager.commands import command_timing_stats_command
from plan_manager.commands.command_timing_stats_command import CommandTimingStatsCommand, _percentile
from plan_manager.storage.command_metrics_store import CommandMetricRecord


def _fake_db():
    @contextmanager
    def _cm():
        yield object()
    return _cm()


def _metric(command_name: str, duration_ms: float, mode: str, outcome: str = "success") -> CommandMetricRecord:
    return CommandMetricRecord(
        metric_uuid=uuid.uuid4(),
        command_name=command_name,
        duration_ms=duration_ms,
        mode=mode,
        outcome=outcome,
        created_at="2026-07-16T00:00:00+00:00",
    )


def test_percentile_single_value_returns_that_value() -> None:
    assert _percentile([42.0], 50.0) == 42.0
    assert _percentile([42.0], 95.0) == 42.0


def test_percentile_linear_interpolation_over_five_values() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _percentile(values, 50.0) == 30.0
    assert _percentile(values, 95.0) == 48.0


def test_execute_groups_by_command_name_sorted_ascending(monkeypatch) -> None:
    metrics = [
        _metric("step_get", 10.0, "direct"),
        _metric("step_get", 20.0, "direct"),
        _metric("step_get", 30.0, "direct"),
        _metric("step_get", 40.0, "direct"),
        _metric("step_get", 50.0, "queued", outcome="error"),
        _metric("bug_list", 100.0, "direct"),
    ]
    monkeypatch.setattr(command_timing_stats_command, "db_connection", _fake_db)
    monkeypatch.setattr(command_timing_stats_command, "list_command_metrics", lambda conn, **kwargs: metrics)

    result = asyncio.run(CommandTimingStatsCommand().execute())
    data = result.to_dict()["data"]

    assert [row["command_name"] for row in data["commands"]] == ["bug_list", "step_get"]
    assert data["total"] == 2


def test_execute_computes_call_count_and_percentiles_per_command(monkeypatch) -> None:
    metrics = [
        _metric("step_get", 10.0, "direct"),
        _metric("step_get", 20.0, "direct"),
        _metric("step_get", 30.0, "direct"),
        _metric("step_get", 40.0, "direct"),
        _metric("step_get", 50.0, "queued", outcome="error"),
    ]
    monkeypatch.setattr(command_timing_stats_command, "db_connection", _fake_db)
    monkeypatch.setattr(command_timing_stats_command, "list_command_metrics", lambda conn, **kwargs: metrics)

    result = asyncio.run(CommandTimingStatsCommand().execute())
    row = result.to_dict()["data"]["commands"][0]

    assert row["command_name"] == "step_get"
    assert row["call_count"] == 5
    assert row["p50_ms"] == 30.0
    assert row["p95_ms"] == 48.0
    assert row["max_ms"] == 50.0
    assert row["direct_count"] == 4
    assert row["queued_count"] == 1


def test_execute_single_call_command_reports_that_duration_for_all_percentiles(monkeypatch) -> None:
    metrics = [_metric("bug_list", 100.0, "direct")]
    monkeypatch.setattr(command_timing_stats_command, "db_connection", _fake_db)
    monkeypatch.setattr(command_timing_stats_command, "list_command_metrics", lambda conn, **kwargs: metrics)

    result = asyncio.run(CommandTimingStatsCommand().execute())
    row = result.to_dict()["data"]["commands"][0]

    assert row["call_count"] == 1
    assert row["p50_ms"] == 100.0
    assert row["p95_ms"] == 100.0
    assert row["max_ms"] == 100.0


def test_execute_passes_command_name_filter_through_to_store(monkeypatch) -> None:
    captured: dict = {}

    def _fake_list_command_metrics(conn, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(command_timing_stats_command, "db_connection", _fake_db)
    monkeypatch.setattr(command_timing_stats_command, "list_command_metrics", _fake_list_command_metrics)

    asyncio.run(CommandTimingStatsCommand().execute(command_name="step_get"))

    assert captured["command_name"] == "step_get"


def test_execute_rejects_invalid_pagination(monkeypatch) -> None:
    monkeypatch.setattr(command_timing_stats_command, "db_connection", _fake_db)
    monkeypatch.setattr(command_timing_stats_command, "list_command_metrics", lambda conn, **kwargs: [])

    result = asyncio.run(CommandTimingStatsCommand().execute(limit=0))
    payload = result.to_dict()

    assert payload["success"] is False
