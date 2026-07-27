"""Command: update mutable fields of a runtime wish item."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import perform_runtime_update
from plan_manager.commands.wish_command_metadata import wish_metadata
from plan_manager.storage.wish_store import get_wish, update_wish


class WishUpdateCommand(Command):
    name: ClassVar[str] = "wish_update"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Update mutable fields of a runtime wish item."
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
                "wish": {"type": "string", "format": "uuid", "description": "Wish UUID."},
                "changed_by": {"type": "string", "description": "Actor updating the wish."},
                "title": {"type": "string", "description": "New title, if changing."},
                "description": {"type": "string", "description": "New description, if changing."},
                "kind": {"type": "string", "description": "New wish kind, if changing."},
                "status": {"type": "string", "description": "New wish status, if changing."},
                "priority_nice": {"type": "integer", "description": "New nice-scale priority, if changing."},
                "assigned_to": {"type": "string", "description": "New assigned actor, if changing."},
                "target_release": {"type": "string", "description": "New target release label, if changing."},
                "rationale": {"type": "string", "description": "New rationale or decision note, if changing."},
            },
            "required": ["wish", "changed_by"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        params = {
            "wish": {"description": "Wish UUID.", "type": "string", "required": True},
            "changed_by": {"description": "Actor updating the wish.", "type": "string", "required": True},
            "title": {"description": "New title, if changing.", "type": "string", "required": False},
            "description": {"description": "New description, if changing.", "type": "string", "required": False},
            "kind": {"description": "New wish kind, if changing.", "type": "string", "required": False},
            "status": {"description": "New wish status, if changing.", "type": "string", "required": False},
            "priority_nice": {"description": "New nice-scale priority, if changing.", "type": "integer", "required": False},
            "assigned_to": {"description": "New assigned actor, if changing.", "type": "string", "required": False},
            "target_release": {"description": "New target release label, if changing.", "type": "string", "required": False},
            "rationale": {"description": "New rationale or decision note, if changing.", "type": "string", "required": False},
        }
        return wish_metadata(
            cls,
            params,
            {"success": {"description": "The updated WishItem payload."}},
            [{"description": "Move a wish into planned status.", "command": {"wish": "11111111-1111-1111-1111-111111111111", "changed_by": "owner", "status": "planned"}}],
            include_not_found=True,
            best_practices=[
                "Omit any field you do not want to change; only non-null parameters are patched.",
                "Status transitions are intentionally lightweight here: the wish is a planning desire, not a bug or TODO state machine.",
            ],
        )

    async def execute(
        self,
        wish: str,
        changed_by: str,
        title: str | None = None,
        description: str | None = None,
        kind: str | None = None,
        status: str | None = None,
        priority_nice: int | None = None,
        assigned_to: str | None = None,
        target_release: str | None = None,
        rationale: str | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_update(
                raw_entity_id=wish,
                get_record=get_wish,
                update_record=update_wish,
                changed_by=changed_by,
                not_found_code="WISH_NOT_FOUND",
                not_found_message=f"wish not found: {wish}",
                update_fields={
                    "title": title,
                    "description": description,
                    "kind": kind,
                    "status": status,
                    "priority_nice": priority_nice,
                    "assigned_to": assigned_to,
                    "target_release": target_release,
                    "rationale": rationale,
                },
            )
        except Exception as exc:
            return map_exception(exc)
