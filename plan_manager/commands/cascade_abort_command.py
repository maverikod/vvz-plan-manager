"""Cascade abort command: discards the open cascade of a plan."""

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.cascade.record import get_open_cascade
from plan_manager.cascade.close import abort_cascade
from plan_manager.domain.plan import get_plan
from plan_manager.commands.cascade_abort_metadata import get_cascade_abort_metadata


class CascadeAbortCommand(Command):
    """Discard the plan's open cascade and restore the base revision."""

    name = "cascade_abort"
    version = "1.0.0"
    descr = (
        "Discard the plan's open cascade, restoring the working state "
        "to the base revision."
    )
    category = "cascade"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the JSON Schema for cascade_abort input parameters.

        Returns:
            A JSON Schema object accepting exactly one required string
            parameter, "plan".
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan UUID or unique plan name.",
                }
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        """Return the extended documentation metadata for cascade_abort.

        Returns:
            The dictionary produced by get_cascade_abort_metadata(cls).
        """
        return get_cascade_abort_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate cascade_abort input parameters.

        Args:
            params: Raw input parameters as received by the command.

        Returns:
            The validated parameters dictionary.
        """
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs):
        """Abort the open cascade and verify the result by re-read.

        Args:
            **kwargs: Keyword arguments containing "plan" (str): plan
                UUID or unique plan name.

        Returns:
            A SuccessResult with data {"aborted": True,
            "head_revision_uuid": str} on success, an ErrorResult with
            code CASCADE_REQUIRED when the plan has no open cascade, or
            an ErrorResult produced by map_exception on other failures.
        """
        plan = kwargs["plan"]
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                if get_open_cascade(conn, p.uuid) is None:
                    return domain_error(
                        "CASCADE_REQUIRED",
                        f"plan {p.name} has no open cascade",
                    )
                abort_cascade(conn, p.uuid)
                still_open = get_open_cascade(conn, p.uuid)
                assert still_open is None, (
                    f"cascade abort for plan {p.name} did not verify by "
                    "re-read"
                )
                refreshed = get_plan(conn, p.uuid)
                return SuccessResult(
                    data={
                        "aborted": True,
                        "head_revision_uuid": str(
                            refreshed.head_revision_uuid
                        ),
                    }
                )
        except Exception as exc:
            return map_exception(exc)
