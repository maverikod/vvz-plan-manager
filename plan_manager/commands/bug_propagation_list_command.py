"""Command: list a paginated page of bug fix propagation records filtered by bug fix or impact (C-025, C-029, C-031)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
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
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations
from plan_manager.storage.project_scope import resolve_project_plan_uuids
from plan_manager.commands.list_projection import (
    parse_view,
    project_entities,
    view_metadata_params,
    view_schema_properties,
)

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
                "plan": {
                    "type": "string",
                    "description": (
                        "Plan identifier (name or UUID), optional. When supplied, scopes the "
                        "listing: only propagations whose parent bug is anchored to the resolved "
                        "plan are returned (propagation -> bug_fix -> bug_report.source_plan_uuid); "
                        "propagations of bugs with a NULL or foreign source_plan_uuid are excluded. "
                        "The linked_plan_uuid column is the propagation TARGET plan and is NOT the "
                        "scope column. When omitted, no plan scoping is applied."
                    ),
                },
                "bug_fix_id": {"type": "string", "description": "Optional UUID filter: only propagations for this bug fix."},
                "impact_id": {"type": "string", "description": "Optional UUID filter: only propagations for this impact."},
                "status": {"type": "string", "description": _STATUS_DESCRIPTION, "enum": _STATUS_VALUES},
                "project": {
                    "type": "string",
                    "format": "uuid",
                    "description": (
                        "Optional project UUID filter, matched transitively: a propagation whose "
                        "parent bug's source_project_id equals it matches directly, and a "
                        "propagation whose parent bug has source_project_id NULL still matches "
                        "when that bug's source_plan_uuid is bound to the project (plan.project_ids)."
                    ),
                },
                "include_deleted": {"type": "boolean", "description": "Include soft-deleted propagation records. Defaults to false."},
                **pagination_schema_properties(),
                **view_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "plan": {
                "description": (
                    "Plan identifier (name or UUID), optional. When supplied, scopes the "
                    "listing: only propagations whose parent bug is anchored to the resolved "
                    "plan are returned (propagation -> bug_fix -> bug_report.source_plan_uuid); "
                    "propagations of bugs with a NULL or foreign source_plan_uuid are excluded. "
                    "The linked_plan_uuid column is the propagation TARGET plan and is NOT the "
                    "scope column. When omitted, no plan scoping is applied."
                ),
                "type": "string",
                "required": False,
            },
            "bug_fix_id": {"description": "Optional UUID filter: only propagations for this bug fix.", "type": "string", "required": False},
            "impact_id": {"description": "Optional UUID filter: only propagations for this impact.", "type": "string", "required": False},
            "status": {"description": _STATUS_DESCRIPTION, "type": "string", "required": False, "enum": _STATUS_VALUES},
            "project": {
                "description": (
                    "Optional project UUID filter, matched transitively: a propagation whose "
                    "parent bug's source_project_id equals it matches directly, and a "
                    "propagation whose parent bug has source_project_id NULL still matches "
                    "when that bug's source_plan_uuid is bound to the project (plan.project_ids)."
                ),
                "type": "string",
                "required": False,
            },
            "include_deleted": {"description": "Include soft-deleted propagation records. Defaults to false.", "type": "boolean", "required": False},
            **pagination_metadata_params(),
            **view_metadata_params(),
        }
        return bug_propagation_metadata(
            cls,
            params,
            {"success": {"description": "A page of bug fix propagation record payloads (or, with view=summary, compact projections), ordered oldest first, with every UUID field rendered as a string, plus total/limit/offset."}},
            [{"description": "List propagations for a bug fix.", "command": {"plan": "plan_manager", "bug_fix_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"}}],
            best_practices=[
                "The optional plan parameter scopes the listing by the parent bug's anchor (propagation -> bug_fix -> bug_report.source_plan_uuid); NULL and foreign plan anchors are excluded. linked_plan_uuid (the propagation target) is never used for this scope. Omit it to list across all plans.",
                "A supplied but nonexistent plan name or UUID raises PLAN_NOT_FOUND rather than returning an empty page.",
                "The project filter matches transitively through the parent bug: source_project_id equality, or the parent bug's source_plan_uuid bound to that project (plan.project_ids).",
                "bug_fix_id and impact_id filters intersect (AND) with the plan scope; they never widen it beyond the plan's own bugs.",
                "Filter by bug_fix_id to see every downstream action required by one fix.",
                "Filter by impact_id to see all propagation actions for a single impact target.",
                "Use status to isolate propagations that are still pending or blocked.",
                "Set include_deleted=true only when auditing soft-deleted propagation history.",
                "Compare offset+limit against total to detect additional pages.",
                "view=summary returns a compact per-row projection (uuid, bug_fix_uuid, impact_uuid, target_type, action, status, updated_at) instead of the full record (drops evidence and verification_result); there is no bug_propagation_get command, so full detail means re-calling this command with view=full (the default).",
            ],
        )

    async def execute(
        self,
        plan: str | None = None,
        bug_fix_id: str | None = None,
        impact_id: str | None = None,
        status: str | None = None,
        project: str | None = None,
        include_deleted: bool = False,
        limit: int | None = None,
        offset: int | None = None,
        view: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            view_value = parse_view(view)
            with db_connection() as conn:
                plan_record = resolve_plan(conn, plan) if plan is not None else None
                if status is not None and status not in PROPAGATION_STATUSES:
                    raise DomainCommandError(
                        "INVALID_FILTER",
                        f"'status' must be one of {sorted(PROPAGATION_STATUSES)}; got {status!r}",
                    )
                pagination = parse_pagination({"limit": limit, "offset": offset})
                project_uuid = validate_uuid(project) if project is not None else None
                bound_plan_uuids: list = []
                if project_uuid is not None:
                    bound_plan_uuids = list(resolve_project_plan_uuids(conn, project_uuid))
                records = list_bug_fix_propagations(
                    conn,
                    bug_fix_uuid=uuid.UUID(bug_fix_id) if bug_fix_id is not None else None,
                    impact_uuid=uuid.UUID(impact_id) if impact_id is not None else None,
                    status=status,
                    include_deleted=include_deleted,
                    source_plan_uuid=plan_record.uuid if plan_record is not None else None,
                    source_project_id=project_uuid,
                    project_bound_plan_uuids=bound_plan_uuids,
                )
                total = len(records)
                page = records[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "propagations": project_entities(page, view_value),
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
