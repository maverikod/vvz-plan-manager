"""Command: retrieve a single tool instrument record by identifier (C-001, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.tool_command_metadata import tool_metadata
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.tool_store import get_tool


class ToolGetCommand(Command):
    name: ClassVar[str] = "tool_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single tool instrument record (C-001) by its tool identifier."
    category: ClassVar[str] = "tool"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "tool_uuid": {"description": "The tool_uuid identifier of the tool record.", "type": "string"},
            },
            "required": ["tool_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "tool_uuid": {"description": "The tool_uuid identifier of the tool record.", "type": "string", "required": True},
        }
        return_value = {"description": "The Tool record.", "type": "object"}
        examples = [
            {"description": "Fetch a tool by its uuid.", "command": {"tool_uuid": "b6b6b6b6-0000-0000-0000-000000000000"}},
        ]
        best_practices = [
            "Pass the tool_uuid returned by tool_create or tool_list, not a toolset, provider, or model uuid.",
            "get_tool returns soft-deleted records too; check the deleted_at field in the payload to know if a tool is still active.",
            "Use tool_list first when the exact tool_uuid is unknown.",
        ]
        return tool_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(self, tool_uuid: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(tool_uuid)
                tool = get_tool(conn, parsed_uuid)
                if tool is None:
                    raise DomainCommandError("TOOL_NOT_FOUND", f"tool not found: {tool_uuid}")
                return SuccessResult(data=tool.to_payload())
        except Exception as exc:
            return map_exception(exc)
