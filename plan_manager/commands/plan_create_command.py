"""Command: plan_create — creates a new plan aggregate."""

from typing import ClassVar

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult
from mcp_proxy_adapter.core.errors import InvalidParamsError

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_create_metadata import get_plan_create_metadata
from plan_manager.domain.plan import create_plan, get_plan
from plan_manager.runtime.context import db_connection


class PlanCreateCommand(Command):
    """Create a new plan aggregate at revision zero with empty HRS and MRS."""

    name: ClassVar[str] = "plan_create"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = "Create a new plan aggregate with a unique name."
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the machine-readable input schema for plan_create.

        Returns:
            dict: JSON-schema-like dict with "name" (required string) and
                "context_budget" (optional integer, default 4000).
        """
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Unique plan name.",
                },
                "context_budget": {
                    "type": "integer",
                    "description": (
                        "Context budget in tokens for prompt assembly; "
                        "must be at least 1. Defaults to 4000."
                    ),
                    "default": 4000,
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        """Return the extended documentation metadata for plan_create.

        Returns:
            dict: Metadata dictionary from get_plan_create_metadata(cls).
        """
        return get_plan_create_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate and normalize plan_create parameters.

        Args:
            params: Raw parameters as received by the adapter.

        Returns:
            dict: Normalized parameters with "name" stripped and
                "context_budget" defaulted to 4000 when absent.

        Raises:
            InvalidParamsError: When name is empty after stripping, or when
                context_budget is not an integer >= 1. These are
                parameter-shape violations, not domain conditions.
        """
        params = super().validate_params(params)
        name = params.get("name")
        if not isinstance(name, str) or not name.strip():
            raise InvalidParamsError("name must be a non-empty string")
        params["name"] = name.strip()
        context_budget = params.get("context_budget", 4000)
        if (
            not isinstance(context_budget, int)
            or isinstance(context_budget, bool)
            or context_budget < 1
        ):
            raise InvalidParamsError("context_budget must be an integer >= 1")
        params["context_budget"] = context_budget
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        """Create the plan, then verify by re-reading the stored row.

        Args:
            **kwargs: Validated parameters: "name" (str) and
                "context_budget" (int).

        Returns:
            SuccessResult | ErrorResult: On success, data has "uuid",
                "name", "status", "context_budget". On failure, an
                ErrorResult produced by map_exception (e.g. DUPLICATE_ID
                for a name collision).
        """
        name = kwargs["name"]
        context_budget = kwargs.get("context_budget", 4000)
        try:
            with db_connection() as conn:
                created = create_plan(conn, name, context_budget)
                verified = get_plan(conn, created.uuid)
                return SuccessResult(
                    data={
                        "uuid": str(verified.uuid),
                        "name": verified.name,
                        "status": verified.status,
                        "context_budget": verified.context_budget,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
