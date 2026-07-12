"""Command: create an escalation raised to the owner of the next level up (C-037, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.review_escalation_command_metadata import review_escalation_metadata, BASE_PARAMETERS
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.runtime.context import db_connection
from plan_manager.storage.escalation_store import create_escalation


class EscalationCreateCommand(Command):
    name: ClassVar[str] = "escalation_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create an escalation raised to the owner of the next level up."
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
                "anchor_type": {
                    "type": "string",
                    "enum": [
                        "none", "project", "file", "plan", "revision", "step",
                        "execution_attempt", "review_result", "bug", "bug_fix", "todo",
                    ],
                    "description": "Primary anchor type this escalation is attached to.",
                },
                "anchor_project_id": {"type": "string", "description": "UUID of the anchor project, when anchor_type is project."},
                "anchor_file_path": {"type": "string", "description": "Project-relative file path, when anchor_type is file."},
                "anchor_plan_uuid": {"type": "string", "description": "UUID of the anchor plan, when anchor_type is plan, revision, or step."},
                "anchor_revision_uuid": {"type": "string", "description": "UUID of the anchor revision, when anchor_type is revision or step."},
                "anchor_step_uuid": {"type": "string", "description": "UUID of the anchor step, when anchor_type is step."},
                "anchor_step_path": {"type": "string", "description": "Canonical path of the anchor step, when anchor_type is step."},
                "anchor_ref_id": {"type": "string", "description": "UUID of the anchored entity, when anchor_type is execution_attempt, review_result, bug, bug_fix, or todo."},
                "reason": {"type": "string", "description": "Reason this escalation was raised."},
                "created_by": {"type": "string", "description": "Actor recorded as the creator of this escalation."},
                "from_level": {"type": "string", "description": "Owner level the escalation was raised from."},
                "to_level": {"type": "string", "description": "Owner level the escalation was raised to."},
            },
            "required": ["plan", "anchor_type", "reason", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "anchor_type": {"description": "Primary anchor type this escalation is attached to.", "type": "string", "required": True},
            "anchor_project_id": {"description": "UUID of the anchor project, when anchor_type is project.", "type": "string", "required": False},
            "anchor_file_path": {"description": "Project-relative file path, when anchor_type is file.", "type": "string", "required": False},
            "anchor_plan_uuid": {"description": "UUID of the anchor plan, when anchor_type is plan, revision, or step.", "type": "string", "required": False},
            "anchor_revision_uuid": {"description": "UUID of the anchor revision, when anchor_type is revision or step.", "type": "string", "required": False},
            "anchor_step_uuid": {"description": "UUID of the anchor step, when anchor_type is step.", "type": "string", "required": False},
            "anchor_step_path": {"description": "Canonical path of the anchor step, when anchor_type is step.", "type": "string", "required": False},
            "anchor_ref_id": {"description": "UUID of the anchored entity, when anchor_type is execution_attempt, review_result, bug, bug_fix, or todo.", "type": "string", "required": False},
            "reason": {"description": "Reason this escalation was raised.", "type": "string", "required": True},
            "created_by": {"description": "Actor recorded as the creator of this escalation.", "type": "string", "required": True},
            "from_level": {"description": "Owner level the escalation was raised from.", "type": "string", "required": False},
            "to_level": {"description": "Owner level the escalation was raised to.", "type": "string", "required": False},
        }
        meta = review_escalation_metadata(
            cls,
            params,
            {"success": {"description": "The created escalation payload, including escalation_uuid, anchor fields, reason, from_level, to_level, and status open."}},
            [{
                "description": "Escalate a review decision the TS owner cannot make alone.",
                "command": {
                    "plan": "plan_manager",
                    "anchor_type": "execution_attempt",
                    "anchor_ref_id": "b1f2e3a4-1111-2222-3333-444455556666",
                    "reason": "Retry limit exhausted after one failed retry; owner lacks confidence to accept.",
                    "created_by": "ts-owner-sonnet",
                    "from_level": "ts",
                    "to_level": "gs",
                },
            }],
            best_practices=[
                "anchor_type selects the required anchor_* fields: project needs anchor_project_id; file needs anchor_project_id+anchor_file_path; plan needs anchor_plan_uuid; revision needs anchor_revision_uuid; step needs anchor_plan_uuid+anchor_step_uuid; execution_attempt/review_result/bug/bug_fix/todo need anchor_ref_id; none leaves all anchor_* fields unset.",
                "Set from_level and to_level per the owner review ladder (hrs_mrs > gs > ts > as) to record who raised the escalation and who must decide it.",
                "New escalations start at status open; resolve them with escalation_resolve rather than creating a duplicate.",
                "Write reason as the concrete blocker (missing context, competence gap, low confidence, or exhausted retries) so the target owner can act without re-deriving it.",
                "Escalation status vocabulary (EscalationStatus) has exactly two values: open, resolved. "
                "escalation_resolve is the only transition, and it always moves open -> resolved.",
            ],
        )
        meta["detailed_description"] = (
            meta["detailed_description"]
            + " Escalation status vocabulary (EscalationStatus): open, resolved. An escalation "
            "is always created in status open; there is no command-level way to create one "
            "directly in status resolved."
        )
        return meta

    async def execute(
        self,
        plan: str,
        anchor_type: str,
        reason: str,
        created_by: str,
        anchor_project_id: str | None = None,
        anchor_file_path: str | None = None,
        anchor_plan_uuid: str | None = None,
        anchor_revision_uuid: str | None = None,
        anchor_step_uuid: str | None = None,
        anchor_step_path: str | None = None,
        anchor_ref_id: str | None = None,
        from_level: str | None = None,
        to_level: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        # Retry policy (C-019): an escalation is created when an owner lacks context,
        # competence, or confidence to decide alone, or when plan_manager.domain.retry_policy
        # .decide_retry(attempts_made=..., max_retries=..., last_attempt_failed=...) reports
        # should_escalate=True (retry limit exhausted). escalation_create's schema does not carry
        # attempt-count/retry-limit arguments, so this command does not invoke decide_retry
        # directly; the caller is expected to have consulted the retry policy before deciding to
        # escalate, or to be escalating for a non-retry reason (context/competence/confidence).
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                anchor = PrimaryAnchor(
                    anchor_type=anchor_type,
                    project_id=uuid.UUID(anchor_project_id) if anchor_project_id else None,
                    file_path=anchor_file_path,
                    plan_uuid=uuid.UUID(anchor_plan_uuid) if anchor_plan_uuid else None,
                    revision_uuid=uuid.UUID(anchor_revision_uuid) if anchor_revision_uuid else None,
                    step_uuid=uuid.UUID(anchor_step_uuid) if anchor_step_uuid else None,
                    step_path=anchor_step_path,
                    ref_id=uuid.UUID(anchor_ref_id) if anchor_ref_id else None,
                )
                record = create_escalation(
                    conn,
                    anchor=anchor,
                    reason=reason,
                    created_by=created_by,
                    from_level=from_level,
                    to_level=to_level,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
