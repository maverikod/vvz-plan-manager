"""Command: create a new tool instrument record (C-001, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.tool_command_metadata import tool_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.tool_store import create_tool


class ToolCreateCommand(Command):
    name: ClassVar[str] = "tool_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new tool instrument record (C-001): a server reference, a command name, and a pinned option set."
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
                "name": {"description": "Tool name.", "type": "string"},
                "server_id": {"description": "Server reference the tool routes to.", "type": "string"},
                "command": {"description": "Command name the tool invokes on the server.", "type": "string"},
                "pinned_options": {"description": "Declarative constraints fixed at authoring time (for example project id, path prefix, result limits); caller-supplied arguments merge UNDER these at execution time in consuming runtimes.", "type": "object"},
                "created_by": {"description": "Actor creating this tool, recorded on the audit trail.", "type": "string"},
                "description": {"description": "Optional free-text description of the tool.", "type": "string"},
            },
            "required": ["name", "server_id", "command", "pinned_options", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "name": {"description": "Tool name.", "type": "string", "required": True},
            "server_id": {"description": "Server reference the tool routes to.", "type": "string", "required": True},
            "command": {"description": "Command name the tool invokes on the server.", "type": "string", "required": True},
            "pinned_options": {"description": "Declarative constraints fixed at authoring time (for example project id, path prefix, result limits); caller-supplied arguments merge UNDER these at execution time in consuming runtimes.", "type": "object", "required": True},
            "created_by": {"description": "Actor creating this tool, recorded on the audit trail.", "type": "string", "required": True},
            "description": {"description": "Optional free-text description of the tool.", "type": "string", "required": False},
        }
        return_value = {"description": "The created Tool record.", "type": "object"}
        examples = [
            {"description": "Create a tool routing to a code-analysis server command.", "command": {"name": "ca_search", "server_id": "code-analysis-server-vvz", "command": "search", "pinned_options": {"project_id": "4acd4be1-d166-417d-81c6-76bf77b4a392"}, "created_by": "owner"}},
        ]
        best_practices = [
            "pinned_options fixes both call routing and sandbox bounds; caller-supplied arguments merge UNDER pinned_options at execution time in consuming runtimes, not in this command.",
            "Pass a stable server_id that a consuming runtime can resolve; this command does not validate server_id against a live server registry.",
            "Re-read with tool_get after the call to confirm the stored record.",
        ]
        return tool_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        name: str,
        server_id: str,
        command: str,
        pinned_options: dict[str, Any],
        created_by: str,
        description: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                tool = create_tool(
                    conn,
                    name=name,
                    server_id=server_id,
                    command=command,
                    pinned_options=pinned_options,
                    created_by=created_by,
                    description=description,
                )
                return SuccessResult(data=tool.to_payload())
        except Exception as exc:
            return map_exception(exc)
