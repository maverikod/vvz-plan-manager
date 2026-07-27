"""Command: delete a bug fix attempt under the universal deletion rule (C-008): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_fix_command_metadata import bug_fix_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_bug_fix_plan_completed
from plan_manager.commands.runtime_delete_command_helpers import perform_runtime_delete
from plan_manager.domain.bug_fix import BugFix
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.storage.runtime_hard_delete import hard_delete_bug_fix
from plan_manager.storage.bug_fix_store import get_bug_fix, soft_delete_bug_fix


class BugFixDeleteCommand(Command):
    name: ClassVar[str] = "bug_fix_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a bug fix attempt: soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "fix"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for bug_fix_delete."""
        return {
            "type": "object",
            "properties": {
                "bug_fix": {"type": "string", "format": "uuid", "description": "UUID of the BugFix (C-024) fix attempt to delete."},
                "changed_by": {"type": "string", "description": "Identity of the actor performing the deletion; recorded on the audit trail."},
                "hard": {"type": "boolean", "description": "When false (the default), soft-delete: recoverable, hidden from listings. When true, irreversibly remove the row; gated by the inbound-reference integrity check.", "default": False},
                "dry_run": {"type": "boolean", "description": "When true, write nothing: report the deletion target, mode, whether it would be blocked, and the live referencing records as a dict mapping 'table.column' to the count of live referencing rows.", "default": False},
            },
            "required": ["bug_fix", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate bug_fix_delete parameters beyond the base schema check: bug_fix must parse as a UUID."""
        params = super().validate_params(params)
        bug_fix = params.get("bug_fix")
        if bug_fix is not None:
            validate_uuid(bug_fix)
        return params

    async def execute(
        self,
        bug_fix: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Delete a bug fix attempt (soft by default, hard when hard=true), or preview with dry_run=true."""
        try:
            return perform_runtime_delete(
                raw_entity_id=bug_fix,
                changed_by=changed_by,
                hard=hard,
                dry_run=dry_run,
                entity_cls=BugFix,
                get_record=get_bug_fix,
                soft_delete=soft_delete_bug_fix,
                not_found_code="BUG_FIX_NOT_FOUND",
                not_found_message=f"bug fix not found: {bug_fix}",
                payload_key="bug_fix",
                entity_label="bug_fix",
                pre_delete=refuse_if_bug_fix_plan_completed,
                hard_delete=hard_delete_bug_fix,
            )
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for bug_fix_delete."""
        params = {
            "bug_fix": {"description": "UUID of the BugFix (C-024) fix attempt to delete.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor performing the deletion; recorded on the audit trail.", "type": "string", "required": True},
            "hard": {"description": "False (default): soft-delete - recoverable, hidden from listings. True: irreversible row removal, gated by the inbound-reference integrity check.", "type": "boolean", "required": False, "default": False},
            "dry_run": {"description": "True: write nothing; report target, mode, blocked flag, and all live referencing records.", "type": "boolean", "required": False, "default": False},
        }
        return bug_fix_metadata(
            cls,
            params,
            {"success": {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references} or deletion result: soft {dry_run, mode, bug_fix} / hard {dry_run, mode, deleted_uuid}."}},
            [
                {"description": "Preview a deletion without writing.", "command": {"bug_fix": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"bug_fix": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"bug_fix": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the bug fix exist (anchored comments, execution attempts, or bug-fix propagations); the universal deletion rule refuses the deletion.",
                    "message": "cannot delete bug_fix {bug_fix}: inbound references exist: {references}",
                    "solution": "Inspect details.references (table.column to live count), detach or delete the referrers first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from bug_fix_list, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while live blocking referrers exist (anchored comments, execution attempts, bug-fix propagations) the command refuses with DELETE_BLOCKED; detach or delete referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by.",
                "The audit record written by this command is readable via audit_list.",
            ],
        )
