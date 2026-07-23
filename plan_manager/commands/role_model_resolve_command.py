"""Command: resolve the effective (provider, model) for a role from active providers, model-level candidates, explicit model bindings, and the manual role-model level relation (C-006, C-015)."""
from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve_command_metadata import resolve_command_metadata, BASE_PARAMETERS
from plan_manager.domain.model_binding import InvalidRuntimeRoleError
from plan_manager.domain.model_resolution import ResolutionTarget, binding_applies
from plan_manager.domain.role_model_binding import RoleModelBinding
from plan_manager.domain.role_model_resolution import (
    CandidateModel,
    RoleModelResolutionError,
    RoleModelResolutionTarget,
    role_model_resolve,
)
from plan_manager.domain.runtime_role import validate_runtime_role
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.model_binding_store import list_bindings_for_resolution
from plan_manager.storage.model_store import list_models
from plan_manager.storage.provider_store import list_providers
from plan_manager.storage.role_model_binding_store import list_for_resolution as list_role_bindings_for_resolution


class RoleModelResolveCommand(Command):
    name: ClassVar[str] = "role_model_resolve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Resolve the effective (provider, model) for a role from active providers, explicit model bindings, and the manual role-model level relation (C-006)."
    category: ClassVar[str] = "role_model"
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
                    "description": "Plan UUID to resolve the effective role-model within.",
                },
                "role": {
                    "type": "string",
                    "description": "RuntimeRole value (C-011) to resolve the effective model for.",
                },
                "step_required_level": {
                    "type": "string",
                    "description": "Optional step-declared required model level; feeds the step-level-requirement resolution step when no explicit binding applies. There is no separate step-level-requirement store in this plan — the caller supplies this value directly.",
                },
                "phase": {
                    "type": "string",
                    "description": "Optional phase selector used to pick the matching role_model_binding as the role-default candidate; a phase-specific binding wins over a phase-generic (phase=None) one. See _select_role_default_binding.",
                },
                "spec_level": {
                    "type": "string",
                    "description": "Optional spec level (HRS, MRS, GS, TS, AS) target for level-scope explicit-binding filtering.",
                },
                "branch_step": {
                    "type": "string",
                    "description": "Optional branch (GS) step UUID target for branch-scope explicit-binding filtering.",
                },
                "step": {
                    "type": "string",
                    "description": "Optional step UUID target for step-scope explicit-binding filtering.",
                },
            },
            "required": ["plan", "role"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters = dict(BASE_PARAMETERS)
        parameters.update({
            "plan": {
                "description": "Plan UUID to resolve the effective role-model within.",
                "type": "string",
                "required": True,
            },
            "role": {
                "description": "RuntimeRole value (C-011) to resolve the effective model for.",
                "type": "string",
                "required": True,
            },
            "step_required_level": {
                "description": "Optional step-declared required model level; feeds the step-level-requirement resolution step when no explicit binding applies. There is no separate step-level-requirement store in this plan — the caller supplies this value directly.",
                "type": "string",
                "required": False,
            },
            "phase": {
                "description": "Optional phase selector used to pick the matching role_model_binding as the role-default candidate; a phase-specific binding wins over a phase-generic (phase=None) one. See _select_role_default_binding.",
                "type": "string",
                "required": False,
            },
            "spec_level": {
                "description": "Optional spec level (HRS, MRS, GS, TS, AS) target for level-scope explicit-binding filtering.",
                "type": "string",
                "required": False,
            },
            "branch_step": {
                "description": "Optional branch (GS) step UUID target for branch-scope explicit-binding filtering.",
                "type": "string",
                "required": False,
            },
            "step": {
                "description": "Optional step UUID target for step-scope explicit-binding filtering.",
                "type": "string",
                "required": False,
            },
        })
        return_value = {
            "description": "The RoleModelResolutionResult record: source (explicit_binding|step_requirement|role_default), chosen provider, chosen model, chosen level, and provenance.",
            "type": "object",
        }
        examples = [
            {
                "description": "Resolve the effective role-model for as_author on a given plan.",
                "command": {
                    "plan": "b6b6b6b6-0000-0000-0000-000000000000",
                    "role": "as_author",
                },
            }
        ]
        best_practices = [
            "resolve is read-only: it reports the effective role-model without creating or mutating any record.",
            "plan and role are required; step_required_level and phase refine which candidate wins at the step-requirement and role-default steps respectively.",
            "Resolution order is fixed: explicit model binding, then step-level requirement, then role default (C-006); inspect provenance to see which source won.",
            "Ensure at least one active provider carries a model of the level a role or step requires, or resolution raises.",
        ]
        error_cases = {
            "ROLE_MODEL_RESOLUTION_FAILED": {
                "description": "No explicit model binding, step-level requirement, or active role-default binding applies to the target (C-006).",
                "message": "no explicit model binding, step-level requirement, or active role-default binding for role {role}",
                "solution": "Register an explicit model binding, supply step_required_level, or create an active role_model_binding for the role/phase before retrying.",
            }
        }
        return resolve_command_metadata(
            cls, parameters, return_value, examples, error_cases=error_cases, best_practices=best_practices
        )

    async def execute(
        self,
        plan: str,
        role: str,
        step_required_level: str | None = None,
        phase: str | None = None,
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

                binding_target = ResolutionTarget(
                    role=validated_role,
                    plan_uuid=plan_uuid,
                    spec_level=spec_level,
                    branch_step_uuid=branch_step_uuid,
                    step_uuid=step_uuid,
                )
                all_bindings = list_bindings_for_resolution(conn, plan_uuid=plan_uuid)
                explicit_bindings = tuple(b for b in all_bindings if binding_applies(b, binding_target))

                role_bindings = list_role_bindings_for_resolution(conn, validated_role)
                role_default_binding = _select_role_default_binding(role_bindings, phase)

                active_providers = list_providers(conn, status="active")
                provider_name_by_uuid = {p.provider_uuid: p.name for p in active_providers}
                candidates = [
                    CandidateModel(name=m.name, level=m.level, provider=provider_name_by_uuid[m.provider_uuid], provider_active=True)
                    for m in list_models(conn)
                    if m.provider_uuid in provider_name_by_uuid
                ]

                target = RoleModelResolutionTarget(
                    role=validated_role,
                    phase=phase,
                    step_required_level=step_required_level,
                    role_default_binding=role_default_binding,
                    explicit_bindings=explicit_bindings,
                )
                try:
                    resolution = role_model_resolve(target, candidates)
                except RoleModelResolutionError as exc:
                    raise DomainCommandError("ROLE_MODEL_RESOLUTION_FAILED", str(exc)) from exc
                return SuccessResult(data=resolution.to_payload())
        except Exception as exc:
            return map_exception(exc)


def _select_role_default_binding(bindings: list[RoleModelBinding], phase: str | None) -> RoleModelBinding | None:
    """Pick the RoleModelBinding to pass as RoleModelResolutionTarget.role_default_binding.

    `bindings` is already filtered to active, non-deleted rows for one role by
    role_model_binding_store.list_for_resolution, ordered by created_at ascending.

    Preference: the most recently created binding whose phase equals the
    requested `phase` (last element of the ascending-order phase match list);
    if none match (or phase is None), the most recently created binding whose
    phase is None (the phase-generic default); otherwise None (role_model_resolve
    then falls through to raising RoleModelResolutionError unless step_required_level
    or an explicit binding is available).
    """
    if phase is not None:
        phase_matches = [b for b in bindings if b.phase == phase]
        if phase_matches:
            return phase_matches[-1]
    generic = [b for b in bindings if b.phase is None]
    if generic:
        return generic[-1]
    return None
