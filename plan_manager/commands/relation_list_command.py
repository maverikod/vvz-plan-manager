"""Command: return a paginated page of the relation list of a plan (relation_list)."""

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import map_exception
from plan_manager.commands.relation_list_metadata import get_relation_list_metadata
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.relation_store import list_relations
from plan_manager.runtime.context import db_connection

class RelationListCommand(Command):
    """Return a paginated page of the MRS relation (C-004) list of a resolved plan.

    Read-only command: never mutates plan state.
    """

    name = "relation_list"
    version = "1.0.0"
    descr = "Return a paginated page of the relation list of a plan."
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
                **pagination_schema_properties(),
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
        limit: int | None = None,
        offset: int | None = None,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return one page of relations of plan.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            limit: Maximum number of relations to return (default 50, max 200).
            offset: Number of relations to skip before returning results (default 0).

        Returns:
            SuccessResult with data {"relations": [...], "total": int, "limit": int,
            "offset": int}, where relations is the requested page (each entry has
            from_concept, to_concept, type) and total is the count of the full
            relation set before pagination, or ErrorResult with code
            PLAN_NOT_FOUND or INVALID_PAGINATION.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                relations = list_relations(conn, p.uuid)
                total = len(relations)
                page = relations[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "relations": [
                        {"from_concept": r[0], "to_concept": r[1], "type": r[2]}
                        for r in page
                    ],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
