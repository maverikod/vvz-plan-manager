"""Command: fetch one calendar-entry work item by UUID."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.calendar_entry_command_metadata import calendar_entry_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import (
    get_command_metadata_params,
    get_command_schema,
    perform_runtime_get,
)
from plan_manager.storage.calendar_entry_store import get_calendar_entry


class CalendarEntryGetCommand(Command):
    name: ClassVar[str] = "calendar_entry_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Fetch one calendar-based work entry by UUID."
    category: ClassVar[str] = "calendar_entry"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return get_command_schema("calendar_entry", "Calendar-entry UUID.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return calendar_entry_metadata(
            cls,
            get_command_metadata_params("calendar_entry", "Calendar-entry UUID."),
            {"success": {"description": "The CalendarEntry payload."}},
            [{"description": "Fetch one calendar entry by UUID.", "command": {"calendar_entry": "11111111-1111-1111-1111-111111111111"}}],
            include_not_found=True,
            best_practices=[
                "calendar_entry_get returns only live rows; a soft-deleted row and a never-existing UUID both become CALENDAR_ENTRY_NOT_FOUND.",
                "Use calendar_entry_list to discover identifiers before direct lookups.",
            ],
        )

    async def execute(self, calendar_entry: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_get(
                raw_entity_id=calendar_entry,
                get_record=get_calendar_entry,
                not_found_code="CALENDAR_ENTRY_NOT_FOUND",
                not_found_message=f"calendar entry not found: {calendar_entry}",
            )
        except Exception as exc:
            return map_exception(exc)
