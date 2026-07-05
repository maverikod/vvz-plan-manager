"""Command: return the relation list of a plan (relation_list)."""

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.relation_list_metadata import get_relation_list_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.relation_store import list_relations
from plan_manager.runtime.context import db_connection


class RelationListCommand(Command):
    """Return the full MRS relation (C-004) list of a resolved plan.

    Read-only command: never mutates plan state.
    """

    name = "relation_list"
    version = "1.0.0"
    descr = "Return the relation list of a plan."
    category = "mrs"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the strict input schema for relation_list."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or unique plan name) to resolve.",
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_relation_list_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate params: shallow schema checks only; no further semantics needed."""
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return every relation of plan.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.

        Returns:
            SuccessResult with data {"relations": [...]}, one entry per stored
            relation with keys from_concept, to_concept, type, or ErrorResult
            with code PLAN_NOT_FOUND.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                relations = list_relations(conn, p.uuid)
                return SuccessResult(data={
                    "relations": [
                        {"from_concept": r[0], "to_concept": r[1], "type": r[2]}
                        for r in relations
                    ]
                })
        except Exception as exc:
            return map_exception(exc)
