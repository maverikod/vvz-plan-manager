"""Command: transition the status or amend fields of an existing BugImpact record (C-022, C-029)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.bug_impact_command_metadata import BASE_PARAMETERS, bug_impact_metadata
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_bug_impact_plan_completed
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_impact_store import get_bug_impact, update_bug_impact


class BugImpactUpdateCommand(Command):
    name: ClassVar[str] = "bug_impact_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Transition the status or amend fields of an existing BugImpact record."
    category: ClassVar[str] = "impact"
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
                "impact_uuid": {"type": "string", "format": "uuid", "description": "UUID of the bug_impact record to update."},
                "changed_by": {"type": "string", "description": "Actor identifier recorded as the author of this change."},
                "status": {"type": "string", "description": "New impact status: suspected, confirmed, unaffected, pending_resolution, resolved, verified, or skipped (skipped requires a non-empty reason and skip_decided_by, existing or newly supplied)."},
                "reason": {"type": "string", "description": "Explanation for the impact status; required when the resulting status is skipped."},
                "skip_decided_by": {"type": "string", "description": "Owner decision identity for a skipped impact; required together with reason when the resulting status is skipped."},
                "discovery_method": {"type": "string", "description": "How this impact was discovered."},
                "resolution_evidence": {"type": "object", "description": "Structured evidence supporting resolution of this impact."},
            },
            "required": ["plan", "impact_uuid", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "impact_uuid": {"description": "UUID of the bug_impact record to update.", "type": "string", "required": True},
            "changed_by": {"description": "Actor identifier recorded as the author of this change.", "type": "string", "required": True},
            "status": {"description": "New impact status.", "type": "string", "required": False},
            "reason": {"description": "Explanation for the impact status; required when the resulting status is skipped.", "type": "string", "required": False},
            "skip_decided_by": {"description": "Owner decision identity for a skipped impact; required with reason when the resulting status is skipped.", "type": "string", "required": False},
            "discovery_method": {"description": "How this impact was discovered.", "type": "string", "required": False},
            "resolution_evidence": {"description": "Structured evidence supporting resolution of this impact.", "type": "object", "required": False},
        }
        return bug_impact_metadata(
            cls,
            params,
            {"success": {"description": "The updated BugImpact payload."}},
            [{
                "description": "Confirm a suspected impact.",
                "command": {
                    "plan": "plan_manager",
                    "impact_uuid": "33333333-3333-3333-3333-333333333333",
                    "changed_by": "alice",
                    "status": "confirmed",
                },
            }],
            best_practices=[
                "Provide reason and skip_decided_by (existing or newly supplied) before setting status to skipped.",
                "Attach resolution_evidence when transitioning an impact to resolved or verified.",
                "Only pass the fields that changed; omitted fields keep their current value.",
                "Record changed_by as the actual actor performing the transition, for audit history.",
                "Impact type, including the defect_source owning-repo value, is fixed when a bug_impact record is created via bug_impact_add and cannot be changed by bug_impact_update; to correct a wrongly-typed record, create a replacement record with bug_impact_add instead.",
            ],
        )

    async def execute(
        self,
        plan: str,
        impact_uuid: str,
        changed_by: str,
        status: str | None = None,
        reason: str | None = None,
        skip_decided_by: str | None = None,
        discovery_method: str | None = None,
        resolution_evidence: dict[str, Any] | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                impact_id = validate_uuid(impact_uuid)
                current = get_bug_impact(conn, impact_id)
                if current is None:
                    raise DomainCommandError("BUG_IMPACT_NOT_FOUND", f"bug impact not found: {impact_uuid}")
                refuse_if_bug_impact_plan_completed(conn, current)
                if status == "skipped":
                    resulting_reason = reason if reason is not None else current.reason
                    resulting_decider = skip_decided_by if skip_decided_by is not None else current.skip_decided_by
                    if not (resulting_reason and resulting_decider):
                        raise DomainCommandError(
                            "INVALID_RUNTIME_STATUS_TRANSITION",
                            f"cannot transition bug impact {impact_uuid} to skipped without a reason and an owner decision",
                        )
                record = update_bug_impact(
                    conn,
                    impact_id,
                    changed_by=changed_by,
                    status=status,
                    reason=reason,
                    skip_decided_by=skip_decided_by,
                    discovery_method=discovery_method,
                    resolution_evidence=resolution_evidence,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
