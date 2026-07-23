"""Command: retrieve a single invocable model record by identifier (C-005, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.model_command_metadata import model_metadata
from plan_manager.domain.runtime_validation import validate_uuid
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
        return {
            "type": "object",
            "properties": {
                "model_uuid": {"description": "The model_uuid identifier of the model record.", "type": "string"},
            },
            "required": ["model_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "model_uuid": {"description": "The model_uuid identifier of the model record.", "type": "string", "required": True},
        }
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
            with db_connection() as conn:
                parsed_uuid = validate_uuid(model_uuid)
                model = get_model(conn, parsed_uuid)
                if model is None:
                    raise DomainCommandError("MODEL_NOT_FOUND", f"model not found: {model_uuid}")
                return SuccessResult(data=model.to_payload())
        except Exception as exc:
            return map_exception(exc)
