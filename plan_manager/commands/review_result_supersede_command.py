"""Command: record that a stale review result was replaced by a specific
later review result, without touching the stale review's own status (bug
74479c06 group-4 fix; C-018, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.review_escalation_command_metadata import review_escalation_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.entity_supersede_store import supersede_review_result


class ReviewResultSupersedeCommand(Command):
    name: ClassVar[str] = "review_result_supersede"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Record that a stale review result was replaced by a specific later review result. "
        "Never rewrites the stale review's own status -- only the forward pointer."
    )
    category: ClassVar[str] = "review"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier (name or UUID)."},
                "review_uuid": {"type": "string", "description": "UUID of the STALE review result being superseded."},
                "superseded_by_uuid": {
                    "type": "string",
                    "description": "UUID of the REPLACEMENT review result; must review the same object_type as review_uuid and, for execution_attempt reviews, the same step.",
                },
                "changed_by": {"type": "string", "description": "Actor recording this supersede."},
            },
            "required": ["plan", "review_uuid", "superseded_by_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "review_uuid": {"description": "UUID of the STALE review result being superseded.", "type": "string", "required": True},
            "superseded_by_uuid": {"description": "UUID of the REPLACEMENT review result.", "type": "string", "required": True},
            "changed_by": {"description": "Actor recording this supersede.", "type": "string", "required": True},
        }
        return review_escalation_metadata(
            cls,
            params,
            {"success": {"description": (
                "The stale review result record after the write, with an additional already_superseded "
                "boolean: true when the call was an idempotent no-op against an already-matching "
                "superseded_by_uuid."
            )}},
            [{
                "description": "Record that a corrected review superseded a stale one.",
                "command": {
                    "plan": "plan_manager",
                    "review_uuid": "c2a3b4c5-1111-2222-3333-444455556666",
                    "superseded_by_uuid": "d3b4c5d6-2222-3333-4444-555566667777",
                    "changed_by": "ts-owner-sonnet",
                },
            }],
            best_practices=[
                "The stale review's own status is never rewritten by this command -- only superseded_by_uuid changes; the original verdict stays on record exactly as it was rendered.",
                "superseded_by_uuid must review the same object_type as review_uuid, and, when both review execution attempts, the two reviewed attempts must share a step; otherwise refused as REVIEW_RESULT_LINEAGE_MISMATCH.",
                "Calling again with the SAME superseded_by_uuid already on file is idempotent (already_superseded: true, nothing written); calling with a DIFFERENT value is refused as REVIEW_RESULT_ALREADY_SUPERSEDED rather than silently overwriting the pointer.",
                "review_uuid and superseded_by_uuid must be different review results; passing the same uuid for both is refused as REVIEW_RESULT_SELF_SUPERSEDE.",
            ],
        )

    _UUID_FIELDS: ClassVar[tuple[str, ...]] = ("review_uuid", "superseded_by_uuid")

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate review_result_supersede parameters beyond the base schema check.

        Raises:
            InvalidParamsError: If review_uuid or superseded_by_uuid is not a valid UUID string.
        """
        params = super().validate_params(params)
        for field in self._UUID_FIELDS:
            value = params.get(field)
            if value is not None:
                try:
                    uuid.UUID(value)
                except ValueError as exc:
                    raise InvalidParamsError(f"{field} is not a valid UUID: {value!r}") from exc
        return params

    async def execute(
        self,
        plan: str,
        review_uuid: str,
        superseded_by_uuid: str,
        changed_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                record, already_superseded = supersede_review_result(
                    conn,
                    uuid.UUID(review_uuid),
                    superseded_by_uuid=uuid.UUID(superseded_by_uuid),
                    changed_by=changed_by,
                )
                payload = record.to_payload()
                payload["already_superseded"] = already_superseded
                return SuccessResult(data=payload)
        except Exception as exc:
            return map_exception(exc)
