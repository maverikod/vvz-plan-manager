"""Command: resolve an open escalation (C-037, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.review_escalation_command_metadata import review_escalation_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.escalation_store import resolve_escalation


class EscalationResolveCommand(Command):
    name: ClassVar[str] = "escalation_resolve"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Resolve an open escalation, recording the resolution and the resolving owner."
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
                "escalation_uuid": {"type": "string", "description": "UUID of the escalation to resolve."},
                "resolved_by": {"type": "string", "description": "Actor recorded as resolving this escalation."},
                "resolution": {"type": "string", "description": "Resolution text recorded on the escalation."},
            },
            "required": ["plan", "escalation_uuid", "resolved_by", "resolution"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "escalation_uuid": {"description": "UUID of the escalation to resolve.", "type": "string", "required": True},
            "resolved_by": {"description": "Actor recorded as resolving this escalation.", "type": "string", "required": True},
            "resolution": {"description": "Resolution text recorded on the escalation.", "type": "string", "required": True},
        }
        return review_escalation_metadata(
            cls,
            params,
            {"success": {"description": "The resolved escalation payload, with status resolved, resolution, resolved_by, and resolved_at set."}},
            [{
                "description": "Resolve an open escalation with the owner's decision.",
                "command": {
                    "plan": "plan_manager",
                    "escalation_uuid": "d3e4f5a6-1111-2222-3333-444455556666",
                    "resolved_by": "gs-owner-opus",
                    "resolution": "Accepted with a follow-up TODO to tighten the retry limit.",
                },
            }],
            best_practices=[
                "escalation_uuid must reference an existing, non-deleted escalation; soft-deleted escalations raise an error.",
                "resolve_escalation does not check whether the escalation is already resolved, so resolving twice silently overwrites the prior resolution.",
                "resolved_by should be the owner identity at the escalation's to_level, per the owner review ladder.",
                "resolution should record the concrete decision taken, not just confirmation of receipt — it becomes the permanent record of the ruling.",
            ],
        )

    async def execute(
        self, plan: str, escalation_uuid: str, resolved_by: str, resolution: str, context: object | None = None
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                record = resolve_escalation(
                    conn, uuid.UUID(escalation_uuid), resolved_by=resolved_by, resolution=resolution
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
