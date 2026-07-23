"""Command: create an invocation profile runtime-configuration record (C-008, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.invocation_profile_command_metadata import invocation_profile_metadata, BASE_PARAMETERS
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.invocation_profile_store import create_invocation_profile


class InvocationProfileCreateCommand(Command):
    name: ClassVar[str] = "invocation_profile_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create an invocation profile runtime-configuration record (C-008) for the given scope."
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
                "scope": {"description": "BindingScope value (C-010 inheritance level, reused unchanged from model bindings): system, plan, level, branch, step, or role.", "type": "string"},
                "created_by": {"description": "Actor creating this invocation profile.", "type": "string"},
                "role": {"description": "Optional RuntimeRole value (C-011) restricting this profile to one role.", "type": "string"},
                "plan": {"description": "Plan UUID this invocation profile applies to. Required for scope plan/level/branch/step; optional for scope role; must be omitted for scope system.", "type": "string"},
                "spec_level": {"description": "One of HRS, MRS, GS, TS, AS. Required when scope is level; omitted otherwise.", "type": "string"},
                "branch_step": {"description": "UUID of the branch (GS) step. Required when scope is branch; omitted otherwise.", "type": "string"},
                "revision": {"description": "Optional revision UUID, applicable only when scope is step.", "type": "string"},
                "step": {"description": "UUID of the step. Required when scope is step; omitted otherwise.", "type": "string"},
                "step_path": {"description": "Optional diagnostic display snapshot of the step path, applicable only when scope is step.", "type": "string"},
                "temperature": {"description": "Optional informational sampling temperature.", "type": "number"},
                "top_p": {"description": "Optional informational nucleus-sampling top_p.", "type": "number"},
                "max_output_tokens": {"description": "Optional informational maximum output token count.", "type": "integer"},
                "reasoning_effort": {"description": "Optional informational reasoning effort or budget label.", "type": "string"},
                "context_window_budget": {"description": "Optional informational context-window token budget.", "type": "integer"},
                "timeout": {"description": "Optional informational timeout in seconds.", "type": "integer"},
                "retry_policy": {"description": "Optional informational retry policy object.", "type": "object"},
                "concurrency": {"description": "Optional informational concurrency hint.", "type": "integer"},
                "rate_hint": {"description": "Optional informational rate-limit hint object for batch waves.", "type": "object"},
                "response_format": {"description": "Optional informational response-format flag.", "type": "string"},
                "response_schema": {"description": "Optional informational response schema object, applicable when response_format designates a structured format.", "type": "object"},
                "max_tool_iterations": {"description": "Optional informational maximum tool-call iteration count.", "type": "integer"},
                "per_call_timeout": {"description": "Optional informational per-call timeout in seconds.", "type": "integer"},
                "execution_mode": {"description": "Optional informational execution mode. One of: interactive, batch.", "type": "string"},
                "token_budget": {"description": "Optional informational per-step token budget.", "type": "integer"},
                "cost_budget": {"description": "Optional informational per-step cost budget.", "type": "number"},
                "dialogue_chain_ref": {"description": "Optional reserved dialogue-chain reference UUID.", "type": "string"},
                "active": {"description": "Whether the invocation profile is active.", "type": "boolean", "default": True},
            },
            "required": ["scope", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = dict(BASE_PARAMETERS)
        parameters["plan"] = {"description": "Plan UUID this invocation profile applies to. Required for scope plan/level/branch/step; optional for scope role; must be omitted for scope system.", "type": "string", "required": False}
        parameters["scope"] = {"description": "BindingScope value (C-010 inheritance level, reused unchanged from model bindings): system, plan, level, branch, step, or role.", "type": "string", "required": True}
        parameters["created_by"] = {"description": "Actor creating this invocation profile.", "type": "string", "required": True}
        parameters["role"] = {"description": "Optional RuntimeRole value (C-011) restricting this profile to one role.", "type": "string", "required": False}
        parameters["spec_level"] = {"description": "One of HRS, MRS, GS, TS, AS. Required when scope is level; omitted otherwise.", "type": "string", "required": False}
        parameters["branch_step"] = {"description": "UUID of the branch (GS) step. Required when scope is branch; omitted otherwise.", "type": "string", "required": False}
        parameters["revision"] = {"description": "Optional revision UUID, applicable only when scope is step.", "type": "string", "required": False}
        parameters["step"] = {"description": "UUID of the step. Required when scope is step; omitted otherwise.", "type": "string", "required": False}
        parameters["step_path"] = {"description": "Optional diagnostic display snapshot of the step path, applicable only when scope is step.", "type": "string", "required": False}
        parameters["temperature"] = {"description": "Optional informational sampling temperature.", "type": "number", "required": False}
        parameters["top_p"] = {"description": "Optional informational nucleus-sampling top_p.", "type": "number", "required": False}
        parameters["max_output_tokens"] = {"description": "Optional informational maximum output token count.", "type": "integer", "required": False}
        parameters["reasoning_effort"] = {"description": "Optional informational reasoning effort or budget label.", "type": "string", "required": False}
        parameters["context_window_budget"] = {"description": "Optional informational context-window token budget.", "type": "integer", "required": False}
        parameters["timeout"] = {"description": "Optional informational timeout in seconds.", "type": "integer", "required": False}
        parameters["retry_policy"] = {"description": "Optional informational retry policy object.", "type": "object", "required": False}
        parameters["concurrency"] = {"description": "Optional informational concurrency hint.", "type": "integer", "required": False}
        parameters["rate_hint"] = {"description": "Optional informational rate-limit hint object for batch waves.", "type": "object", "required": False}
        parameters["response_format"] = {"description": "Optional informational response-format flag.", "type": "string", "required": False}
        parameters["response_schema"] = {"description": "Optional informational response schema object, applicable when response_format designates a structured format.", "type": "object", "required": False}
        parameters["max_tool_iterations"] = {"description": "Optional informational maximum tool-call iteration count.", "type": "integer", "required": False}
        parameters["per_call_timeout"] = {"description": "Optional informational per-call timeout in seconds.", "type": "integer", "required": False}
        parameters["execution_mode"] = {"description": "Optional informational execution mode. One of: interactive, batch.", "type": "string", "required": False}
        parameters["token_budget"] = {"description": "Optional informational per-step token budget.", "type": "integer", "required": False}
        parameters["cost_budget"] = {"description": "Optional informational per-step cost budget.", "type": "number", "required": False}
        parameters["dialogue_chain_ref"] = {"description": "Optional reserved dialogue-chain reference UUID.", "type": "string", "required": False}
        parameters["active"] = {"description": "Whether the invocation profile is active. Defaults to true.", "type": "boolean", "required": False}
        return_value = {"description": "The created InvocationProfile record.", "type": "object"}
        examples = [
            {
                "description": "Create a role-scoped invocation profile for as_author.",
                "command": {"scope": "role", "role": "as_author", "created_by": "owner", "temperature": 0.2, "max_output_tokens": 4096},
            }
        ]
        best_practices = [
            "Choose the narrowest applicable scope (role > step > branch > level > plan > system) so the override targets intent precisely, matching the model-binding resolve pattern.",
            "Supply only the companion fields required by the chosen scope: system needs none, plan needs plan, level needs plan+spec_level, branch needs plan+branch_step, step needs plan+step.",
            "Set role to restrict a profile to one RuntimeRole (e.g. as_author); omit role to apply the profile to every role.",
            "All generation, timeout, retry, concurrency, response-format, and budget fields are purely informational in this release: nothing enforces them (user order 2026-07-16).",
            "execution_mode, when supplied, must be one of 'interactive' or 'batch'.",
        ]
        return invocation_profile_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        scope: str,
        created_by: str,
        role: str | None = None,
        plan: str | None = None,
        spec_level: str | None = None,
        branch_step: str | None = None,
        revision: str | None = None,
        step: str | None = None,
        step_path: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_output_tokens: int | None = None,
        reasoning_effort: str | None = None,
        context_window_budget: int | None = None,
        timeout: int | None = None,
        retry_policy: dict[str, Any] | None = None,
        concurrency: int | None = None,
        rate_hint: dict[str, Any] | None = None,
        response_format: str | None = None,
        response_schema: dict[str, Any] | None = None,
        max_tool_iterations: int | None = None,
        per_call_timeout: int | None = None,
        execution_mode: str | None = None,
        token_budget: int | None = None,
        cost_budget: float | None = None,
        dialogue_chain_ref: str | None = None,
        active: bool = True,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_uuid = validate_uuid(plan) if plan is not None else None
                branch_step_uuid = validate_uuid(branch_step) if branch_step is not None else None
                revision_uuid = validate_uuid(revision) if revision is not None else None
                step_uuid = validate_uuid(step) if step is not None else None
                dialogue_chain_uuid = validate_uuid(dialogue_chain_ref) if dialogue_chain_ref is not None else None
                profile = create_invocation_profile(
                    conn,
                    scope=scope,
                    created_by=created_by,
                    role=role,
                    plan_uuid=plan_uuid,
                    spec_level=spec_level,
                    branch_step_uuid=branch_step_uuid,
                    revision_uuid=revision_uuid,
                    step_uuid=step_uuid,
                    step_path=step_path,
                    temperature=temperature,
                    top_p=top_p,
                    max_output_tokens=max_output_tokens,
                    reasoning_effort=reasoning_effort,
                    context_window_budget=context_window_budget,
                    timeout=timeout,
                    retry_policy=retry_policy,
                    concurrency=concurrency,
                    rate_hint=rate_hint,
                    response_format=response_format,
                    response_schema=response_schema,
                    max_tool_iterations=max_tool_iterations,
                    per_call_timeout=per_call_timeout,
                    execution_mode=execution_mode,
                    token_budget=token_budget,
                    cost_budget=cost_budget,
                    dialogue_chain_ref=dialogue_chain_uuid,
                    active=active,
                )
                return SuccessResult(data=profile.to_payload())
        except Exception as exc:
            return map_exception(exc)
