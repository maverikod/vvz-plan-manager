"""Command: resolve the effective invocation profile along the six-scope specificity ladder (C-008, C-015)."""
from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve_command_metadata import resolve_command_metadata, BASE_PARAMETERS
from plan_manager.domain.invocation_profile_resolution import (
    InvocationProfileResolution,
    ProfileResolutionError,
    ProfileResolutionTarget,
    invocation_profile_resolve,
)
from plan_manager.domain.model_binding import InvalidRuntimeRoleError
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.invocation_profile_store import list_profiles_for_resolution


class InvocationProfileResolveCommand(Command):
    name: ClassVar[str] = "invocation_profile_resolve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Resolve the effective invocation profile along the six-scope specificity ladder (C-008)."
    category: ClassVar[str] = "invocation_profile"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan UUID to resolve the effective invocation profile within.",
                },
                "role": {
                    "type": "string",
                    "description": "RuntimeRole value (C-011) used both as the optional role filter on candidate invocation_profile rows and as the target's role coordinate.",
                },
                "spec_level": {
                    "type": "string",
                    "description": "Optional spec level (HRS, MRS, GS, TS, AS) target for level-scope resolution.",
                },
                "branch_step": {
                    "type": "string",
                    "description": "Optional branch (GS) step UUID target for branch-scope resolution.",
                },
                "step": {
                    "type": "string",
                    "description": "Optional step UUID target for step-scope resolution.",
                },
            },
            "required": ["plan", "role"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters = dict(BASE_PARAMETERS)
        parameters["plan"] = {
            "type": "string",
            "description": "Plan UUID to resolve the effective invocation profile within.",
            "required": True,
        }
        parameters["role"] = {
            "type": "string",
            "description": "RuntimeRole value (C-011) used both as the optional role filter on candidate invocation_profile rows and as the target's role coordinate.",
            "required": True,
        }
        parameters["spec_level"] = {
            "type": "string",
            "description": "Optional spec level (HRS, MRS, GS, TS, AS) target for level-scope resolution.",
            "required": False,
        }
        parameters["branch_step"] = {
            "type": "string",
            "description": "Optional branch (GS) step UUID target for branch-scope resolution.",
            "required": False,
        }
        parameters["step"] = {
            "type": "string",
            "description": "Optional step UUID target for step-scope resolution.",
            "required": False,
        }

        return_value = {
            "description": "The InvocationProfileResolution record: the winning profile's own payload, source scope, source profile UUID, and inheritance path. Purely informational — nothing in CR-5a enforces the resolved profile's field values.",
            "type": "object",
        }

        examples = [
            {
                "description": "Resolve the effective invocation profile for as_author on a given plan.",
                "command": {
                    "plan": "b6b6b6b6-0000-0000-0000-000000000000",
                    "role": "as_author",
                },
            }
        ]

        best_practices = [
            "resolve is read-only: it reports the effective invocation profile without creating or mutating any record.",
            "plan and role are required; add spec_level, branch_step, or step to resolve at a more specific scope.",
            "Precedence follows system < plan < level < branch < step < role (C-010), reused unchanged for invocation profiles (C-008); the highest-ranked applicable profile wins.",
            "Inspect inheritance_path in the result to see every applicable candidate considered, not just the winner.",
            "Field values on the resolved profile are informational only in CR-5a; nothing in this command or the underlying resolver enforces them.",
        ]

        error_cases = {
            "PROFILE_RESOLUTION_FAILED": {
                "description": "No candidate invocation_profile record applies to the resolution target (C-008).",
                "message": "no applicable invocation profile for target",
                "solution": "Register an invocation_profile record at a scope that covers the target (system, plan, level, branch, step, or role), then retry.",
            }
        }

        return resolve_command_metadata(
            cls,
            parameters,
            return_value,
            examples,
            error_cases=error_cases,
            best_practices=best_practices,
        )

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
                candidates = list_profiles_for_resolution(conn, plan_uuid=plan_uuid)
                target = ProfileResolutionTarget(
                    role=validated_role,
                    plan_uuid=plan_uuid,
                    spec_level=spec_level,
                    branch_step_uuid=branch_step_uuid,
                    step_uuid=step_uuid,
                )
                try:
                    resolution = invocation_profile_resolve(candidates, target)
                except ProfileResolutionError as exc:
                    raise DomainCommandError("PROFILE_RESOLUTION_FAILED", str(exc)) from exc
                return SuccessResult(data=resolution.to_payload())
        except Exception as exc:
            return map_exception(exc)
