"""HrsImportCommand: replace a plan's HRS text from a Markdown source."""

import uuid
from pathlib import Path
from typing import Any, ClassVar, Dict, Optional, Type

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.cascade.record import CascadeError
from plan_manager.cascade.regime import check_admission
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan_guarded as resolve_plan
from plan_manager.commands.hrs_import_metadata import get_hrs_import_metadata
from plan_manager.exchange.importer import import_hrs, validate_hrs
from plan_manager.domain.paragraph_store import list_paragraphs
from plan_manager.domain.runtime_validation import validate_uuid
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.views.dependency_graph import load_steps


def _invalid_request(message: str, field: str) -> ErrorResult:
    return ErrorResult(
        message=message,
        code=-32602,
        details={"error_type": "InvalidRequest", "field": field},
    )


class HrsImportCommand(Command):
    """Replace the HRS text of a resolved plan from Markdown content."""

    name: ClassVar[str] = "hrs_import"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Replace a plan's HRS text from a Markdown file under the configured "
        "export root or from inline source_text."
    )
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
                "source_text": {
                    "type": "string",
                    "description": (
                        "Inline Markdown HRS source text. Mutually exclusive "
                        "with source."
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
            "required": ["plan"],
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

        Note:
            A malformed ``cascade_uuid`` is NOT parsed here: a bare ValueError
            raised from validate_params is wrapped by the adapter into a
            generic -32603 InternalError. execute() validates cascade_uuid
            through validate_uuid instead, so a malformed value surfaces as a
            clean RUNTIME_VALIDATION_ERROR domain code.
        """
        return super().validate_params(params)

    async def execute(
        self,
        plan: str,
        source: Optional[str] = None,
        source_text: Optional[str] = None,
        dry_run: bool = True,
        cascade_uuid: Optional[str] = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Replace the HRS text of the resolved plan from a Markdown source.

        Args:
            plan: Plan identifier resolved against the catalog.
            source: Optional bare Markdown file name under the configured
                export root.
            source_text: Optional inline Markdown HRS content. Exactly
                one of source and source_text is required.
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
            # Validate the optional cascade_uuid up front so a malformed value returns a clean
            # RUNTIME_VALIDATION_ERROR instead of a raw ValueError (-32603) from the later parse.
            parsed_cascade_uuid = (
                validate_uuid(cascade_uuid) if cascade_uuid is not None else None
            )
            has_source = source is not None
            has_source_text = source_text is not None
            if has_source == has_source_text:
                return _invalid_request(
                    "exactly one of source or source_text must be supplied",
                    "source",
                )
            if source is not None and (
                not source or "/" in source or "\\" in source or ".." in source
            ):
                return _invalid_request(
                    "source must be a bare file name without path separators",
                    "source",
                )
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                if source_text is not None:
                    text = source_text
                elif source is not None:
                    text = Path(app_config().export_root, source).read_text(encoding="utf-8")
                issues = validate_hrs(text)
                if issues:
                    return domain_error(
                        "IMPORT_INVALID", "hrs validation failed", {"issues": issues}
                    )
                if dry_run:
                    return SuccessResult(data={"dry_run": True, "valid": True})
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
                reread = [
                    {
                        "label": paragraph.label,
                        "text": paragraph.text,
                        "position": paragraph.position,
                    }
                    for paragraph in list_paragraphs(conn, p.uuid)
                ]
                if reread != summary["written"]:
                    raise RuntimeError(
                        "hrs_import verification mismatch: stored paragraphs differ from written paragraphs"
                    )
                return SuccessResult(data={"dry_run": False, "paragraphs": summary["paragraphs"]})
        except Exception as exc:
            return map_exception(exc)
