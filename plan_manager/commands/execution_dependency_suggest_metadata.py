"""Extended metadata for the execution_dependency_suggest command (EIG block D)."""
from __future__ import annotations

from typing import Any

from plan_manager.commands.runtime_filtering import pagination_metadata_params


def get_execution_dependency_suggest_metadata(cls) -> dict[str, Any]:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Loads the dependency projection (C-009) for the plan once and builds "
            "the extended execution graph (execution_graph/views.execution_graph."
            "build_execution_graph). From its INFERRED edges (types "
            "object_producer and verification_target — both always between two "
            "atomic (level-5) steps), excludes: (1) any object_producer edge "
            "whose object appears in ambiguous_dependencies (more than one "
            "distinct producer — no single correct depends_on target), and (2) "
            "any edge already implied by the explicit graph (the producer can "
            "already reach the consumer, directly or transitively, through "
            "declared depends_on or derived same-file order). What survives is "
            "returned two ways: proposed_changes, a step_dependency_apply-"
            "compatible list of {op: 'add', step_id, depends_on} grouped by "
            "consumer step (ready to pass straight to execution_dependency_apply "
            "or step_dependency_apply), and proposed_edges, the same edges "
            "individually with provenance/evidence, paginated. "
            "Cross-branch rule: every proposed edge is expressed directly at the "
            "atomic step's own level using full canonical step paths for both "
            "step_id and depends_on, never lifted to an ancestor GS/TS depends_on "
            "— step_dependency_ops.resolve_dependency_bare already admits a "
            "level-5-to-level-5 dependency across tactical/global branches "
            "directly (stored as a canonical path), unlike GS/TS depends_on which "
            "stays sibling-scoped; the ancestor-level-inheritance technique "
            "same-file ordering needs (derive_cross_branch_edges/waves()) does "
            "not apply here because these edges are AS-scoped from the start. "
            "Read-only: never writes."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or uuid) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            **pagination_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": (
                    "The full apply-ready change set plus a paginated page of the "
                    "individual edges backing it, and the always-full ambiguous/"
                    "missing-producer context."
                ),
                "data": {
                    "proposed_changes": (
                        "Full list of {op: 'add', step_id, depends_on}, one entry per "
                        "consumer step gaining edges, sorted by step_id; ready to pass "
                        "as-is to execution_dependency_apply(changes=...) or "
                        "step_dependency_apply(changes=...). Never paginated."
                    ),
                    "proposed_edges": (
                        "Page of the surviving inferred edge dicts (from, to, type, "
                        "provenance, evidence) backing proposed_changes."
                    ),
                    "total_proposed_edges": "Count of the full proposed_edges list before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                    "ambiguous_dependencies": (
                        "Full list of {object, producers}: the skipped-as-ambiguous "
                        "report — objects with more than one distinct producer AS, "
                        "whose object_producer edges are excluded from the proposal."
                    ),
                    "missing_producers": "Full list of {object, consumers}: objects consumed by some AS but produced by none.",
                    "summary": "Counts: proposed_edge_count, proposed_step_count, ambiguous_dependency_count, missing_producer_count.",
                },
                "example": {
                    "proposed_changes": [
                        {
                            "op": "add",
                            "step_id": "G-001/T-002/A-002",
                            "depends_on": ["G-001/T-001/A-001"],
                        }
                    ],
                    "proposed_edges": [
                        {
                            "from": "G-001/T-001/A-001",
                            "to": "G-001/T-002/A-002",
                            "type": "object_producer",
                            "provenance": "inferred",
                            "evidence": {
                                "object": "widget_schema",
                                "producer_role": "create",
                                "consumer_role": "consume",
                            },
                        }
                    ],
                    "total_proposed_edges": 1,
                    "limit": 50,
                    "offset": 0,
                    "ambiguous_dependencies": [],
                    "missing_producers": [],
                    "summary": {
                        "proposed_edge_count": 1,
                        "proposed_step_count": 1,
                        "ambiguous_dependency_count": 0,
                        "missing_producer_count": 0,
                    },
                },
            },
            "error": {
                "description": "Domain error returned when the plan cannot be resolved, a declared dependency is unresolved, same-file writer order is ambiguous, or pagination is invalid.",
                "code": "PLAN_NOT_FOUND | AS_SAME_FILE_ORDER_AMBIGUOUS | INVALID_PAGINATION",
                "message": "Human-readable message identifying the missing plan, ambiguity, or pagination error.",
                "details": "None for PLAN_NOT_FOUND; writer-order conflict details for AS_SAME_FILE_ORDER_AMBIGUOUS when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Get the current unambiguous depends_on proposal for a plan.",
                "command": {"plan": "doc-store"},
                "explanation": (
                    "Returns proposed_changes (full) ready for execution_dependency_apply "
                    "or step_dependency_apply, plus the first page of proposed_edges and "
                    "the ambiguous/missing-producer context."
                ),
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not match any plan in the catalog.",
                "message": "plan not found: {plan}",
                "solution": "List plans through the catalog command and retry with a valid plan identifier.",
            },
            "AS_SAME_FILE_ORDER_AMBIGUOUS": {
                "description": "Two atomic writers target the same file but no dependency path establishes their execution order.",
                "message": "ambiguous same-file writer order: {details}",
                "solution": "Resolve the ambiguity (e.g. via step_dependency_apply) before requesting a fresh proposal.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Pass proposed_changes straight to execution_dependency_apply(changes=..., dry_run=true) to preview the impact before applying.",
            "ambiguous_dependencies names objects with more than one producer: resolve the authoring ambiguity (or add the dependency by hand) rather than expecting a suggestion for it.",
            "Re-run after any authoring change: the proposal reflects only the current graph and is never cached.",
        ],
    }
