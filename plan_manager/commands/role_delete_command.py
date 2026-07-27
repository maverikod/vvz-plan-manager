"""Command: delete a role record under the universal deletion rule (C-003, C-015): soft by default, guarded hard mode, dry-run preview."""

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
from plan_manager.commands.role_command_metadata import role_metadata
from plan_manager.domain.role import Role
from plan_manager.storage.role_store import get_role, remove_role


class RoleDeleteCommand(Command):
    name: ClassVar[str] = "role_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a role record (C-003): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "role"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return delete_command_schema("role_uuid", "The role_uuid identifier of the role record to delete.")

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate role_delete parameters beyond the base schema check: role_uuid must parse as a UUID."""
        return validate_delete_uuid_param(super().validate_params(params), "role_uuid")

    async def execute(
        self,
        role_uuid: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_delete(
                raw_entity_id=role_uuid,
                changed_by=changed_by,
                hard=hard,
                dry_run=dry_run,
                entity_cls=Role,
                get_record=get_role,
                soft_delete=remove_role,
                not_found_code="ROLE_NOT_FOUND",
                not_found_message=f"role not found: {role_uuid}",
                payload_key="role",
            )
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params: dict[str, Any] = delete_command_metadata_params(
            "role_uuid", "The role_uuid identifier of the role record to delete."
        )
        return role_metadata(
            cls,
            params,
            {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references} or deletion result: soft {dry_run, mode, role} / hard {dry_run, mode, deleted_uuid}.", "type": "object"},
            [
                {"description": "Preview a deletion without writing.", "command": {"role_uuid": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"role_uuid": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"role_uuid": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the role exist (for example a model binding still naming this role); the universal deletion rule refuses the deletion.",
                    "message": "cannot delete role {role_uuid}: inbound references exist: {references}",
                    "solution": "Inspect details.references (table.column to live count), detach or repoint the referrers first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from role_list's default view, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while live blocking referrers exist (for example a model binding still naming this role) the command refuses with DELETE_BLOCKED; detach or repoint referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by; verify the outcome with role_get, which still returns a soft-deleted row with deleted_at set, or NOT_FOUND after a hard delete.",
            ],
        )
