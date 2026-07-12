"""Extended metadata for the step_dependency_preview command."""
from __future__ import annotations

from typing import Any


def get_step_dependency_preview_metadata(cls) -> dict[str, Any]:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Simulate a batch of dependency changes ({op, step_id, depends_on}) "
            "against the current graph and report the outcome without any "
            "mutation or new revision. The changes compose in order. The report "
            "states whether the result is valid, whether it would create a cycle, "
            "which steps would change, and the before/after topological execution "
            "order and parallel wave partition. References are validated the same "
            "way as the mutating commands, so an out-of-scope or unknown "
            "reference is reported as a domain error."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID).",
                "type": "string",
                "required": True,
            },
            "changes": {
                "description": "Ordered dependency changes to simulate; each is {op, step_id, depends_on?}.",
                "type": "array",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "Validity, cycle risk, changed steps, and before/after impact.",
                "data": {
                    "valid": "True when the simulated graph is acyclic.",
                    "would_create_cycle": "True when the changes would close a cycle.",
                    "changed_steps": "Canonical paths of steps whose depends_on would change.",
                    "impact": "execution_order_before/after and parallel_waves_before/after as canonical paths.",
                    "findings": "List of finding objects; a DEPENDENCY_CYCLE finding when a cycle is detected.",
                },
                "example": {
                    "valid": True,
                    "would_create_cycle": False,
                    "changed_steps": ["G-005/T-002/A-003"],
                    "impact": {
                        "execution_order_before": [],
                        "execution_order_after": [],
                        "parallel_waves_before": [],
                        "parallel_waves_after": [],
                    },
                    "findings": [],
                },
            },
            "error": {
                "description": "A stable domain error when a change references an invalid step or scope.",
                "code": "INVALID_DEPENDENCY_SCOPE",
                "message": "a dependency must reference a sibling step (same parent and level)",
                "details": {},
            },
        },
        "usage_examples": [
            {
                "description": "Preview making A-003 depend on A-001.",
                "command": {
                    "plan": "doc-store",
                    "changes": [
                        {"op": "add", "step_id": "G-005/T-002/A-003", "depends_on": ["G-005/T-002/A-001"]}
                    ],
                },
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve.",
                "message": "plan not found",
                "solution": "Pass a valid plan name or UUID.",
            },
            "STEP_NOT_FOUND": {
                "description": "A change references a step that does not resolve.",
                "message": "step not found: G-999",
                "solution": "Use canonical paths or unambiguous ids.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare id matches more than one step.",
                "message": "step_id A-001 resolves to multiple steps",
                "solution": "Use the canonical path such as G-005/T-002/A-001.",
            },
            "DEPENDENCY_STEP_NOT_FOUND": {
                "description": "A depends_on reference does not resolve.",
                "message": "step not found: A-099",
                "solution": "Reference existing sibling steps.",
            },
            "SELF_DEPENDENCY": {
                "description": "A change references the same step on both sides.",
                "message": "a step cannot depend on itself",
                "solution": "Remove the self-reference.",
            },
            "INVALID_DEPENDENCY_SCOPE": {
                "description": "A reference is not a sibling (different parent or level).",
                "message": "a dependency must reference a sibling step (same parent and level)",
                "solution": "Reference siblings only.",
            },
        },
        "best_practices": [
            "Preview large or cross-cutting dependency edits before applying them.",
            "Use the before/after impact to confirm the new execution order is what you intend.",
        ],
    }
