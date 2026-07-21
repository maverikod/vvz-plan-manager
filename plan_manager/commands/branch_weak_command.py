"""BranchWeakCommand: rank the plan's branches by ascending semantic index."""
from typing import Any, ClassVar, Dict

from plan_manager.commands.base_command import Command
from mcp_proxy_adapter.commands.result import ErrorResult, SuccessResult

from plan_manager.commands.branch_weak_metadata import get_branch_weak_metadata
from plan_manager.commands.errors import map_exception
from plan_manager.commands.progress import progress_from_context
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.scoring.index import (
    ScoringConfig,
    branch_summary,
    embedding_block,
    score_plan,
)


class BranchWeakCommand(Command):
    """Rank the plan's branches by ascending semantic index, read-only."""

    name: ClassVar[str] = "branch_weak"
    version: ClassVar[str] = "1.0.0"
    descr: ClassVar[str] = (
        "Rank the plan's branches by ascending semantic index, "
        "refusing when the plan has not passed the mechanical gate."
    )
    category: ClassVar[str] = "branch"
    author: ClassVar[str] = "Vasiliy Zdanovskiy"
    email: ClassVar[str] = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue: ClassVar[bool] = True

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for this command.

        :return: A dict with object type, properties for plan (type
            string) and verbose (type boolean, default False), a
            required list naming only plan, and additionalProperties
            False.
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (name or UUID).",
                },
                "verbose": {
                    "type": "boolean",
                    "description": (
                        "When true, include per-estimator internals "
                        "in each weakest-branch summary."
                    ),
                    "default": False,
                },
                "require_embeddings": {
                    "type": "boolean",
                    "description": (
                        "When true, fail fast with EMBEDDINGS_UNAVAILABLE if the "
                        "embedding model is not ready instead of returning a "
                        "degraded ranking; when false (default), a not-ready model "
                        "degrades to the deterministic estimators and is reported "
                        "under 'embedding'."
                    ),
                    "default": False,
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return extended AI/documentation metadata for this command.

        :return: The dictionary produced by get_branch_weak_metadata(cls).
        """
        return get_branch_weak_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize the raw parameters for this command.

        :param params: Raw parameter dict as received from the
            adapter, already checked against get_schema(): object
            type, plan required and of type string, verbose optional
            and of type boolean when present, no additional
            properties.
        :return: The params dict, unchanged beyond the base validation
            already performed by the superclass. No further semantic
            validation applies to this command: plan existence and
            gate state are resolved and reported as domain errors
            during execute(), not during schema validation.
        """
        params = super().validate_params(params)
        return params

    async def execute(
        self,
        plan: str,
        verbose: bool = False,
        require_embeddings: bool = False,
        context: object | None = None,
    ) -> SuccessResult | ErrorResult:
        """Rank the plan's branches by ascending semantic index.

        :param plan: Plan identifier (name or UUID) resolved via
            resolve_plan(conn, plan) -> Plan (fields uuid, name,
            status, context_budget, head_revision_uuid).
        :param verbose: When True, include per-estimator internals in
            each weakest-branch summary via
            branch_summary(branch, verbose=True). Defaults to False.
        :return: SuccessResult(data={"plan_index": float, "color": str,
            "aggregation": str, "weakest": list[dict],
            "revision_uuid": str}) on success; ErrorResult from
            map_exception(exc) for any exception, including a
            DomainCommandError with code PLAN_NOT_FOUND raised by
            resolve_plan when the plan does not resolve, a
            ScoreRefusedError mapped to code GATE_RED when the plan
            has not passed the mechanical gate at the current
            revision, and an EmbeddingUnavailable exception mapped to
            code EMBEDDINGS_UNAVAILABLE when the embedding service is
            unreachable.
        """
        progress = progress_from_context(context)
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                cfg = app_config()
                score = score_plan(
                    conn,
                    p.uuid,
                    ScoringConfig(
                        threshold=cfg.scoring_threshold,
                        aggregation=cfg.scoring_aggregation,
                        concept_weight=cfg.concept_weight,
                        trust_floor=cfg.trust_floor,
                        embedding_url=cfg.embedding_url,
                        embedding_timeout=cfg.embedding_timeout,
                    ),
                    progress=progress,
                    require_embeddings=require_embeddings,
                )
                return SuccessResult(
                    data={
                        "plan_index": score.index,
                        "color": score.color,
                        "aggregation": score.aggregation,
                        "weakest": [
                            branch_summary(b, verbose) for b in score.weakest
                        ],
                        "embedding": embedding_block(
                            score.embedding_state, score.embedding_detail
                        ),
                        "revision_uuid": str(score.revision_uuid),
                    }
                )
        except Exception as exc:
            return map_exception(exc)
