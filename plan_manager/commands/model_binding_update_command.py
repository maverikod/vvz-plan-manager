"""Command: patch the mutable fields of an existing model binding record (C-009, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.model_binding_command_metadata import model_binding_metadata, BASE_PARAMETERS
from plan_manager.commands.plan_completion_guard import refuse_if_model_binding_plan_completed
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_binding_store import get_model_binding, update_model_binding

class ModelBindingUpdateCommand(Command):
    name: ClassVar[str] = "model_binding_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch the mutable fields of an existing model binding record (C-009) in place."
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
                "binding_uuid": {"description": "The binding_uuid identifier of the model_binding record to patch.", "type": "string"},
                "changed_by": {"description": "The actor patching this binding.", "type": "string"},
                "provider": {"description": "New model provider name for the binding.", "type": "string"},
                "model": {"description": "New model name for the binding.", "type": "string"},
                "fallback_provider": {"description": "New fallback provider name.", "type": "string"},
                "fallback_model": {"description": "New fallback model name.", "type": "string"},
                "max_retries": {"description": "New maximum retry count for this binding.", "type": "integer"},
                "timeout": {"description": "New timeout in seconds for this binding.", "type": "integer"},
                "context_budget": {"description": "New context budget token ceiling.", "type": "integer"},
                "active": {"description": "New active flag for this binding.", "type": "boolean"}
            },
            "required": ["binding_uuid", "changed_by"],
            "additionalProperties": False
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "binding_uuid": {"description": "The binding_uuid identifier of the model_binding record to patch.", "type": "string", "required": True},
            "changed_by": {"description": "The actor patching this binding.", "type": "string", "required": True},
            "provider": {"description": "New model provider name for the binding.", "type": "string", "required": False},
            "model": {"description": "New model name for the binding.", "type": "string", "required": False},
            "fallback_provider": {"description": "New fallback provider name.", "type": "string", "required": False},
            "fallback_model": {"description": "New fallback model name.", "type": "string", "required": False},
            "max_retries": {"description": "New maximum retry count for this binding.", "type": "integer", "required": False},
            "timeout": {"description": "New timeout in seconds for this binding.", "type": "integer", "required": False},
            "context_budget": {"description": "New context budget token ceiling.", "type": "integer", "required": False},
            "active": {"description": "New active flag for this binding.", "type": "boolean", "required": False}
        }
        return_value = {"description": "The patched ModelBinding record.", "type": "object"}
        examples = [
            {"description": "Patch a binding's retry count and timeout.", "command": {"binding_uuid": "b6b6b6b6-0000-0000-0000-000000000000", "changed_by": "owner", "max_retries": 3, "timeout": 900}}
        ]
        best_practices = [
            "Only the fields supplied are patched; omitted fields keep their current stored value.",
            "At least one mutable field beyond binding_uuid and changed_by must be supplied, or the call fails with RUNTIME_VALIDATION_ERROR.",
            "scope, role, plan_uuid, spec_level, branch_step_uuid, step_uuid, and revision_uuid are immutable identity fields and cannot be patched; remove and re-create the binding to change them.",
            "Re-read with model_binding_get after the call to confirm the patch was applied as expected."
        ]
        return model_binding_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        binding_uuid: str,
        changed_by: str,
        provider: str | None = None,
        model: str | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
        max_retries: int | None = None,
        timeout: int | None = None,
        context_budget: int | None = None,
        active: bool | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(binding_uuid)
                existing = get_model_binding(conn, parsed_uuid)
                if existing is None:
                    raise DomainCommandError("MODEL_BINDING_NOT_FOUND", f"model binding not found: {binding_uuid}")
                refuse_if_model_binding_plan_completed(conn, existing)
                if all(
                    value is None
                    for value in (provider, model, fallback_provider, fallback_model, max_retries, timeout, context_budget, active)
                ):
                    raise RuntimeValidationError("model_binding_update requires at least one mutable field to patch")
                binding = update_model_binding(
                    conn,
                    parsed_uuid,
                    changed_by=changed_by,
                    provider=provider,
                    model=model,
                    fallback_provider=fallback_provider,
                    fallback_model=fallback_model,
                    max_retries=max_retries,
                    timeout=timeout,
                    context_budget=context_budget,
                    active=active,
                )
                return SuccessResult(data=binding.to_payload())
        except Exception as exc:
            return map_exception(exc)
