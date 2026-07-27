"""Command: retrieve a single invocable model record by identifier (C-005, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import (
    get_command_metadata_params,
    get_command_schema,
    perform_runtime_get,
)
from plan_manager.commands.model_command_metadata import model_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_store import get_model


class ModelGetCommand(Command):
    name: ClassVar[str] = "model_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single invocable model record (C-005) by its model identifier."
    category: ClassVar[str] = "model"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return get_command_schema("model_uuid", "The model_uuid identifier of the model record.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters = get_command_metadata_params("model_uuid", "The model_uuid identifier of the model record.")
        return_value = {"description": "The Model record.", "type": "object"}
        examples = [
            {"description": "Fetch a model by its uuid.", "command": {"model_uuid": "d6d6d6d6-0000-0000-0000-000000000000"}},
        ]
        best_practices = [
            "Pass the model_uuid returned by model_create or model_list, not a provider or model-binding uuid.",
            "get_model returns soft-deleted records too; check the deleted_at field in the payload to know if a model is still active.",
            "Use model_list first when the exact model_uuid is unknown.",
        ]
        return model_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(self, model_uuid: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_get(
                raw_entity_id=model_uuid,
                get_record=get_model,
                not_found_code="MODEL_NOT_FOUND",
                not_found_message=f"model not found: {model_uuid}",
                db_connect=db_connection,
            )
        except Exception as exc:
            return map_exception(exc)
