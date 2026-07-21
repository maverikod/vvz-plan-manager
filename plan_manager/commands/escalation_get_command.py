"""Command: retrieve a single escalation by identifier (C-037, C-029)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.review_escalation_command_metadata import review_escalation_metadata, BASE_PARAMETERS
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.escalation_store import get_escalation

class EscalationGetCommand(Command):
    name: ClassVar[str] = "escalation_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Retrieve a single escalation by its identifier."
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
                "escalation_uuid": {"type": "string", "description": "UUID of the escalation to retrieve."},
            },
            "required": ["plan", "escalation_uuid"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "escalation_uuid": {"description": "UUID of the escalation to retrieve.", "type": "string", "required": True},
        }
        return review_escalation_metadata(
            cls,
            params,
            {"success": {"description": "The retrieved escalation payload, including escalation_uuid, anchor fields, reason, from_level, to_level, status, and (when resolved) resolution/resolved_by/resolved_at."}},
            [{
                "description": "Fetch an escalation by its uuid.",
                "command": {
                    "plan": "plan_manager",
                    "escalation_uuid": "d3e4f5a6-1111-2222-3333-444455556666",
                },
            }],
            best_practices=[
                "escalation_uuid must be the escalation's own identifier, not the anchor_ref_id it is attached to.",
                "get_escalation returns soft-deleted escalations too; check the deleted_at field in the payload to know if an escalation is still active.",
                "Use escalation_list first when the exact escalation_uuid is unknown.",
            ],
        )

    async def execute(
        self, plan: str, escalation_uuid: str, context: object | None = None
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                parsed_uuid = validate_uuid(escalation_uuid)
                record = get_escalation(conn, parsed_uuid)
                if record is None:
                    raise DomainCommandError("ESCALATION_NOT_FOUND", f"escalation not found: {escalation_uuid}")
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
