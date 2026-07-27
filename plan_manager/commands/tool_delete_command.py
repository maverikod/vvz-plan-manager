"""Command: delete a tool instrument record under the universal deletion rule (C-001, C-015): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.runtime_delete_command_helpers import (
    delete_command_metadata_params,
    delete_command_schema,
    perform_runtime_delete,
    validate_delete_uuid_param,
)
from plan_manager.commands.tool_command_metadata import tool_metadata
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.domain.tool import Tool
from plan_manager.storage.tool_store import get_tool, remove_tool


class ToolDeleteCommand(Command):
    name: ClassVar[str] = "tool_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a tool instrument record (C-001): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "tool"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return delete_command_schema("tool_uuid", "The tool_uuid identifier of the tool record to delete.")

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate tool_delete parameters beyond the base schema check: tool_uuid must parse as a UUID."""
        return validate_delete_uuid_param(super().validate_params(params), "tool_uuid")

    async def execute(
        self,
        tool_uuid: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_delete(
                raw_entity_id=tool_uuid,
                changed_by=changed_by,
                hard=hard,
                dry_run=dry_run,
                entity_cls=Tool,
                get_record=get_tool,
                soft_delete=remove_tool,
                not_found_code="TOOL_NOT_FOUND",
                not_found_message=f"tool not found: {tool_uuid}",
                payload_key="tool",
            )
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params: dict[str, Any] = delete_command_metadata_params(
            "tool_uuid", "The tool_uuid identifier of the tool record to delete."
        )
        return tool_metadata(
            cls,
            params,
            {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references} or deletion result: soft {dry_run, mode, tool} / hard {dry_run, mode, deleted_uuid}.", "type": "object"},
            [
                {"description": "Preview a deletion without writing.", "command": {"tool_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"tool_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"tool_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the tool exist (for example toolset memberships); the universal deletion rule refuses the deletion.",
                    "message": "cannot delete tool {tool_uuid}: inbound references exist: {references}",
                    "solution": "Inspect details.references (table.column to live count), detach or delete the referrers first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from tool_list's default view, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while live blocking referrers exist (for example toolset memberships) the command refuses with DELETE_BLOCKED; detach or delete referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by; verify the outcome with tool_get, which still returns a soft-deleted row with deleted_at set, or NOT_FOUND after a hard delete.",
            ],
        )
