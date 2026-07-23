"""Command: create a new toolset record (C-002, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.toolset_command_metadata import toolset_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.toolset_store import create_toolset


class ToolsetCreateCommand(Command):
    name: ClassVar[str] = "toolset_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new toolset record (C-002): a named, ordered set of tool references describing the equipment list of one kind of work."
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
                "name": {"description": "Toolset name.", "type": "string"},
                "created_by": {"description": "Actor creating this toolset, recorded on the audit trail.", "type": "string"},
                "description": {"description": "Optional free-text description of the toolset.", "type": "string"},
            },
            "required": ["name", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "name": {"description": "Toolset name.", "type": "string", "required": True},
            "created_by": {"description": "Actor creating this toolset, recorded on the audit trail.", "type": "string", "required": True},
            "description": {"description": "Optional free-text description of the toolset.", "type": "string", "required": False},
        }
        return_value = {"description": "The created Toolset record.", "type": "object"}
        examples = [
            {"description": "Create a toolset for the code-writer role.", "command": {"name": "code-writer", "created_by": "owner", "description": "File open, preview, edit, write, and per-file verification commands."}},
        ]
        best_practices = [
            "A toolset references tool entities only via ordered membership rows; it never embeds tool definitions inline - use toolset_member_add to attach tools after creation.",
            "Re-read with toolset_get after the call to confirm the stored record.",
        ]
        return toolset_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        name: str,
        created_by: str,
        description: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                toolset = create_toolset(
                    conn,
                    name=name,
                    created_by=created_by,
                    description=description,
                )
                return SuccessResult(data=toolset.to_payload())
        except Exception as exc:
            return map_exception(exc)
