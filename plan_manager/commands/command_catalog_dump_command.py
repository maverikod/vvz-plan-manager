"""Command: dump the complete machine-readable command catalog (C-007), paginated (C-001)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.command_catalog_dump_metadata import get_command_catalog_dump_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.views.command_catalog import build_command_catalog

class CommandCatalogDumpCommand(Command):
    name: ClassVar[str] = "command_catalog_dump"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Return the complete machine-readable command catalog, generated from the live command inventory."
    category: ClassVar[str] = "system"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return get_command_catalog_dump_metadata(cls)

    async def execute(
        self,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            pagination = parse_pagination({"limit": limit, "offset": offset})
            entries = build_command_catalog()
            total = len(entries)
            page = entries[pagination.offset : pagination.offset + pagination.limit]
            return SuccessResult(data={
                "commands": page,
                "total": total,
                "limit": pagination.limit,
                "offset": pagination.offset,
            })
        except Exception as exc:
            return map_exception(exc)
