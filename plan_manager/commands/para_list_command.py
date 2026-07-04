"""Read-only command listing every paragraph of a plan's HRS text."""

from __future__ import annotations

from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.hrs.paragraphs import list_paragraphs
from plan_manager.commands.para_list_metadata import get_para_list_metadata


class ParaListCommand(Command):
    """List every paragraph of the resolved plan's HRS in position order."""

    name = "para_list"
    version = "1.0.0"
    descr = "List every paragraph of a plan's HRS with label, binding flag, and position."
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
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                paragraphs = list_paragraphs(conn, p.uuid)
            return SuccessResult(data={"paragraphs": paragraphs})
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_para_list_metadata(cls)
