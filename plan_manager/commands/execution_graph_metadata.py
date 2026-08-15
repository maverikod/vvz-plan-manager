"""Metadata for the execution_graph command (EIG block B, todo 16853f27)."""
from __future__ import annotations

from plan_manager.commands.runtime_filtering import pagination_metadata_params


def get_execution_graph_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Resolves the plan against the catalog, loads the dependency "
            "projection (C-009) for the plan once, and builds the extended "
            "execution graph: declared/derived dependency edges (types "
            "'explicit' and 'file_order', decomposed from the same "
            "build_edges machinery graph_deps/graph_order/graph_parallel_map "
            "use) plus two INFERRED edge families read off the block-A "
            "object roles (types 'object_producer' and "
            "'verification_target'). Returns one paginated page of the "
            "combined edge list (explicit_edges then inferred_edges, "
            "uniform offset/limit convention, default limit 50, max 200) "
            "together with the always-full missing_producers, "
            "ambiguous_dependencies, and cycles sections and a summary "
            "count block. The command is read-only and mutates nothing."
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
                    "A page of the combined explicit+inferred edge list, plus "
                    "the always-full missing_producers/ambiguous_dependencies/"
                    "cycles sections and a summary count block."
                ),
                "data": {
                    "edges": "List of edge dicts in the requested page; each has from, to, type, provenance, evidence.",
                    "total_edges": "Count of the full combined edge list before pagination.",
                    "limit": "The limit actually applied.",
                    "offset": "The offset actually applied.",
                    "summary": "Counts: explicit_edge_count, inferred_edge_count, missing_producer_count, ambiguous_dependency_count, cycle_count.",
                    "missing_producers": "Full list of {object, consumers}: objects consumed by some AS but produced by none.",
                    "ambiguous_dependencies": "Full list of {object, producers}: objects with more than one distinct producer AS.",
                    "cycles": "Full list of cycles, each an ordered list of artifact paths.",
                },
                "example": {
                    "edges": [
                        {
                            "from": "G-001-domain-model/T-001-plan-aggregate/atomic_steps/A-001-plan.yaml",
                            "to": "G-001-domain-model/T-002-step-lifecycle/atomic_steps/A-001-status.yaml",
                            "type": "explicit",
                            "provenance": "explicit",
                            "evidence": {},
                        }
                    ],
                    "total_edges": 1,
                    "limit": 50,
                    "offset": 0,
                    "summary": {
                        "explicit_edge_count": 1,
                        "inferred_edge_count": 0,
                        "missing_producer_count": 0,
                        "ambiguous_dependency_count": 0,
                        "cycle_count": 0,
                    },
                    "missing_producers": [],
                    "ambiguous_dependencies": [],
                    "cycles": [],
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
                "description": "Get the first page of the extended execution graph of a plan.",
                "command": {"plan": "plan_manager"},
                "explanation": "Returns the first page (default limit 50) of the combined explicit+inferred edge list, plus the full missing_producers/ambiguous_dependencies/cycles sections.",
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
                "solution": "Add an explicit dependency between the affected TS/GS branches, then retry.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of range or not an integer.",
                "message": "limit must be between 1 and 200, got {limit}",
                "solution": "Retry with limit in [1, 200] and offset >= 0.",
            },
        },
        "best_practices": [
            "Use graph_deps/graph_order/graph_parallel_map instead when only the declared/derived dependency graph (no object-role inference) is needed.",
            "missing_producers and ambiguous_dependencies flag object-role declarations (domain.step_objects.OBJECT_ROLES) that need authoring attention.",
            "cycles reports genuine cycles only (Tarjan SCCs), never the wider Kahn's-algorithm residual that also includes nodes merely blocked behind one.",
            "Compare offset+limit against total_edges to detect additional pages of edges.",
        ],
    }
