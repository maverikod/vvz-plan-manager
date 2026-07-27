"""Command: delete an invocation profile record under the universal deletion rule (C-008, C-015): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.invocation_profile_command_metadata import invocation_profile_metadata
from plan_manager.commands.runtime_delete_command_helpers import (
    delete_command_metadata_params,
    delete_command_schema,
    perform_runtime_delete,
    validate_delete_uuid_param,
)
from plan_manager.domain.invocation_profile import InvocationProfile
from plan_manager.storage.invocation_profile_store import get_invocation_profile, remove_invocation_profile


class InvocationProfileDeleteCommand(Command):
    name: ClassVar[str] = "invocation_profile_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete an invocation profile record (C-008): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "invocation_profile"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return delete_command_schema(
            "profile_uuid", "The profile_uuid identifier of the invocation_profile record to delete."
        )

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate invocation_profile_delete parameters beyond the base schema check: profile_uuid must parse as a UUID."""
        return validate_delete_uuid_param(super().validate_params(params), "profile_uuid")

    async def execute(
        self,
        profile_uuid: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_delete(
                raw_entity_id=profile_uuid,
                changed_by=changed_by,
                hard=hard,
                dry_run=dry_run,
                entity_cls=InvocationProfile,
                get_record=get_invocation_profile,
                soft_delete=remove_invocation_profile,
                not_found_code="INVOCATION_PROFILE_NOT_FOUND",
                not_found_message=f"invocation profile not found: {profile_uuid}",
                payload_key="invocation_profile",
                audit_plan_uuid=lambda record: record.plan_uuid,
            )
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params: dict[str, Any] = delete_command_metadata_params(
            "profile_uuid", "The profile_uuid identifier of the invocation_profile record to delete."
        )
        return invocation_profile_metadata(
            cls,
            params,
            {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references} or deletion result: soft {dry_run, mode, invocation_profile} / hard {dry_run, mode, deleted_uuid}.", "type": "object"},
            [
                {"description": "Preview a deletion without writing.", "command": {"profile_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"profile_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"profile_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the invocation profile exist; the universal deletion rule refuses the hard deletion.",
                    "message": "cannot delete invocation profile {profile_uuid}: inbound references exist: {references}",
                    "solution": "Inspect details.references (table.column to live count), detach or delete the referrers first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from invocation_profile_list's default view, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while live blocking referrers exist the hard-delete path refuses with DELETE_BLOCKED; detach or delete referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by, anchored to the profile's own plan_uuid (invocation profiles are scope-attached, unlike plan-independent core entities); verify the outcome with invocation_profile_get, which still returns a soft-deleted row with deleted_at set, or INVOCATION_PROFILE_NOT_FOUND after a hard delete.",
            ],
        )
