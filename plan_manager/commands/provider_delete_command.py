"""Command: delete a provider record under the universal deletion rule (C-004, C-015): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.provider_command_metadata import provider_metadata
from plan_manager.domain.provider import Provider
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.provider_store import get_provider, remove_provider
from plan_manager.storage.runtime_audit_store import record_runtime_change


class ProviderDeleteCommand(Command):
    name: ClassVar[str] = "provider_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a provider record (C-004): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "provider"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "provider_uuid": {"type": "string", "description": "The provider_uuid identifier of the provider record to delete."},
                "changed_by": {"type": "string", "description": "Identity of the actor performing the deletion; recorded on the audit trail."},
                "hard": {"type": "boolean", "description": "When false (the default), soft-delete: recoverable, hidden from listings. When true, irreversibly remove the row; gated by the inbound-reference integrity check.", "default": False},
                "dry_run": {"type": "boolean", "description": "When true, write nothing: report the deletion target, mode, whether it would be blocked, and the live referencing records as a dict mapping 'table.column' to the count of live referencing rows.", "default": False},
            },
            "required": ["provider_uuid", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate provider_delete parameters beyond the base schema check: provider_uuid must parse as a UUID."""
        params = super().validate_params(params)
        provider_uuid = params.get("provider_uuid")
        if provider_uuid is not None:
            validate_uuid(provider_uuid)
        return params

    async def execute(
        self,
        provider_uuid: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(provider_uuid)
                record = get_provider(conn, parsed_uuid)
                if record is None:
                    raise DomainCommandError("PROVIDER_NOT_FOUND", f"provider not found: {provider_uuid}")
                references = Provider.crud_reference_counts(conn, parsed_uuid)
                if dry_run:
                    return SuccessResult(data={
                        "dry_run": True,
                        "would_delete": str(parsed_uuid),
                        "mode": "hard" if hard else "soft",
                        "blocked": bool(references),
                        "references": references,
                    })
                if hard:
                    Provider.crud_hard_delete(conn, parsed_uuid, returning=False, require_soft_deleted=False)
                    record_runtime_change(
                        conn,
                        plan_uuid=None,
                        entity_type="provider",
                        entity_id=parsed_uuid,
                        action="hard_delete",
                        changed_by=changed_by,
                    )
                    data = {"dry_run": False, "mode": "hard", "deleted_uuid": str(parsed_uuid)}
                else:
                    deleted = remove_provider(conn, parsed_uuid, changed_by=changed_by)
                    data = {"dry_run": False, "mode": "soft", "provider": deleted.to_payload()}
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params: dict[str, Any] = {
            "provider_uuid": {"description": "The provider_uuid identifier of the provider record to delete.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor performing the deletion; recorded on the audit trail.", "type": "string", "required": True},
            "hard": {"description": "False (default): soft-delete - recoverable, hidden from listings. True: irreversible row removal, gated by the inbound-reference integrity check.", "type": "boolean", "required": False, "default": False},
            "dry_run": {"description": "True: write nothing; report target, mode, blocked flag, and all live referencing records.", "type": "boolean", "required": False, "default": False},
        }
        return provider_metadata(
            cls,
            params,
            {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references} or deletion result: soft {dry_run, mode, provider} / hard {dry_run, mode, deleted_uuid}.", "type": "object"},
            [
                {"description": "Preview a deletion without writing.", "command": {"provider_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"provider_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"provider_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the provider exist (for example a model still naming this provider via model.provider_uuid); the universal deletion rule refuses the deletion.",
                    "message": "cannot delete provider {provider_uuid}: inbound references exist: {references}",
                    "solution": "Inspect details.references (table.column to live count), repoint or delete the referring models first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from provider_list's default view, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while live blocking referrers exist (for example a model still naming this provider) the command refuses with DELETE_BLOCKED; repoint or delete referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by; verify the outcome with provider_get, which still returns a soft-deleted row with deleted_at set, or PROVIDER_NOT_FOUND after a hard delete.",
                "Suspending a provider via provider_set_status is reversible and does not require passing the deletion reference-integrity check; prefer suspension over deletion when the provider may be reactivated later.",
            ],
        )
