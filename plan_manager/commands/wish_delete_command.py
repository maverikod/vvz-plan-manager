"""Command: delete a runtime wish item with the universal deletion contract."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_delete_command_helpers import (
    delete_command_metadata_params,
    delete_command_schema,
    perform_runtime_delete,
)
from plan_manager.commands.wish_command_metadata import wish_metadata
from plan_manager.domain.wish import WishItem
from plan_manager.storage.wish_store import get_wish, soft_delete_wish


class WishDeleteCommand(Command):
    name: ClassVar[str] = "wish_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Delete a runtime wish item: soft by default, hard=true gated by the inbound-reference integrity check, dry_run previews."
    category: ClassVar[str] = "wish"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return delete_command_schema("wish", "Wish UUID.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return wish_metadata(
            cls,
            delete_command_metadata_params("wish", "Wish UUID."),
            {"success": {"description": "Dry-run preview or soft/hard deletion result."}},
            [{"description": "Preview wish deletion.", "command": {"wish": "11111111-1111-1111-1111-111111111111", "changed_by": "owner", "dry_run": True}}],
            include_not_found=True,
            error_cases={
                "DELETE_BLOCKED": {
                    "description": "Live inbound references block deletion (for example calendar entries linked to this wish).",
                    "message": "cannot delete wish {wish}: inbound references exist: {references}",
                    "solution": "Inspect the references map in the dry-run preview and detach or delete referrers first.",
                },
            },
            best_practices=[
                "Run dry_run=true before hard deletion to see whether linked calendar entries or other future referrers still point at the wish.",
                "Soft deletion is the default and keeps the row recoverable at the store level while hiding it from wish_get and wish_list.",
            ],
        )

    async def execute(
        self,
        wish: str,
        changed_by: str,
        hard: bool = False,
        dry_run: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_delete(
                raw_entity_id=wish,
                changed_by=changed_by,
                hard=hard,
                dry_run=dry_run,
                entity_cls=WishItem,
                get_record=get_wish,
                soft_delete=soft_delete_wish,
                not_found_code="WISH_NOT_FOUND",
                not_found_message=f"wish not found: {wish}",
                payload_key="wish",
            )
        except Exception as exc:
            return map_exception(exc)
