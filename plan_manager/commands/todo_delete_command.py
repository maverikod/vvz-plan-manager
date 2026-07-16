"""Command: delete a TODO work item under the universal deletion rule (C-008): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.todo_command_metadata import todo_metadata
from plan_manager.domain.entity import EntityReferencedError
from plan_manager.domain.todo import TodoItem
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_hard_delete import hard_delete_todo
from plan_manager.storage.todo_store import get_todo, soft_delete_todo


class TodoDeleteCommand(Command):
    name: ClassVar[str] = "todo_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a TODO work item: soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "todo"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for todo_delete."""
        return {
            "type": "object",
            "properties": {
                "todo": {"type": "string", "format": "uuid", "description": "TODO item UUID to delete."},
                "changed_by": {"type": "string", "description": "Identity of the actor performing the deletion; recorded on the audit trail."},
                "hard": {"type": "boolean", "description": "When false (the default), soft-delete: recoverable, hidden from listings. When true, irreversibly remove the row; gated by the inbound-reference integrity check.", "default": False},
                "dry_run": {"type": "boolean", "description": "When true, write nothing: report the deletion target, mode, whether it would be blocked, and the live referencing records as a dict mapping 'table.column' to the count of live referencing rows.", "default": False},
            },
            "required": ["todo", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate todo_delete parameters beyond the base schema check: todo must parse as a UUID."""
        params = super().validate_params(params)
        todo = params.get("todo")
        if todo is not None:
            uuid.UUID(todo)
        return params

    async def execute(
        self,
        todo: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Delete a TODO item (soft by default, hard when hard=true), or preview with dry_run=true."""
        try:
            with db_connection() as conn:
                todo_uuid = uuid.UUID(todo)
                record = get_todo(conn, todo_uuid)
                if record is None:
                    raise DomainCommandError("TODO_NOT_FOUND", f"todo not found: {todo}")
                references = TodoItem.crud_reference_counts(conn, todo_uuid)
                if dry_run:
                    return SuccessResult(data={
                        "dry_run": True,
                        "would_delete": str(todo_uuid),
                        "mode": "hard" if hard else "soft",
                        "blocked": bool(references),
                        "references": references,
                    })
                if references:
                    raise EntityReferencedError("todo", todo_uuid, references)
                if hard:
                    hard_delete_todo(conn, todo_uuid, changed_by=changed_by)
                    data = {"dry_run": False, "mode": "hard", "deleted_uuid": str(todo_uuid)}
                else:
                    deleted = soft_delete_todo(conn, todo_uuid, changed_by=changed_by)
                    data = {"dry_run": False, "mode": "soft", "todo": deleted.to_payload()}
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for todo_delete."""
        params = {
            "todo": {"description": "TODO item UUID to delete.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor performing the deletion; recorded on the audit trail.", "type": "string", "required": True},
            "hard": {"description": "False (default): soft-delete - recoverable, hidden from listings. True: irreversible row removal, gated by the inbound-reference integrity check.", "type": "boolean", "required": False, "default": False},
            "dry_run": {"description": "True: write nothing; report target, mode, blocked flag, and all live referencing records.", "type": "boolean", "required": False, "default": False},
        }
        return todo_metadata(
            cls,
            params,
            {"success": {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references[]} or deletion result: soft {dry_run, mode, todo} / hard {dry_run, mode, deleted_uuid, cascade_removed[]}."}},
            [
                {"description": "Preview a deletion without writing.", "command": {"todo": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"todo": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"todo": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the TODO item exist (anchored comments, execution attempts, escalations, or bug-fix propagations); the universal deletion rule refuses the deletion.",
                    "message": "cannot delete todo {todo}: inbound references exist: {references}",
                    "solution": "Inspect details.references (uuid + kind per referrer), detach or delete the referrers first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from todo_get/todo_list, and recoverable at the store level.",
                "hard=true irreversibly removes the row and cascade-removes the item's todo_link rows; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while live blocking referrers exist the command refuses with DELETE_BLOCKED and lists every referencing record (uuid + kind); detach or delete referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by; verify the outcome with todo_get, which no longer returns the item.",
            ],
        )
