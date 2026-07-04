"""Metadata for the plan_status command."""

from typing import Any


def get_plan_status_metadata(cls: Any) -> dict:
    """Return the full metadata dictionary for PlanStatusCommand.

    Args:
        cls: The PlanStatusCommand class, providing name, version, descr,
            category, author, email class attributes.

    Returns:
        dict: Metadata dictionary conforming to metadatastd.yaml
            required_fields: name, version, description, category,
            author, email, detailed_description, parameters,
            return_value, usage_examples, error_cases, best_practices.
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Returns the read-only dashboard for one resolved plan "
            "(C-001): artifact counts per level (3, 4, 5), the status "
            "distribution across all steps, the mechanical gate "
            "verdict for the current tree, and — only when the gate is "
            "green — the plan semantic index, its color, and the "
            "ranked weakest branches. When the gate is not green, the "
            "scoring section is refused and carries the GATE_RED "
            "marker instead of a score, because the plan index is "
            "only published for a gate-green plan. If the embedding "
            "integration is unreachable while scoring a gate-green "
            "plan, the command fails with the EMBEDDINGS_UNAVAILABLE "
            "domain code."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier: either the plan UUID or its unique name.",
                "type": "string",
                "required": True,
                "examples": ["my-plan", "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e"],
            },
        },
        "return_value": {
            "success": {
                "description": (
                    "The plan dashboard: identity, counts, status "
                    "distribution, gate verdict, and scoring section."
                ),
                "data": {
                    "plan": "Resolved plan identity: uuid, name, status.",
                    "counts_by_level": "Artifact counts keyed by level 3, 4, 5.",
                    "status_distribution": "Count of steps per status value across all levels.",
                    "gate": "Gate verdict: green (bool), scope, revision_uuid.",
                    "scoring": (
                        "When gate is green: index, color, weakest "
                        "(list of branch summaries). When gate is not "
                        "green: {'refused': 'GATE_RED'}."
                    ),
                },
                "example": {
                    "plan": {
                        "uuid": "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e",
                        "name": "my-plan",
                        "status": "draft",
                    },
                    "counts_by_level": {"3": 2, "4": 8, "5": 40},
                    "status_distribution": {"draft": 10, "frozen": 40},
                    "gate": {
                        "green": True,
                        "scope": "plan",
                        "revision_uuid": "9a1e3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e",
                    },
                    "scoring": {
                        "index": 92.5,
                        "color": "green",
                        "weakest": [],
                    },
                },
            },
            "error": {
                "description": "A domain error result carrying a stable string code.",
                "code": "PLAN_NOT_FOUND",
                "message": "Plan not found: my-plan",
            },
        },
        "usage_examples": [
            {
                "description": "Get the dashboard for a plan by name.",
                "command": {"plan": "my-plan"},
                "explanation": "Resolves 'my-plan' and returns its dashboard.",
            },
            {
                "description": "Get the dashboard for a plan by UUID.",
                "command": {"plan": "3fae3c1e-2b0e-4a1a-9e2a-6f6b1a2c3d4e"},
                "explanation": "Resolves the plan by UUID and returns its dashboard.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not match any uuid or name in the catalog.",
                "message": "Plan not found: {plan}",
                "solution": "Call plan_list to discover valid plan identifiers and retry.",
            },
            "GATE_RED": {
                "description": (
                    "Not a command-level error: when the mechanical "
                    "gate is not green, the command still returns "
                    "SuccessResult, but the 'scoring' section of the "
                    "data is the refusal marker "
                    "{'refused': 'GATE_RED'} instead of an index, "
                    "because the plan index is only published for a "
                    "gate-green plan."
                ),
                "message": "Scoring refused: plan gate is not green.",
                "solution": "Resolve the mechanical gate findings for the plan, then call plan_status again.",
            },
            "EMBEDDINGS_UNAVAILABLE": {
                "description": "The plan gate is green but the embedding service is unreachable while scoring.",
                "message": "Embedding service is unavailable.",
                "solution": "Restore embedding service connectivity, or retry once it is reachable again.",
            },
        },
        "best_practices": [
            "Call plan_status after a cascade commit to confirm the gate is still green before relying on the scoring section.",
            "Treat a 'scoring': {'refused': 'GATE_RED'} response as informational, not as a failed call.",
            "Use plan_list to resolve a valid plan identifier before calling plan_status.",
        ],
    }
