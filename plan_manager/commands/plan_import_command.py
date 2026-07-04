"""PlanImportCommand: create a new plan from a standard file layout."""

from pathlib import Path
from typing import Any, ClassVar, Dict, Type

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.plan_import_metadata import get_plan_import_metadata
from plan_manager.exchange.importer import import_plan, validate_layout
from plan_manager.runtime.context import app_config, db_connection


class PlanImportCommand(Command):
    """Create a new plan from a standard file layout under the export root."""

    name: ClassVar[str] = "plan_import"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Import a plan from a standard file layout under the configured export root."
    category: ClassVar[str] = "exchange"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[Type[SuccessResult]] = SuccessResult
    use_queue: ClassVar[bool] = True

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for plan_import.

        Returns:
            A JSON-schema-shaped dictionary with an explicit
            additionalProperties=False and an exact required list.
        """
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": (
                        "Name of the standard layout directory under the "
                        "configured export root."
                    ),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "When true (the default), only validate the "
                        "layout without writing to the database."
                    ),
                    "default": True,
                },
            },
            "required": ["source"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return the extended documentation metadata for plan_import.

        Returns:
            The dictionary produced by get_plan_import_metadata(cls).
        """
        return get_plan_import_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate plan_import parameters.

        Args:
            params: Raw parameter dictionary received from the platform.

        Returns:
            The validated parameter dictionary, unchanged beyond the base
            validator's own normalization.

        Raises:
            ValueError: When 'source' is empty or contains '/', '\\' or
                '..'.
        """
        params = super().validate_params(params)
        source = params["source"]
        if not source or "/" in source or "\\" in source or ".." in source:
            raise ValueError("source must be a bare layout name without path separators")
        return params

    async def execute(self, source: str, dry_run: bool = True) -> SuccessResult | ErrorResult:
        """Import a plan from a standard file layout, validating before write.

        Args:
            source: Bare directory name under the configured export root.
            dry_run: When True (the default), only validate the layout.

        Returns:
            SuccessResult with the dry-run report or the created plan
            state (verified by re-read) on success, or ErrorResult with
            domain code IMPORT_INVALID on a malformed layout.
        """
        try:
            source_root = str(Path(app_config().export_root) / source)
            issues = validate_layout(source_root)
            if issues:
                return domain_error(
                    "IMPORT_INVALID", "layout validation failed", {"issues": issues}
                )
            if dry_run:
                return SuccessResult(
                    data={"dry_run": True, "valid": True, "source": source}
                )
            with db_connection() as conn:
                new_uuid = import_plan(conn, source_root, "api")
                created = resolve_plan(conn, str(new_uuid))
                return SuccessResult(
                    data={
                        "dry_run": False,
                        "plan_uuid": str(new_uuid),
                        "name": created.name,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
