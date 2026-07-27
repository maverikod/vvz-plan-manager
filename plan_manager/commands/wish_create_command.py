"""Command: create a new runtime wish item."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_work_command_helpers import (
    build_primary_anchor,
    primary_anchor_metadata_params,
    primary_anchor_schema_properties,
)
from plan_manager.commands.wish_command_metadata import wish_metadata
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import db_connection
from plan_manager.storage.wish_store import create_wish


class WishCreateCommand(Command):
    name: ClassVar[str] = "wish_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new runtime wish item: a feature desire tracked separately from todos and bugs."
    category: ClassVar[str] = "wish"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Wish title."},
                "description": {"type": "string", "description": "Wish description."},
                "kind": {"type": "string", "description": "Wish kind: feature, ux, automation, integration, reporting, tooling, or other."},
                "priority_nice": {"type": "integer", "description": "Nice-scale priority in [-20, 19]."},
                "created_by": {"type": "string", "description": "Actor creating the wish."},
                "status": {"type": "string", "description": "Initial wish status (defaults to proposed)."},
                "assigned_to": {"type": "string", "description": "Actor currently owning follow-up on this wish."},
                "target_release": {"type": "string", "description": "Optional target release or milestone label."},
                "rationale": {"type": "string", "description": "Optional rationale or decision note."},
                **primary_anchor_schema_properties(),
            },
            "required": ["title", "description", "kind", "priority_nice", "created_by", "anchor_type"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "title": {"description": "Wish title.", "type": "string", "required": True},
            "description": {"description": "Wish description.", "type": "string", "required": True},
            "kind": {"description": "Wish kind: feature, ux, automation, integration, reporting, tooling, or other.", "type": "string", "required": True},
            "priority_nice": {"description": "Nice-scale priority in [-20, 19].", "type": "integer", "required": True},
            "created_by": {"description": "Actor creating the wish.", "type": "string", "required": True},
            "status": {"description": "Initial wish status (defaults to proposed).", "type": "string", "required": False},
            "assigned_to": {"description": "Actor currently owning follow-up on this wish.", "type": "string", "required": False},
            "target_release": {"description": "Optional target release or milestone label.", "type": "string", "required": False},
            "rationale": {"description": "Optional rationale or decision note.", "type": "string", "required": False},
            **primary_anchor_metadata_params(),
        }
        return wish_metadata(
            cls,
            params,
            {"success": {"description": "The created WishItem payload."}},
            [{
                "description": "Create a feature wish anchored to a project step.",
                "command": {
                    "title": "Calendar-based rollout view",
                    "description": "Need a first-class calendar graph for implementation work.",
                    "kind": "feature",
                    "priority_nice": -4,
                    "created_by": "owner",
                    "anchor_type": "step",
                    "anchor_plan_uuid": "11111111-1111-1111-1111-111111111111",
                    "anchor_step_uuid": "22222222-2222-2222-2222-222222222222",
                },
            }],
            best_practices=[
                "Use wishes for product or capability desires, not for concrete execution items; once work is accepted, a TODO or calendar entry can track delivery.",
                "priority_nice uses the same [-20, 19] scale as TODOs; lower values are higher priority.",
                "The wish's primary anchor is immutable after creation; use it to bind the wish to the plan, step, project, file, or runtime artifact it refers to.",
            ],
        )

    async def execute(
        self,
        title: str,
        description: str,
        kind: str,
        priority_nice: int,
        created_by: str,
        anchor_type: str,
        status: str = "proposed",
        assigned_to: str | None = None,
        target_release: str | None = None,
        rationale: str | None = None,
        anchor_project_id: str | None = None,
        anchor_file_path: str | None = None,
        anchor_plan_uuid: str | None = None,
        anchor_revision_uuid: str | None = None,
        anchor_step_uuid: str | None = None,
        anchor_step_path: str | None = None,
        anchor_ref_id: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            anchor = build_primary_anchor(
                anchor_type=anchor_type,
                anchor_project_id=anchor_project_id,
                anchor_file_path=anchor_file_path,
                anchor_plan_uuid=anchor_plan_uuid,
                anchor_revision_uuid=anchor_revision_uuid,
                anchor_step_uuid=anchor_step_uuid,
                anchor_step_path=anchor_step_path,
                anchor_ref_id=anchor_ref_id,
            )
            with db_connection() as conn:
                record = create_wish(
                    conn,
                    title=title,
                    description=description,
                    kind=kind,
                    priority_nice=priority_nice,
                    created_by=created_by,
                    anchor=anchor,
                    status=status,
                    assigned_to=assigned_to,
                    target_release=target_release,
                    rationale=rationale,
                )
                return SuccessResult(data=record.to_payload())
        except Exception as exc:
            return map_exception(exc)
