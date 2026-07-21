"""Command: return a paginated page of the concept list of a plan (concept_list)."""

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.concept_list_metadata import get_concept_list_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.commands.runtime_filtering import (
    pagination_schema_properties,
    parse_pagination,
)
from plan_manager.domain.concept_store import list_concepts
from plan_manager.runtime.context import db_connection

class ConceptListCommand(Command):
    """Return a paginated page of the MRS concept (C-003) list of a resolved plan.

    Read-only command: never mutates plan state.
    """

    name = "concept_list"
    version = "1.0.0"
    descr = "Return a paginated page of the concept list of a plan."
    category = "mrs"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the strict input schema for concept_list."""
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
        return get_concept_list_metadata(cls)

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
        """Return one page of concepts of plan.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            limit: Maximum number of concepts to return (default 50, max 200).
            offset: Number of concepts to skip before returning results (default 0).

        Returns:
            SuccessResult with data {"concepts": [...], "total": int, "limit": int,
            "offset": int}, where concepts is the requested page (each entry has
            concept_id, name, definition, properties, source_labels) and total is
            the count of the full concept set before pagination, or ErrorResult
            with code PLAN_NOT_FOUND or INVALID_PAGINATION.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                pagination = parse_pagination({"limit": limit, "offset": offset})
                concepts = list_concepts(conn, p.uuid)
                total = len(concepts)
                page = concepts[pagination.offset : pagination.offset + pagination.limit]
                return SuccessResult(data={
                    "concepts": [
                        {
                            "concept_id": c.concept_id,
                            "name": c.name,
                            "definition": c.definition,
                            "properties": c.properties,
                            "source_labels": c.source_labels,
                        }
                        for c in page
                    ],
                    "total": total,
                    "limit": pagination.limit,
                    "offset": pagination.offset,
                })
        except Exception as exc:
            return map_exception(exc)
