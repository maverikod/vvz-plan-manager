"""Command: delete a bug impact record under the universal deletion rule (C-008): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_impact_command_metadata import bug_impact_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_bug_impact_plan_completed
from plan_manager.domain.entity import EntityReferencedError
from plan_manager.domain.bug_impact import BugImpact
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_hard_delete import hard_delete_bug_impact
from plan_manager.storage.bug_impact_store import get_bug_impact, soft_delete_bug_impact


class BugImpactDeleteCommand(Command):
    name: ClassVar[str] = "bug_impact_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a bug impact record: soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "impact"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for bug_impact_delete."""
        return {
            "type": "object",
            "properties": {
                "impact_uuid": {"type": "string", "format": "uuid", "description": "UUID of the bug_impact record to delete."},
                "changed_by": {"type": "string", "description": "Identity of the actor performing the deletion; recorded on the audit trail."},
                "hard": {"type": "boolean", "description": "When false (the default), soft-delete: recoverable, hidden from listings. When true, irreversibly remove the row; gated by the inbound-reference integrity check.", "default": False},
                "dry_run": {"type": "boolean", "description": "When true, write nothing: report the deletion target, mode, whether it would be blocked, and the live referencing records as a dict mapping 'table.column' to the count of live referencing rows.", "default": False},
            },
            "required": ["impact_uuid", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate bug_impact_delete parameters beyond the base schema check: impact_uuid must parse as a UUID."""
        params = super().validate_params(params)
        impact_uuid = params.get("impact_uuid")
        if impact_uuid is not None:
            validate_uuid(impact_uuid)
        return params

    async def execute(
        self,
        impact_uuid: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Delete a bug impact record (soft by default, hard when hard=true), or preview with dry_run=true."""
        try:
            with db_connection() as conn:
                impact_id = validate_uuid(impact_uuid)
                record = get_bug_impact(conn, impact_id)
                if record is None:
                    raise DomainCommandError("BUG_IMPACT_NOT_FOUND", f"bug impact not found: {impact_uuid}")
                references = BugImpact.crud_reference_counts(conn, impact_id)
                if dry_run:
                    return SuccessResult(data={
                        "dry_run": True,
                        "would_delete": str(impact_id),
                        "mode": "hard" if hard else "soft",
                        "blocked": bool(references),
                        "references": references,
                    })
                refuse_if_bug_impact_plan_completed(conn, record)
                if references:
                    raise EntityReferencedError("bug_impact", impact_id, references)
                if hard:
                    hard_delete_bug_impact(conn, impact_id, changed_by=changed_by)
                    data = {"dry_run": False, "mode": "hard", "deleted_uuid": str(impact_id)}
                else:
                    deleted = soft_delete_bug_impact(conn, impact_id, changed_by=changed_by)
                    data = {"dry_run": False, "mode": "soft", "bug_impact": deleted.to_payload()}
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for bug_impact_delete."""
        params = {
            "impact_uuid": {"description": "UUID of the bug_impact record to delete.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor performing the deletion; recorded on the audit trail.", "type": "string", "required": True},
            "hard": {"description": "False (default): soft-delete - recoverable, hidden from listings. True: irreversible row removal, gated by the inbound-reference integrity check.", "type": "boolean", "required": False, "default": False},
            "dry_run": {"description": "True: write nothing; report target, mode, blocked flag, and all live referencing records.", "type": "boolean", "required": False, "default": False},
        }
        return bug_impact_metadata(
            cls,
            params,
            {"success": {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references} or deletion result: soft {dry_run, mode, bug_impact} / hard {dry_run, mode, deleted_uuid}."}},
            [
                {"description": "Preview a deletion without writing.", "command": {"impact_uuid": "33333333-3333-3333-3333-333333333333", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"impact_uuid": "33333333-3333-3333-3333-333333333333", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"impact_uuid": "33333333-3333-3333-3333-333333333333", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the bug impact exist (a bug fix propagation targeting this impact); the universal deletion rule refuses the deletion.",
                    "message": "cannot delete bug_impact {impact_uuid}: inbound references exist: {references}",
                    "solution": "Inspect details.references (table.column to live count), detach or delete the referrers first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from bug_impact_list, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while a live bug fix propagation still references this impact the command refuses with DELETE_BLOCKED; delete or reassign the propagation first.",
                "The deletion is recorded on the runtime audit trail under changed_by.",
            ],
        )
