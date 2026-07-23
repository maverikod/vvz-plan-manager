"""Command: resolve the effective per-step role/toolset assignment along the six-scope specificity ladder (C-007, C-015)."""
from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve_command_metadata import resolve_command_metadata, BASE_PARAMETERS
from plan_manager.domain.model_binding import InvalidRuntimeRoleError
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.domain.step_assignment_resolution import (
    AssignmentTarget,
    StepAssignmentResolutionError,
    step_assignment_resolve,
)
from plan_manager.runtime.context import db_connection
from plan_manager.storage.step_assignment_store import list_for_resolution


class StepAssignmentResolveCommand(Command):
    name: ClassVar[str] = "step_assignment_resolve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Resolve the effective per-step role and toolset assignment along the six-scope specificity ladder (C-007)."
    category: ClassVar[str] = "step_assignment"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return JSON-schema for the command parameters."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan UUID to resolve the effective per-step assignment within.",
                },
                "role": {
                    "type": "string",
                    "description": "RuntimeRole value (C-011) used both as the optional role filter on candidate step_assignment rows and as the target's role coordinate.",
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
        """Return metadata for the command."""
        parameters = dict(BASE_PARAMETERS)
        parameters["plan"] = {
            "description": "Plan UUID to resolve the effective per-step assignment within.",
            "type": "string",
            "required": True,
        }
        parameters["role"] = {
            "description": "RuntimeRole value (C-011) used both as the optional role filter on candidate step_assignment rows and as the target's role coordinate.",
            "type": "string",
            "required": True,
        }
        parameters["spec_level"] = {
            "description": "Optional spec level (HRS, MRS, GS, TS, AS) target for level-scope resolution.",
            "type": "string",
            "required": False,
        }
        parameters["branch_step"] = {
            "description": "Optional branch (GS) step UUID target for branch-scope resolution.",
            "type": "string",
            "required": False,
        }
        parameters["step"] = {
            "description": "Optional step UUID target for step-scope resolution.",
            "type": "string",
            "required": False,
        }

        return_value = {
            "description": "The StepAssignmentResolution record: resolved assigned role, resolved toolset UUID, source scope, source assignment UUID, and inheritance path.",
            "type": "object",
        }

        examples = [
            {
                "description": "Resolve the effective per-step assignment for as_author on a given plan.",
                "command": {
                    "plan": "b6b6b6b6-0000-0000-0000-000000000000",
                    "role": "as_author",
                },
            }
        ]

        best_practices = [
            "resolve is read-only: it reports the effective per-step assignment without creating or mutating any record.",
            "plan and role are required; add spec_level, branch_step, or step to resolve at a more specific scope.",
            "Precedence follows system < plan < level < branch < step < role (C-010), reused unchanged for step assignment (C-007); the highest-ranked applicable assignment wins.",
            "Inspect inheritance_path in the result to see every applicable candidate considered, not just the winner.",
            "A step with no explicit assignment inherits along the ladder exactly as model bindings do; ensure at least a system- or plan-scope fallback assignment exists, or resolution raises.",
        ]

        error_cases = {
            "NO_APPLICABLE_ASSIGNMENT": {
                "description": "No candidate step_assignment record applies to the resolution target (C-007).",
                "message": "no applicable step assignment for target",
                "solution": "Register a step_assignment record at a scope that covers the target (system, plan, level, branch, step, or role), then retry.",
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
        """Execute the step_assignment_resolve command."""
        try:
            with db_connection() as conn:
                plan_uuid = validate_uuid(plan)
                try:
                    validated_role = validate_runtime_role(role)
                except RuntimeValidationError as exc:
                    raise InvalidRuntimeRoleError(str(exc)) from exc
                branch_step_uuid = validate_uuid(branch_step) if branch_step is not None else None
                step_uuid = validate_uuid(step) if step is not None else None
                candidates = list_for_resolution(conn, plan_uuid=plan_uuid)
                target = AssignmentTarget(
                    role=validated_role,
                    plan_uuid=plan_uuid,
                    spec_level=spec_level,
                    branch_step_uuid=branch_step_uuid,
                    step_uuid=step_uuid,
                )
                try:
                    resolution = step_assignment_resolve(candidates, target)
                except StepAssignmentResolutionError as exc:
                    raise DomainCommandError("NO_APPLICABLE_ASSIGNMENT", str(exc)) from exc
                return SuccessResult(data=resolution.to_payload())
        except Exception as exc:
            return map_exception(exc)
