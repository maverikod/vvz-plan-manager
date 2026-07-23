"""Command: delete an invocable model record under the universal deletion rule (C-005, C-015): soft by default, guarded hard mode, dry-run preview."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.model_command_metadata import model_metadata
from plan_manager.domain.model import Model
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_store import get_model, remove_model
from plan_manager.storage.runtime_audit_store import record_runtime_change


class ModelDeleteCommand(Command):
    name: ClassVar[str] = "model_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete an invocable model record (C-005): soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "model"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "model_uuid": {"type": "string", "description": "The model_uuid identifier of the model record to delete."},
                "changed_by": {"type": "string", "description": "Identity of the actor performing the deletion; recorded on the audit trail."},
                "hard": {"type": "boolean", "description": "When false (the default), soft-delete: recoverable, hidden from listings. When true, irreversibly remove the row; gated by the inbound-reference integrity check.", "default": False},
                "dry_run": {"type": "boolean", "description": "When true, write nothing: report the deletion target, mode, whether it would be blocked, and the live referencing records as a dict mapping 'table.column' to the count of live referencing rows.", "default": False},
            },
            "required": ["model_uuid", "changed_by"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate model_delete parameters beyond the base schema check: model_uuid must parse as a UUID."""
        params = super().validate_params(params)
        model_uuid = params.get("model_uuid")
        if model_uuid is not None:
            validate_uuid(model_uuid)
        return params

    async def execute(
        self,
        model_uuid: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(model_uuid)
                record = get_model(conn, parsed_uuid)
                if record is None:
                    raise DomainCommandError("MODEL_NOT_FOUND", f"model not found: {model_uuid}")
                references = Model.crud_reference_counts(conn, parsed_uuid)
                if dry_run:
                    return SuccessResult(data={
                        "dry_run": True,
                        "would_delete": str(parsed_uuid),
                        "mode": "hard" if hard else "soft",
                        "blocked": bool(references),
                        "references": references,
                    })
                if hard:
                    Model.crud_hard_delete(conn, parsed_uuid, returning=False, require_soft_deleted=False)
                    record_runtime_change(
                        conn,
                        plan_uuid=None,
                        entity_type="model",
                        entity_id=parsed_uuid,
                        action="hard_delete",
                        changed_by=changed_by,
                    )
                    data = {"dry_run": False, "mode": "hard", "deleted_uuid": str(parsed_uuid)}
                else:
                    deleted = remove_model(conn, parsed_uuid, changed_by=changed_by)
                    data = {"dry_run": False, "mode": "soft", "model": deleted.to_payload()}
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model_uuid": {"description": "The model_uuid identifier of the model record to delete.", "type": "string", "required": True},
            "changed_by": {"description": "Identity of the actor performing the deletion; recorded on the audit trail.", "type": "string", "required": True},
            "hard": {"description": "False (default): soft-delete - recoverable, hidden from listings. True: irreversible row removal, gated by the inbound-reference integrity check.", "type": "boolean", "required": False, "default": False},
            "dry_run": {"description": "True: write nothing; report target, mode, blocked flag, and all live referencing records.", "type": "boolean", "required": False, "default": False},
        }
        return model_metadata(
            cls,
            params,
            {"description": "Dry-run preview {dry_run, would_delete, mode, blocked, references} or deletion result: soft {dry_run, mode, model} / hard {dry_run, mode, deleted_uuid}.", "type": "object"},
            [
                {"description": "Preview a deletion without writing.", "command": {"model_uuid": "33333333-3333-3333-3333-333333333333", "changed_by": "agent-1", "dry_run": True}},
                {"description": "Soft-delete (default): recoverable, hidden from listings.", "command": {"model_uuid": "33333333-3333-3333-3333-333333333333", "changed_by": "agent-1"}},
                {"description": "Hard-delete: irreversible, gated by the integrity check.", "command": {"model_uuid": "33333333-3333-3333-3333-333333333333", "changed_by": "agent-1", "hard": True}},
            ],
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references to the model exist (for example model bindings); the universal deletion rule refuses the deletion.",
                    "message": "cannot delete model {model_uuid}: inbound references exist: {references}",
                    "solution": "Inspect details.references (table.column to live count), detach or delete the referrers first, or run dry_run=true to preview; then retry.",
                },
            },
            best_practices=[
                "Deletion is soft by default: the row is preserved with a deletion timestamp, hidden from model_list's default view, and recoverable at the store level.",
                "hard=true irreversibly removes the row; it cannot be undone - always run dry_run=true first.",
                "Both modes are gated by the universal deletion rule: while live blocking referrers exist (for example model bindings) the command refuses with DELETE_BLOCKED; detach or delete referrers first.",
                "The deletion is recorded on the runtime audit trail under changed_by; verify the outcome with model_get, which still returns a soft-deleted row with deleted_at set, or NOT_FOUND after a hard delete.",
            ],
        )
