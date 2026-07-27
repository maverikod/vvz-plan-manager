"""Command: list calendar-based work entries with pagination."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.calendar_entry_command_metadata import calendar_entry_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_filtering import (
    filter_metadata_params,
    filter_schema_properties,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)
from plan_manager.commands.runtime_work_command_helpers import resolve_anchor_scope
from plan_manager.domain.calendar_entry import CALENDAR_ENTRY_STATUSES, CalendarEntryStatus
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.calendar_entry_store import list_calendar_entries_page

CALENDAR_ENTRY_FILTER_FIELDS = [
    "project",
    "file",
    "anchor_plan",
    "revision",
    "step",
    "status",
    "owner",
    "assignee",
    "created_after",
    "created_before",
    "active_only",
    "unanchored_only",
]
_PARSE_FILTER_FIELDS = [name for name in CALENDAR_ENTRY_FILTER_FIELDS if name != "anchor_plan"]
_FILTER_ENUMS = {"status": CALENDAR_ENTRY_STATUSES}
_ENUM_OVERRIDES = {"status": [item.value for item in CalendarEntryStatus]}


class CalendarEntryListCommand(Command):
    name: ClassVar[str] = "calendar_entry_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List calendar-based work entries with filtering and pagination."
    category: ClassVar[str] = "calendar_entry"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                **filter_schema_properties(CALENDAR_ENTRY_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
                **pagination_schema_properties(),
                "day_from": {"type": "string", "format": "date", "description": "Lower bound of the requested calendar window (inclusive overlap check)."},
                "day_to": {"type": "string", "format": "date", "description": "Upper bound of the requested calendar window (inclusive overlap check)."},
                "wish": {"type": "string", "format": "uuid", "description": "Optional linked wish UUID to restrict the calendar graph to one desire."},
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **filter_metadata_params(CALENDAR_ENTRY_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
            **pagination_metadata_params(),
            "day_from": {"description": "Lower bound of the requested calendar window (inclusive overlap check).", "type": "string", "required": False},
            "day_to": {"description": "Upper bound of the requested calendar window (inclusive overlap check).", "type": "string", "required": False},
            "wish": {"description": "Optional linked wish UUID to restrict the calendar graph to one desire.", "type": "string", "required": False},
        }
        return calendar_entry_metadata(
            cls,
            params,
            {"success": {"description": "A page of CalendarEntry payloads plus total, limit, and offset."}},
            [{"description": "List planned entries overlapping one week.", "command": {"status": "planned", "day_from": "2026-07-27", "day_to": "2026-08-02", "limit": 20}}],
            best_practices=[
                "day_from/day_to form an overlap window: an entry is returned when its end_date is on or after day_from and its start_date is on or before day_to.",
                "Use the optional wish filter to render the delivery calendar for one specific wish.",
                "Results are ordered by start_date first, then creation time for stable same-day ordering.",
            ],
        )

    async def execute(
        self,
        project: str | None = None,
        file: str | None = None,
        anchor_plan: str | None = None,
        revision: str | None = None,
        step: str | None = None,
        status: str | None = None,
        owner: str | None = None,
        assignee: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        active_only: bool | None = None,
        unanchored_only: bool | None = None,
        limit: int | None = None,
        offset: int | None = None,
        day_from: str | None = None,
        day_to: str | None = None,
        wish: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                raw_params: dict[str, Any] = {
                    "project": project,
                    "file": file,
                    "revision": revision,
                    "step": step,
                    "status": status,
                    "owner": owner,
                    "assignee": assignee,
                    "created_after": created_after,
                    "created_before": created_before,
                    "active_only": active_only,
                    "unanchored_only": unanchored_only,
                }
                filters = parse_filters(raw_params, _PARSE_FILTER_FIELDS, enums=_FILTER_ENUMS)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                scope = resolve_anchor_scope(
                    conn,
                    project=filters.get("project"),
                    anchor_plan=anchor_plan,
                    revision=filters.get("revision"),
                    step=filters.get("step"),
                )
                wish_uuid = validate_uuid(wish) if wish is not None else None
                records, total = list_calendar_entries_page(
                    conn,
                    status=filters.get("status"),
                    anchor_file_path=filters.get("file"),
                    anchor_plan_uuid=scope.anchor_plan_uuid,
                    anchor_revision_uuid=scope.revision_uuid,
                    anchor_step_uuid=scope.step_uuid,
                    owner=filters.get("owner"),
                    assignee=filters.get("assignee"),
                    created_after=filters.get("created_after"),
                    created_before=filters.get("created_before"),
                    active_only=bool(filters.get("active_only")),
                    unanchored_only=bool(filters.get("unanchored_only")),
                    project_id=scope.project_uuid,
                    day_from=day_from,
                    day_to=day_to,
                    wish_uuid=wish_uuid,
                    limit=pagination.limit,
                    offset=pagination.offset,
                )
                return SuccessResult(
                    data={
                        "calendar_entries": [record.to_payload() for record in records],
                        "total": total,
                        "limit": pagination.limit,
                        "offset": pagination.offset,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
