"""Command: create a new invocable model record (C-005, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.model_command_metadata import model_metadata
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_store import create_model


class ModelCreateCommand(Command):
    name: ClassVar[str] = "model_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new invocable model record (C-005): name, provider reference, capability level, and execution mode."
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
                "name": {"description": "Model name.", "type": "string"},
                "provider_uuid": {"description": "The provider this model runs on; validated to reference a live (non-soft-deleted) provider row.", "type": "string"},
                "level": {"description": "Capability level: the indirection roles request against, not a concrete model. Free-form text, not a closed enum.", "type": "string"},
                "execution_mode": {"description": "Interactive or batch; batch carries discounted asynchronous economics with no tool-use loop inside a single item.", "type": "string", "enum": ["interactive", "batch"]},
                "created_by": {"description": "Actor creating this model, recorded on the audit trail.", "type": "string"},
                "context_window": {"description": "Optional context window size.", "type": "integer"},
                "cost_class": {"description": "Optional cost classification.", "type": "string"},
                "availability": {"description": "Optional availability descriptor.", "type": "string"},
            },
            "required": ["name", "provider_uuid", "level", "execution_mode", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "name": {"description": "Model name.", "type": "string", "required": True},
            "provider_uuid": {"description": "The provider this model runs on; validated to reference a live (non-soft-deleted) provider row.", "type": "string", "required": True},
            "level": {"description": "Capability level: the indirection roles request against, not a concrete model. Free-form text, not a closed enum.", "type": "string", "required": True},
            "execution_mode": {"description": "Interactive or batch; batch carries discounted asynchronous economics with no tool-use loop inside a single item.", "type": "string", "required": True},
            "created_by": {"description": "Actor creating this model, recorded on the audit trail.", "type": "string", "required": True},
            "context_window": {"description": "Optional context window size.", "type": "integer", "required": False},
            "cost_class": {"description": "Optional cost classification.", "type": "string", "required": False},
            "availability": {"description": "Optional availability descriptor.", "type": "string", "required": False},
        }
        return_value = {"description": "The created Model record.", "type": "object"}
        examples = [
            {"description": "Create an interactive model on a live provider.", "command": {"name": "gpt-5", "provider_uuid": "c6c6c6c6-0000-0000-0000-000000000000", "level": "frontier", "execution_mode": "interactive", "created_by": "owner"}},
        ]
        best_practices = [
            "provider_uuid must reference a live (non-soft-deleted) provider row; create_model raises RUNTIME_VALIDATION_ERROR otherwise.",
            "level is free-form text, not a closed enum; roles request a level and equivalent-level models of different providers are interchangeable.",
            "execution_mode must be exactly 'interactive' or 'batch'.",
            "Re-read with model_get after the call to confirm the stored record.",
        ]
        return model_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        name: str,
        provider_uuid: str,
        level: str,
        execution_mode: str,
        created_by: str,
        context_window: int | None = None,
        cost_class: str | None = None,
        availability: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                model = create_model(
                    conn,
                    name=name,
                    provider_uuid=validate_uuid(provider_uuid),
                    level=level,
                    execution_mode=execution_mode,
                    created_by=created_by,
                    context_window=context_window,
                    cost_class=cost_class,
                    availability=availability,
                )
                return SuccessResult(data=model.to_payload())
        except Exception as exc:
            return map_exception(exc)
