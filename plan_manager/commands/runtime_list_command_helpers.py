"""Shared helpers for paginated runtime list commands with row projection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from mcp_proxy_adapter.commands.result import SuccessResult

from plan_manager.commands.list_projection import parse_view, project_entities
from plan_manager.commands.runtime_filtering import parse_pagination
from plan_manager.runtime.context import db_connection


def perform_runtime_list_page(
    *,
    fetch_records: Callable[[Any], list[Any]],
    result_key: str,
    row_mapper: Callable[[Any], dict[str, Any]],
    limit: int | None,
    offset: int | None,
    db_connect: Callable[[], Any] | None = None,
) -> SuccessResult:
    """Fetch and paginate one runtime list result page with a custom row mapper."""
    if db_connect is None:
        db_connect = db_connection
    with db_connect() as conn:
        pagination = parse_pagination({"limit": limit, "offset": offset})
        records = fetch_records(conn)
        total = len(records)
        page = records[pagination.offset : pagination.offset + pagination.limit]
        return SuccessResult(
            data={
                result_key: [row_mapper(record) for record in page],
                "total": total,
                "limit": pagination.limit,
                "offset": pagination.offset,
            }
        )


def perform_projected_runtime_list(
    *,
    fetch_records: Callable[[Any], list[Any]],
    result_key: str,
    limit: int | None,
    offset: int | None,
    view: str | None,
    view_default: str = "full",
    db_connect: Callable[[], Any] | None = None,
) -> SuccessResult:
    """Fetch, paginate, and project one runtime list result page."""
    view_value = parse_view(view, default=view_default)
    return perform_runtime_list_page(
        fetch_records=fetch_records,
        result_key=result_key,
        row_mapper=lambda record: project_entities([record], view_value)[0],
        limit=limit,
        offset=offset,
        db_connect=db_connect,
    )
