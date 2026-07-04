"""Command: plan_list — returns the database catalog of plans."""

from typing import ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_list_metadata import get_plan_list_metadata
from plan_manager.domain.plan import list_plans
from plan_manager.runtime.context import db_connection


class PlanListCommand(Command):
    """Return the catalog of all plans, read-only."""

    name: ClassVar[str] = "plan_list"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "List all plans in the catalog."
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the machine-readable input schema for plan_list.

        Returns:
            dict: JSON-schema-like dict with no properties and no
                required parameters.
        """
        return {
            "type": "object",
            "properties": {},
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
        """Validate plan_list parameters (none beyond the base schema check).

        Args:
            params: Raw parameters as received by the adapter.

        Returns:
            dict: The parameters unchanged (after base validation).
        """
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        """List all plans in the catalog.

        Args:
            **kwargs: Unused; plan_list takes no parameters.

        Returns:
            SuccessResult | ErrorResult: On success, data has "plans": a
                list of dicts with "uuid", "name", "status",
                "context_budget", "has_head". On unexpected failure, an
                ErrorResult produced by map_exception.
        """
        try:
            with db_connection() as conn:
                plans = list_plans(conn)
                return SuccessResult(
                    data={
                        "plans": [
                            {
                                "uuid": str(pl.uuid),
                                "name": pl.name,
                                "status": pl.status,
                                "context_budget": pl.context_budget,
                                "has_head": pl.head_revision_uuid is not None,
                            }
                            for pl in plans
                        ]
                    }
                )
        except Exception as exc:
            return map_exception(exc)
