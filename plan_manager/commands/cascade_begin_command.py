"""Cascade begin command: opens a new cascade transaction on a plan."""

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.cascade.record import get_open_cascade
from plan_manager.cascade.begin import begin_cascade
from plan_manager.commands.cascade_begin_metadata import get_cascade_begin_metadata


class CascadeBeginCommand(Command):
    """Open a new cascade transaction anchored at the plan's head revision."""

    name = "cascade_begin"
    version = "1.0.0"
    descr = (
        "Open a new cascade transaction on a plan, anchored at its "
        "current head revision."
    )
    category = "cascade"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the JSON Schema for cascade_begin input parameters.

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
        """Return the extended documentation metadata for cascade_begin.

        Returns:
            The dictionary produced by get_cascade_begin_metadata(cls).
        """
        return get_cascade_begin_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate cascade_begin input parameters.

        Args:
            params: Raw input parameters as received by the command.

        Returns:
            The validated parameters dictionary.
        """
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs):
        """Open a cascade on the resolved plan and verify it by re-read.

        Args:
            **kwargs: Keyword arguments containing "plan" (str): plan
                UUID or unique plan name.

        Returns:
            A SuccessResult with data {"cascade_uuid": str,
            "base_revision_uuid": str, "ref_name": str, "created_at": str}
            on success, or an ErrorResult produced by map_exception on
            failure.
        """
        plan = kwargs["plan"]
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                rec = begin_cascade(conn, p.uuid)
                reread = get_open_cascade(conn, p.uuid)
                assert reread is not None and reread.uuid == rec.uuid, (
                    f"cascade {rec.uuid} for plan {p.name} did not verify "
                    "by re-read"
                )
                return SuccessResult(
                    data={
                        "cascade_uuid": str(rec.uuid),
                        "base_revision_uuid": str(rec.base_revision_uuid),
                        "ref_name": rec.name,
                        "created_at": rec.created_at.isoformat(),
                    }
                )
        except Exception as exc:
            return map_exception(exc)
