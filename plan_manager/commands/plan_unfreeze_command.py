"""Command: the audited escape hatch out of full freeze (defect d01b3bc6).

A fully frozen plan (non-empty step set, every step status='frozen') is
read-only: cascade_begin refuses it (FROZEN_TRUTH_WRITE) and the ordinary
reopen path (open a cascade, then scoped step_transition frozen->draft) can
never start. plan_unfreeze is the only sanctioned door out: it audits the
escape and opens a cascade, bypassing ONLY the all-steps-frozen refusal via
an explicit internal entry point of begin_cascade. The public cascade_begin
guard is unchanged and still refuses fully frozen plans.
"""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.cascade.begin import _all_steps_frozen, begin_cascade
from plan_manager.cascade.record import get_open_cascade
from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.plan_unfreeze_metadata import get_plan_unfreeze_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_audit_store import record_runtime_change


class PlanUnfreezeCommand(Command):
    """Reopen a fully frozen plan by opening an audited cascade."""

    name: ClassVar[str] = "plan_unfreeze"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Reopen a fully frozen plan: audit the escape and open a cascade under "
        "which scoped step_transition frozen->draft may then run."
    )
    category: ClassVar[str] = "cascade"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the JSON Schema for plan_unfreeze input parameters."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan UUID or unique plan name to unfreeze.",
                },
                "changed_by": {
                    "type": "string",
                    "description": (
                        "Identity of the actor requesting the unfreeze; recorded "
                        "in the audit trail. Must be a non-empty string."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": (
                        "Why the fully-frozen plan is being reopened; recorded in "
                        "the audit trail. Must be a non-empty string."
                    ),
                },
            },
            "required": ["plan", "changed_by", "reason"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for plan_unfreeze."""
        return get_plan_unfreeze_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate plan_unfreeze input parameters."""
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        changed_by: str,
        reason: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Open an audited cascade on a fully frozen plan.

        Args:
            plan: Plan UUID or unique plan name to unfreeze.
            changed_by: Actor identity recorded in the audit trail.
            reason: Reason for the unfreeze recorded in the audit trail.

        Returns:
            A SuccessResult carrying the opened cascade identity, the audit
            record uuid, and a next-steps statement, or an ErrorResult
            produced by domain_error / map_exception on failure.
        """
        try:
            if not changed_by or not changed_by.strip():
                raise DomainCommandError(
                    "RUNTIME_VALIDATION_ERROR", "changed_by must be a non-empty string"
                )
            if not reason or not reason.strip():
                raise DomainCommandError(
                    "RUNTIME_VALIDATION_ERROR", "reason must be a non-empty string"
                )
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                if not _all_steps_frozen(conn, p.uuid):
                    raise DomainCommandError(
                        "PLAN_NOT_FULLY_FROZEN",
                        f"plan {p.name} is not fully frozen; open a cascade with "
                        "cascade_begin instead",
                    )
                if get_open_cascade(conn, p.uuid) is not None:
                    raise DomainCommandError(
                        "CASCADE_CONFLICT",
                        f"plan {p.name} already has an open cascade",
                    )
                head = p.head_revision_uuid
                audit = record_runtime_change(
                    conn,
                    plan_uuid=p.uuid,
                    entity_type="plan",
                    entity_id=p.uuid,
                    action="plan_unfreeze",
                    changed_by=changed_by,
                    change_reason=reason,
                    changed_fields={
                        "head_revision_uuid": str(head) if head is not None else None
                    },
                )
                rec = begin_cascade(conn, p.uuid, allow_all_frozen=True)
                reread = get_open_cascade(conn, p.uuid)
                assert reread is not None and reread.uuid == rec.uuid, (
                    f"cascade {rec.uuid} for plan {p.name} did not verify by re-read"
                )
                next_steps = (
                    "Cascade opened. Run step_transition(plan="
                    f"'{p.name}', to_status='draft', scope=..., cascade_uuid="
                    f"'{rec.uuid}') to reopen frozen steps, then cascade_commit "
                    "(requires a green gate) or cascade_abort."
                )
                return SuccessResult(
                    data={
                        "cascade_uuid": str(rec.uuid),
                        "base_revision_uuid": str(rec.base_revision_uuid),
                        "ref_name": rec.name,
                        "created_at": rec.created_at.isoformat(),
                        "plan_uuid": str(p.uuid),
                        "audit_uuid": str(audit.audit_uuid),
                        "next_steps": next_steps,
                    }
                )
        except DomainCommandError as exc:
            return domain_error(exc.code, exc.message, exc.details)
        except Exception as exc:
            return map_exception(exc)
