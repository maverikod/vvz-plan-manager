"""Command: list a paginated page of bug fix propagation records filtered by bug fix or impact (C-025, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.bug_propagation_command_metadata import bug_propagation_metadata, BASE_PARAMETERS
from plan_manager.commands.runtime_filtering import (
    pagination_metadata_params,
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.bug_fix_propagation import PROPAGATION_STATUSES, PropagationStatus
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations

# Ordered vocabulary published in the schema/metadata so the values are
# discoverable directly, not only via an INVALID_FILTER error. This command
# does not route filters through plan_manager.commands.runtime_filtering (it
# builds its schema/metadata by hand), so the vocabulary is spliced into the
# "status" description/enum inline below rather than via enum_overrides.
_STATUS_VALUES = [e.value for e in PropagationStatus]
_STATUS_DESCRIPTION = "Optional status filter. One of: " + ", ".join(_STATUS_VALUES) + "."

class BugPropagationListCommand(Command):
    name: ClassVar[str] = "bug_propagation_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List a paginated page of bug fix propagation records filtered by bug fix or impact (read-only)."
    category: ClassVar[str] = "propagation"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {"type": "string", "description": "Plan identifier."},
                "bug_fix_id": {"type": "string", "description": "Optional UUID filter: only propagations for this bug fix."},
                "impact_id": {"type": "string", "description": "Optional UUID filter: only propagations for this impact."},
                "status": {"type": "string", "description": _STATUS_DESCRIPTION, "enum": _STATUS_VALUES},
                "include_deleted": {"type": "boolean", "description": "Include soft-deleted propagation records. Defaults to false."},
                **pagination_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "bug_fix_id": {"description": "Optional UUID filter: only propagations for this bug fix.", "type": "string", "required": False},
            "impact_id": {"description": "Optional UUID filter: only propagations for this impact.", "type": "string", "required": False},
            "status": {"description": _STATUS_DESCRIPTION, "type": "string", "required": False, "enum": _STATUS_VALUES},
            "include_deleted": {"description": "Include soft-deleted propagation records. Defaults to false.", "type": "boolean", "required": False},
            **pagination_metadata_params(),
        }
        return bug_propagation_metadata(
            cls,
            params,
            {"success": {"description": "A page of bug fix propagation record payloads, ordered oldest first, with every UUID field rendered as a string, plus total/limit/offset."}},
            [{"description": "List propagations for a bug fix.", "command": {"plan": "plan_manager", "bug_fix_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"}}],
            best_practices=[
                "Filter by bug_fix_id to see every downstream action required by one fix.",
                "Filter by impact_id to see all propagation actions for a single impact target.",
                "Use status to isolate propagations that are still pending or blocked.",
                "Set include_deleted=true only when auditing soft-deleted propagation history.",
                "Compare offset+limit against total to detect additional pages.",
            ],
        )

    async def execute(
        self,
        plan: str,
        bug_fix_id: str | None = None,
        impact_id: str | None = None,
        status: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                if status is not None and status not in PROPAGATION_STATUSES:
                    raise DomainCommandError(
                        "INVALID_FILTER",
                        f"'status' must be one of {sorted(PROPAGATION_STATUSES)}; got {status!r}",
                    )
                pagination = parse_pagination({"limit": limit, "offset": offset})
                records = list_bug_fix_propagations(
                    conn,
                    bug_fix_uuid=uuid.UUID(bug_fix_id) if bug_fix_id is not None else None,
                    impact_uuid=uuid.UUID(impact_id) if impact_id is not None else None,
                    status=status,
                    include_deleted=include_deleted,
                )
                total = len(records)
                page = records[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "propagations": [r.to_payload() for r in page],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
