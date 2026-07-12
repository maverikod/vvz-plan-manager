"""Command: create a model binding runtime-configuration record (C-009, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.model_binding_command_metadata import model_binding_metadata, BASE_PARAMETERS
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_binding_store import create_model_binding


class ModelBindingSetCommand(Command):
    name: ClassVar[str] = "model_binding_set"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a model binding runtime-configuration record (C-009) for the given scope."
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
                "scope": {"description": "BindingScope value (C-010 inheritance level): system, plan, level, branch, step, or role.", "type": "string"},
                "provider": {"description": "Model provider name for the binding.", "type": "string"},
                "model": {"description": "Model name for the binding.", "type": "string"},
                "max_retries": {"description": "Maximum retry count for this binding.", "type": "integer"},
                "timeout": {"description": "Timeout in seconds for this binding.", "type": "integer"},
                "created_by": {"description": "Actor creating this binding.", "type": "string"},
                "role": {"description": "Optional RuntimeRole value (C-011) restricting this binding to one role.", "type": "string"},
                "plan": {"description": "Plan UUID this binding applies to. Required for scope plan/level/branch/step; optional for scope role; must be omitted for scope system.", "type": "string"},
                "spec_level": {"description": "One of HRS, MRS, GS, TS, AS. Required when scope is level; omitted otherwise.", "type": "string"},
                "branch_step": {"description": "UUID of the branch (GS) step. Required when scope is branch; omitted otherwise.", "type": "string"},
                "revision": {"description": "Optional revision UUID, applicable only when scope is step.", "type": "string"},
                "step": {"description": "UUID of the step. Required when scope is step; omitted otherwise.", "type": "string"},
                "step_path": {"description": "Optional diagnostic display snapshot of the step path, applicable only when scope is step.", "type": "string"},
                "fallback_provider": {"description": "Optional fallback provider name.", "type": "string"},
                "fallback_model": {"description": "Optional fallback model name.", "type": "string"},
                "context_budget": {"description": "Optional context budget token ceiling.", "type": "integer"},
                "active": {"description": "Whether the binding is active.", "type": "boolean", "default": True},
            },
            "required": ["scope", "provider", "model", "max_retries", "timeout", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = dict(BASE_PARAMETERS)
        parameters["plan"] = {"description": "Plan UUID this binding applies to. Required for scope plan/level/branch/step; optional for scope role; must be omitted for scope system.", "type": "string", "required": False}
        parameters["scope"] = {"description": "BindingScope value (C-010 inheritance level): system, plan, level, branch, step, or role.", "type": "string", "required": True}
        parameters["provider"] = {"description": "Model provider name for the binding.", "type": "string", "required": True}
        parameters["model"] = {"description": "Model name for the binding.", "type": "string", "required": True}
        parameters["max_retries"] = {"description": "Maximum retry count for this binding.", "type": "integer", "required": True}
        parameters["timeout"] = {"description": "Timeout in seconds for this binding.", "type": "integer", "required": True}
        parameters["created_by"] = {"description": "Actor creating this binding.", "type": "string", "required": True}
        parameters["role"] = {"description": "Optional RuntimeRole value (C-011) restricting this binding to one role.", "type": "string", "required": False}
        parameters["spec_level"] = {"description": "One of HRS, MRS, GS, TS, AS. Required when scope is level; omitted otherwise.", "type": "string", "required": False}
        parameters["branch_step"] = {"description": "UUID of the branch (GS) step. Required when scope is branch; omitted otherwise.", "type": "string", "required": False}
        parameters["revision"] = {"description": "Optional revision UUID, applicable only when scope is step.", "type": "string", "required": False}
        parameters["step"] = {"description": "UUID of the step. Required when scope is step; omitted otherwise.", "type": "string", "required": False}
        parameters["step_path"] = {"description": "Optional diagnostic display snapshot of the step path, applicable only when scope is step.", "type": "string", "required": False}
        parameters["fallback_provider"] = {"description": "Optional fallback provider name.", "type": "string", "required": False}
        parameters["fallback_model"] = {"description": "Optional fallback model name.", "type": "string", "required": False}
        parameters["context_budget"] = {"description": "Optional context budget token ceiling.", "type": "integer", "required": False}
        parameters["active"] = {"description": "Whether the binding is active. Defaults to true.", "type": "boolean", "required": False}
        return_value = {"description": "The created ModelBinding record.", "type": "object"}
        examples = [
            {
                "description": "Create a role-scoped binding for as_author.",
                "command": {"scope": "role", "role": "as_author", "provider": "anthropic", "model": "haiku", "max_retries": 1, "timeout": 600, "created_by": "owner"},
            }
        ]
        best_practices = [
            "Choose the narrowest applicable scope (role > step > branch > level > plan > system) so the override targets intent precisely.",
            "Supply only the companion fields required by the chosen scope: system needs none, plan needs plan, level needs plan+spec_level, branch needs plan+branch_step, step needs plan+step.",
            "Set role to restrict a binding to one RuntimeRole (e.g. as_author); omit role to apply the binding to every role.",
            "Provide fallback_provider and fallback_model together when a secondary model should be tried on failure.",
            "Keep max_retries within the configured retry-policy bounds (0-10); timeout is seconds per attempt.",
        ]
        return model_binding_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        scope: str,
        provider: str,
        model: str,
        max_retries: int,
        timeout: int,
        created_by: str,
        role: str | None = None,
        plan: str | None = None,
        spec_level: str | None = None,
        branch_step: str | None = None,
        revision: str | None = None,
        step: str | None = None,
        step_path: str | None = None,
        fallback_provider: str | None = None,
        fallback_model: str | None = None,
        context_budget: int | None = None,
        active: bool = True,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_uuid = validate_uuid(plan) if plan is not None else None
                branch_step_uuid = validate_uuid(branch_step) if branch_step is not None else None
                revision_uuid = validate_uuid(revision) if revision is not None else None
                step_uuid = validate_uuid(step) if step is not None else None
                binding = create_model_binding(
                    conn,
                    scope=scope,
                    provider=provider,
                    model=model,
                    max_retries=max_retries,
                    timeout=timeout,
                    created_by=created_by,
                    role=role,
                    plan_uuid=plan_uuid,
                    spec_level=spec_level,
                    branch_step_uuid=branch_step_uuid,
                    revision_uuid=revision_uuid,
                    step_uuid=step_uuid,
                    step_path=step_path,
                    fallback_provider=fallback_provider,
                    fallback_model=fallback_model,
                    context_budget=context_budget,
                    active=active,
                )
                return SuccessResult(data=binding.to_payload())
        except Exception as exc:
            return map_exception(exc)
