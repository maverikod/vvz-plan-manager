"""Command: retrieve a single BugReport by identifier (C-020)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_command_metadata import bug_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_report_store import get_bug


class BugGetCommand(Command):
    name: ClassVar[str] = "bug_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single bug report by identifier."
    category: ClassVar[str] = "bug"
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
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to retrieve."},
            },
            "required": ["plan", "bug_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {"type": prop["type"], "description": prop["description"], "required": name in schema["required"]}
            for name, prop in schema["properties"].items()
        }
        return bug_metadata(
            cls,
            params,
            {"type": "object", "description": "The BugReport payload."},
            [{"description": "Retrieve a bug by id.", "command": {"plan": "my-plan", "bug_id": "11111111-1111-1111-1111-111111111111"}}],
            best_practices=[
                "Call bug_list first if you don't already have the bug_id.",
                "bug_get returns a bug regardless of soft-delete status; check the deleted_at field in the payload.",
                "Use the returned status field to decide the next valid lifecycle command to call.",
            ],
        )

    async def execute(self, plan: str, bug_id: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                bug = get_bug(conn, bug_uuid)
                if bug is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
                return SuccessResult(data=bug.to_payload())
        except Exception as exc:
            return map_exception(exc)
