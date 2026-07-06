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
            "Compiles the prompt-chain corpus for a committed, gate-green "
            "plan revision and scope. The command is read-only and queue-bound. "
            "It validates plan, revision, scope, role, and include_statuses, "
            "runs the mechanical gate before assembly, and returns no partial "
            "payload when the gate is red. The result is structured data: waves, "
            "level-keyed deduplicated blocks for hrs, mrs, gs, ts, as, and "
            "tool_instructions, a role-scoped assembly manifest, and meta. Every "
            "block carries a stable cache_key over canonical bytes. For role=coder, "
            "assembly.use contains only the AS block and the fixed tool_instructions "
            "block; upper-layer blocks remain available in the corpus for traceability "
            "and reviewer/conscience roles. The command performs no retrieval, "
            "semantic search, tokenization, padding, provider-specific formatting, "
            "model-tier selection, prompt dispatch, or execution logging."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the plan catalog.",
                "type": "string",
                "required": True,
            },
            "revision": {
                "description": "Optional revision UUID. Omit or pass 'head' to use the current plan head.",
                "type": "string",
                "required": False,
                "default": "head",
            },
            "scope": {
                "description": "Optional scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                "type": "string",
                "required": False,
                "default": "whole_plan",
            },
            "role": {
                "description": "Assembly role selector: coder, review, or conscience.",
                "type": "string",
                "required": False,
                "default": "coder",
                "enum": ["coder", "review", "conscience"],
            },
            "include_statuses": {
                "description": "Eligible statuses for the GS, TS, and AS chain.",
                "type": "array",
                "required": False,
                "default": ["frozen", "ready_for_review"],
                "items": {"type": "string", "enum": ["frozen", "ready_for_review"]},
            },
        },
        "return_value": {
            "success": {
                "description": "Structured prompt-chain corpus for the requested scope.",
                "data": {
                    "plan": "Resolved plan name.",
                    "revision": "Resolved head revision UUID, or null when the plan has no revision.",
                    "scope": "Normalized scope: whole_plan, G-NNN, or G-NNN/T-NNN.",
                    "role": "Assembly role used to build assembly.use.",
                    "waves": "Dependency waves as lists of G-NNN/T-NNN/A-NNN step keys.",
                    "blocks": "Level-keyed block corpus: hrs, mrs, gs, ts, as, tool_instructions.",
                    "assembly": "Per-step manifest with wave, branch_path, priority, role, and use.",
                    "meta": "Counts, dag_source, include_statuses, and project bindings.",
                },
                "example": {
                    "plan": "plan_manager",
                    "revision": "00000000-0000-0000-0000-000000000000",
                    "scope": "G-001/T-001",
                    "role": "coder",
                    "waves": [["G-001/T-001/A-001"]],
                    "blocks": {
                        "as": {
                            "G-001/T-001/A-001": {
                                "content": {
                                    "prompt": "Create the file...",
                                    "operation": "create_file",
                                    "target_file": "plan_manager/example.py",
                                    "verification": {"type": "import"},
                                },
                                "cache_key": "0123456789abcdef",
                            }
                        },
                        "tool_instructions": {
                            "coder": {
                                "content": "Use tool access...",
                                "cache_key": "abcdef0123456789",
                            }
                        },
                    },
                    "assembly": [
                        {
                            "step": "G-001/T-001/A-001",
                            "wave": 0,
                            "branch_path": "G-001/T-001",
                            "priority": 1,
                            "role": "coder",
                            "use": {
                                "as": "G-001/T-001/A-001",
                                "tool_instructions": "coder",
                            },
                        }
                    ],
                    "meta": {"dag_source": "derived: relations+target_file"},
                },
            },
            "error": {
                "description": "Domain error returned when the plan, revision, scope, role, status filter, graph, or gate cannot be accepted.",
                "code": "PLAN_NOT_FOUND | REVISION_NOT_FOUND | INVALID_SCOPE | INVALID_ROLE | INVALID_STATUS_FILTER | CYCLE_DETECTED | GATE_RED",
                "message": "Human-readable explanation of the refused request.",
                "details": "For GATE_RED, includes scope and findings_count.",
            },
        },
        "usage_examples": [
            {
                "description": "Compile the coder prompt-chain corpus for the current head.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns coder assembly only as AS plus tool_instructions when the whole-plan gate is green.",
            },
            {
                "description": "Compile one tactical scope for review.",
                "command": {
                    "plan": "plan_manager",
                    "scope": "G-001/T-002",
                    "role": "review",
                },
                "explanation": "Returns the full block corpus and review-oriented assembly for the scoped tactical branch.",
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
                "solution": "Omit revision, pass 'head', or retry with the current head revision UUID.",
            },
            "INVALID_SCOPE": {
                "description": "The scope string is invalid.",
                "message": "scope must be omitted, 'whole_plan', 'G-NNN', or 'G-NNN/T-NNN'",
                "solution": "Call step_tree to discover valid scope identifiers and retry.",
            },
            "INVALID_ROLE": {
                "description": "The role selector is not supported.",
                "message": "role must be one of ['coder', 'review', 'conscience']",
                "solution": "Use role coder, review, or conscience.",
            },
            "INVALID_STATUS_FILTER": {
                "description": "include_statuses is empty or contains an unsupported status.",
                "message": "unknown status in include_statuses: {statuses}",
                "solution": "Use the default or pass only frozen and ready_for_review.",
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
            "Use role=coder for execution: assembly.use intentionally contains only AS plus tool_instructions.",
            "Use review or conscience when the consumer must judge the AS against upper-layer context.",
            "Keep provider-specific wrappers outside this artifact; the output is model-neutral structured data.",
            "Run plan_validate first for a predictable green-gate path.",
        ],
    }
