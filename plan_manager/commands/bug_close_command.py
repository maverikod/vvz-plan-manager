"""Command: transition a BugReport to status 'closed' after enforcing the BugClosureDiscipline invariant on server-derived state (C-020, C-026)."""

from __future__ import annotations

from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from plan_manager.commands.bug_command_metadata import bug_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.plan_completion_guard import refuse_if_bug_plan_completed
from plan_manager.domain.bug_closure_discipline import ImpactState, PropagationState, guard_close
from plan_manager.domain.bug_status_transitions import guard_bug_transition
from plan_manager.domain.runtime_validation import RuntimeValidationError, validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.bug_fix_propagation_store import list_bug_fix_propagations
from plan_manager.storage.bug_fix_store import list_bug_fixes
from plan_manager.storage.bug_impact_store import list_bug_impacts
from plan_manager.storage.bug_report_store import get_bug, set_bug_status


class BugCloseCommand(Command):
    name: ClassVar[str] = "bug_close"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Transition a bug report to status closed after enforcing the closure discipline invariant on server-derived state."
    category: ClassVar[str] = "bug"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                **BASE_PARAMETERS,
                "bug_id": {"type": "string", "format": "uuid", "description": "UUID of the bug report to close."},
                "closed_by": {"type": "string", "description": "Actor performing this closure transition, for audit."},
                "mandatory_todos_closed": {"type": "boolean", "description": "Whether every mandatory linked TODO item for this bug is closed. TODO linkage is not derivable from the G-005 stores, so it is caller-attested. Defaults to true."},
                "required_cascades_finished": {"type": "boolean", "description": "Whether every required plan cascade for this bug is finished. Cascade completion is not derivable from the G-005 stores, so it is caller-attested. Defaults to true."},
            },
            "required": ["plan", "bug_id", "closed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {"type": prop["type"], "description": prop["description"], "required": name in schema["required"]}
            for name, prop in schema["properties"].items()
        }
        return bug_metadata(
            cls,
            params,
            {"type": "object", "description": "The updated BugReport payload."},
            [{"description": "Close a bug once its source fix is verified and every downstream impact and propagation is handled (all derived server-side).", "command": {"plan": "my-plan", "bug_id": "11111111-1111-1111-1111-111111111111", "closed_by": "alice"}}],
            best_practices=[
                "bug_close enforces BugClosureDiscipline server-side: it fails unless a fix is verified and passed, every impact is resolved/verified or explicitly skipped with a reason and owner decision, and every propagation is done/verified/skipped.",
                "Only set mandatory_todos_closed or required_cascades_finished to false if you are intentionally attesting they are not finished; both default to true.",
                "On INVALID_RUNTIME_STATUS_TRANSITION, inspect the error details to see exactly which precondition failed.",
            ],
        )

    async def execute(
        self,
        plan: str,
        bug_id: str,
        closed_by: str,
        mandatory_todos_closed: bool = True,
        required_cascades_finished: bool = True,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                bug_uuid = validate_uuid(bug_id)
                existing = get_bug(conn, bug_uuid)
                if existing is None:
                    raise DomainCommandError("BUG_NOT_FOUND", f"bug not found: {bug_id}")
                refuse_if_bug_plan_completed(conn, existing)
                # Structural terminal-status guard first: a closed/rejected/duplicate bug can
                # only be left via bug_reopen, and re-closing an already-closed bug is refused
                # before the (heavier) BugClosureDiscipline evaluation below.
                guard_bug_transition("bug_close", existing.status)
                fixes = list_bug_fixes(conn, bug_uuid=bug_uuid)
                source_fix_verified = any(fix.status == "verified" and bool(fix.passed) for fix in fixes)
                impacts = list_bug_impacts(conn, bug_uuid=bug_uuid)
                impact_states = [
                    ImpactState(status=impact.status, has_reason=bool(impact.reason), has_owner_decision=bool(impact.skip_decided_by))
                    for impact in impacts
                ]
                propagation_states = []
                for fix in fixes:
                    for propagation in list_bug_fix_propagations(conn, bug_fix_uuid=fix.fix_uuid):
                        propagation_states.append(PropagationState(status=propagation.status))
                try:
                    guard_close(
                        source_fix_verified=source_fix_verified,
                        impacts=impact_states,
                        propagations=propagation_states,
                        mandatory_todos_closed=bool(mandatory_todos_closed),
                        required_cascades_finished=bool(required_cascades_finished),
                    )
                except RuntimeValidationError as exc:
                    raise DomainCommandError("INVALID_RUNTIME_STATUS_TRANSITION", str(exc)) from exc
                updated = set_bug_status(conn, bug_uuid, changed_by=closed_by, status="closed")
                return SuccessResult(data=updated.to_payload())
        except Exception as exc:
            return map_exception(exc)
