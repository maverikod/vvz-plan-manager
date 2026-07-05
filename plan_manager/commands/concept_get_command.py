"""Command: return one concept by identifier (concept_get)."""

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.concept_get_metadata import get_concept_get_metadata
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.domain.concept_store import get_concept
from plan_manager.runtime.context import db_connection


class ConceptGetCommand(Command):
    """Return one MRS concept (C-003) of a resolved plan by its concept_id.

    Read-only command: never mutates plan state.
    """

    name = "concept_get"
    version = "1.0.0"
    descr = "Return one concept of a plan by concept_id."
    category = "mrs"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the strict input schema for concept_get."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or unique plan name) to resolve.",
                },
                "concept_id": {
                    "type": "string",
                    "description": "Concept identifier in pattern C-NNN.",
                },
            },
            "required": ["plan", "concept_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_concept_get_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate params: shallow schema checks only; no further semantics needed."""
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        concept_id: str,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Return the concept with concept_id in plan, or CONCEPT_NOT_FOUND.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            concept_id: Concept identifier in pattern C-NNN.

        Returns:
            SuccessResult with the concept fields, or ErrorResult with code
            PLAN_NOT_FOUND or CONCEPT_NOT_FOUND.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                concept = get_concept(conn, p.uuid, concept_id)
                if concept is None:
                    return domain_error(
                        "CONCEPT_NOT_FOUND",
                        f"concept not found: {concept_id}",
                    )
                return SuccessResult(data={
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "definition": concept.definition,
                    "properties": concept.properties,
                    "source_labels": concept.source_labels,
                })
        except Exception as exc:
            return map_exception(exc)
