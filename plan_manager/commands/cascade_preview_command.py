"""Cascade preview command: reports the open cascade's change set and gate."""

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.cascade.record import get_open_cascade
from plan_manager.cascade.preview import preview_cascade
from plan_manager.commands.cascade_preview_metadata import get_cascade_preview_metadata


class CascadePreviewCommand(Command):
    """Read-only report of the open cascade's change set and gate verdict."""

    name = "cascade_preview"
    version = "1.0.0"
    descr = (
        "Report the accumulated change set, needs_review blast radius, "
        "and mechanical gate verdict of a plan's open cascade."
    )
    category = "cascade"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the JSON Schema for cascade_preview input parameters.

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
        """Return the extended documentation metadata for cascade_preview.

        Returns:
            The dictionary produced by get_cascade_preview_metadata(cls).
        """
        return get_cascade_preview_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate cascade_preview input parameters.

        Args:
            params: Raw input parameters as received by the command.

        Returns:
            The validated parameters dictionary.
        """
        params = super().validate_params(params)
        return params

    async def execute(self, **kwargs):
        """Return the open cascade's change set, blast radius, and gate.

        Args:
            **kwargs: Keyword arguments containing "plan" (str): plan
                UUID or unique plan name.

        Returns:
            A SuccessResult wrapping the dict returned by preview_cascade
            on success, an ErrorResult with code CASCADE_REQUIRED when the
            plan has no open cascade, or an ErrorResult produced by
            map_exception on other failures.
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
                data = preview_cascade(conn, p.uuid)
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
