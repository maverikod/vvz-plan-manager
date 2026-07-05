"""PlanExportCommand: read-only export of a plan to the standard file layout."""

import uuid
from typing import Any, ClassVar, Dict, Optional, Type

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.plan_export_metadata import get_plan_export_metadata
from plan_manager.exchange.exporter import export_plan
from plan_manager.runtime.context import app_config, db_connection


class PlanExportCommand(Command):
    """Render one resolved plan into the standard file layout, read-only."""

    name: ClassVar[str] = "plan_export"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Export a plan to the standard file layout under the configured export root."
    category: ClassVar[str] = "exchange"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[Type[SuccessResult]] = SuccessResult
    use_queue: ClassVar[bool] = True

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for plan_export.

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
                "revision": {
                    "type": "string",
                    "description": (
                        "Optional revision UUID to export instead of the "
                        "plan head revision."
                    ),
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return the extended documentation metadata for plan_export.

        Returns:
            The dictionary produced by get_plan_export_metadata(cls).
        """
        return get_plan_export_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate plan_export parameters.

        Args:
            params: Raw parameter dictionary received from the platform.

        Returns:
            The validated parameter dictionary, unchanged beyond the base
            validator's own normalization.

        Raises:
            ValueError: When the optional 'revision' parameter is present
                but does not parse as a UUID.
        """
        params = super().validate_params(params)
        revision = params.get("revision")
        if revision is not None:
            uuid.UUID(revision)
        return params

    async def execute(
        self,
        plan: str,
        revision: Optional[str] = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Export the resolved plan to the standard file layout.

        Args:
            plan: Plan identifier resolved against the catalog.
            revision: Optional revision UUID string; when omitted the plan
                head revision is exported.

        Returns:
            SuccessResult with data {"root": str, "files": int,
            "revision": str} on success, or ErrorResult with a domain code
            (PLAN_NOT_FOUND, REVISION_NOT_FOUND) on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                parsed_revision = uuid.UUID(revision) if revision is not None else None
                summary = export_plan(
                    conn,
                    p.uuid,
                    app_config().export_root,
                    revision_uuid=parsed_revision,
                )
                return SuccessResult(
                    data={
                        "root": summary["root"],
                        "files": summary["files"],
                        "revision": revision if revision is not None else "head",
                    }
                )
        except Exception as exc:
            return map_exception(exc)
