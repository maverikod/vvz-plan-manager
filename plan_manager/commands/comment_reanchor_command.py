"""Command: move a runtime comment's primary anchor to a new target, with an audit record (group-3 fix, bug 2c568c0c).

Deliberately does NOT route the candidate anchor through
plan_manager.commands.anchor_confirmation.confirm_anchor, unlike
wish_reanchor/calendar_entry_reanchor/escalation_reanchor/todo_reanchor/bug_reanchor:
comment_add_command.py (comment creation itself) never wires CA confirmation for a
project/file comment anchor either, and the bug 5926d536 "fall back to unanchored on
an unconfirmed project/file anchor" precedent those other five commands share has no
comment-side counterpart -- a comment may never be anchor_type "none" (RuntimeComment's
own eleven-kind vocabulary excludes it), so there is no safe unanchored fallback to
fall back to. Matching comment_add's own choice keeps this command consistent with the
rest of its own command family rather than importing a precedent built for a different
family and only partially applicable here.
"""

from __future__ import annotations

import uuid
from typing import Any, ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.comment_command_metadata import comment_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_completion_guard import refuse_if_comment_plan_completed
from plan_manager.commands.reanchor_command_metadata import REANCHOR_BEST_PRACTICES, REANCHOR_ERROR_CASES
from plan_manager.domain.primary_anchor import PrimaryAnchor
from plan_manager.runtime.context import db_connection
from plan_manager.storage.entity_reanchor_store import reanchor_comment
from plan_manager.storage.runtime_comment_store import get_comment


class CommentReanchorCommand(Command):
    name: ClassVar[str] = "comment_reanchor"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Move a runtime comment's primary anchor to a new target, with an audit record."
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
                "comment_uuid": {"type": "string", "format": "uuid", "description": "Comment UUID to re-anchor."},
                "changed_by": {"type": "string", "description": "Actor performing this re-anchor move, for audit."},
                "new_anchor_type": {"type": "string", "description": "The candidate new primary anchor kind: plan, revision, step, project, file, todo, bug, bug_fix, execution_attempt, review_result, or escalation. 'none' is not allowed: a comment always attaches to a subject."},
                "new_anchor_project_id": {"type": "string", "format": "uuid", "description": "Project UUID; required when new_anchor_type is project or file."},
                "new_anchor_file_path": {"type": "string", "description": "Project-relative file path; required when new_anchor_type is file."},
                "new_anchor_plan_uuid": {"type": "string", "format": "uuid", "description": "Plan UUID; required when new_anchor_type is plan or step."},
                "new_anchor_revision_uuid": {"type": "string", "format": "uuid", "description": "Revision UUID; required when new_anchor_type is revision (optionally supplied alongside step)."},
                "new_anchor_step_uuid": {"type": "string", "format": "uuid", "description": "Step UUID; required when new_anchor_type is step."},
                "new_anchor_step_path": {"type": "string", "description": "Step path, optionally supplied alongside new_anchor_step_uuid."},
                "new_anchor_ref_id": {"type": "string", "format": "uuid", "description": "Reference UUID; required when new_anchor_type is todo, bug, bug_fix, execution_attempt, review_result, or escalation."},
            },
            "required": ["comment_uuid", "changed_by", "new_anchor_type"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        schema = cls.get_schema()
        params = {
            name: {"type": prop["type"], "description": prop["description"], "required": name in schema["required"]}
            for name, prop in schema["properties"].items()
        }
        return comment_metadata(
            cls,
            params,
            {"success": {"description": "The re-anchored RuntimeComment payload."}},
            [{"description": "Move a comment's anchor to a step.", "command": {"comment_uuid": "11111111-1111-1111-1111-111111111111", "changed_by": "agent-1", "new_anchor_type": "step", "new_anchor_plan_uuid": "22222222-2222-2222-2222-222222222222", "new_anchor_step_uuid": "33333333-3333-3333-3333-333333333333"}}],
            error_cases=REANCHOR_ERROR_CASES,
            best_practices=REANCHOR_BEST_PRACTICES + [
                "'none' is never a valid new_anchor_type here: unlike todo_reanchor/wish_reanchor/etc., a comment always attaches to a subject.",
                "An 'escalation' new_anchor_type requires new_anchor_ref_id and is checked against the escalation table, exactly as comment_add's own anchor_type=escalation branch checks it.",
            ],
        )

    _UUID_FIELDS: ClassVar[tuple[str, ...]] = (
        "comment_uuid", "new_anchor_project_id", "new_anchor_plan_uuid",
        "new_anchor_revision_uuid", "new_anchor_step_uuid", "new_anchor_ref_id",
    )

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate comment_reanchor parameters beyond the base schema check:
        comment_uuid and every UUID-shaped new_anchor_* field, when supplied, must
        parse as a UUID.

        Raises:
            InvalidParamsError: If comment_uuid or any new_anchor_* UUID field is
                not a valid UUID string.
        """
        params = super().validate_params(params)
        for field in self._UUID_FIELDS:
            value = params.get(field)
            if value is not None:
                try:
                    uuid.UUID(value)
                except ValueError as exc:
                    raise InvalidParamsError(f"{field} is not a valid UUID: {value!r}") from exc
        return params

    async def execute(
        self,
        comment_uuid: str,
        changed_by: str,
        new_anchor_type: str,
        new_anchor_project_id: str | None = None,
        new_anchor_file_path: str | None = None,
        new_anchor_plan_uuid: str | None = None,
        new_anchor_revision_uuid: str | None = None,
        new_anchor_step_uuid: str | None = None,
        new_anchor_step_path: str | None = None,
        new_anchor_ref_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            with db_connection() as conn:
                comment_uuid_val = uuid.UUID(comment_uuid)
                # The CURRENT anchor's plan, before the move (mirrors todo_reanchor's
                # own c3950b83 seam); the NEW anchor's plan is separately covered by
                # reanchor_comment's own validate_anchor call when new_anchor_type is
                # plan/step. A missing comment is left to the store's own
                # COMMENT_NOT_FOUND.
                current = get_comment(conn, comment_uuid_val)
                if current is not None:
                    refuse_if_comment_plan_completed(conn, current)
                new_anchor = PrimaryAnchor(
                    anchor_type=new_anchor_type,
                    project_id=uuid.UUID(new_anchor_project_id) if new_anchor_project_id is not None else None,
                    file_path=new_anchor_file_path,
                    plan_uuid=uuid.UUID(new_anchor_plan_uuid) if new_anchor_plan_uuid is not None else None,
                    revision_uuid=uuid.UUID(new_anchor_revision_uuid) if new_anchor_revision_uuid is not None else None,
                    step_uuid=uuid.UUID(new_anchor_step_uuid) if new_anchor_step_uuid is not None else None,
                    step_path=new_anchor_step_path,
                    ref_id=uuid.UUID(new_anchor_ref_id) if new_anchor_ref_id is not None else None,
                )
                updated = reanchor_comment(
                    conn,
                    comment_uuid_val,
                    changed_by=changed_by,
                    new_anchor=new_anchor,
                )
                return SuccessResult(data=updated.to_payload())
        except Exception as exc:
            return map_exception(exc)
