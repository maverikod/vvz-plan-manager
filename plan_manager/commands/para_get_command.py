"""Read-only command resolving one paragraph label to its text."""

from __future__ import annotations

import re
from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.hrs.paragraphs import get_paragraph
from plan_manager.commands.para_get_metadata import get_para_get_metadata

_LABEL_RE = re.compile(r"^[0-9a-z]{4}$")


class ParaGetCommand(Command):
    """Resolve one bare four-character base36 paragraph label to its text."""

    name = "para_get"
    version = "1.0.0"
    descr = "Resolve one paragraph label of a plan's HRS to its text."
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
                "label": {
                    "type": "string",
                    "description": "Bare four-character base36 paragraph label (no braces).",
                },
            },
            "required": ["plan", "label"],
            "additionalProperties": False,
        }

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = super().validate_params(params)
        label = params.get("label", "")
        if not _LABEL_RE.match(label):
            raise ValueError(
                f"label must be exactly four base36 characters [0-9a-z]: {label!r}"
            )
        return params

    async def execute(self, **kwargs: Any) -> SuccessResult | ErrorResult:
        try:
            plan = kwargs["plan"]
            label = kwargs["label"]
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                para = get_paragraph(conn, p.uuid, label)
            if para is None:
                return domain_error("PARAGRAPH_NOT_FOUND", f"label not found: {label}")
            return SuccessResult(data=para)
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        return get_para_get_metadata(cls)
