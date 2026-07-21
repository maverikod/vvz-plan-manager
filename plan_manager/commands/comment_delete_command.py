"""Command: delete a runtime comment under the universal deletion rule (C-008): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.comment_command_metadata import comment_metadata
from plan_manager.domain.entity import EntityReferencedError
from plan_manager.domain.runtime_comment import RuntimeComment
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_hard_delete import hard_delete_comment
from plan_manager.storage.runtime_comment_store import get_comment, soft_delete_comment


class CommentDeleteCommand(Command):
    name: ClassVar[str] = "comment_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a runtime comment: soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "comment"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for comment_delete."""
        return {
            "type": "object",
            "properties": {
                "comment": {"type": "string", "format": "uuid", "description": "Runtime comment UUID to delete."},
                "changed_by": {"type": "string", "description": "Identity of the actor performing the deletion; recorded on the audit trail."},
                "hard": {"type": "boolean", "description": "When false (the default), soft-delete: recoverable, hidden from listings. When true, irreversibly remove the row; gated by the inbound-reference integrity check.", "default": False},
                "dry_run": {"type": "boolean", "description": "When true, write nothing: report the deletion target, mode, whether it would be blocked, and the live referencing records as a dict mapping 'table.column' to the count of live referencing rows.", "default": False},
            },
            "required": ["comment", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate comment_delete parameters beyond the base schema check: comment must parse as a UUID."""
        params = super().validate_params(params)
        comment = params.get("comment")
        if comment is not None:
            uuid.UUID(comment)
        return params

    async def execute(
        self,
        comment: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Delete a runtime comment (soft by default, hard when hard=true), or preview with dry_run=true."""
        try:
            with db_connection() as conn:
                comment_uuid = uuid.UUID(comment)
                record = get_comment(conn, comment_uuid)
                if record is None:
                    raise DomainCommandError("COMMENT_NOT_FOUND", f"comment not found: {comment}")
                references = RuntimeComment.crud_reference_counts(conn, comment_uuid)
                if dry_run:
                    return SuccessResult(data={
                        "dry_run": True,
                        "would_delete": str(comment_uuid),
                        "mode": "hard" if hard else "soft",
                        "blocked": bool(references),
                        "references": references,
                    })
                if references:
                    raise EntityReferencedError("comment", comment_uuid, references)
                if hard:
                    hard_delete_comment(conn, comment_uuid, changed_by=changed_by)
                    data = {"dry_run": False, "mode": "hard", "deleted_uuid": str(comment_uuid)}
                else:
                    deleted = soft_delete_comment(conn, comment_uuid, changed_by=changed_by)
                    data = {"dry_run": False, "mode": "soft", "comment": deleted.to_payload()}
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for comment_delete."""
        params = {
            "comment": {"description": "Runtime comment UUID to delete.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor performing the deletion; recorded on the audit trail.", "type": "string", "required": True},
            "hard": {"description": "False (default): soft-delete - recoverable, hidden from listings. True: irreversible row removal, gated by the inbound-reference integrity check.", "type": "boolean", "required": False, "default": False},
            "dry_run": {"description": "True: write nothing; report target, mode, blocked flag, and all live referencing records.", "type": "boolean", "required": False, "default": False},
        }
        return comment_metadata(
            cls,
            params,
            {"success": {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references[]} or deletion result: soft {dry_run, mode, comment} / hard {dry_run, mode, deleted_uuid}."}},
            [
                {"description": "Preview a deletion without writing.", "command": {"comment": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"comment": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"comment": "22222222-2222-2222-2222-222222222222", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "A live comment superseding this comment exists; the universal deletion rule refuses the deletion while inbound references are live.",
                    "message": "cannot delete runtime_comment {comment}: inbound references exist: {references}",
                    "solution": "Inspect details.references (uuid + kind per referrer), delete the superseding comment first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from comment_get/comment_list, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while a live superseding comment references this one the command refuses with DELETE_BLOCKED and lists every referencing record (uuid + kind); delete the referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by; verify the outcome with comment_get, which no longer returns the comment.",
            ],
        )
