"""Command: remove (soft-delete) a generic runtime link, with an optional dry-run preview (C-012, C-016)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.runtime_link_command_metadata import runtime_link_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_link_store import get_runtime_link, remove_runtime_link

class RuntimeLinkRemoveCommand(Command):
    name: ClassVar[str] = "runtime_link_remove"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Remove (soft-delete) a generic runtime link, with an optional dry-run preview."
    category: ClassVar[str] = "runtime_link"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "link": {"type": "string", "format": "uuid", "description": "Runtime link UUID."},
                "changed_by": {"type": "string", "description": "Identity of the actor removing this link."},
                "dry_run": {
                    "type": "boolean",
                    "description": "When true, return the link that WOULD be removed without soft-deleting it (default false, which performs the soft-delete).",
                },
            },
            "required": ["link", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        params = super().validate_params(params)
        link = params.get("link")
        if link is not None:
            uuid.UUID(link)
        return params

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "link": {"description": "Runtime link UUID.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor removing this link.", "type": "string", "required": True},
            "dry_run": {"description": "When true, return the link that WOULD be removed without soft-deleting it (default false, which performs the soft-delete).", "type": "boolean", "required": False, "default": False},
        }
        return runtime_link_metadata(
            cls,
            params,
            {"success": {"description": "The removed (or, under dry_run, the still-active) RuntimeLink payload."}},
            [{"description": "Remove a runtime link.", "command": {"link": "33333333-3333-3333-3333-333333333333", "changed_by": "agent-1"}}],
            detailed_description="Soft-deletes a generic runtime link by setting its deleted_at timestamp; the row is never physically removed and remains visible via runtime_link_list(include_deleted=True). Every non-dry-run removal writes an audit record to the runtime audit trail (entity_type='runtime_link', action='soft_delete'). Passing dry_run=true previews the effect of the removal (the current row, unchanged) without writing anything: no deleted_at update, no updated_at change, no audit record — a safe, side-effect-free preview mode.",
            best_practices=[
                "This is a soft-delete (deleted_at is set); the link row is never physically removed and stays visible via runtime_link_list(include_deleted=True).",
                "Set dry_run true to preview which link would be affected before committing: the call returns the current row unchanged and performs no write, no audit record, and no deleted_at update.",
                "get_runtime_link does not filter on deleted_at, so removing an already-removed link succeeds again (refreshing deleted_at/updated_at) instead of erroring — effectively idempotent in practice when dry_run is false.",
                "The link parameter is the link_uuid returned by runtime_link_add, not one of the two endpoint uuids it connects.",
                "Every non-dry-run removal is recorded in the runtime audit trail (entity_type='runtime_link', action='soft_delete') via the same audit mechanism runtime_link_add uses for 'create'.",
            ],
        )

    async def execute(
        self,
        link: str,
        changed_by: str,
        dry_run: bool | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                link_uuid = uuid.UUID(link)
                existing = get_runtime_link(conn, link_uuid)
                if existing is None:
                    raise DomainCommandError("RUNTIME_LINK_NOT_FOUND", f"runtime link not found: {link}")
                if dry_run:
                    return SuccessResult(data={**existing.to_payload(), "dry_run": True})
                record = remove_runtime_link(conn, link_uuid, changed_by=changed_by)
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
