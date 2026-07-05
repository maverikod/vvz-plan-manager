"""HrsImportCommand: replace a plan's HRS text from a Markdown source."""

import uuid
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Type

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.hrs_import_metadata import get_hrs_import_metadata
from plan_manager.exchange.exporter import export_hrs
from plan_manager.exchange.importer import import_hrs, validate_hrs
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.views.dependency_graph import load_steps


class HrsImportCommand(Command):
    """Replace the HRS text of a resolved plan from a Markdown source."""

    name: ClassVar[str] = "hrs_import"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Replace a plan's HRS text from a Markdown source under the configured export root."
    category: ClassVar[str] = "exchange"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[Type[SuccessResult]] = SuccessResult
    use_queue: ClassVar[bool] = True

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for hrs_import.

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
                "source": {
                    "type": "string",
                    "description": (
                        "Name of the Markdown source file under the "
                        "configured export root."
                    ),
                },
                "dry_run": {
                    "type": "boolean",
                    "description": (
                        "When true (the default), only validate the HRS "
                        "text without writing to the database."
                    ),
                    "default": True,
                },
                "cascade_uuid": {
                    "type": "string",
                    "description": (
                        "Identifier of an already-open cascade to scope "
                        "this import to."
                    ),
                },
            },
            "required": ["plan", "source"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return the extended documentation metadata for hrs_import.

        Returns:
            The dictionary produced by get_hrs_import_metadata(cls).
        """
        return get_hrs_import_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate hrs_import parameters.

        Args:
            params: Raw parameter dictionary received from the platform.

        Returns:
            The validated parameter dictionary, unchanged beyond the base
            validator's own normalization.

        Raises:
            ValueError: When 'source' is empty or contains '/', '\\' or
                '..', or when 'cascade_uuid' is present but does not
                parse as a UUID.
        """
        params = super().validate_params(params)
        source = params["source"]
        if not source or "/" in source or "\\" in source or ".." in source:
            raise ValueError("source must be a bare file name without path separators")
        cascade_uuid = params.get("cascade_uuid")
        if cascade_uuid is not None:
            uuid.UUID(cascade_uuid)
        return params

    async def execute(
        self,
        plan: str,
        source: str,
        dry_run: bool = True,
        cascade_uuid: Optional[str] = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Replace the HRS text of the resolved plan from a Markdown source.

        Args:
            plan: Plan identifier resolved against the catalog.
            source: Bare Markdown file name under the configured export
                root.
            dry_run: When True (the default), only validate the source
                text.
            cascade_uuid: Optional identifier of an already-open cascade
                to scope this import to.

        Returns:
            SuccessResult with the dry-run report or the paragraph count
            of the replaced HRS (verified by re-read) on success, or
            ErrorResult with domain code PLAN_NOT_FOUND, IMPORT_INVALID,
            CASCADE_REQUIRED, CASCADE_CONFLICT, or FROZEN_ARTIFACT on
            failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                text = Path(app_config().export_root, source).read_text(encoding="utf-8")
                issues = validate_hrs(text)
                if issues:
                    return domain_error(
                        "IMPORT_INVALID", "hrs validation failed", {"issues": issues}
                    )
                if dry_run:
                    return SuccessResult(data={"dry_run": True, "valid": True})
                parsed_cascade_uuid = (
                    uuid.UUID(cascade_uuid) if cascade_uuid is not None else None
                )
                try:
                    rec = check_admission(conn, p.uuid, "paragraph", None, parsed_cascade_uuid)
                except CascadeError as exc:
                    if cascade_uuid is not None:
                        return domain_error("CASCADE_CONFLICT", str(exc))
                    steps = load_steps(conn, p.uuid)
                    if any(s.status == "frozen" for s in steps.values()):
                        return domain_error("FROZEN_ARTIFACT", str(exc))
                    return domain_error("CASCADE_REQUIRED", str(exc))
                summary = import_hrs(conn, p.uuid, text, "api", rec)
                reread = export_hrs(conn, p.uuid)
                assert reread == text, "hrs_import verification mismatch: re-read text differs from imported text"
                return SuccessResult(data={"dry_run": False, "paragraphs": summary["paragraphs"]})
        except Exception as exc:
            return map_exception(exc)
