"""Command PlanScoreCommand: run the semantic scoring layer (C-013) over a plan or branch."""
from __future__ import annotations

import uuid
from typing import Any, Dict

from mcp_proxy_adapter.commands.base import Command
from mcp_proxy_adapter.commands.result import SuccessResult, ErrorResult

from plan_manager.commands.errors import domain_error, map_exception
from plan_manager.commands.plan_score_metadata import get_plan_score_metadata
from plan_manager.commands.progress import progress_from_context
from plan_manager.commands.resolve import resolve_plan
from plan_manager.runtime.context import app_config, db_connection
from plan_manager.scoring.index import ScoringConfig, branch_summary, score_branch, score_plan
from plan_manager.verify.verdict import current_head_revision


class PlanScoreCommand(Command):
    """Run the semantic completeness index (C-013) over a plan or one branch."""

    name = "plan_score"
    version = "1.0.0"
    descr = "Run the semantic scoring layer over a plan or one branch and return index, trust, and color."
    category = "verification"
    author = "Vasiliy Zdanovskiy"
    email = "vasilyvz@gmail.com"
    result_class = SuccessResult
    use_queue = True

    @classmethod
    def get_schema(cls) -> Dict[str, Any]:
        """Return the machine-readable input schema for this command.

        :returns: A JSON-schema-shaped dict with keys type, properties,
            required, additionalProperties.
        :rtype: Dict[str, Any]
        """
        return {
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "Plan identifier (UUID or unique plan name) to score.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["plan", "branch"],
                    "default": "plan",
                    "description": "Scoring scope: the whole plan or one branch named by its three step ids.",
                },
                "gs_step_id": {
                    "type": "string",
                    "description": "Global step id (e.g. G-005) of the branch. Required when scope is 'branch'.",
                },
                "ts_step_id": {
                    "type": "string",
                    "description": "Tactical step id (e.g. T-009) of the branch. Required when scope is 'branch'.",
                },
                "as_step_id": {
                    "type": "string",
                    "description": "Atomic step id (e.g. A-101) of the branch. Required when scope is 'branch'.",
                },
                "verbose": {
                    "type": "boolean",
                    "default": False,
                    "description": "Force per-estimator internals into the result even when the score is above threshold.",
                },
                "require_embeddings": {
                    "type": "boolean",
                    "default": False,
                    "description": "When true, fail fast with EMBEDDINGS_UNAVAILABLE if the embedding model is not ready instead of returning a degraded score; when false (default), a not-ready embedding model degrades the score to the deterministic estimators and is reported under 'embedding'.",
                },
                "expected_revision": {
                    "type": "string",
                    "description": "The caller's view of the plan head revision (UUID string). When it does not match the current head revision, the command refuses with VERDICT_STALE.",
                },
            },
            "required": ["plan"],
            "additionalProperties": False,
        }

    @classmethod
    def metadata(cls) -> Dict[str, Any]:
        """Return the extended documentation metadata for this command.

        :returns: The dict produced by get_plan_score_metadata(cls).
        :rtype: Dict[str, Any]
        """
        return get_plan_score_metadata(cls)

    def validate_params(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize the parameters for this command.

        Calls the platform validator first, then enforces the scope
        selector semantics that the JSON schema cannot express (when
        scope is 'branch', gs_step_id, ts_step_id, and as_step_id must
        all be present and non-empty; when scope is 'plan', all three
        must be absent), and parses expected_revision as a UUID when it
        is supplied.

        :param params: Raw parameter dict as received from the platform.
        :type params: Dict[str, Any]
        :returns: The validated (and platform-normalized) parameter dict.
        :rtype: Dict[str, Any]
        :raises ValueError: When the scope selector semantics above are
            violated, or when expected_revision is supplied but is not a
            valid UUID string. This is a platform invalid-params failure,
            not a domain error code.
        """
        params = super().validate_params(params)
        scope = params.get("scope", "plan")
        gs_step_id = params.get("gs_step_id")
        ts_step_id = params.get("ts_step_id")
        as_step_id = params.get("as_step_id")
        if scope == "branch":
            if not gs_step_id or not ts_step_id or not as_step_id:
                raise ValueError(
                    "gs_step_id, ts_step_id, and as_step_id are all required "
                    "and must be non-empty when scope is 'branch'"
                )
        elif scope == "plan":
            if gs_step_id or ts_step_id or as_step_id:
                raise ValueError(
                    "gs_step_id, ts_step_id, and as_step_id must be absent "
                    "when scope is 'plan'"
                )
        expected_revision = params.get("expected_revision")
        if expected_revision is not None:
            try:
                uuid.UUID(expected_revision)
            except ValueError as exc:
                raise ValueError(
                    f"expected_revision is not a valid UUID: {expected_revision}"
                ) from exc
        return params

    async def execute(self, **kwargs: Any):
        """Run the semantic scoring layer over the requested scope.

        Applies the revision freshness guard first (C-020: a verdict is
        fresh iff its recorded revision equals the current revision,
        compared by identifier, never by timestamp), then scores the
        plan or the named branch.

        :param kwargs: Validated parameters: plan (str, plan identifier),
            scope (str, 'plan' or 'branch', default 'plan'), gs_step_id
            (str | None), ts_step_id (str | None), as_step_id
            (str | None), verbose (bool, default False),
            expected_revision (str | None, UUID string).
        :type kwargs: Any
        :returns: A SuccessResult with the score data on success; an
            ErrorResult with code VERDICT_STALE when expected_revision
            was supplied and does not match the current head revision; an
            ErrorResult with code STEP_NOT_FOUND when scope is 'branch'
            and the branch cannot be resolved; otherwise an ErrorResult
            produced by map_exception for any exception raised while
            resolving the plan or scoring (in particular PLAN_NOT_FOUND
            when the plan does not resolve, GATE_RED when the scope has
            not passed the mechanical gate, and EMBEDDINGS_UNAVAILABLE
            when the embedding service cannot be reached).
        :rtype: SuccessResult | ErrorResult
        """
        plan = kwargs["plan"]
        scope = kwargs.get("scope", "plan")
        gs_step_id = kwargs.get("gs_step_id")
        ts_step_id = kwargs.get("ts_step_id")
        as_step_id = kwargs.get("as_step_id")
        verbose = kwargs.get("verbose", False)
        require_embeddings = kwargs.get("require_embeddings", False)
        expected_revision = kwargs.get("expected_revision")
        progress = progress_from_context(kwargs.get("context"))
        try:
            with db_connection() as conn:
                p = resolve_plan(conn, plan)
                if expected_revision is not None:
                    current = current_head_revision(conn, p.uuid)
                    if expected_revision != (str(current) if current else None):
                        return domain_error(
                            "VERDICT_STALE",
                            "caller's revision is not the current head",
                            {
                                "expected": expected_revision,
                                "current": str(current) if current else None,
                            },
                        )
                cfg = app_config()
                config = ScoringConfig(
                    threshold=cfg.scoring_threshold,
                    aggregation=cfg.scoring_aggregation,
                    concept_weight=cfg.concept_weight,
                    trust_floor=cfg.trust_floor,
                    embedding_url=cfg.embedding_url,
                    embedding_timeout=cfg.embedding_timeout,
                )
                if scope == "plan":
                    score = score_plan(
                        conn,
                        p.uuid,
                        config,
                        progress=progress,
                        require_embeddings=require_embeddings,
                    )
                    data = {
                        "scope": "plan",
                        "index": score.index,
                        "color": score.color,
                        "aggregation": score.aggregation,
                        "weakest": [
                            branch_summary(b, verbose) for b in score.weakest
                        ],
                        "embedding": {
                            "available": score.embedding_state == "ready",
                            "state": score.embedding_state,
                        },
                        "revision_uuid": str(score.revision_uuid),
                    }
                    return SuccessResult(data=data)
                try:
                    bs = score_branch(
                        conn,
                        p.uuid,
                        gs_step_id,
                        ts_step_id,
                        as_step_id,
                        config,
                        progress=progress,
                        require_embeddings=require_embeddings,
                    )
                except ValueError as exc:
                    return domain_error("STEP_NOT_FOUND", str(exc))
                data = {
                    "scope": "branch",
                    **branch_summary(bs, verbose),
                    "embedding": {
                        "available": bs.embedding_state == "ready",
                        "state": bs.embedding_state,
                    },
                    "revision_uuid": str(bs.revision_uuid),
                }
                return SuccessResult(data=data)
        except Exception as exc:
            return map_exception(exc)
