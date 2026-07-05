"""Metadata for the plan_prompt_chain command."""

from __future__ import annotations


def get_plan_prompt_chain_metadata(cls) -> dict:
    """Return extended AI/documentation metadata for PlanPromptChainCommand."""
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Builds a deterministic, deduplicated prompt-chain artifact "
            "for a whole plan, one global-step scope, or one "
            "global/tactical scope. Before any payload is assembled, the "
            "command runs the mechanical gate for the requested scope: "
            "the whole plan for whole_plan, or every atomic branch inside "
            "a G-NNN or G-NNN/T-NNN scope. If any checked gate is red, "
            "the command returns GATE_RED and no partial prompt-chain "
            "payload. On success, blocks are keyed by stable content "
            "hashes and contain only canonical HRS fragments, MRS "
            "fragments, global steps, tactical steps, and atomic steps. "
            "The steps array lists eligible atomic steps with target "
            "file, operation, priority, block ids, wave number from the "
            "same graph algorithm as graph_parallel_map, branch path, "
            "and direct depends_on values. The command is read-only and "
            "does not tokenize, pad, or add provider-specific prompt "
            "markup. Historical reconstruction is not available in this "
            "storage model, so an explicit revision must match the "
            "current plan head."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the plan catalog.",
                "type": "string",
                "required": True,
            },
            "revision": {
                "description": "Optional revision UUID. When supplied, it must equal the current plan head.",
                "type": "string",
                "required": False,
            },
            "scope": {
                "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN. Defaults to whole_plan.",
                "type": "string",
                "required": False,
            },
            "include_statuses": {
                "description": "Optional status filter for eligible GS/TS/AS chains. Defaults to ['frozen', 'ready_for_review'].",
                "type": "array",
                "required": False,
            },
        },
        "return_value": {
            "success": {
                "description": "A deterministic prompt-chain artifact for eligible atomic steps in the requested scope.",
                "data": {
                    "plan": "Resolved plan name.",
                    "revision": "Current head revision UUID, or null when the plan has no revision.",
                    "scope": "Normalized scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                    "blocks": "Map of stable block_id to canonical prompt-chain block.",
                    "steps": "Ordered atomic execution rows referencing block_ids.",
                },
                "example": {
                    "plan": "plan_manager",
                    "revision": "00000000-0000-0000-0000-000000000000",
                    "scope": "G-001/T-001",
                    "blocks": {
                        "atomic-step-0123456789abcdef": {
                            "block_id": "atomic-step-0123456789abcdef",
                            "type": "atomic_step",
                            "source_ref": ["G-001/T-001/A-001"],
                            "content": "{\"step_id\":\"A-001\"}",
                        }
                    },
                    "steps": [
                        {
                            "step_id": "A-001",
                            "target_file": "plan_manager/example.py",
                            "operation": "update",
                            "priority": 1,
                            "block_ids": ["atomic-step-0123456789abcdef"],
                            "wave": 3,
                            "branch_path": "G-001/T-001",
                            "depends_on": [],
                        }
                    ],
                },
            },
            "error": {
                "description": "Domain error returned when the plan, revision, scope, graph, or gate cannot be accepted.",
                "code": "PLAN_NOT_FOUND | REVISION_NOT_FOUND | STEP_NOT_FOUND | CYCLE_DETECTED | GATE_RED | INVALID_TRANSITION",
                "message": "Human-readable explanation of the refused request.",
                "details": "For GATE_RED, includes scope and findings_count.",
            },
        },
        "usage_examples": [
            {
                "description": "Build a prompt chain for the whole current plan using the default status filter.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns blocks and atomic step rows only if the whole-plan gate is green.",
            },
            {
                "description": "Build a prompt chain for one tactical scope and include draft rows as well.",
                "command": {
                    "plan": "plan_manager",
                    "scope": "G-001/T-002",
                    "include_statuses": ["draft", "ready_for_review", "frozen"],
                },
                "explanation": "Checks every atomic branch in G-001/T-002 and then emits eligible rows in deterministic order.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to a plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan name or UUID.",
            },
            "REVISION_NOT_FOUND": {
                "description": "The supplied revision is not the current head revision.",
                "message": "revision not found for current head: {revision}",
                "solution": "Omit revision to use the current head, or retry with the current head revision UUID.",
            },
            "STEP_NOT_FOUND": {
                "description": "The scope string is invalid or names a missing global/tactical scope.",
                "message": "scope must be omitted, 'whole_plan', 'G-NNN', or 'G-NNN/T-NNN'",
                "solution": "Call step_tree to discover valid scope identifiers and retry.",
            },
            "CYCLE_DETECTED": {
                "description": "The dependency graph cannot be partitioned into waves.",
                "message": "cycle detected",
                "solution": "Inspect graph_deps or graph_order, break the cycle, and retry.",
            },
            "GATE_RED": {
                "description": "The mechanical gate for the requested scope is not green.",
                "message": "scope {scope} refused: mechanical gate not green ({findings_count} findings)",
                "solution": "Fix the gate findings through the normal plan workflow, then call plan_prompt_chain again.",
            },
        },
        "best_practices": [
            "Call this command only after plan_validate is green for the same scope when you want a predictable success path.",
            "Keep provider-specific wrappers outside this artifact; the output is intentionally model-neutral.",
            "Use include_statuses to select lifecycle-ready work, not to bypass the mechanical gate.",
        ],
    }
