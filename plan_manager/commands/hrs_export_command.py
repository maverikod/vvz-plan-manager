"""HrsExportCommand: read-only export of a plan's HRS Markdown text."""

from typing import Any, ClassVar, Dict, Type

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.hrs_export_metadata import get_hrs_export_metadata
from plan_manager.exchange.exporter import export_hrs
from plan_manager.runtime.context import db_connection


class HrsExportCommand(Command):
    """Return the byte-identical HRS Markdown text of a resolved plan."""

    name: ClassVar[str] = "hrs_export"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Export the byte-identical HRS Markdown text of a plan."
    category: ClassVar[str] = "exchange"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[Type[SuccessResult]] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for hrs_export.

        Returns:
            A JSON-schema-shaped dictionary with an explicit
            additionalProperties=False and an exact required list.
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier resolved against the catalog.",
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return the extended documentation metadata for hrs_export.

        Returns:
            The dictionary produced by get_hrs_export_metadata(cls).
        """
        return get_hrs_export_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate hrs_export parameters.

        Args:
            params: Raw parameter dictionary received from the platform.

        Returns:
            The validated parameter dictionary, unchanged beyond the base
            validator's own normalization.
        """
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return the HRS Markdown text of the resolved plan.

        Args:
            plan: Plan identifier resolved against the catalog.

        Returns:
            SuccessResult with data {"markdown": str} on success, or
            ErrorResult with domain code PLAN_NOT_FOUND on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                markdown = export_hrs(conn, p.uuid)
                return SuccessResult(data={"markdown": markdown})
        except Exception as exc:
            return map_exception(exc)
