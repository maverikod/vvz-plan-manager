"""Metadata for the graph_dependents command (C-009, C-024)."""
from __future__ import annotations

from plan_manager.commands.runtime_filtering import pagination_metadata_params


def get_graph_dependents_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Resolves the plan against the catalog, loads the dependency "
            "projection (C-009) for the plan once, locates the origin step "
            "identified by step_id, and computes the bounded transitive "
            "closure. The direction parameter selects whether to compute "
            "dependents (steps that depend on the target) or dependencies "
            "(steps on which the target depends). The depth_limit bounds the "
            "transitive closure depth; results are paginated via limit and "
            "offset parameters."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or uuid) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "step_id of the target step within the plan.",
                "type": "string",
                "required": True,
            },
            "direction": {
                "description": "Direction of dependency traversal. One of: dependents, dependencies.",
                "type": "string",
                "required": True,
                "enum": ["dependents", "dependencies"],
            },
            "depth_limit": {
                "description": "Maximum depth of transitive closure traversal (default 10).",
                "type": "integer",
                "required": False,
            },
            **pagination_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": "The bounded transitive closure of steps in the specified direction.",
                "data": {
                    "step": "Artifact path of the target step.",
                    "direction": "Direction of traversal: 'dependents' or 'dependencies'.",
                    "depth_limit": "Maximum depth limit applied to the closure computation.",
                    "steps": "Artifact paths of steps in the computed closure (paginated).",
                    "total": "Total count of steps in the full closure (before pagination).",
                    "limit": "Pagination limit applied to this result.",
                    "offset": "Pagination offset applied to this result.",
                },
                "example": {
                    "step": "G-001-domain-model/T-007-graph-commands/atomic_steps/A-001-graph-dependents.yaml",
                    "direction": "dependents",
                    "depth_limit": 10,
                    "steps": [
                        "G-001-domain-model/T-008-command-surface/atomic_steps/A-001-metadata.yaml"
                    ],
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": "Domain error returned when the plan, step, or pagination parameters cannot be resolved.",
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND | INVALID_PAGINATION",
                "message": "Human-readable message identifying the missing plan, step, or invalid pagination.",
                "details": "Details about the error condition.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the dependents of a step with default pagination.",
                "command": {"plan": "plan_manager", "step_id": "T-007", "direction": "dependents"},
                "explanation": "Returns artifact paths of every step that transitively depends on T-007, up to depth 10.",
            },
            {
                "description": "Get the dependencies of a step with depth and pagination bounds.",
                "command": {
                    "plan": "plan_manager",
                    "step_id": "T-007",
                    "direction": "dependencies",
                    "depth_limit": 5,
                    "limit": 20,
                    "offset": 0,
                },
                "explanation": "Returns up to 20 steps on which T-007 depends, traversing up to depth 5.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not match any plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "List plans through the catalog command and retry with a valid plan identifier.",
            },
            "STEP_NOT_FOUND": {
                "description": "No step with the given step_id exists in the resolved plan.",
                "message": "step not found: {step_id}",
                "solution": "Inspect the plan tree to find a valid step_id and retry.",
            },
            "INVALID_PAGINATION": {
                "description": "The pagination parameters (limit, offset) are invalid or out of range.",
                "message": "invalid pagination: limit and offset out of range",
                "solution": "Ensure limit is between 1 and 200, and offset is non-negative.",
            },
        },
        "best_practices": [
            "Use direction='dependents' to find downstream impacts of a change; direction='dependencies' to understand prerequisites.",
            "Start with a shallow depth_limit to explore the immediate closure, then increase if needed.",
            "Use pagination (limit/offset) to retrieve large closure sets incrementally and reduce memory overhead.",
            "This command never changes status; combine with the step status command to act on results.",
        ],
    }
