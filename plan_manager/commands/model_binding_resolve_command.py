"""Command: resolve the effective model for a target step and role from the binding inheritance (C-012, C-009, C-010, C-031)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.model_binding_command_metadata import model_binding_metadata, BASE_PARAMETERS
from plan_manager.domain.model_binding import InvalidRuntimeRoleError
from plan_manager.domain.model_resolution import ModelResolutionError, ResolutionTarget, resolve_effective_binding
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_binding_store import list_bindings_for_resolution


class ModelBindingResolveCommand(Command):
    name: ClassVar[str] = "model_binding_resolve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Resolve the effective model for a target step and role from the binding inheritance (C-012)."
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
                "plan": {"description": "Plan UUID to resolve the effective model within.", "type": "string"},
                "role": {"description": "RuntimeRole value (C-011) to resolve the effective model for.", "type": "string"},
                "spec_level": {"description": "Optional spec level (HRS, MRS, GS, TS, AS) target for level-scope resolution.", "type": "string"},
                "branch_step": {"description": "Optional branch (GS) step UUID target for branch-scope resolution.", "type": "string"},
                "step": {"description": "Optional step UUID target for step-scope resolution.", "type": "string"},
            },
            "required": ["plan", "role"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = dict(BASE_PARAMETERS)
        parameters["plan"] = {"description": "Plan UUID to resolve the effective model within.", "type": "string", "required": True}
        parameters["role"] = {"description": "RuntimeRole value (C-011) to resolve the effective model for.", "type": "string", "required": True}
        parameters["spec_level"] = {"description": "Optional spec level (HRS, MRS, GS, TS, AS) target for level-scope resolution.", "type": "string", "required": False}
        parameters["branch_step"] = {"description": "Optional branch (GS) step UUID target for branch-scope resolution.", "type": "string", "required": False}
        parameters["step"] = {"description": "Optional step UUID target for step-scope resolution.", "type": "string", "required": False}
        return_value = {"description": "The ModelResolution record: effective provider/model, source, fallback, retry count, timeout, context budget, and inheritance path.", "type": "object"}
        examples = [
            {"description": "Resolve the effective model for as_author on a given plan.", "command": {"plan": "b6b6b6b6-0000-0000-0000-000000000000", "role": "as_author"}},
        ]
        best_practices = [
            "resolve is read-only: it reports the effective binding without creating or mutating any record.",
            "plan and role are required; add spec_level, branch_step, or step to resolve at a more specific scope.",
            "Precedence follows system < plan < level < branch < step < role (C-010); the highest-ranked applicable binding wins.",
            "Inspect inheritance_path in the result to see every applicable binding considered, not just the winner.",
            "Ensure at least a system- or plan-scope fallback binding exists; resolution raises when no binding applies.",
        ]
        return model_binding_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        plan: str,
        role: str,
        spec_level: str | None = None,
        branch_step: str | None = None,
        step: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_uuid = validate_uuid(plan)
                try:
                    validated_role = validate_runtime_role(role)
                except RuntimeValidationError as exc:
                    raise InvalidRuntimeRoleError(str(exc)) from exc
                branch_step_uuid = validate_uuid(branch_step) if branch_step is not None else None
                step_uuid = validate_uuid(step) if step is not None else None
                candidates = list_bindings_for_resolution(conn, plan_uuid=plan_uuid)
                target = ResolutionTarget(
                    role=validated_role,
                    plan_uuid=plan_uuid,
                    spec_level=spec_level,
                    branch_step_uuid=branch_step_uuid,
                    step_uuid=step_uuid,
                )
                try:
                    resolution = resolve_effective_binding(candidates, target)
                except ModelResolutionError as exc:
                    raise DomainCommandError("MODEL_BINDING_NOT_FOUND", str(exc)) from exc
                return SuccessResult(data=resolution.to_payload())
        except Exception as exc:
            return map_exception(exc)
