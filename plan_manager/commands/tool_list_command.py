"""Command: list a paginated page of tool instrument records filtered by name (C-001, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.commands.tool_command_metadata import tool_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.tool_store import list_tools


class ToolListCommand(Command):
    name: ClassVar[str] = "tool_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of tool instrument records (C-001) filtered by name."
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
                "name": {"description": "Optional exact tool name to filter by.", "type": "string"},
                "include_deleted": {"description": "Include soft-deleted tools. Defaults to false.", "type": "boolean", "default": False},
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "name": {"description": "Optional exact tool name to filter by.", "type": "string", "required": False},
            "include_deleted": {"description": "Include soft-deleted tools. Defaults to false.", "type": "boolean", "required": False},
        }
        parameters.update(pagination_metadata_params())
        return_value = {
            "description": "An object with a tools key holding a page of Tool records, plus total/limit/offset.",
            "type": "object",
        }
        examples = [
            {"description": "List all active tools.", "command": {}},
        ]
        best_practices = [
            "Filter by name to look up one specific tool by its unique-in-practice name; omit name to list every tool.",
            "include_deleted=true surfaces soft-deleted tools for audit review; the default false hides them.",
            "Results are ordered by created_at ascending.",
            "Compare offset+limit against total to detect additional pages.",
        ]
        return tool_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        name: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                pagination = parse_pagination({"limit": limit, "offset": offset})
                tools = list_tools(conn, name=name, include_deleted=include_deleted)
                total = len(tools)
                page = tools[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "tools": [tool.to_payload() for tool in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
