"""Command: retrieve a single model binding runtime-configuration record by identifier (C-009, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.model_binding_command_metadata import model_binding_metadata, BASE_PARAMETERS
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_binding_store import get_model_binding


class ModelBindingGetCommand(Command):
    name: ClassVar[str] = "model_binding_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single model binding record (C-009) by its binding identifier."
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
                "binding_uuid": {"description": "The binding_uuid identifier of the model_binding record.", "type": "string"},
            },
            "required": ["binding_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "binding_uuid": {"description": "The binding_uuid identifier of the model_binding record.", "type": "string", "required": True},
        }
        return_value = {"description": "The ModelBinding record.", "type": "object"}
        examples = [
            {"description": "Fetch a binding by its uuid.", "command": {"binding_uuid": "b6b6b6b6-0000-0000-0000-000000000000"}},
        ]
        best_practices = [
            "Pass the binding_uuid returned by model_binding_set or model_binding_list, not a plan, step, or branch uuid.",
            "get_model_binding returns soft-deleted records too; check the deleted_at field in the payload to know if a binding is still active.",
            "Use model_binding_list first when the exact binding_uuid is unknown.",
        ]
        return model_binding_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(self, binding_uuid: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(binding_uuid)
                binding = get_model_binding(conn, parsed_uuid)
                if binding is None:
                    raise DomainCommandError("MODEL_BINDING_NOT_FOUND", f"model binding not found: {binding_uuid}")
                return SuccessResult(data=binding.to_payload())
        except Exception as exc:
            return map_exception(exc)
