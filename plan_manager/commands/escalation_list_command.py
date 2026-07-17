"""Command: list escalations with optional status/anchor filtering and pagination (C-037, C-029, C-030)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.review_escalation_command_metadata import review_escalation_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_command_metadata import filter_schema_properties, filter_metadata_params, pagination_schema_properties, pagination_metadata_params
from plan_manager.commands.runtime_filtering import parse_filters, parse_pagination
from plan_manager.domain.escalation import ESCALATION_STATUSES
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.escalation_store import list_escalations

_STATUS_ENUM = sorted(ESCALATION_STATUSES)


class EscalationListCommand(Command):
    name: ClassVar[str] = "escalation_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List escalations with optional status/anchor filtering and pagination."
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
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or UUID). Scopes the listing: only escalations whose anchor_plan_uuid equals the resolved plan are returned; escalations anchored to other plans or with no plan anchor (anchor_plan_uuid NULL) are excluded. No transitive matching is performed.",
                },
                **filter_schema_properties(["status"], enum_overrides={"status": _STATUS_ENUM}),
                "anchor_ref_id": {"type": "string", "description": "UUID of the anchor_ref_id to filter escalations by."},
                "include_deleted": {"type": "boolean", "description": "When true, include soft-deleted escalations.", "default": False},
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "plan": {
                "description": "Plan identifier (name or UUID). Scopes the listing: only escalations whose anchor_plan_uuid equals the resolved plan are returned; escalations anchored to other plans or with no plan anchor (anchor_plan_uuid NULL) are excluded. No transitive matching is performed.",
                "type": "string",
                "required": True,
            },
            **filter_metadata_params(["status"], enum_overrides={"status": _STATUS_ENUM}),
            "anchor_ref_id": {"description": "UUID of the anchor_ref_id to filter escalations by.", "type": "string", "required": False},
            "include_deleted": {"description": "When true, include soft-deleted escalations.", "type": "boolean", "required": False, "default": False},
            **pagination_metadata_params(),
        }
        return review_escalation_metadata(
            cls,
            params,
            {"success": {"description": "A page of escalation payloads plus total/limit/offset."}},
            [{
                "description": "List open escalations for a plan.",
                "command": {"plan": "plan_manager", "status": "open"},
            }],
            best_practices=[
                "The required plan parameter scopes the listing by direct anchor: only escalations with anchor_plan_uuid equal to the resolved plan are returned; NULL and foreign plan anchors are excluded (no transitive matching via anchor_ref_id or other anchor fields).",
                "A nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "Use status='open' to find escalations awaiting a decision.",
                "anchor_ref_id filters by the escalation's anchor_ref_id column, not by escalation_uuid.",
                "Set include_deleted=True to also see soft-deleted escalations; the default excludes them.",
                "Use limit/offset for pagination and compare offset+limit against total to detect more pages.",
            ],
        )

    async def execute(
        self,
        plan: str,
        status: str | None = None,
        anchor_ref_id: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                plan_record = resolve_plan(conn, plan)
                raw_params = {"status": status, "limit": limit, "offset": offset}
                filters = parse_filters(raw_params, ["status"], enums={"status": ESCALATION_STATUSES})
                pagination = parse_pagination(raw_params)
                anchor_uuid = validate_uuid(anchor_ref_id) if anchor_ref_id is not None else None
                escalations = list_escalations(
                    conn,
                    status=filters.get("status"),
                    anchor_ref_id=anchor_uuid,
                    anchor_plan_uuid=plan_record.uuid,
                    include_deleted=include_deleted,
                )
                total = len(escalations)
                page = escalations[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "escalations": [e.to_payload() for e in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
