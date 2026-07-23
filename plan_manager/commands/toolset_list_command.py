"""Command: list a paginated page of toolset records filtered by name (C-002, C-015)."""

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
from plan_manager.commands.toolset_command_metadata import toolset_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.toolset_store import list_toolsets


class ToolsetListCommand(Command):
    name: ClassVar[str] = "toolset_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of toolset records (C-002) filtered by name."
    category: ClassVar[str] = "toolset"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {"description": "Optional exact toolset name to filter by.", "type": "string"},
                "include_deleted": {"description": "Include soft-deleted toolsets. Defaults to false.", "type": "boolean", "default": False},
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "name": {"description": "Optional exact toolset name to filter by.", "type": "string", "required": False},
            "include_deleted": {"description": "Include soft-deleted toolsets. Defaults to false.", "type": "boolean", "required": False},
        }
        parameters.update(pagination_metadata_params())
        return_value = {
            "description": "An object with a toolsets key holding a page of Toolset records, plus total/limit/offset.",
            "type": "object",
        }
        examples = [
            {"description": "List all active toolsets.", "command": {}},
        ]
        best_practices = [
            "Filter by name to look up one specific toolset by its unique-in-practice name; omit name to list every toolset.",
            "include_deleted=true surfaces soft-deleted toolsets for audit review; the default false hides them.",
            "Results are ordered by created_at ascending.",
            "Compare offset+limit against total to detect additional pages.",
            "This command lists toolsets only; use toolset_get plus the member commands to inspect one toolset's tool membership.",
        ]
        return toolset_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

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
                toolsets = list_toolsets(conn, name=name, include_deleted=include_deleted)
                total = len(toolsets)
                page = toolsets[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "toolsets": [toolset.to_payload() for toolset in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
