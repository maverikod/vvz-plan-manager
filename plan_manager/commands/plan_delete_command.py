"""Command: plan_delete — soft-delete or permanently delete a plan."""

from typing import ClassVar

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.plan_delete_metadata import get_plan_delete_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.plan import (
    PlanNotFoundError,
    get_plan,
    hard_delete_plan,
    soft_delete_plan,
)
from plan_manager.runtime.context import db_connection


class PlanDeleteCommand(Command):
    """Delete a plan, either soft (hideable, reversible) or hard (permanent)."""

    name: ClassVar[str] = "plan_delete"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Delete a plan: soft by default (hidden from the catalog, "
        "reversible), or permanently with hard=true."
    )
    category: ClassVar[str] = "plan"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class: ClassVar[type] = SuccessResult
    use_queue: ClassVar[bool] = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the machine-readable input schema for plan_delete.

        Returns:
            dict: JSON-schema-like dict with required "plan" (string: uuid
                or name) and optional "hard" (boolean, default False).
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": (
                        "Plan identifier: either the plan UUID or its "
                        "unique name."
                    ),
                },
                "hard": {
                    "type": "boolean",
                    "description": (
                        "Deletion mode. False (the default) performs a soft "
                        "delete: the plan is marked deleted and hidden from "
                        "the default catalog but preserved and reversible. "
                        "True performs a hard delete: the plan and every "
                        "artifact belonging to it are removed permanently "
                        "and irreversibly."
                    ),
                    "default": False,
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        """Return the extended documentation metadata for plan_delete.

        Returns:
            dict: Metadata dictionary from get_plan_delete_metadata(cls).
        """
        return get_plan_delete_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate and normalize plan_delete parameters.

        Args:
            params: Raw parameters as received by the adapter.

        Returns:
            dict: Normalized parameters with "plan" stripped and "hard"
                defaulted to False when absent.

        Raises:
            ValueError: When "plan" is empty after stripping, or when
                "hard" is present but not a boolean. These are
                parameter-shape violations, not domain conditions.
        """
        params = super().validate_params(params)
        plan = params.get("plan")
        if not isinstance(plan, str) or not plan.strip():
            raise ValueError("plan must be a non-empty string")
        params["plan"] = plan.strip()
        hard = params.get("hard", False)
        if not isinstance(hard, bool):
            raise ValueError("hard must be a boolean")
        params["hard"] = hard
        return params

    async def execute(self, **kwargs) -> SuccessResult | ErrorResult:
        """Delete the resolved plan, then verify the result by re-reading.

        Args:
            **kwargs: Validated parameters: "plan" (str) and "hard" (bool).

        Returns:
            SuccessResult | ErrorResult: On success, data has "uuid",
                "name", "mode" ("soft" or "hard"), "deleted" (True), and,
                for soft deletion, "already_deleted" (True when the plan was
                already soft-deleted before this call). On a missing plan,
                an ErrorResult with the PLAN_NOT_FOUND domain code; on other
                failures, an ErrorResult produced by map_exception.
        """
        plan_identifier = kwargs["plan"]
        hard = kwargs.get("hard", False)
        try:
            with db_connection() as conn:
                target = resolve_plan(conn, plan_identifier)

                if hard:
                    hard_delete_plan(conn, target.uuid)
                    try:
                        get_plan(conn, target.uuid)
                    except PlanNotFoundError:
                        pass
                    else:
                        raise RuntimeError(
                            "hard delete did not remove the plan row"
                        )
                    return SuccessResult(
                        data={
                            "uuid": str(target.uuid),
                            "name": target.name,
                            "mode": "hard",
                            "deleted": True,
                        }
                    )

                already_deleted = target.deleted_at is not None
                if not already_deleted:
                    soft_delete_plan(conn, target.uuid)
                verified = get_plan(conn, target.uuid)
                return SuccessResult(
                    data={
                        "uuid": str(verified.uuid),
                        "name": verified.name,
                        "mode": "soft",
                        "deleted": verified.deleted_at is not None,
                        "already_deleted": already_deleted,
                    }
                )
        except Exception as exc:
            return map_exception(exc)
