"""Command: create a new runtime comment attached to a comment anchor (C-014, C-029)."""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.comment_command_metadata import comment_metadata, BASE_PARAMETERS
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.domain.runtime_comment import validate_comment_anchor_type
from plan_manager.runtime.context import db_connection
from plan_manager.storage.runtime_comment_store import add_comment


class CommentAddCommand(Command):
    name: ClassVar[str] = "comment_add"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new runtime comment attached to a comment anchor."
    category: ClassVar[str] = "comment"
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
                "anchor_type": {"type": "string", "description": "Comment anchor type: plan, revision, step, project, file, todo, bug, bug_fix, execution_attempt, review_result, or escalation. 'none' is not allowed: a comment always attaches to a subject."},
                "anchor_project_id": {"type": "string", "format": "uuid", "description": "Project UUID for the anchor, when applicable."},
                "anchor_file_path": {"type": "string", "description": "Project-relative file path for the anchor, when applicable."},
                "anchor_plan_uuid": {"type": "string", "format": "uuid", "description": "Plan UUID for the anchor, when applicable."},
                "anchor_revision_uuid": {"type": "string", "format": "uuid", "description": "Revision UUID for the anchor, when applicable."},
                "anchor_step_uuid": {"type": "string", "format": "uuid", "description": "Step UUID for the anchor, when applicable."},
                "anchor_step_path": {"type": "string", "description": "Step path for the anchor, when applicable."},
                "anchor_ref_id": {"type": "string", "format": "uuid", "description": "Reference UUID for the anchor (e.g. todo, bug, bug_fix, execution_attempt, review_result, or escalation identifier), when applicable."},
                "kind": {"type": "string", "description": "Comment kind: comment, observation, warning, blocker, decision, review, question, answer, evidence, escalation, execution_note, or verification_note."},
                "visibility": {"type": "string", "description": "Comment visibility mode: audit_only, execution_context, owner_context, reviewer_context, or public_summary."},
                "author": {"type": "string", "description": "Identity of the party who authored the comment content."},
                "body": {"type": "string", "description": "Free-text content of the comment."},
                "created_by": {"type": "string", "description": "Identity of the caller performing this operation, recorded as the audit actor."},
                "resolved": {"type": "boolean", "description": "Optional initial resolved flag for the comment."},
                "supersedes_comment_uuid": {"type": "string", "format": "uuid", "description": "Optional UUID of an existing comment this new comment supersedes."},
            },
            "required": ["plan", "anchor_type", "kind", "visibility", "author", "body", "created_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            **BASE_PARAMETERS,
            "anchor_type": {"description": "Comment anchor type: plan, revision, step, project, file, todo, bug, bug_fix, execution_attempt, review_result, or escalation. 'none' is not allowed: a comment always attaches to a subject.", "type": "string", "required": True},
            "anchor_project_id": {"description": "Project UUID for the anchor, when applicable.", "type": "string", "required": False},
            "anchor_file_path": {"description": "Project-relative file path for the anchor, when applicable.", "type": "string", "required": False},
            "anchor_plan_uuid": {"description": "Plan UUID for the anchor, when applicable.", "type": "string", "required": False},
            "anchor_revision_uuid": {"description": "Revision UUID for the anchor, when applicable.", "type": "string", "required": False},
            "anchor_step_uuid": {"description": "Step UUID for the anchor, when applicable.", "type": "string", "required": False},
            "anchor_step_path": {"description": "Step path for the anchor, when applicable.", "type": "string", "required": False},
            "anchor_ref_id": {"description": "Reference UUID for the anchor (e.g. todo, bug, bug_fix, execution_attempt, review_result, or escalation identifier), when applicable.", "type": "string", "required": False},
            "kind": {"description": "Comment kind.", "type": "string", "required": True},
            "visibility": {"description": "Comment visibility mode.", "type": "string", "required": True},
            "author": {"description": "Identity of the party who authored the comment content.", "type": "string", "required": True},
            "body": {"description": "Free-text content of the comment.", "type": "string", "required": True},
            "created_by": {"description": "Identity of the caller performing this operation.", "type": "string", "required": True},
            "resolved": {"description": "Optional initial resolved flag.", "type": "boolean", "required": False},
            "supersedes_comment_uuid": {"description": "Optional UUID of an existing comment this new comment supersedes.", "type": "string", "required": False},
        }
        return comment_metadata(
            cls,
            params,
            {"success": {"description": "The created RuntimeComment payload."}},
            [{"description": "Add a comment to a step.", "command": {"plan": "plan_manager", "anchor_type": "step", "anchor_plan_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6", "anchor_step_uuid": "5a1e9b0a-2222-4444-8888-abcdefabcdef", "kind": "observation", "visibility": "execution_context", "author": "reviewer", "body": "Looks correct.", "created_by": "reviewer"}}],
            best_practices=[
                "Visibility gates reachability: audit_only reaches no prompt context, execution_context/owner_context/reviewer_context reach only their own context, public_summary reaches all four — choose deliberately.",
                "Anchor fields must match anchor_type: escalation requires anchor_ref_id (checked against the escalation table); the other 10 anchor types go through standard anchor validation.",
                "supersedes_comment_uuid here only checks the target exists — it does not copy kind/visibility/author from it; use comment_supersede for that copy-forward behavior.",
                "created_by (audit actor) and author (comment writer) are distinct fields — don't collapse them when recording a third party's observation.",
            ],
        )

    async def execute(
        self,
        plan: str,
        anchor_type: str,
        kind: str,
        visibility: str,
        author: str,
        body: str,
        created_by: str,
        anchor_project_id: str | None = None,
        anchor_file_path: str | None = None,
        anchor_plan_uuid: str | None = None,
        anchor_revision_uuid: str | None = None,
        anchor_step_uuid: str | None = None,
        anchor_step_path: str | None = None,
        anchor_ref_id: str | None = None,
        resolved: bool | None = None,
        supersedes_comment_uuid: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                resolve_plan(conn, plan)
                validate_comment_anchor_type(anchor_type)
                anchor = PrimaryAnchor(
                    anchor_type=anchor_type,
                    project_id=uuid.UUID(anchor_project_id) if anchor_project_id is not None else None,
                    file_path=anchor_file_path,
                    plan_uuid=uuid.UUID(anchor_plan_uuid) if anchor_plan_uuid is not None else None,
                    revision_uuid=uuid.UUID(anchor_revision_uuid) if anchor_revision_uuid is not None else None,
                    step_uuid=uuid.UUID(anchor_step_uuid) if anchor_step_uuid is not None else None,
                    step_path=anchor_step_path,
                    ref_id=uuid.UUID(anchor_ref_id) if anchor_ref_id is not None else None,
                )
                record = add_comment(
                    conn,
                    anchor=anchor,
                    kind=kind,
                    visibility=visibility,
                    author=author,
                    body=body,
                    created_by=created_by,
                    resolved=resolved,
                    supersedes_comment_uuid=uuid.UUID(supersedes_comment_uuid) if supersedes_comment_uuid is not None else None,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
