"""Extended metadata for the step_dependency_add command."""
from __future__ import annotations

from typing import Any


def get_step_dependency_add_metadata(cls) -> dict[str, Any]:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Add exactly one dependency edge (step_id depends_on the referenced "
            "sibling) to the step's real top-level depends_on column. The edge is "
            "sibling-scoped: the dependency must be a sibling of step_id (same "
            "parent, same level) or the call is refused with "
            "INVALID_DEPENDENCY_SCOPE. Adding an existing edge is a no-op that "
            "returns already_present=true without a new revision. A change that "
            "would close a cycle is refused with DEPENDENCY_CYCLE. Mutation is "
            "admitted under the same regime as step_update: draft directly, "
            "frozen only inside a cascade. Same-file writer-order ambiguity is "
            "admitted monotonically (bug 64107707): a pre-existing ambiguity "
            "elsewhere in the graph never refuses this add; only a NEW ambiguous "
            "pair the edge would introduce does, as AS_SAME_FILE_ORDER_AMBIGUOUS."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID).",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Step that receives the dependency (canonical path, bare id, or UUID).",
                "type": "string",
                "required": True,
            },
            "depends_on": {
                "description": "Sibling step that must run before step_id (canonical path, bare id, or UUID).",
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
                "description": "The updated dependency list and the recorded revision.",
                "data": {
                    "step": "Canonical path of the edited step.",
                    "depends_on": "Canonical paths of the step's dependencies after the add.",
                    "added": "Canonical path of the dependency that was requested.",
                    "already_present": "True when the edge already existed (no new revision).",
                    "revision_uuid": "Revision UUID produced by the add, or the head revision on a no-op.",
                },
                "example": {
                    "step": "G-005/T-002/A-003",
                    "depends_on": ["G-005/T-002/A-001", "G-005/T-002/A-002"],
                    "added": "G-005/T-002/A-002",
                    "already_present": False,
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
                "description": "Make A-003 depend on sibling A-001.",
                "command": {
                    "plan": "doc-store",
                    "step_id": "G-005/T-002/A-003",
                    "depends_on": "G-005/T-002/A-001",
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
            "DEPENDENCY_STEP_NOT_FOUND": {
                "description": "The depends_on reference does not resolve.",
                "message": "step not found: A-099",
                "solution": "Reference an existing sibling step.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare id matches more than one step.",
                "message": "step_id A-001 resolves to multiple steps",
                "solution": "Use the canonical path such as G-005/T-002/A-001.",
            },
            "SELF_DEPENDENCY": {
                "description": "step_id and depends_on are the same step.",
                "message": "a step cannot depend on itself: G-005/T-002/A-003",
                "solution": "Reference a different sibling step.",
            },
            "INVALID_DEPENDENCY_SCOPE": {
                "description": "The dependency is not a sibling (different parent or level).",
                "message": "a dependency must reference a sibling step (same parent and level)",
                "solution": "Reference a sibling at the same level under the same parent.",
            },
            "DEPENDENCY_CYCLE": {
                "description": "The edge would create a cycle in the dependency graph.",
                "message": "Dependency change would create a cycle.",
                "solution": "Remove the opposing edge first or choose a different dependency.",
            },
            "AS_SAME_FILE_ORDER_AMBIGUOUS": {
                "description": (
                    "The edge would introduce a NEW same-file writer ambiguity absent "
                    "from the before-state (bug 64107707). A pre-existing ambiguity "
                    "elsewhere in the graph never refuses this add."
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
            "Dependencies are between siblings only; model cross-level ordering at the leaf (AS) level.",
            "Add is idempotent — safe to call repeatedly; check already_present in the response.",
            "Use step_dependency_preview or step_dependency_apply with dry_run for bulk edits.",
        ],
    }
