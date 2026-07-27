"""Command: patch the mutable fields of an existing invocable model record (C-005, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import (
    perform_guarded_runtime_update,
    require_mutable_patch,
)
from plan_manager.commands.model_command_metadata import model_metadata
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_store import get_model, update_model


class ModelUpdateCommand(Command):
    name: ClassVar[str] = "model_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch the mutable fields of an existing invocable model record (C-005) in place."
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
                "model_uuid": {"description": "The model_uuid identifier of the model record to patch.", "type": "string"},
                "changed_by": {"description": "The actor patching this model.", "type": "string"},
                "level": {"description": "New capability level for the model.", "type": "string"},
                "context_window": {"description": "New context window size for the model.", "type": "integer"},
                "cost_class": {"description": "New cost classification for the model.", "type": "string"},
                "availability": {"description": "New availability descriptor for the model.", "type": "string"},
                "execution_mode": {"description": "New execution mode for the model: interactive or batch.", "type": "string", "enum": ["interactive", "batch"]},
            },
            "required": ["model_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "model_uuid": {"description": "The model_uuid identifier of the model record to patch.", "type": "string", "required": True},
            "changed_by": {"description": "The actor patching this model.", "type": "string", "required": True},
            "level": {"description": "New capability level for the model.", "type": "string", "required": False},
            "context_window": {"description": "New context window size for the model.", "type": "integer", "required": False},
            "cost_class": {"description": "New cost classification for the model.", "type": "string", "required": False},
            "availability": {"description": "New availability descriptor for the model.", "type": "string", "required": False},
            "execution_mode": {"description": "New execution mode for the model: interactive or batch.", "type": "string", "required": False},
        }
        return_value = {"description": "The patched Model record.", "type": "object"}
        examples = [
            {"description": "Patch a model's execution mode.", "command": {"model_uuid": "d6d6d6d6-0000-0000-0000-000000000000", "changed_by": "owner", "execution_mode": "batch"}},
        ]
        best_practices = [
            "Only the fields supplied are patched; omitted fields keep their current stored value.",
            "At least one mutable field beyond model_uuid and changed_by must be supplied, or the call fails with RUNTIME_VALIDATION_ERROR.",
            "name and provider_uuid are immutable identity fields fixed at create time and cannot be patched; remove and re-create the model to change them.",
            "Re-read with model_get after the call to confirm the patch was applied as expected.",
        ]
        return model_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        model_uuid: str,
        changed_by: str,
        level: str | None = None,
        context_window: int | None = None,
        cost_class: str | None = None,
        availability: str | None = None,
        execution_mode: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_guarded_runtime_update(
                raw_entity_id=model_uuid,
                get_record=get_model,
                update_record=update_model,
                changed_by=changed_by,
                not_found_code="MODEL_NOT_FOUND",
                not_found_message=f"model not found: {model_uuid}",
                db_connect=db_connection,
                update_fields={
                    "level": level,
                    "context_window": context_window,
                    "cost_class": cost_class,
                    "availability": availability,
                    "execution_mode": execution_mode,
                },
                pre_update=lambda conn, existing, update_fields: require_mutable_patch(
                    update_fields,
                    "model_update requires at least one mutable field to patch",
                ),
            )
        except Exception as exc:
            return map_exception(exc)
