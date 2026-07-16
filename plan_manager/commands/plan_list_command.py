"""Command: plan_list — returns a paginated page of the database catalog of plans."""

from typing import ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_list_metadata import get_plan_list_metadata
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.plan import list_plans
from plan_manager.runtime.context import db_connection

class PlanListCommand(Command):
    """Return a paginated page of the catalog of all plans, read-only."""

    name: ClassVar[str] = "plan_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "List a paginated page of plans in the catalog with their bound "
        "projects; soft-deleted plans are hidden unless show_deleted is true."
    )
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the machine-readable input schema for plan_list.

        Returns:
            dict: JSON-schema-like dict with an optional boolean
                ``show_deleted`` parameter (default False) plus the
                uniform pagination properties (limit, offset).
        """
        return {
            "type": "object",
            "properties": {
                "show_deleted": {
                    "type": "boolean",
                    "description": (
                        "When true, include soft-deleted plans in the "
                        "catalog; when false (the default), soft-deleted "
                        "plans are omitted."
                    ),
                    "default": False,
                },
                **pagination_schema_properties(),
            },
            "required": [],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        """Return the extended documentation metadata for plan_list.

        Returns:
            dict: Metadata dictionary from get_plan_list_metadata(cls).
        """
        return get_plan_list_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate and normalize plan_list parameters.

        Args:
            params: Raw parameters as received by the adapter.

        Returns:
            dict: Normalized parameters with ``show_deleted`` defaulted to
                False when absent.

        Raises:
            ValueError: When ``show_deleted`` is present but not a boolean;
                a parameter-shape violation, not a domain condition.
        """
        params = super().validate_params(params)
        show_deleted = params.get("show_deleted", False)
        if not isinstance(show_deleted, bool):
            raise ValueError("show_deleted must be a boolean")
        params["show_deleted"] = show_deleted
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        """List one page of plans in the catalog with their bound projects.

        Args:
            **kwargs: Validated parameters: ``show_deleted`` (bool), ``limit``
                (int, default 50, max 200), ``offset`` (int, default 0). When
                show_deleted is False (the default) soft-deleted plans are
                omitted.

        Returns:
            SuccessResult | ErrorResult: On success, data has "plans": a
                page of dicts with "uuid", "name", "status",
                "context_budget", "has_head", the bound projects
                ("project_ids", "project_count", "primary_project_id"), and
                the soft-deletion flag "deleted", plus "total", "limit", and
                "offset". On unexpected failure, an ErrorResult produced by
                map_exception, including INVALID_PAGINATION for an
                out-of-range limit or offset.
        """
        show_deleted = kwargs.get("show_deleted", False)
        try:
            pagination = parse_pagination({"limit": kwargs.get("limit"), "offset": kwargs.get("offset")})
            with db_connection() as conn:
                plans = list_plans(conn, show_deleted=show_deleted)
                total = len(plans)
                page = plans[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(
                    data={
                        "plans": [
                            {
                                "uuid": str(pl.uuid),
                                "name": pl.name,
                                "status": pl.status,
                                "context_budget": pl.context_budget,
                                "has_head": pl.head_revision_uuid is not None,
                                "project_ids": list(pl.project_ids),
                                "project_count": len(pl.project_ids),
                                "primary_project_id": pl.primary_project_id,
                                "deleted": pl.deleted_at is not None,
                            }
                            for pl in page
                        ],
                        "total": total,
                        "limit": pagination.limit,
                        "offset": pagination.offset,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
