"""Command: read-only per-command timing aggregate (C-004), summarizing the append-only command_metric store written by the registration timing hook (C-005)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.command_timing_stats_metadata import get_command_timing_stats_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_filtering import (
    filter_schema_properties,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.storage.command_metrics_store import list_command_metrics

_WINDOW_FILTER_FIELDS = ["created_after", "created_before"]


def _percentile(sorted_values: list[float], percentile: float) -> float:
    """Return the linear-interpolation percentile of a non-empty ascending-sorted list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = percentile / 100.0 * (len(sorted_values) - 1)
    lower_index = int(rank)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    fraction = rank - lower_index
    return sorted_values[lower_index] + (sorted_values[upper_index] - sorted_values[lower_index]) * fraction


class CommandTimingStatsCommand(Command):
    name: ClassVar[str] = "command_timing_stats"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Return per-command call counts and p50/p95/max latency percentiles from the command timing metrics store."
    category: ClassVar[str] = "observability"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command_name": {"type": "string", "description": "Exact command name to filter the metrics store by. Omit to aggregate over every recorded command."},
                **filter_schema_properties(_WINDOW_FILTER_FIELDS),
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_command_timing_stats_metadata(cls)

    async def execute(
        self,
        command_name: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            raw_params = {"created_after": created_after, "created_before": created_before, "limit": limit, "offset": offset}
            filters = parse_filters(raw_params, _WINDOW_FILTER_FIELDS)
            pagination = parse_pagination(raw_params)
            with db_connection() as conn:
                metrics = list_command_metrics(
                    conn,
                    command_name=command_name,
                    created_after=filters.get("created_after"),
                    created_before=filters.get("created_before"),
                )
            grouped: dict[str, list[Any]] = {}
            for metric in metrics:
                grouped.setdefault(metric.command_name, []).append(metric)
            rows = []
            for name in sorted(grouped):
                records = grouped[name]
                durations = sorted(record.duration_ms for record in records)
                rows.append({
                    "command_name": name,
                    "call_count": len(records),
                    "p50_ms": _percentile(durations, 50.0),
                    "p95_ms": _percentile(durations, 95.0),
                    "max_ms": durations[-1],
                    "direct_count": sum(1 for record in records if record.mode == "direct"),
                    "queued_count": sum(1 for record in records if record.mode == "queued"),
                })
            total = len(rows)
            page = rows[pagination.offset : pagination.offset + pagination.limit]
            return SuccessResult(data={"commands": page, "total": total, "limit": pagination.limit, "offset": pagination.offset})
        except Exception as exc:
            return map_exception(exc)
