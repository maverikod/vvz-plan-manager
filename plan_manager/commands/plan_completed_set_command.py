"""Command: set or unset a plan's completion lock (bug c3950b83).

L1 design ruling 2026-07-23 (superseding an earlier per-step-status
carve-out attempt): plan-level completion bookkeeping is a single boolean
flag on the plan row, not a per-atomic-step status. When `completed` is
true, every OTHER mutating command that resolves its `plan` parameter to
this plan (via plan_manager.commands.resolve.resolve_plan_guarded, or the
parallel anchor-validation seam in domain.primary_anchor for
todo/comment/execution_attempt/review_result/escalation/bug anchors)
refuses with the PLAN_COMPLETED domain code. This command, and its sibling
plan_comment_set, are the two commands EXEMPT from that guard -- they call
resolve_plan directly, unguarded, so the flag itself is always reachable.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.plan_completion_metadata import get_plan_completed_set_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.plan import get_plan, set_plan_completed
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_audit_store import record_runtime_change


class PlanCompletedSetCommand(Command):
    """Set or unset a plan's completion lock; always reachable."""

    name: ClassVar[str] = "plan_completed_set"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Set or unset a plan's completion lock; always reachable regardless "
        "of freeze state or the current flag value."
    )
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the JSON Schema for plan_completed_set input parameters."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or unique name) to resolve.",
                },
                "completed": {
                    "type": "boolean",
                    "description": "The new completion-lock value.",
                },
                "changed_by": {
                    "type": "string",
                    "description": (
                        "Identity of the actor requesting the change; recorded "
                        "in the audit trail. Must be a non-empty string."
                    ),
                },
            },
            "required": ["plan", "completed", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for plan_completed_set."""
        return get_plan_completed_set_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate plan_completed_set input parameters."""
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        completed: bool,
        changed_by: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Set or unset a plan's completion lock and audit the change.

        Args:
            plan: Plan identifier (UUID or unique name).
            completed: The new completion-lock value.
            changed_by: Actor identity recorded in the audit trail.

        Returns:
            SuccessResult with the plan uuid, the completed value re-read
            from storage, and the audit record uuid, or ErrorResult
            produced by domain_error / map_exception on failure.
        """
        try:
            if not changed_by or not changed_by.strip():
                raise DomainCommandError(
                    "RUNTIME_VALIDATION_ERROR", "changed_by must be a non-empty string"
                )
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                from_value = p.completed
                set_plan_completed(conn, p.uuid, completed)
                audit = record_runtime_change(
                    conn,
                    plan_uuid=p.uuid,
                    entity_type="plan",
                    entity_id=p.uuid,
                    action="plan_completed_set",
                    changed_by=changed_by,
                    change_reason=None,
                    changed_fields={"from": from_value, "to": completed},
                )
                verified = get_plan(conn, p.uuid)
                return SuccessResult(
                    data={
                        "plan_uuid": str(p.uuid),
                        "completed": verified.completed,
                        "audit_uuid": str(audit.audit_uuid),
                    }
                )
        except DomainCommandError as exc:
            return domain_error(exc.code, exc.message, exc.details)
        except Exception as exc:
            return map_exception(exc)
