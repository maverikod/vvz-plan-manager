"""Command: retrieve a single model binding runtime-configuration record by identifier (C-009, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.model_binding_command_metadata import model_binding_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_record_command_helpers import (
    get_command_metadata_params,
    get_command_schema,
    perform_runtime_get,
)
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
        return get_command_schema("binding_uuid", "The binding_uuid identifier of the model_binding record.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters = get_command_metadata_params("binding_uuid", "The binding_uuid identifier of the model_binding record.")
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
            return perform_runtime_get(
                raw_entity_id=binding_uuid,
                get_record=get_model_binding,
                not_found_code="MODEL_BINDING_NOT_FOUND",
                not_found_message=f"model binding not found: {binding_uuid}",
                db_connect=db_connection,
            )
        except Exception as exc:
            return map_exception(exc)
