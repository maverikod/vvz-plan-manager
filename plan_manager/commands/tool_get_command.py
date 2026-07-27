"""Command: retrieve a single tool instrument record by identifier (C-001, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import (
    get_command_metadata_params,
    get_command_schema,
    perform_runtime_get,
)
from plan_manager.commands.tool_command_metadata import tool_metadata
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
        return get_command_schema("tool_uuid", "The tool_uuid identifier of the tool record.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters = get_command_metadata_params("tool_uuid", "The tool_uuid identifier of the tool record.")
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
            return perform_runtime_get(
                raw_entity_id=tool_uuid,
                get_record=get_tool,
                not_found_code="TOOL_NOT_FOUND",
                not_found_message=f"tool not found: {tool_uuid}",
                db_connect=db_connection,
            )
        except Exception as exc:
            return map_exception(exc)
