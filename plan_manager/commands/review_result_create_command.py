"""Command: create a review result recording the outcome of reviewing an execution attempt or revision (C-018, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import DomainCommandError, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.review_escalation_command_metadata import review_escalation_metadata, BASE_PARAMETERS
from plan_manager.runtime.context import db_connection
from plan_manager.storage.execution_attempt_store import get_execution_attempt
from plan_manager.storage.review_result_store import create_review_result


class ReviewResultCreateCommand(Command):
    name: ClassVar[str] = "review_result_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a review result recording the outcome of reviewing an execution attempt or revision."
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
                "object_type": {
                    "type": "string",
                    "enum": ["execution_attempt", "revision"],
                    "description": "Type of object under review.",
                },
                "reviewer": {"type": "string", "description": "Identity of the reviewer (model or owner)."},
                "status": {
                    "type": "string",
                    "enum": ["accepted", "rejected", "changes_requested", "escalated", "needs_owner_decision"],
                    "description": "Review outcome status.",
                },
                "created_by": {"type": "string", "description": "Actor recorded as the creator of this review result."},
                "reviewed_attempt_uuid": {
                    "type": "string",
                    "description": "UUID of the execution attempt under review; required when object_type is execution_attempt.",
                },
                "reviewed_revision_uuid": {
                    "type": "string",
                    "description": "UUID of the revision under review; required when object_type is revision.",
                },
                "findings": {"type": "string", "description": "Free-text findings recorded by the reviewer."},
                "evidence": {"type": "object", "description": "Structured evidence supporting the review outcome."},
                "verification_commands": {
                    "type": "array",
                    "items": {},
                    "description": "List of verification commands the reviewer ran or recommends.",
                },
                "escalation_target_uuid": {
                    "type": "string",
                    "description": "UUID of an escalation this review result is linked to, if any.",
                },
            },
            "required": ["plan", "object_type", "reviewer", "status", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "object_type": {"description": "Type of object under review: execution_attempt or revision.", "type": "string", "required": True},
            "reviewer": {"description": "Identity of the reviewer (model or owner).", "type": "string", "required": True},
            "status": {"description": "Review outcome status: accepted, rejected, changes_requested, escalated, or needs_owner_decision.", "type": "string", "required": True},
            "created_by": {"description": "Actor recorded as the creator of this review result.", "type": "string", "required": True},
            "reviewed_attempt_uuid": {"description": "UUID of the execution attempt under review; required when object_type is execution_attempt.", "type": "string", "required": False},
            "reviewed_revision_uuid": {"description": "UUID of the revision under review; required when object_type is revision.", "type": "string", "required": False},
            "findings": {"description": "Free-text findings recorded by the reviewer.", "type": "string", "required": False},
            "evidence": {"description": "Structured evidence supporting the review outcome.", "type": "object", "required": False},
            "verification_commands": {"description": "List of verification commands the reviewer ran or recommends.", "type": "array", "required": False},
            "escalation_target_uuid": {"description": "UUID of an escalation this review result is linked to, if any.", "type": "string", "required": False},
        }
        return review_escalation_metadata(
            cls,
            params,
            {"success": {"description": "The created review result payload, including review_uuid, object_type, reviewer, status, findings, evidence, and verification_commands."}},
            [{
                "description": "Record an accepted review of an execution attempt.",
                "command": {
                    "plan": "plan_manager",
                    "object_type": "execution_attempt",
                    "reviewer": "ts-owner-sonnet",
                    "status": "accepted",
                    "created_by": "ts-owner-sonnet",
                    "reviewed_attempt_uuid": "b1f2e3a4-1111-2222-3333-444455556666",
                    "findings": "Implementation matches the atomic step prompt; tests pass.",
                },
            }],
            best_practices=[
                "Never set reviewer equal to the execution attempt's created_by; self-certification is rejected as SELF_CERTIFICATION_FORBIDDEN.",
                "Set reviewed_attempt_uuid when object_type is execution_attempt, or reviewed_revision_uuid when object_type is revision; the store requires the matching field.",
                "Use status escalated together with escalation_target_uuid to link this review to an escalation raised via escalation_create.",
                "Record findings and verification_commands so a later reviewer can zero-trust re-check the outcome without re-running the review.",
            ],
        )

    async def execute(
        self,
        plan: str,
        object_type: str,
        reviewer: str,
        status: str,
        created_by: str,
        reviewed_attempt_uuid: str | None = None,
        reviewed_revision_uuid: str | None = None,
        findings: str | None = None,
        evidence: dict[str, Any] | None = None,
        verification_commands: list[Any] | None = None,
        escalation_target_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        # Owner review ladder (C-017): the code executor must never certify its own execution result.
        # This command enforces the ladder at the level of producer IDENTITY: when the object under review
        # is an execution_attempt, the attempt's producer identity is ExecutionAttempt.created_by; a review
        # whose reviewer identity equals that producer identity (string equality after stripping surrounding
        # whitespace) is self-certification and is refused with SELF_CERTIFICATION_FORBIDDEN. review_result
        # carries no ladder-level arguments (reviewer_level/produced_level), so the library guard functions in
        # plan_manager.domain.owner_review_ladder are intentionally NOT invoked here; this identity-level
        # check is the command-surface projection of C-017 (identity-only self-certification).
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                if object_type == "execution_attempt" and reviewed_attempt_uuid:
                    attempt = get_execution_attempt(conn, uuid.UUID(reviewed_attempt_uuid))
                    if (
                        attempt is not None
                        and attempt.created_by is not None
                        and reviewer.strip() == attempt.created_by.strip()
                    ):
                        raise DomainCommandError(
                            "SELF_CERTIFICATION_FORBIDDEN",
                            f"reviewer {reviewer!r} may not certify their own execution attempt "
                            f"{reviewed_attempt_uuid} (producer identity {attempt.created_by!r})",
                        )
                record = create_review_result(
                    conn,
                    object_type=object_type,
                    reviewer=reviewer,
                    status=status,
                    created_by=created_by,
                    reviewed_attempt_uuid=uuid.UUID(reviewed_attempt_uuid) if reviewed_attempt_uuid else None,
                    reviewed_revision_uuid=uuid.UUID(reviewed_revision_uuid) if reviewed_revision_uuid else None,
                    findings=findings,
                    evidence=evidence,
                    verification_commands=verification_commands,
                    escalation_target_uuid=uuid.UUID(escalation_target_uuid) if escalation_target_uuid else None,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
