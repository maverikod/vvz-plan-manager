"""Command: reverse coverage query for one concept (concept_coverage)."""

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.concept_coverage_metadata import get_concept_coverage_metadata
from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import db_connection
from plan_manager.scoring.estimators import load_concept_rows
from plan_manager.views.dependency_graph import load_steps
from plan_manager.verify.gate_data import artifact_path_of


class ConceptCoverageCommand(Command):
    """Return the reverse coverage (C-010) of one concept (C-003) in a resolved plan.

    Read-only command: never mutates plan state. For one concept_id, returns
    the steps that reference it and the HRS paragraph labels that justify it.
    """

    name = "concept_coverage"
    version = "1.0.0"
    descr = "Return the steps and HRS paragraphs that justify one concept."
    category = "mrs"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = False

    @classmethod
    def get_schema(cls) -> dict:
        """Return the strict input schema for concept_coverage."""
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or unique plan name) to resolve.",
                },
                "concept_id": {
                    "type": "string",
                    "description": "Concept identifier to compute reverse coverage for.",
                },
            },
            "required": ["plan", "concept_id"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> dict:
        return get_concept_coverage_metadata(cls)

    def validate_params(self, params: dict) -> dict:
        """Validate params: shallow schema checks only; no further semantics needed."""
        params = super().validate_params(params)
        return params

    async def execute(self, plan: str, concept_id: str) -> SuccessResult | ErrorResult:
        """Return the referencing steps and justifying paragraphs of concept_id.

        Args:
            plan: Plan identifier (UUID or unique plan name) to resolve.
            concept_id: Concept identifier to compute reverse coverage for.

        Returns:
            SuccessResult with data {"concept_id", "steps", "paragraphs"}, or
            ErrorResult with code PLAN_NOT_FOUND or CONCEPT_NOT_FOUND.
        """
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                rows = load_concept_rows(conn, p.uuid)
                match = next((r for r in rows if r[0] == concept_id), None)
                if match is None:
                    return domain_error(
                        "CONCEPT_NOT_FOUND",
                        f"concept not found: {concept_id}",
                    )
                _, _, source_labels = match
                nodes = load_steps(conn, p.uuid)
                referencing = sorted(
                    artifact_path_of(nodes, s)
                    for s in nodes.values()
                    if concept_id in s.concepts
                )
                return SuccessResult(data={
                    "concept_id": concept_id,
                    "steps": referencing,
                    "paragraphs": source_labels,
                })
        except Exception as exc:
            return map_exception(exc)
