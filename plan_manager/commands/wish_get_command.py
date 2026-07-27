"""Command: fetch one runtime wish item by UUID."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.base_command import Command
from plan_manager.commands.errors import map_exception
from plan_manager.commands.runtime_record_command_helpers import (
    get_command_metadata_params,
    get_command_schema,
    perform_runtime_get,
)
from plan_manager.commands.wish_command_metadata import wish_metadata
from plan_manager.storage.wish_store import get_wish


class WishGetCommand(Command):
    name: ClassVar[str] = "wish_get"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Fetch one runtime wish item by UUID."
    category: ClassVar[str] = "wish"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        return get_command_schema("wish", "Wish UUID.")

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        return wish_metadata(
            cls,
            get_command_metadata_params("wish", "Wish UUID."),
            {"success": {"description": "The WishItem payload."}},
            [{"description": "Fetch one wish item by UUID.", "command": {"wish": "11111111-1111-1111-1111-111111111111"}}],
            include_not_found=True,
            best_practices=[
                "wish_get returns only live rows; a soft-deleted wish and a never-existing UUID are both reported as WISH_NOT_FOUND.",
                "Use wish_list to discover identifiers before a direct get.",
            ],
        )

    async def execute(self, wish: str, context: object | None = None) -> SuccessResult | ErrorResult:
        try:
            return perform_runtime_get(
                raw_entity_id=wish,
                get_record=get_wish,
                not_found_code="WISH_NOT_FOUND",
                not_found_message=f"wish not found: {wish}",
            )
        except Exception as exc:
            return map_exception(exc)
