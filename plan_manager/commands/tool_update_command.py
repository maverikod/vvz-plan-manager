"""Command: patch the mutable fields of an existing tool instrument record (C-001, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.tool_command_metadata import tool_metadata
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.tool_store import get_tool, update_tool


class ToolUpdateCommand(Command):
    name: ClassVar[str] = "tool_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch the mutable fields of an existing tool instrument record (C-001) in place."
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
                "tool_uuid": {"description": "The tool_uuid identifier of the tool record to patch.", "type": "string"},
                "changed_by": {"description": "The actor patching this tool.", "type": "string"},
                "server_id": {"description": "New server reference for the tool.", "type": "string"},
                "command": {"description": "New command name the tool invokes on the server.", "type": "string"},
                "pinned_options": {"description": "New declarative constraint set for the tool.", "type": "object"},
                "description": {"description": "New free-text description for the tool.", "type": "string"},
            },
            "required": ["tool_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "tool_uuid": {"description": "The tool_uuid identifier of the tool record to patch.", "type": "string", "required": True},
            "changed_by": {"description": "The actor patching this tool.", "type": "string", "required": True},
            "server_id": {"description": "New server reference for the tool.", "type": "string", "required": False},
            "command": {"description": "New command name the tool invokes on the server.", "type": "string", "required": False},
            "pinned_options": {"description": "New declarative constraint set for the tool.", "type": "object", "required": False},
            "description": {"description": "New free-text description for the tool.", "type": "string", "required": False},
        }
        return_value = {"description": "The patched Tool record.", "type": "object"}
        examples = [
            {"description": "Patch a tool's pinned options.", "command": {"tool_uuid": "b6b6b6b6-0000-0000-0000-000000000000", "changed_by": "owner", "pinned_options": {"result_limit": 50}}},
        ]
        best_practices = [
            "Only the fields supplied are patched; omitted fields keep their current stored value.",
            "At least one mutable field beyond tool_uuid and changed_by must be supplied, or the call fails with RUNTIME_VALIDATION_ERROR.",
            "name is an immutable identity field and cannot be patched; remove and re-create the tool to change it.",
            "Re-read with tool_get after the call to confirm the patch was applied as expected.",
        ]
        return tool_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        tool_uuid: str,
        changed_by: str,
        server_id: str | None = None,
        command: str | None = None,
        pinned_options: dict[str, Any] | None = None,
        description: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(tool_uuid)
                existing = get_tool(conn, parsed_uuid)
                if existing is None:
                    raise DomainCommandError("TOOL_NOT_FOUND", f"tool not found: {tool_uuid}")
                if all(value is None for value in (server_id, command, pinned_options, description)):
                    raise RuntimeValidationError("tool_update requires at least one mutable field to patch")
                tool = update_tool(
                    conn,
                    parsed_uuid,
                    changed_by=changed_by,
                    server_id=server_id,
                    command=command,
                    pinned_options=pinned_options,
                    description=description,
                )
                return SuccessResult(data=tool.to_payload())
        except Exception as exc:
            return map_exception(exc)
