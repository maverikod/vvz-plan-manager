"""Read-only command listing a paginated page of a plan's HRS paragraphs."""

from __future__ import annotations

from typing import Any, Dict

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.hrs.paragraphs import list_paragraphs
from plan_manager.commands.para_list_metadata import get_para_list_metadata
from plan_manager.commands.list_projection import parse_view, project_rows, view_schema_properties

# Compact view=summary projection (bug 8a13977d): drops "text", the paragraph
# body itself -- the field that makes a full HRS paragraph listing large.
PARA_LIST_SUMMARY_FIELDS = ("label", "binding", "position")

class ParaListCommand(Command):
    """List a paginated page of the resolved plan's HRS paragraphs in position order."""

    name = "para_list"
    version = "1.0.0"
    descr = "List a paginated page of a plan's HRS paragraphs with label, binding flag, and position."
    category = "paragraph"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or catalog name) to resolve.",
                },
                **pagination_schema_properties(),
                **view_schema_properties(),
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            view = parse_view(kwargs.get("view"))
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": kwargs.get("limit"), "offset": kwargs.get("offset")})
                paragraphs = list_paragraphs(conn, p.uuid)
                total = len(paragraphs)
                page = paragraphs[pagination.offset : pagination.offset + pagination.limit]
            return SuccessResult(data={
                "paragraphs": project_rows(page, view, PARA_LIST_SUMMARY_FIELDS),
                "total": total,
                "limit": pagination.limit,
                "offset": pagination.offset,
            })
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_para_list_metadata(cls)
