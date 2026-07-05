"""Command: return the concept list of a plan (concept_list)."""

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.concept_list_metadata import get_concept_list_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.concept_store import list_concepts
from plan_manager.runtime.context import db_connection


class ConceptListCommand(Command):
    """Return the full MRS concept (C-003) list of a resolved plan.

    Read-only command: never mutates plan state.
    """

    name = "concept_list"
    version = "1.0.0"
    descr = "Return the concept list of a plan."
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
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return every concept of plan.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.

        Returns:
            SuccessResult with data {"concepts": [...]}, one entry per stored
            concept, or ErrorResult with code PLAN_NOT_FOUND.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                concepts = list_concepts(conn, p.uuid)
                return SuccessResult(data={
                    "concepts": [
                        {
                            "concept_id": c.concept_id,
                            "name": c.name,
                            "definition": c.definition,
                            "properties": c.properties,
                            "source_labels": c.source_labels,
                        }
                        for c in concepts
                    ]
                })
        except Exception as exc:
            return map_exception(exc)
