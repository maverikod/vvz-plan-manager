"""Command: add an ordered tool reference to a toolset (C-002 uses C-001, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.toolset_command_metadata import toolset_metadata
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.toolset_store import add_toolset_member, get_toolset


class ToolsetMemberAddCommand(Command):
    name: ClassVar[str] = "toolset_member_add"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Add an ordered tool reference to a toolset (C-002 uses C-001): attaches one tool_uuid at a given position without embedding the Tool record."
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
                "toolset_uuid": {"description": "The toolset_uuid identifier of the toolset to attach the tool to.", "type": "string"},
                "tool_uuid": {"description": "The tool_uuid identifier of the tool to attach; referenced by uuid only, never embedded.", "type": "string"},
                "position": {"description": "The ordinal position of this tool within the toolset's ordered membership.", "type": "integer"},
                "created_by": {"description": "Actor adding this membership, recorded on the audit trail.", "type": "string"},
            },
            "required": ["toolset_uuid", "tool_uuid", "position", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "toolset_uuid": {"description": "The toolset_uuid identifier of the toolset to attach the tool to.", "type": "string", "required": True},
            "tool_uuid": {"description": "The tool_uuid identifier of the tool to attach; referenced by uuid only, never embedded.", "type": "string", "required": True},
            "position": {"description": "The ordinal position of this tool within the toolset's ordered membership.", "type": "integer", "required": True},
            "created_by": {"description": "Actor adding this membership, recorded on the audit trail.", "type": "string", "required": True},
        }
        return_value = {"description": "The created ToolsetMembership record.", "type": "object"}
        examples = [
            {"description": "Attach a tool to a toolset at position 0.", "command": {"toolset_uuid": "c7c7c7c7-0000-0000-0000-000000000000", "tool_uuid": "b6b6b6b6-0000-0000-0000-000000000000", "position": 0, "created_by": "owner"}},
        ]
        best_practices = [
            "position is caller-assigned; this command does not auto-increment it - read the toolset's current memberships first to choose the next free position.",
            "A membership is soft by default; use toolset_member_remove to detach a tool.",
            "The (toolset_uuid, tool_uuid) pair is unique among live memberships; a duplicate attach raises DUPLICATE_ID.",
        ]
        return toolset_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        toolset_uuid: str,
        tool_uuid: str,
        position: int,
        created_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_toolset_uuid = validate_uuid(toolset_uuid)
                parsed_tool_uuid = validate_uuid(tool_uuid)
                toolset = get_toolset(conn, parsed_toolset_uuid)
                if toolset is None:
                    raise DomainCommandError("TOOLSET_NOT_FOUND", f"toolset not found: {toolset_uuid}")
                membership = add_toolset_member(
                    conn,
                    toolset_uuid=parsed_toolset_uuid,
                    tool_uuid=parsed_tool_uuid,
                    position=position,
                    created_by=created_by,
                )
                return SuccessResult(data=membership.to_payload())
        except Exception as exc:
            return map_exception(exc)
