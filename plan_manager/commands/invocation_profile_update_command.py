"""Command: patch the mutable informational fields of an existing invocation profile record (C-008, C-015)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.invocation_profile_command_metadata import invocation_profile_metadata
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.invocation_profile_store import get_invocation_profile, update_invocation_profile


class InvocationProfileUpdateCommand(Command):
    name: ClassVar[str] = "invocation_profile_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Patch the mutable informational fields of an existing invocation profile record (C-008) in place."
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
                "profile_uuid": {"description": "The profile_uuid identifier of the invocation_profile record to patch.", "type": "string"},
                "changed_by": {"description": "The actor patching this invocation profile.", "type": "string"},
                "step_path": {"description": "New diagnostic display snapshot of the step path.", "type": "string"},
                "temperature": {"description": "New informational sampling temperature.", "type": "number"},
                "top_p": {"description": "New informational nucleus-sampling top_p.", "type": "number"},
                "max_output_tokens": {"description": "New informational maximum output token count.", "type": "integer"},
                "reasoning_effort": {"description": "New informational reasoning effort or budget label.", "type": "string"},
                "context_window_budget": {"description": "New informational context-window token budget.", "type": "integer"},
                "timeout": {"description": "New informational timeout in seconds.", "type": "integer"},
                "retry_policy": {"description": "New informational retry policy object.", "type": "object"},
                "concurrency": {"description": "New informational concurrency hint.", "type": "integer"},
                "rate_hint": {"description": "New informational rate-limit hint object for batch waves.", "type": "object"},
                "response_format": {"description": "New informational response-format flag.", "type": "string"},
                "response_schema": {"description": "New informational response schema object.", "type": "object"},
                "max_tool_iterations": {"description": "New informational maximum tool-call iteration count.", "type": "integer"},
                "per_call_timeout": {"description": "New informational per-call timeout in seconds.", "type": "integer"},
                "execution_mode": {"description": "New informational execution mode. One of: interactive, batch.", "type": "string"},
                "token_budget": {"description": "New informational per-step token budget.", "type": "integer"},
                "cost_budget": {"description": "New informational per-step cost budget.", "type": "number"},
                "dialogue_chain_ref": {"description": "New reserved dialogue-chain reference UUID.", "type": "string"},
                "active": {"description": "New active flag for this invocation profile.", "type": "boolean"},
            },
            "required": ["profile_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        parameters: dict[str, Any] = {
            "profile_uuid": {"description": "The profile_uuid identifier of the invocation_profile record to patch.", "type": "string", "required": True},
            "changed_by": {"description": "The actor patching this invocation profile.", "type": "string", "required": True},
            "step_path": {"description": "New diagnostic display snapshot of the step path.", "type": "string", "required": False},
            "temperature": {"description": "New informational sampling temperature.", "type": "number", "required": False},
            "top_p": {"description": "New informational nucleus-sampling top_p.", "type": "number", "required": False},
            "max_output_tokens": {"description": "New informational maximum output token count.", "type": "integer", "required": False},
            "reasoning_effort": {"description": "New informational reasoning effort or budget label.", "type": "string", "required": False},
            "context_window_budget": {"description": "New informational context-window token budget.", "type": "integer", "required": False},
            "timeout": {"description": "New informational timeout in seconds.", "type": "integer", "required": False},
            "retry_policy": {"description": "New informational retry policy object.", "type": "object", "required": False},
            "concurrency": {"description": "New informational concurrency hint.", "type": "integer", "required": False},
            "rate_hint": {"description": "New informational rate-limit hint object for batch waves.", "type": "object", "required": False},
            "response_format": {"description": "New informational response-format flag.", "type": "string", "required": False},
            "response_schema": {"description": "New informational response schema object.", "type": "object", "required": False},
            "max_tool_iterations": {"description": "New informational maximum tool-call iteration count.", "type": "integer", "required": False},
            "per_call_timeout": {"description": "New informational per-call timeout in seconds.", "type": "integer", "required": False},
            "execution_mode": {"description": "New informational execution mode. One of: interactive, batch.", "type": "string", "required": False},
            "token_budget": {"description": "New informational per-step token budget.", "type": "integer", "required": False},
            "cost_budget": {"description": "New informational per-step cost budget.", "type": "number", "required": False},
            "dialogue_chain_ref": {"description": "New reserved dialogue-chain reference UUID.", "type": "string", "required": False},
            "active": {"description": "New active flag for this invocation profile.", "type": "boolean", "required": False},
        }
        return_value = {"description": "The patched InvocationProfile record.", "type": "object"}
        examples = [
            {"description": "Patch a profile's temperature and token budget.", "command": {"profile_uuid": "b6b6b6b6-0000-0000-0000-000000000000", "changed_by": "owner", "temperature": 0.5, "token_budget": 20000}}
        ]
        best_practices = [
            "Only the fields supplied are patched; omitted fields keep their current stored value.",
            "At least one mutable field beyond profile_uuid and changed_by must be supplied, or the call fails with RUNTIME_VALIDATION_ERROR.",
            "scope, role, plan_uuid, spec_level, branch_step_uuid, step_uuid, and revision_uuid are immutable identity fields and cannot be patched; remove and re-create the profile to change them.",
            "execution_mode, when supplied, must be one of 'interactive' or 'batch'.",
            "Re-read with invocation_profile_get after the call to confirm the patch was applied as expected.",
        ]
        return invocation_profile_metadata(cls, parameters, return_value, examples, best_practices=best_practices)

    async def execute(
        self,
        profile_uuid: str,
        changed_by: str,
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
        active: bool | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                parsed_uuid = validate_uuid(profile_uuid)
                existing = get_invocation_profile(conn, parsed_uuid)
                if existing is None:
                    raise DomainCommandError("INVOCATION_PROFILE_NOT_FOUND", f"invocation profile not found: {profile_uuid}")
                if all(
                    value is None
                    for value in (
                        step_path, temperature, top_p, max_output_tokens, reasoning_effort,
                        context_window_budget, timeout, retry_policy, concurrency, rate_hint,
                        response_format, response_schema, max_tool_iterations, per_call_timeout,
                        execution_mode, token_budget, cost_budget, dialogue_chain_ref, active,
                    )
                ):
                    raise RuntimeValidationError("invocation_profile_update requires at least one mutable field to patch")
                dialogue_chain_uuid = validate_uuid(dialogue_chain_ref) if dialogue_chain_ref is not None else None
                profile = update_invocation_profile(
                    conn,
                    parsed_uuid,
                    changed_by=changed_by,
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
