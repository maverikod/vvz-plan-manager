"""Read-only verification command comparing a produced artifact against a
frozen step prompt (C-006), reusing the shipped per-field content-hashing
foundation (C-007) unchanged.
"""
from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.step_prompt_verify_metadata import get_step_prompt_verify_metadata
from plan_manager.commands.step_ref import canonical_step_path, resolve_step_ref
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import load_steps
from plan_manager.views.step_prompt_verify import (
    compare_verdict,
    resolve_candidate_bytes,
    resolve_target_content,
)


class StepPromptVerifyCommand(Command):
    """Server-side byte/hash verification of a produced artifact against a frozen step prompt."""

    name: ClassVar[str] = "step_prompt_verify"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Server-side byte/hash verification of a produced artifact against a frozen step prompt: never mutates a step."
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return JSON schema for command parameters."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or uuid) resolved against the catalog.",
                },
                "step": {
                    "type": "string",
                    "description": "Step reference (uuid, canonical path, or step_id) of the frozen step to verify against.",
                },
                "candidate_base64": {
                    "type": "string",
                    "description": "Candidate artifact content as standard base64 text; provide either this or candidate_sha256, not both.",
                },
                "candidate_sha256": {
                    "type": "string",
                    "description": "Candidate artifact content as a precomputed lowercase hex sha256 digest; provide either this or candidate_base64, not both.",
                },
                "field": {
                    "type": "string",
                    "description": "Optional step field name to narrow the comparison to one field; omit to compare the whole step content.",
                },
                "block_index": {
                    "type": "integer",
                    "description": "Optional 0-based index of a fenced code block within the named field's text to narrow the comparison further; requires field to be given.",
                },
            },
            "required": ["plan", "step"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return command metadata."""
        return get_step_prompt_verify_metadata(cls)

    async def execute(
        self,
        plan: str,
        step: str,
        candidate_base64: str | None = None,
        candidate_sha256: str | None = None,
        field: str | None = None,
        block_index: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Execute the read-only step-prompt verification.

        Returns a single match verdict object; never mutates the step.
        """
        try:
            if block_index is not None and field is None:
                raise DomainCommandError(
                    "UNKNOWN_STEP_SELECTOR", "block_index requires field to be given"
                )
            try:
                candidate_bytes, candidate_digest = resolve_candidate_bytes(
                    candidate_base64, candidate_sha256
                )
            except ValueError as exc:
                raise DomainCommandError("INVALID_CANDIDATE_CONTENT", str(exc)) from exc
            with db_connection() as conn:
                plan_obj = resolve_plan(conn, plan)
                nodes = load_steps(conn, plan_obj.uuid)
                resolved_step = resolve_step_ref(nodes, step)
                try:
                    target_content, canonical_hash = resolve_target_content(
                        resolved_step, field, block_index
                    )
                except (KeyError, ValueError) as exc:
                    raise DomainCommandError("UNKNOWN_STEP_SELECTOR", str(exc)) from exc
                verdict = compare_verdict(
                    target_content, candidate_bytes, candidate_digest, canonical_hash
                )
                data = {
                    "step": canonical_step_path(nodes, resolved_step),
                    "field": field,
                    "block_index": block_index,
                    **verdict,
                }
            return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
