"""Command: soft-delete a model binding runtime-configuration record (C-009, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.model_binding_command_metadata import model_binding_metadata, BASE_PARAMETERS
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_binding_store import get_model_binding, remove_model_binding


class ModelBindingRemoveCommand(Command):
    name: ClassVar[str] = "model_binding_remove"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Soft-delete a model binding record (C-009) by its binding identifier."
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
                "binding_uuid": {"description": "The binding_uuid identifier of the model_binding record to remove.", "type": "string"},
                "changed_by": {"description": "The actor removing this binding.", "type": "string"},
            },
            "required": ["binding_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "binding_uuid": {"description": "The binding_uuid identifier of the model_binding record to remove.", "type": "string", "required": True},
            "changed_by": {"description": "The actor removing this binding.", "type": "string", "required": True},
        }
        return_value = {"description": "The soft-deleted ModelBinding record.", "type": "object"}
        examples = [
            {"description": "Soft-delete a binding.", "command": {"binding_uuid": "b6b6b6b6-0000-0000-0000-000000000000", "changed_by": "owner"}},
        ]
        best_practices = [
            "Removal is a soft-delete: it sets deleted_at and keeps the row in place for audit history.",
            "Calling remove again on an already-removed binding_uuid is idempotent and does not error.",
            "Pass the real actor in changed_by so the audit trail records who removed the binding.",
            "After removal, re-run model_binding_resolve to confirm which binding now wins for the affected targets.",
        ]
        return model_binding_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(self, binding_uuid: str, changed_by: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(binding_uuid)
                existing = get_model_binding(conn, parsed_uuid)
                if existing is None:
                    raise DomainCommandError("MODEL_BINDING_NOT_FOUND", f"model binding not found: {binding_uuid}")
                binding = remove_model_binding(conn, parsed_uuid, changed_by=changed_by)
                return SuccessResult(data=binding.to_payload())
        except Exception as exc:
            return map_exception(exc)
