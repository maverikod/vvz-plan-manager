"""Extended metadata for the step_dependency_set command."""
from __future__ import annotations

from typing import Any


def get_step_dependency_set_metadata(cls) -> dict[str, Any]:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Replace the step's entire top-level depends_on list with the given "
            "sibling references. Every reference is validated (must be a sibling, "
            "not the step itself), the list is deduplicated preserving order, and "
            "the resulting graph is refused with DEPENDENCY_CYCLE if it would "
            "contain a cycle. Returns both the old and new lists. Mutation is "
            "admitted under the same regime as step_update. Same-file "
            "writer-order ambiguity is admitted monotonically (bug 64107707): a "
            "pre-existing ambiguity elsewhere in the graph never refuses this "
            "set; only a NEW ambiguous pair the replacement would introduce "
            "does, as AS_SAME_FILE_ORDER_AMBIGUOUS."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID).",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Step whose dependency list is replaced (canonical path, bare id, or UUID).",
                "type": "string",
                "required": True,
            },
            "depends_on": {
                "description": "Complete replacement list of sibling dependency references.",
                "type": "array",
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
                "description": "The old and new dependency lists and the recorded revision.",
                "data": {
                    "step": "Canonical path of the edited step.",
                    "old_depends_on": "Canonical paths of the dependencies before the replacement.",
                    "depends_on": "Canonical paths of the dependencies after the replacement.",
                    "revision_uuid": "Revision UUID produced by the set, or the head revision on a no-op.",
                },
                "example": {
                    "step": "G-005/T-002/A-003",
                    "old_depends_on": ["G-005/T-002/A-001"],
                    "depends_on": ["G-005/T-002/A-001", "G-005/T-002/A-002"],
                    "revision_uuid": "bbc68757-563a-4646-b5ba-6f01c53c105e",
                },
            },
            "error": {
                "description": "A stable domain error on invalid reference, scope, cycle, or admission.",
                "code": "DEPENDENCY_CYCLE",
                "message": "Dependency change would create a cycle.",
                "details": {"path": "G-005/T-002/A-003", "cycle": ["G-005/T-002/A-001", "G-005/T-002/A-003"]},
            },
        },
        "usage_examples": [
            {
                "description": "Set A-003 to depend on A-001 and A-002.",
                "command": {
                    "plan": "doc-store",
                    "step_id": "G-005/T-002/A-003",
                    "depends_on": ["G-005/T-002/A-001", "G-005/T-002/A-002"],
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
            "DEPENDENCY_STEP_NOT_FOUND": {
                "description": "A depends_on entry does not resolve.",
                "message": "step not found: A-099",
                "solution": "Reference existing sibling steps only.",
            },
            "SELF_DEPENDENCY": {
                "description": "The list references the step itself.",
                "message": "a step cannot depend on itself: G-005/T-002/A-003",
                "solution": "Remove the self-reference.",
            },
            "INVALID_DEPENDENCY_SCOPE": {
                "description": "A reference is not a sibling (different parent or level).",
                "message": "a dependency must reference a sibling step (same parent and level)",
                "solution": "Reference siblings only.",
            },
            "DEPENDENCY_CYCLE": {
                "description": "The new list would create a cycle.",
                "message": "Dependency change would create a cycle.",
                "solution": "Break the opposing edges before setting this list.",
            },
            "AS_SAME_FILE_ORDER_AMBIGUOUS": {
                "description": (
                    "The replacement list would introduce a NEW same-file writer "
                    "ambiguity absent from the before-state (bug 64107707). A "
                    "pre-existing ambiguity elsewhere in the graph never refuses this."
                ),
                "message": "Dependency change would introduce a new same-file writer ambiguity.",
                "solution": (
                    "Add an explicit dependency between the branches of the newly "
                    "conflicting pair(s) named in introduced_pairs, or preview first "
                    "with step_dependency_preview."
                ),
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
            "Use set for a full rewrite; use add/remove for incremental single-edge edits.",
            "Preview large rewrites with step_dependency_preview first.",
        ],
    }
