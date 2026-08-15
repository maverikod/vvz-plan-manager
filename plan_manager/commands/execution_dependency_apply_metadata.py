"""Extended metadata for the execution_dependency_apply command (EIG block D)."""
from __future__ import annotations

from typing import Any


def get_execution_dependency_apply_metadata(cls) -> dict[str, Any]:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Applies a depends_on change set — normally the proposed_changes "
            "returned by execution_dependency_suggest — through the exact same "
            "engine step_dependency_apply uses (step_dependency_ops.plan_changes/"
            "detect_cycle/same_file_admission/persist_changes): every reference "
            "is validated and the resulting graph is checked for cycles before "
            "anything is written; if any change is invalid or would create a "
            "cycle, nothing is applied. Pass changes explicitly (the recommended "
            "flow: call execution_dependency_suggest, inspect proposed_changes, "
            "then pass that list back here) to apply exactly what was reviewed. "
            "Omit changes and pass confirm=true to instead have the server "
            "recompute the CURRENT proposal at apply time and apply that — useful "
            "for a scripted 'always take the latest suggestion' flow, at the cost "
            "of applying whatever the graph looks like right now rather than what "
            "was reviewed; changes omitted without confirm=true is a parameter "
            "error, not a silent no-op. With dry_run=true (the default) no "
            "mutation happens and the before/after impact is returned, exactly as "
            "step_dependency_apply's preview does; the applied changes are also "
            "echoed back as changes_applied so a confirm=true recompute caller can "
            "see what was actually used. With dry_run=false the whole batch is "
            "written as exactly one revision under the step mutation regime "
            "(direct for draft steps, or under cascade_uuid for frozen steps).\n"
            "Same-file writer-order ambiguity (bug 64107707) is admitted "
            "monotonically, identically to step_dependency_apply: a pre-existing "
            "ambiguity in the before-state graph never refuses the batch — only a "
            "NEW ambiguous pair the batch would introduce does, reported (and, on "
            "refusal, nothing is written) as AS_SAME_FILE_ORDER_AMBIGUOUS with the "
            "specific introduced_pairs named."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID).",
                "type": "string",
                "required": True,
            },
            "changes": {
                "description": (
                    "Ordered dependency changes to apply, normally the proposed_changes "
                    "returned by execution_dependency_suggest; each is {op, step_id, "
                    "depends_on?}. Omit together with confirm=true to have the server "
                    "recompute and apply the current proposal instead."
                ),
                "type": "array",
                "required": False,
            },
            "confirm": {
                "description": (
                    "Required (true) when changes is omitted, to explicitly opt into "
                    "applying the server-recomputed current proposal."
                ),
                "type": "boolean",
                "required": False,
                "default": False,
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
                "description": "Whether the batch was applied, the changes actually used, and before/after impact.",
                "data": {
                    "applied": "True when the batch was written (dry_run=false).",
                    "dry_run": "Echo of the dry_run flag.",
                    "valid": "True when the batch is acyclic and admissible.",
                    "would_create_cycle": "Always false on success (a cycle raises DEPENDENCY_CYCLE).",
                    "changed_steps": "Canonical paths of steps whose depends_on changed.",
                    "changes_applied": "The exact change list used (the caller-supplied changes, or the server-recomputed proposal when confirm=true was used instead).",
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
                    "changed_steps": ["G-001/T-002/A-002"],
                    "changes_applied": [
                        {"op": "add", "step_id": "G-001/T-002/A-002", "depends_on": ["G-001/T-001/A-001"]}
                    ],
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
                "details": {"cycle": ["G-001/T-001/A-001", "G-001/T-002/A-002"]},
            },
        },
        "usage_examples": [
            {
                "description": "Review then apply the current suggestion in two steps.",
                "command": {
                    "plan": "doc-store",
                    "changes": [
                        {"op": "add", "step_id": "G-001/T-002/A-002", "depends_on": ["G-001/T-001/A-001"]}
                    ],
                    "dry_run": False,
                },
            },
            {
                "description": "Recompute and apply the current proposal in one call.",
                "command": {"plan": "doc-store", "confirm": True, "dry_run": False},
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
            "DEPENDENCY_STEP_NOT_FOUND": {
                "description": "A depends_on reference does not resolve.",
                "message": "step not found: A-099",
                "solution": "Re-run execution_dependency_suggest to get a fresh, applicable proposal.",
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
                "solution": "Add an explicit dependency between the affected branches, or preview first with dry_run=true.",
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
            "Prefer the explicit changes flow (suggest, review, apply-with-that-list) over confirm=true for anything reviewed by a human.",
            "Every proposed edge is atomic-step-scoped (level 5) and expressed with full canonical paths, so it applies correctly whether the producer and consumer are siblings or in different branches.",
        ],
    }
