"""Command: delete a bug report under the universal deletion rule (C-008): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_command_metadata import bug_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_bug_plan_completed
from plan_manager.commands.runtime_delete_command_helpers import perform_runtime_delete
from plan_manager.domain.bug_report import BugReport
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.storage.runtime_hard_delete import hard_delete_bug
from plan_manager.storage.bug_report_store import get_bug, soft_delete_bug


class BugDeleteCommand(Command):
    name: ClassVar[str] = "bug_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a bug report: soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "bug"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for bug_delete."""
        return {
            "type": "object",
            "properties": {
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to delete."},
                "changed_by": {"type": "string", "description": "Identity of the actor performing the deletion; recorded on the audit trail."},
                "hard": {"type": "boolean", "description": "When false (the default), soft-delete: recoverable, hidden from listings. When true, irreversibly remove the row; gated by the inbound-reference integrity check.", "default": False},
                "dry_run": {"type": "boolean", "description": "When true, write nothing: report the deletion target, mode, whether it would be blocked, and the live referencing records as a dict mapping 'table.column' to the count of live referencing rows.", "default": False},
            },
            "required": ["bug_id", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate bug_delete parameters beyond the base schema check: bug_id must parse as a UUID."""
        params = super().validate_params(params)
        bug_id = params.get("bug_id")
        if bug_id is not None:
            validate_uuid(bug_id)
        return params

    async def execute(
        self,
        bug_id: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Delete a bug report (soft by default, hard when hard=true), or preview with dry_run=true."""
        try:
            return perform_runtime_delete(
                raw_entity_id=bug_id,
                changed_by=changed_by,
                hard=hard,
                dry_run=dry_run,
                entity_cls=BugReport,
                get_record=get_bug,
                soft_delete=soft_delete_bug,
                not_found_code="BUG_NOT_FOUND",
                not_found_message=f"bug not found: {bug_id}",
                payload_key="bug",
                entity_label="bug",
                pre_delete=refuse_if_bug_plan_completed,
                hard_delete=hard_delete_bug,
            )
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for bug_delete."""
        params = {
            "bug_id": {"description": "UUID of the bug report to delete.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor performing the deletion; recorded on the audit trail.", "type": "string", "required": True},
            "hard": {"description": "False (default): soft-delete - recoverable, hidden from listings. True: irreversible row removal, gated by the inbound-reference integrity check.", "type": "boolean", "required": False, "default": False},
            "dry_run": {"description": "True: write nothing; report target, mode, blocked flag, and all live referencing records.", "type": "boolean", "required": False, "default": False},
        }
        return bug_metadata(
            cls,
            params,
            {"success": {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references} or deletion result: soft {dry_run, mode, bug} / hard {dry_run, mode, deleted_uuid}."}},
            [
                {"description": "Preview a deletion without writing.", "command": {"bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"bug_id": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the bug exist (anchored comments, duplicate/child bugs, bug impacts, or bug fixes); the universal deletion rule refuses the deletion.",
                    "message": "cannot delete bug {bug_id}: inbound references exist: {references}",
                    "solution": "Inspect details.references (table.column to live count), detach or delete the referrers first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from bug_get/bug_list, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while live blocking referrers exist (anchored comments, duplicate/child bugs, bug impacts, bug fixes) the command refuses with DELETE_BLOCKED and lists every referencing record; detach or delete referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by; verify the outcome with bug_get, which still returns a soft-deleted row with deleted_at set, or NOT_FOUND after a hard delete.",
                "The audit record written by this command is readable via audit_list.",
            ],
        )
