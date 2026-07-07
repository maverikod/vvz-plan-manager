"""Extended metadata for the step_dependency_clear command."""
from __future__ import annotations

from typing import Any


def get_step_dependency_clear_metadata(cls) -> dict[str, Any]:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Remove every dependency edge from the step's top-level depends_on "
            "column, leaving an empty list. Returns the old list for auditing. "
            "Clearing an already-empty list is a no-op with no new revision. "
            "Mutation is admitted under the same regime as step_update."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID).",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Step whose dependencies are cleared (canonical path, bare id, or UUID).",
                "type": "string",
                "required": True,
            },
            "cascade_uuid": {
                "description": "Open cascade to admit the mutation under; omit for direct-mode on a non-frozen step.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "The cleared dependency list and the recorded revision.",
                "data": {
                    "step": "Canonical path of the edited step.",
                    "old_depends_on": "Canonical paths of the dependencies before clearing.",
                    "depends_on": "Always the empty list.",
                    "revision_uuid": "Revision UUID produced by the clear, or the head revision on a no-op.",
                },
                "example": {
                    "step": "G-005/T-002/A-003",
                    "old_depends_on": ["G-005/T-002/A-001", "G-005/T-002/A-002"],
                    "depends_on": [],
                    "revision_uuid": "bbc68757-563a-4646-b5ba-6f01c53c105e",
                },
            },
            "error": {
                "description": "A stable domain error on invalid reference or admission.",
                "code": "STEP_NOT_FOUND",
                "message": "step not found: G-999",
                "details": {},
            },
        },
        "usage_examples": [
            {
                "description": "Clear all dependencies of A-003.",
                "command": {
                    "plan": "doc-store",
                    "step_id": "G-005/T-002/A-003",
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
                "description": "step_id does not resolve.",
                "message": "step not found: G-999",
                "solution": "Pass a canonical path, unambiguous bare id, or UUID.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare id matches more than one step.",
                "message": "step_id A-001 resolves to multiple steps",
                "solution": "Use the canonical path such as G-005/T-002/A-001.",
            },
            "CASCADE_REQUIRED": {
                "description": "The step is frozen at or below and no cascade was supplied.",
                "message": "step is not directly mutable",
                "solution": "Open a cascade and pass cascade_uuid.",
            },
            "FROZEN_ARTIFACT": {
                "description": "The target step or a descendant is frozen.",
                "message": "step is not directly mutable",
                "solution": "Edit dependencies inside a cascade.",
            },
            "CASCADE_CONFLICT": {
                "description": "cascade_uuid does not match the plan's open cascade.",
                "message": "cascade id does not match the open cascade",
                "solution": "Pass the current open cascade's UUID.",
            },
        },
        "best_practices": [
            "Use clear to reset a step before re-declaring dependencies with set.",
            "Clearing is idempotent; an empty list produces no new revision.",
        ],
    }
