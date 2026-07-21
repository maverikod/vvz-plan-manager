"""Cascade commit command: publishes the open cascade atomically."""

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.cascade.record import get_open_cascade
from plan_manager.cascade.close import commit_cascade
from plan_manager.domain.plan import get_plan
from plan_manager.commands.cascade_commit_metadata import get_cascade_commit_metadata


class CascadeCommitCommand(Command):
    """Publish the plan's open cascade atomically on a green gate."""

    name = "cascade_commit"
    version = "1.0.0"
    descr = (
        "Publish the plan's open cascade atomically: advance the head "
        "revision on a green gate, or refuse on a red gate."
    )
    category = "cascade"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the JSON Schema for cascade_commit input parameters.

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
        """Return the extended documentation metadata for cascade_commit.

        Returns:
            The dictionary produced by get_cascade_commit_metadata(cls).
        """
        return get_cascade_commit_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate cascade_commit input parameters.

        Args:
            params: Raw input parameters as received by the command.

        Returns:
            The validated parameters dictionary.
        """
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs):
        """Commit the open cascade and verify the result by re-read.

        Args:
            **kwargs: Keyword arguments containing "plan" (str): plan
                UUID or unique plan name.

        Returns:
            A SuccessResult with data {"green": bool, "scope": str,
            "head_revision_uuid": str} on success, an ErrorResult with
            code CASCADE_REQUIRED when the plan has no open cascade, or
            an ErrorResult produced by map_exception on other failures
            (including GATE_RED when the gate refuses the commit).
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
                verdict = commit_cascade(conn, p.uuid)
                still_open = get_open_cascade(conn, p.uuid)
                refreshed = get_plan(conn, p.uuid)
                assert (
                    still_open is None
                    and refreshed.head_revision_uuid is not None
                ), (
                    f"cascade commit for plan {p.name} did not verify by "
                    "re-read"
                )
                return SuccessResult(
                    data={
                        "green": verdict.green,
                        "scope": verdict.scope,
                        "head_revision_uuid": str(
                            refreshed.head_revision_uuid
                        ),
                    }
                )
        except Exception as exc:
            return map_exception(exc)
