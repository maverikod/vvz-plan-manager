"""Command: files_report - target_file to writer-steps matrix for a plan scope (C-004)."""

from __future__ import annotations

from typing import Any, ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.files_report_metadata import get_files_report_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.runtime.context import db_connection
from plan_manager.views.dependency_graph import build_edges, load_steps
from plan_manager.views.files_report import build_files_report
from plan_manager.views.prompt_chain import normalize_scope, scope_atomic_steps


class FilesReportCommand(Command):
    """Return the target_file to writer-steps matrix for a plan scope."""

    name: ClassVar[str] = "files_report"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Return the target_file to writer-steps matrix for a plan scope, "
        "with ordering-conflict detection."
    )
    category: ClassVar[str] = "step"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict[str, Any]:
        """Return the machine-readable input schema for files_report.

        Returns:
            A JSON-Schema-shaped dict with `type`, `properties`,
            `required`, and `additionalProperties` keys.
        """
        properties = {
            "plan": {
                "type": "string",
                "description": "Plan identifier (UUID or name) to resolve the plan against the catalog.",
            },
            "scope": {
                "type": "string",
                "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                "default": "whole_plan",
            },
            **pagination_schema_properties(),
        }
        return {
            "type": "object",
            "properties": properties,
            "required": ["plan"],
            "additionalProperties": False,
        }

    def validate_params(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate files_report parameters and default scope to whole_plan.

        Args:
            params: Raw parameter dict as received by the adapter.

        Returns:
            The validated parameter dict with "scope" defaulted to
            "whole_plan" when absent.
        """
        params = super().validate_params(params)
        normalized = dict(params)
        normalized.setdefault("scope", "whole_plan")
        return normalized

    async def execute(
        self,
        plan: str,
        scope: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return one page of the files-to-writers report for a plan scope.

        Args:
            plan: Plan identifier (UUID or name).
            scope: Optional scope selector: "whole_plan", "G-NNN", or
                "G-NNN/T-NNN". Defaults to "whole_plan".
            limit: Optional page size (default 50, max 200).
            offset: Optional pagination offset (default 0).

        Returns:
            SuccessResult with data {"files": [...], "total_count": N} on
            success, where each files entry is {"target_file", "writers",
            "ordering_conflict"}; ErrorResult with a stable domain error
            code on failure.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                try:
                    normalized_scope = normalize_scope(scope)
                except ValueError as exc:
                    return domain_error("INVALID_SCOPE", str(exc), {"scope": scope})

                nodes = load_steps(conn, p.uuid)
                try:
                    scoped_atomic = scope_atomic_steps(nodes, normalized_scope)
                except ValueError as exc:
                    return domain_error("STEP_NOT_FOUND", str(exc))

                edges = build_edges(nodes)
                pagination = parse_pagination({"limit": limit, "offset": offset})

                full_report = build_files_report(nodes, scoped_atomic, edges)
                total_count = len(full_report)
                page = full_report[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={"files": page, "total_count": total_count})
        except Exception as exc:
            return map_exception(exc)

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """Return the extended documentation metadata for files_report.

        Returns:
            The dict produced by `get_files_report_metadata(cls)`.
        """
        return get_files_report_metadata(cls)
