"""Command: remove an ordered tool reference from a toolset (C-002 uses C-001, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.toolset_command_metadata import toolset_metadata
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.toolset_store import remove_toolset_member


class ToolsetMemberRemoveCommand(Command):
    name: ClassVar[str] = "toolset_member_remove"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Remove (soft-delete) one ordered tool-reference membership from a toolset (C-002 uses C-001)."
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
                "membership_uuid": {"description": "The membership_uuid identifier of the toolset membership to remove.", "type": "string"},
                "changed_by": {"description": "Identity of the actor performing the removal; recorded on the audit trail.", "type": "string"},
            },
            "required": ["membership_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "membership_uuid": {"description": "The membership_uuid identifier of the toolset membership to remove.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor performing the removal; recorded on the audit trail.", "type": "string", "required": True},
        }
        return_value = {"description": "The soft-deleted ToolsetMembership record.", "type": "object"}
        examples = [
            {"description": "Detach a tool from a toolset.", "command": {"membership_uuid": "d8d8d8d8-0000-0000-0000-000000000000", "changed_by": "owner"}},
        ]
        best_practices = [
            "Removal is soft only: the membership row is preserved with a deletion timestamp and hidden from live membership listings; there is no hard-delete mode for memberships.",
            "The removal is recorded on the runtime audit trail under changed_by.",
        ]
        return toolset_metadata(
            cls,
            parameters,
            return_value,
            examples,
            error_cases={
                "TOOLSET_MEMBERSHIP_NOT_FOUND": {
                    "description": "The supplied membership identifier does not resolve to a stored toolset membership record.",
                    "message": "toolset membership not found: {membership_uuid}",
                    "solution": "Confirm the membership_uuid was returned by a prior toolset_member_add call and has not already been removed.",
                },
            },
            best_practices=best_practices,
        )

    async def execute(self, membership_uuid: str, changed_by: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(membership_uuid)
                try:
                    membership = remove_toolset_member(conn, parsed_uuid, changed_by=changed_by)
                except RuntimeValidationError as exc:
                    raise DomainCommandError(
                        "TOOLSET_MEMBERSHIP_NOT_FOUND",
                        f"toolset membership not found: {membership_uuid}",
                    ) from exc
                return SuccessResult(data=membership.to_payload())
        except Exception as exc:
            return map_exception(exc)
