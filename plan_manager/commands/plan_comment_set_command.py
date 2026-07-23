"""Command: set, replace, or clear a plan's free-form comment (bug c3950b83).

Always reachable, like its sibling plan_completed_set, regardless of the
plan's freeze state or completion lock: it calls resolve_plan directly,
unguarded. See plan_completed_set_command.py for the full completion-lock
design note.
"""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, domain_error, map_exception
from plan_manager.commands.plan_completion_metadata import get_plan_comment_set_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.plan import get_plan, set_plan_comment
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_audit_store import record_runtime_change


class PlanCommentSetCommand(Command):
    """Set, replace, or clear a plan's comment; always reachable."""

    name: ClassVar[str] = "plan_comment_set"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Set, replace, or clear a plan's free-form comment; always "
        "reachable regardless of freeze state or the completion lock."
    )
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the JSON Schema for plan_comment_set input parameters."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or unique name) to resolve.",
                },
                "comment": {
                    "type": "string",
                    "description": (
                        "The new comment text; omit or pass null to clear "
                        "the plan's comment."
                    ),
                },
                "changed_by": {
                    "type": "string",
                    "description": (
                        "Identity of the actor requesting the change; recorded "
                        "in the audit trail. Must be a non-empty string."
                    ),
                },
            },
            "required": ["plan", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for plan_comment_set."""
        return get_plan_comment_set_metadata(cls)

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate plan_comment_set input parameters."""
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        changed_by: str,
        comment: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Set, replace, or clear a plan's comment and audit the change.

        Args:
            plan: Plan identifier (UUID or unique name).
            changed_by: Actor identity recorded in the audit trail.
            comment: The new comment text, or None to clear it (the
                default when the parameter is omitted).

        Returns:
            SuccessResult with the plan uuid, the comment re-read from
            storage, and the audit record uuid, or ErrorResult produced
            by domain_error / map_exception on failure.
        """
        try:
            if not changed_by or not changed_by.strip():
                raise DomainCommandError(
                    "RUNTIME_VALIDATION_ERROR", "changed_by must be a non-empty string"
                )
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                from_value = p.comment
                set_plan_comment(conn, p.uuid, comment)
                audit = record_runtime_change(
                    conn,
                    plan_uuid=p.uuid,
                    entity_type="plan",
                    entity_id=p.uuid,
                    action="plan_comment_set",
                    changed_by=changed_by,
                    change_reason=None,
                    changed_fields={"from": from_value, "to": comment},
                )
                verified = get_plan(conn, p.uuid)
                return SuccessResult(
                    data={
                        "plan_uuid": str(p.uuid),
                        "comment": verified.comment,
                        "audit_uuid": str(audit.audit_uuid),
                    }
                )
        except DomainCommandError as exc:
            return domain_error(exc.code, exc.message, exc.details)
        except Exception as exc:
            return map_exception(exc)
