"""Extended metadata for the step_dependency_apply command."""
from __future__ import annotations

from typing import Any


def get_step_dependency_apply_metadata(cls) -> dict[str, Any]:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Apply an ordered batch of dependency changes ({op, step_id, "
            "depends_on}) all-or-nothing. Every reference is validated and the "
            "resulting graph is checked for cycles before anything is written; if "
            "any change is invalid or would create a cycle, nothing is applied. "
            "With dry_run=true (the default) no mutation happens and the "
            "before/after impact is returned. With dry_run=false the whole batch "
            "is written as exactly one revision under the step mutation regime "
            "(direct for draft steps, or under cascade_uuid for frozen steps).\n"
            "Same-file writer-order ambiguity (bug 64107707) is admitted "
            "monotonically: a pre-existing ambiguity in the before-state graph "
            "never refuses the batch — only a NEW ambiguous pair the batch would "
            "introduce does, reported (and, on refusal, nothing is written) as "
            "AS_SAME_FILE_ORDER_AMBIGUOUS with the specific introduced_pairs "
            "named. This check runs the same way whether dry_run is true or "
            "false, mirroring DEPENDENCY_CYCLE."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID).",
                "type": "string",
                "required": True,
            },
            "changes": {
                "description": "Ordered dependency changes to apply; each is {op, step_id, depends_on?}.",
                "type": "array",
                "required": True,
            },
            "dry_run": {
                "description": "When true (default), validate and report impact without mutating.",
                "type": "boolean",
                "required": False,
                "default": True,
            },
            "cascade_uuid": {
                "description": "Open cascade to admit the mutations under; omit for direct-mode on non-frozen steps.",
                "type": "string",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "Whether the batch was applied, the changed steps, and before/after impact.",
                "data": {
                    "applied": "True when the batch was written (dry_run=false).",
                    "dry_run": "Echo of the dry_run flag.",
                    "valid": "True when the batch is acyclic and admissible.",
                    "would_create_cycle": "Always false on success (a cycle raises DEPENDENCY_CYCLE).",
                    "changed_steps": "Canonical paths of steps whose depends_on changed.",
                    "impact": "execution_order_before/after and parallel_waves_before/after as canonical paths.",
                    "same_file_order": {
                        "before_findings": "{target_file, writers} pairs ambiguous before the batch.",
                        "after_findings": "{target_file, writers} pairs ambiguous after the batch.",
                        "resolved_pairs": "Pairs ambiguous before and resolved by the batch.",
                        "introduced_pairs": "Always [] on success — a non-empty set raises AS_SAME_FILE_ORDER_AMBIGUOUS instead.",
                    },
                    "revision_uuid": "Revision UUID when applied, otherwise the head revision.",
                },
                "example": {
                    "applied": True,
                    "dry_run": False,
                    "valid": True,
                    "would_create_cycle": False,
                    "changed_steps": ["G-005/T-002/A-003"],
                    "impact": {
                        "execution_order_before": [],
                        "execution_order_after": [],
                        "parallel_waves_before": [],
                        "parallel_waves_after": [],
                    },
                    "same_file_order": {
                        "before_findings": [],
                        "after_findings": [],
                        "resolved_pairs": [],
                        "introduced_pairs": [],
                    },
                    "revision_uuid": "bbc68757-563a-4646-b5ba-6f01c53c105e",
                },
            },
            "error": {
                "description": "A stable domain error when a change is invalid or would create a cycle.",
                "code": "DEPENDENCY_CYCLE",
                "message": "Dependency change would create a cycle.",
                "details": {"cycle": ["G-005/T-002/A-001", "G-005/T-002/A-003"]},
            },
        },
        "usage_examples": [
            {
                "description": "Dry-run a batch of two dependency additions.",
                "command": {
                    "plan": "doc-store",
                    "changes": [
                        {"op": "add", "step_id": "G-005/T-002/A-003", "depends_on": ["G-005/T-002/A-001"]},
                        {"op": "add", "step_id": "G-005/T-002/A-004", "depends_on": ["G-005/T-002/A-003"]},
                    ],
                    "dry_run": True,
                },
            },
            {
                "description": "Apply the batch as one revision.",
                "command": {
                    "plan": "doc-store",
                    "changes": [
                        {"op": "set", "step_id": "G-005/T-002/A-003", "depends_on": ["G-005/T-002/A-001"]}
                    ],
                    "dry_run": False,
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
            "DEPENDENCY_CYCLE": {
                "description": "The batch would create a cycle; nothing is applied.",
                "message": "Dependency change would create a cycle.",
                "solution": "Adjust the changes so the graph stays acyclic.",
            },
            "AS_SAME_FILE_ORDER_AMBIGUOUS": {
                "description": (
                    "The batch would introduce a NEW same-file writer ambiguity absent "
                    "from the before-state; nothing is applied. A pre-existing ambiguity "
                    "the batch leaves unresolved does NOT trigger this."
                ),
                "message": "Dependency change would introduce a new same-file writer ambiguity.",
                "solution": (
                    "Add an explicit dependency between the branches of the newly "
                    "conflicting pair(s) named in introduced_pairs, or preview first."
                ),
            },
            "CASCADE_REQUIRED": {
                "description": "A target is frozen at or below and no cascade was supplied.",
                "message": "step is not directly mutable",
                "solution": "Open a cascade and pass cascade_uuid.",
            },
            "FROZEN_ARTIFACT": {
                "description": "A target step or a descendant is frozen.",
                "message": "step is not directly mutable",
                "solution": "Apply inside a cascade.",
            },
            "CASCADE_CONFLICT": {
                "description": "cascade_uuid does not match the plan's open cascade.",
                "message": "cascade id does not match the open cascade",
                "solution": "Pass the current open cascade's UUID.",
            },
        },
        "best_practices": [
            "Always dry-run first (the default) and inspect the impact before applying.",
            "Batch related edits so they land as one auditable revision.",
            "Dependencies are sibling-scoped; the batch cannot express cross-level ordering.",
        ],
    }
