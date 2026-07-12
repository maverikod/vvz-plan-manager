"""Extended AI/documentation metadata for PlanScoreCommand."""
from __future__ import annotations

from typing import Any, Dict, Type


def get_plan_score_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Return the extended documentation metadata for PlanScoreCommand.

    :param cls: The command class object (PlanScoreCommand), used to
        source the identity fields name, version, descr, category, author,
        and email from the class attributes so this dictionary never
        contradicts the class or its get_schema().
    :type cls: Type[Any]
    :returns: A metadata dictionary with the required keys name, version,
        description, category, author, email, detailed_description,
        parameters, return_value, usage_examples, error_cases, and
        best_practices.
    :rtype: Dict[str, Any]
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Runs the semantic completeness layer over one plan or one "
            "branch of that plan, expressed as a normalized 0..100 index "
            "with a color verdict and a trust value. Scoring refuses any "
            "scope that has not passed the mechanical gate in the same "
            "tree state (GATE_RED) and refuses to run against a stale "
            "caller view of the plan head revision when expected_revision "
            "is supplied and does not match the current head "
            "(VERDICT_STALE); freshness is always decided by comparing "
            "revision identifiers, never by comparing timestamps. "
            "Per-estimator internals are included in the result only for "
            "scopes below the configured threshold or when verbose is "
            "explicitly set. When the embedding service is unavailable the "
            "command degrades explicitly with the EMBEDDINGS_UNAVAILABLE "
            "code instead of failing silently or lying about the index. "
            "The command mutates nothing and stores nothing."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique plan name) to score.",
                "type": "string",
                "required": True,
            },
            "scope": {
                "description": "Scoring scope: the whole plan or one branch named by its three step ids.",
                "type": "string",
                "required": False,
                "default": "plan",
                "enum": ["plan", "branch"],
            },
            "gs_step_id": {
                "description": "Global step id (e.g. G-005) of the branch. Required and non-empty when scope is 'branch'; must be absent when scope is 'plan'.",
                "type": "string",
                "required": False,
            },
            "ts_step_id": {
                "description": "Tactical step id (e.g. T-009) of the branch. Required and non-empty when scope is 'branch'; must be absent when scope is 'plan'.",
                "type": "string",
                "required": False,
            },
            "as_step_id": {
                "description": "Atomic step id (e.g. A-101) of the branch. Required and non-empty when scope is 'branch'; must be absent when scope is 'plan'.",
                "type": "string",
                "required": False,
            },
            "verbose": {
                "description": "Force per-estimator internals into the result even when the score is above threshold.",
                "type": "boolean",
                "required": False,
                "default": False,
            },
            "require_embeddings": {
                "description": "When true, refuse with EMBEDDINGS_UNAVAILABLE if the embedding model is not ready instead of returning a degraded score; when false (default), a not-ready embedding model degrades the score to the deterministic estimators and is reported under the 'embedding' result block.",
                "type": "boolean",
                "required": False,
                "default": False,
            },
            "expected_revision": {
                "description": "The caller's view of the plan head revision, as a UUID string. When supplied and it does not equal the current head revision, the command refuses with VERDICT_STALE instead of scoring against a moving target.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The score result bound to the measured revision, for plan scope or branch scope.",
                "data": {
                    "scope": "'plan' or 'branch': the scope that was scored.",
                    "index": "Float 0..100 semantic completeness index (plan scope: the plan aggregation of branch indexes; branch scope: the branch index).",
                    "color": "Color verdict string derived from the index and threshold.",
                    "trust": "Trust value for the measurement (branch scope; and inside each entry of weakest for plan scope).",
                    "aggregation": "The aggregation strategy used to combine branch indexes into the plan index (plan scope only).",
                    "weakest": "List of branch summaries ranked by ascending index (plan scope only).",
                    "embedding": "Embedding readiness block: {available: bool, state: one of 'ready'|'unconfigured'|'not_ready'|'unreachable', detail: precise reason the embedding estimator did not contribute, present only when state is not 'ready'}. When health reports the model ready but the scoring batch vectorization fails, state is 'unreachable' and detail carries the real failure reason.",
                    "revision_uuid": "String UUID of the exact revision the score was computed for.",
                },
                "example": {
                    "scope": "plan",
                    "index": 91.5,
                    "color": "green",
                    "aggregation": "minimum",
                    "weakest": [],
                    "revision_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                },
            },
            "error": {
                "description": "A domain error result.",
                "code": "Stable domain error code string.",
                "message": "Human-readable error message.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Score an entire plan.",
                "command": {"plan": "plan_manager", "scope": "plan"},
                "explanation": "Returns the plan-level index, color, aggregation, and the ranked weakest branches, bound to the current head revision.",
            },
            {
                "description": "Score one branch with a freshness guard and verbose internals.",
                "command": {
                    "plan": "plan_manager",
                    "scope": "branch",
                    "gs_step_id": "G-005",
                    "ts_step_id": "T-009",
                    "as_step_id": "A-101",
                    "verbose": True,
                    "expected_revision": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                },
                "explanation": "Scores one branch, refusing with VERDICT_STALE if the plan head revision has advanced past expected_revision, and always includes per-estimator internals because verbose is set.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to any plan in the database.",
                "message": "Plan not found: {plan}",
                "solution": "Verify the plan identifier against the plan catalog and retry.",
            },
            "STEP_NOT_FOUND": {
                "description": "scope is 'branch' but one of gs_step_id, ts_step_id, as_step_id does not resolve within the plan.",
                "message": "Step not found: {step_id}",
                "solution": "Verify the three branch step ids against the plan tree and retry.",
            },
            "GATE_RED": {
                "description": "The scope has not passed the mechanical gate at the current tree state, so scoring is refused.",
                "message": "Scoring refused: the mechanical gate is not green for this scope.",
                "solution": "Run plan_validate over the same scope, resolve every finding, and retry plan_score.",
            },
            "VERDICT_STALE": {
                "description": "expected_revision was supplied and does not equal the current head revision.",
                "message": "caller's revision is not the current head",
                "solution": "Re-read the plan's current head revision and retry with an up-to-date expected_revision, or omit expected_revision to skip the freshness guard.",
            },
            "EMBEDDINGS_UNAVAILABLE": {
                "description": "The configured embedding service could not be reached while computing the semantic index.",
                "message": "Embedding service unavailable.",
                "solution": "Check the embedding service configuration and connectivity, then retry. Trust for any completed measurement drops to the configured floor.",
            },
        },
        "best_practices": [
            "Always run plan_validate first: plan_score refuses any scope that has not passed the gate in the same tree state.",
            "Pass expected_revision when the caller already holds a revision from a prior read, to avoid scoring against a tree state that has since moved on.",
            "Use verbose=True only when investigating a low score; otherwise leave estimator internals out of the result.",
            "This command is read-only: it never mutates or stores anything, so it is always safe to call.",
            "Treat EMBEDDINGS_UNAVAILABLE as a degraded-trust signal, not a hard failure: retry once the embedding service is reachable.",
            "This command runs on the queue: the plan_score call returns an enqueue acknowledgement with job_id, store='queuemgr', and poll_with='queue_get_job_status'. Poll completion with queue_get_job_status (which reports status plus created_at/started_at/completed_at); do NOT poll with the builtin job_status, which reads a separate in-memory JobManager store and will report the job as not found (returning its own poll_with='queue_get_job_status' hint).",
        ],
    }
