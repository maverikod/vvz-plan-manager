"""Command: list the fix attempts recorded for a bug, filtered and paginated (C-024, C-030)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_fix_command_metadata import BASE_PARAMETERS, bug_fix_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    filter_metadata_params,
    filter_schema_properties,
    pagination_metadata_params,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_fix_store import list_bug_fixes
from plan_manager.storage.bug_report_store import get_bug


FILTER_FIELDS = ["status", "unverified_fixes", "created_after", "created_before"]


class BugFixListCommand(Command):
    name: ClassVar[str] = "bug_fix_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List the fix attempts recorded for a bug, filtered and paginated (read-only)."
    category: ClassVar[str] = "fix"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                **BASE_PARAMETERS,
                "bug": {"type": "string", "format": "uuid", "description": "UUID of the BugReport (C-020) whose fix attempts are listed."},
                **filter_schema_properties(FILTER_FIELDS),
                **pagination_schema_properties(),
            },
            "required": ["plan", "bug"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "bug": {"description": "UUID of the BugReport (C-020) whose fix attempts are listed.", "type": "string", "required": True},
            **filter_metadata_params(FILTER_FIELDS),
            **pagination_metadata_params(),
        }
        return bug_fix_metadata(
            cls,
            params,
            {"success": {"description": "A page of BugFix (C-024) payloads for the bug, plus total/limit/offset."}},
            [{"description": "List unverified fix attempts for a bug.", "command": {"plan": "plan_manager", "bug": "11111111-1111-1111-1111-111111111111", "unverified_fixes": True}}],
        )

    async def execute(
        self,
        plan: str,
        bug: str,
        status: str | None = None,
        unverified_fixes: bool | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = uuid.UUID(bug)
                bug_record = get_bug(conn, bug_uuid)
                if bug_record is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug}")
                raw_params = {
                    "status": status,
                    "unverified_fixes": unverified_fixes,
                    "created_after": created_after,
                    "created_before": created_before,
                    "limit": limit,
                    "offset": offset,
                }
                filters = parse_filters(raw_params, FILTER_FIELDS)
                pagination = parse_pagination(raw_params)
                records = list_bug_fixes(conn, bug_uuid=bug_uuid, status=filters.get("status"))
                if filters.get("unverified_fixes"):
                    records = [r for r in records if r.status != "verified"]
                created_after_value = filters.get("created_after")
                if created_after_value is not None:
                    records = [r for r in records if r.created_at > created_after_value]
                created_before_value = filters.get("created_before")
                if created_before_value is not None:
                    records = [r for r in records if r.created_at < created_before_value]
                total = len(records)
                page = records[pagination.offset:pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "bug_fixes": [r.to_payload() for r in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
