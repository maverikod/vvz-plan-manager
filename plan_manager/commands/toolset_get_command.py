"""Command: retrieve a single toolset record by identifier (C-002, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.toolset_command_metadata import toolset_metadata
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.toolset_store import get_toolset


class ToolsetGetCommand(Command):
    name: ClassVar[str] = "toolset_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single toolset record (C-002) by its toolset identifier."
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
                "toolset_uuid": {"description": "The toolset_uuid identifier of the toolset record.", "type": "string"},
            },
            "required": ["toolset_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "toolset_uuid": {"description": "The toolset_uuid identifier of the toolset record.", "type": "string", "required": True},
        }
        return_value = {"description": "The Toolset record.", "type": "object"}
        examples = [
            {"description": "Fetch a toolset by its uuid.", "command": {"toolset_uuid": "c7c7c7c7-0000-0000-0000-000000000000"}},
        ]
        best_practices = [
            "This command returns the Toolset record only, not its tool memberships; use the toolset_member_add / toolset_member_remove commands' returned membership records to track membership.",
            "get_toolset returns soft-deleted records too; check the deleted_at field in the payload to know if a toolset is still active.",
            "Use toolset_list first when the exact toolset_uuid is unknown.",
        ]
        return toolset_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(self, toolset_uuid: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(toolset_uuid)
                toolset = get_toolset(conn, parsed_uuid)
                if toolset is None:
                    raise DomainCommandError("TOOLSET_NOT_FOUND", f"toolset not found: {toolset_uuid}")
                return SuccessResult(data=toolset.to_payload())
        except Exception as exc:
            return map_exception(exc)
