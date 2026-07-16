"""Command: list read-only runtime audit log entries filtered by actor, action, entity, plan, and time window, under uniform pagination (C-009, C-010, C-011)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_command_metadata import runtime_metadata
from plan_manager.commands.runtime_filtering import (
    filter_schema_properties,
    pagination_schema_properties,
    parse_filters,
    parse_pagination,
)
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_audit_store import ALLOWED_ACTIONS, count_runtime_audit, list_runtime_audit

AUDIT_LIST_FILTER_FIELDS = ["actor", "action", "entity_type", "entity_id", "plan", "created_after", "created_before"]

_FILTER_ENUMS = {"action": ALLOWED_ACTIONS}

_ENUM_OVERRIDES = {"action": sorted(ALLOWED_ACTIONS)}


class AuditListCommand(Command):
    name: ClassVar[str] = "audit_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List runtime audit log entries filtered by actor, action, entity, plan, and time window, newest first."
    category: ClassVar[str] = "audit"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                **filter_schema_properties(AUDIT_LIST_FILTER_FIELDS, enum_overrides=_ENUM_OVERRIDES),
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {
                "type": prop["type"],
                "description": prop["description"],
                "required": name in schema["required"],
                **({"enum": prop["enum"]} if "enum" in prop else {}),
            }
            for name, prop in schema["properties"].items()
        }
        return runtime_metadata(
            cls,
            params,
            {"type": "object", "description": "The uniform items/total/limit/offset envelope: items holds a page of audit-record payloads ordered newest-first, total is the matching count independent of paging."},
            [
                {"description": "List audit records for one plan, newest first.", "command": {"plan": "5a06b927-b084-46e6-8f9f-4275ad3434c2"}},
                {"description": "List audit records for a specific actor and action.", "command": {"actor": "orchestrator", "action": "update"}},
            ],
            best_practices=[
                "action must be one of the closed ALLOWED_ACTIONS vocabulary: create, update, soft_delete, hard_delete, archive, restore, plan_unfreeze, subtree_unfreeze.",
                "Records are returned newest-first; compare offset+limit against total to detect additional pages.",
                "entity_id and plan must be well-formed UUID strings when supplied.",
                "The runtime audit log is append-only and read-only through this command; there is no corresponding write command.",
            ],
        )

    async def execute(
        self,
        actor: str | None = None,
        action: str | None = None,
        entity_type: str | None = None,
        entity_id: str | None = None,
        plan: str | None = None,
        created_after: str | None = None,
        created_before: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            raw_params = {
                "actor": actor,
                "action": action,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "plan": plan,
                "created_after": created_after,
                "created_before": created_before,
                "limit": limit,
                "offset": offset,
            }
            filters = parse_filters(raw_params, AUDIT_LIST_FILTER_FIELDS, enums=_FILTER_ENUMS)
            pagination = parse_pagination(raw_params)
            plan_value = filters.get("plan")
            plan_uuid = validate_uuid(plan_value) if plan_value is not None else None
            entity_id_value = filters.get("entity_id")
            entity_uuid = validate_uuid(entity_id_value) if entity_id_value is not None else None
            with db_connection() as conn:
                records = list_runtime_audit(
                    conn,
                    plan_uuid=plan_uuid,
                    entity_type=filters.get("entity_type"),
                    entity_id=entity_uuid,
                    changed_by=filters.get("actor"),
                    action=filters.get("action"),
                    created_after=filters.get("created_after"),
                    created_before=filters.get("created_before"),
                    limit=pagination.limit,
                    offset=pagination.offset,
                )
                total = count_runtime_audit(
                    conn,
                    plan_uuid=plan_uuid,
                    entity_type=filters.get("entity_type"),
                    entity_id=entity_uuid,
                    changed_by=filters.get("actor"),
                    action=filters.get("action"),
                    created_after=filters.get("created_after"),
                    created_before=filters.get("created_before"),
                )
                return SuccessResult(data={
                    "items": [record.to_payload() for record in records],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
