"""Extended metadata for the step_dependency_list command."""
from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_filtering import pagination_metadata_params


def get_step_dependency_list_metadata(cls) -> dict[str, Any]:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Read-only inspection of one step's dependency edges. Returns one "
            "page of the step's top-level depends_on list (the real graph "
            "column, never fields.depends_on) as canonical sibling paths, "
            "paginated with the uniform offset/limit convention (default "
            "limit 50, max 200), plus total/limit/offset for that page. "
            "Unless include_dependents is false, also returns the full list "
            "of sibling steps that declare a dependency on it (dependents is "
            "not paginated). Dependencies are sibling-scoped: same parent and "
            "level. No mutation and no new revision."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID).",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Canonical step path, bare step id if unambiguous, or step UUID.",
                "type": "string",
                "required": True,
            },
            "include_dependents": {
                "description": "Include the reverse dependency (dependents) list.",
                "type": "boolean",
                "required": False,
                "default": True,
            },
            **pagination_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": "The step's dependencies (one paginated page, plus total/limit/offset) and dependents at the current head revision.",
                "data": {
                    "step": "Canonical path of the inspected step.",
                    "depends_on": "Canonical paths of the requested page of sibling steps this step depends on.",
                    "total": "Count of the full depends_on set before pagination.",
                    "limit": "The limit actually applied to depends_on.",
                    "offset": "The offset actually applied to depends_on.",
                    "dependents": "Canonical paths of sibling steps that depend on this step (when include_dependents); not paginated.",
                    "revision_uuid": "Current head revision UUID string.",
                },
                "example": {
                    "step": "G-005/T-002/A-003",
                    "depends_on": ["G-005/T-002/A-001", "G-005/T-002/A-002"],
                    "total": 2,
                    "limit": 50,
                    "offset": 0,
                    "dependents": ["G-005/T-002/A-004"],
                    "revision_uuid": "bbc68757-563a-4646-b5ba-6f01c53c105e",
                },
            },
            "error": {
                "description": "A stable domain error when the plan or step does not resolve.",
                "code": "STEP_NOT_FOUND",
                "message": "step not found: G-999",
                "details": {},
            },
        },
        "usage_examples": [
            {
                "description": "List dependencies and dependents of an atomic step.",
                "command": {
                    "plan": "doc-store",
                    "step_id": "G-005/T-002/A-003",
                },
            },
            {
                "description": "List only the forward dependencies.",
                "command": {
                    "plan": "doc-store",
                    "step_id": "G-005/T-002/A-003",
                    "include_dependents": False,
                },
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve.",
                "message": "plan not found",
                "solution": "Pass a valid plan name or UUID (see plan_list).",
            },
            "STEP_NOT_FOUND": {
                "description": "The step reference does not resolve.",
                "message": "step not found: G-999",
                "solution": "Pass a canonical path, an unambiguous bare id, or a step UUID.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare step id matches more than one step.",
                "message": "step_id A-001 resolves to multiple steps",
                "solution": "Use the canonical path such as G-005/T-002/A-001.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Prefer canonical paths (G-005/T-002/A-003) over bare ids to avoid AMBIGUOUS_STEP_ID.",
            "Use this before editing dependencies to confirm the current graph neighborhood.",
            "Compare offset+limit against total to detect additional depends_on pages; dependents is always returned in full.",
        ],
    }
