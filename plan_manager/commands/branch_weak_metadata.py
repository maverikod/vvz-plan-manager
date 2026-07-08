"""BranchWeakCommand: rank the plan's branches by ascending semantic index."""
from typing import Any, Dict


def get_branch_weak_metadata(cls: type) -> Dict[str, Any]:
    """Return extended AI/documentation metadata for BranchWeakCommand.

    :param cls: The command class requesting its metadata
        (BranchWeakCommand). The returned dict reads cls.name,
        cls.version, cls.descr, cls.category, cls.author, cls.email.
    :return: A dictionary with the required metadata fields: name,
        version, description, category, author, email,
        detailed_description, parameters, return_value, usage_examples,
        error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the plan's branches ranked by ascending semantic "
            "index: the published output discipline of one number and "
            "a color, with the few weakest branches ranked, up to 3 "
            "branches listed in ascending index order. The command "
            "refuses with the GATE_RED code when the plan has not "
            "passed the mechanical gate at the current tree revision, "
            "because semantic scoring only ever runs on scopes that "
            "already passed the mechanical gate. When the embedding "
            "service is unreachable, scoring degrades explicitly and "
            "the command returns the EMBEDDINGS_UNAVAILABLE code "
            "instead of a misleadingly confident index. This command "
            "is read-only: it never modifies the plan."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the plan catalog.",
                "type": "string",
                "required": True,
            },
            "verbose": {
                "description": "When true, include per-estimator internals in each weakest-branch summary.",
                "type": "boolean",
                "required": False,
                "default": False,
            },
            "require_embeddings": {
                "description": "When true, refuse with EMBEDDINGS_UNAVAILABLE if the embedding model is not ready instead of returning a degraded ranking; when false (default), a not-ready model degrades to the deterministic estimators and is reported under the 'embedding' result block.",
                "type": "boolean",
                "required": False,
                "default": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The plan's semantic index, color verdict, and up to 3 weakest branches ascending.",
                "data": {
                    "plan_index": "The plan's aggregated semantic index, 0..100.",
                    "color": "The color verdict derived from the index and trust.",
                    "aggregation": "The aggregation method used across branches (e.g. minimum).",
                    "weakest": "List of up to 3 branch summaries ascending by semantic index.",
                    "embedding": "Embedding readiness block: {available: bool, state: one of 'ready'|'unconfigured'|'not_ready'|'unreachable', detail: precise reason the embedding estimator did not contribute, present only when state is not 'ready'}. When health reports the model ready but the scoring batch vectorization fails, state is 'unreachable' and detail carries the real failure reason.",
                    "revision_uuid": "The plan revision the score was computed for.",
                },
                "example": {
                    "plan_index": 62.5,
                    "color": "yellow",
                    "aggregation": "minimum",
                    "weakest": [{"branch": "G-005/T-008/A-001", "index": 48.0}],
                    "revision_uuid": "00000000-0000-0000-0000-000000000000",
                },
            },
            "error": {
                "description": "The plan could not be resolved, the gate has not passed, or embeddings are unavailable.",
                "code": "PLAN_NOT_FOUND | GATE_RED | EMBEDDINGS_UNAVAILABLE",
                "message": "Human-readable description of the refusal or failure.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Rank the weakest branches of a plan.",
                "command": {"plan": "plan_manager", "verbose": False},
                "explanation": "Returns the plan index, color, and up to 3 weakest branches ascending.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "Plan not found: {plan}",
                "solution": "Call the plan catalog command and retry with a valid plan identifier.",
            },
            "GATE_RED": {
                "description": "The plan has not passed the mechanical gate at the current tree revision.",
                "message": "Scoring refused: mechanical gate is red.",
                "solution": "Run the mechanical gate command, resolve every finding, and retry.",
            },
            "EMBEDDINGS_UNAVAILABLE": {
                "description": "The configured embedding service is unreachable, degrading semantic scoring.",
                "message": "Embedding service unavailable.",
                "solution": "Restore connectivity to the configured embedding_url and retry.",
            },
        },
        "best_practices": [
            "Call this command after a green mechanical gate; a GATE_RED response means the mechanical layer must be fixed first.",
            "Use verbose=True only when investigating a specific weak branch; the default terse output is the published one number and a color discipline.",
        ],
    }
