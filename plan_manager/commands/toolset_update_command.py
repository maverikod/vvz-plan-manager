"""Command: patch the mutable fields of an existing toolset record (C-002, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.toolset_command_metadata import toolset_metadata
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.toolset_store import get_toolset, update_toolset


class ToolsetUpdateCommand(Command):
    name: ClassVar[str] = "toolset_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch the mutable fields of an existing toolset record (C-002) in place."
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
                "toolset_uuid": {"description": "The toolset_uuid identifier of the toolset record to patch.", "type": "string"},
                "changed_by": {"description": "The actor patching this toolset.", "type": "string"},
                "description": {"description": "New free-text description for the toolset.", "type": "string"},
            },
            "required": ["toolset_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "toolset_uuid": {"description": "The toolset_uuid identifier of the toolset record to patch.", "type": "string", "required": True},
            "changed_by": {"description": "The actor patching this toolset.", "type": "string", "required": True},
            "description": {"description": "New free-text description for the toolset.", "type": "string", "required": False},
        }
        return_value = {"description": "The patched Toolset record.", "type": "object"}
        examples = [
            {"description": "Patch a toolset's description.", "command": {"toolset_uuid": "c7c7c7c7-0000-0000-0000-000000000000", "changed_by": "owner", "description": "Updated equipment list for the code-writer role."}},
        ]
        best_practices = [
            "Only description is patchable; name is an immutable identity field and cannot be patched - remove and re-create the toolset to change it.",
            "description must be supplied, or the call fails with RUNTIME_VALIDATION_ERROR.",
            "To change which tools a toolset carries, use toolset_member_add / toolset_member_remove; this command never touches membership rows.",
            "Re-read with toolset_get after the call to confirm the patch was applied as expected.",
        ]
        return toolset_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        toolset_uuid: str,
        changed_by: str,
        description: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(toolset_uuid)
                existing = get_toolset(conn, parsed_uuid)
                if existing is None:
                    raise DomainCommandError("TOOLSET_NOT_FOUND", f"toolset not found: {toolset_uuid}")
                if description is None:
                    raise RuntimeValidationError("toolset_update requires at least one mutable field to patch")
                toolset = update_toolset(
                    conn,
                    parsed_uuid,
                    changed_by=changed_by,
                    description=description,
                )
                return SuccessResult(data=toolset.to_payload())
        except Exception as exc:
            return map_exception(exc)
