"""Command: delete a calendar-based work entry with the universal deletion contract."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.calendar_entry_command_metadata import calendar_entry_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_delete_command_helpers import (
    delete_command_metadata_params,
    delete_command_schema,
    perform_runtime_delete,
)
from plan_manager.domain.calendar_entry import CalendarEntry
from plan_manager.storage.calendar_entry_store import get_calendar_entry, soft_delete_calendar_entry


class CalendarEntryDeleteCommand(Command):
    name: ClassVar[str] = "calendar_entry_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a calendar-based work entry: soft by default, hard=true available, dry_run previews."
    category: ClassVar[str] = "calendar_entry"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return delete_command_schema("calendar_entry", "Calendar-entry UUID.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return calendar_entry_metadata(
            cls,
            delete_command_metadata_params("calendar_entry", "Calendar-entry UUID."),
            {"success": {"description": "Dry-run preview or soft/hard deletion result."}},
            [{"description": "Preview calendar-entry deletion.", "command": {"calendar_entry": "11111111-1111-1111-1111-111111111111", "changed_by": "owner", "dry_run": True}}],
            include_not_found=True,
            best_practices=[
                "calendar_entry currently has no inbound-reference guards, so dry-run previews are mainly a safety check before hard deletion.",
                "Soft deletion is the default and removes the row from calendar_entry_get and calendar_entry_list while preserving its audit trail.",
            ],
        )

    async def execute(
        self,
        calendar_entry: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_delete(
                raw_entity_id=calendar_entry,
                changed_by=changed_by,
                hard=hard,
                dry_run=dry_run,
                entity_cls=CalendarEntry,
                get_record=get_calendar_entry,
                soft_delete=soft_delete_calendar_entry,
                not_found_code="CALENDAR_ENTRY_NOT_FOUND",
                not_found_message=f"calendar entry not found: {calendar_entry}",
                payload_key="calendar_entry",
            )
        except Exception as exc:
            return map_exception(exc)
