"""Shared metadata builders for context-block commands."""

from __future__ import annotations


ERROR_CASES = {
    "PLAN_NOT_FOUND": {
        "description": "The plan identifier does not resolve.",
        "message": "plan not found: {plan}",
        "solution": "Call plan_list and retry with a valid plan name or UUID.",
    },
    "NODE_NOT_FOUND": {
        "description": "The node path is neither 'plan' nor a resolvable step path or UUID.",
        "message": "step not found: {node}",
        "solution": "Call step_tree and retry with a canonical step path.",
    },
    "CONCEPT_NOT_FOUND": {
        "description": "A supplied concept id is not present in the plan MRS.",
        "message": "concept not found: {concept_id}",
        "solution": "Call concept_list and retry with existing concept ids.",
    },
    "CONCEPT_OUT_OF_SCOPE": {
        "description": "Specific child concepts are not a subset of the common block scope.",
        "message": "specific concepts are outside the common block scope",
        "solution": "Compile a wider common block or narrow the child concept set.",
    },
    "COMMON_BLOCK_NOT_FOUND": {
        "description": "The supplied common_block_id does not resolve for this plan.",
        "message": "context block not found: {block_id}",
        "solution": "Call context_common first, then pass its common_block_id.",
    },
    "INVALID_LEVEL": {
        "description": "child_level is not one of 3, 4, or 5.",
        "message": "child_level must be one of [3, 4, 5]",
        "solution": "Use 3 for global, 4 for tactical, or 5 for atomic authoring context.",
    },
    "REVISION_NOT_FOUND": {
        "description": "The explicit revision is not available for live context compilation.",
        "message": "revision not available for live context compilation: {revision}",
        "solution": "Omit revision for current head, or use the open cascade_uuid for working-state context.",
    },
    "CASCADE_CONFLICT": {
        "description": "The supplied cascade_uuid is not the plan's currently open cascade.",
        "message": "supplied cascade_uuid is not the plan's open cascade",
        "solution": "Call cascade_begin or cascade_preview and pass the open cascade UUID.",
    },
    "PARENT_STEP_INVALID": {
        "description": (
            "The parent node is a level-4 (TS) step whose fields.inputs/fields.outputs "
            "fail the nested {name, type, description} item schema (bug 26fa21a5); "
            "compiling context for its descendants is refused so no child author receives "
            "a structurally invalid parent artifact."
        ),
        "message": "parent {node_path} fails structural parsing: {problems}",
        "solution": (
            "Fix the parent TS's inputs/outputs with step_update (each item must be "
            'an object {name, type, description} with type one of "input" or "output"), '
            "then retry."
        ),
    },
}


def context_metadata(
    cls,
    parameters: dict,
    return_value: dict,
    examples: list[dict],
    error_cases: dict[str, dict[str, str]] | None = None,
    extra_best_practices: list[str] | None = None,
) -> dict:
    """Build the standard metadata dict for a context-block command, merging optional command-specific error_cases over the shared ERROR_CASES and appending optional extra_best_practices to the default best-practices list. Existing callers passing only the first four positional arguments are unaffected."""
    merged_error_cases = dict(ERROR_CASES)
    if error_cases:
        merged_error_cases.update(error_cases)
    best_practices = [
        "Call context_common before context_specific so the shared scope is explicit and reusable.",
        "Use cascade_uuid when authoring against an open cascade so the compiled context tracks working state.",
        "Keep child concept sets as subsets of the common scope; widen common only when the parent genuinely owns that material.",
    ]
    if extra_best_practices:
        best_practices.extend(extra_best_practices)
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Compiles typed, deterministic authoring context blocks from live plan truth. "
            "Concept ids are the join key: the command gathers MRS concept blocks, HRS "
            "fragments referenced by concept source_labels, and MRS relations whose "
            "from_concept is in scope. Common blocks include plan-independent authoring "
            "template, standards prose, field schema, and optionally the parent step "
            "definition; specific blocks are strict deltas over their common block. "
            "Blocks are stored as derived database records keyed by content hash and "
            "revision/cascade identity. No plan artifact, head revision, export_root file, "
            "gate, or cascade status is mutated."
        ),
        "parameters": parameters,
        "return_value": return_value,
        "usage_examples": examples,
        "error_cases": merged_error_cases,
        "best_practices": best_practices,
    }


BASE_PARAMETERS = {
    "plan": {
        "description": "Plan identifier (name or UUID).",
        "type": "string",
        "required": True,
    },
    "revision": {
        "description": "Optional current head revision UUID. Historical reconstruction is not available for live context compilation.",
        "type": "string",
        "required": False,
    },
    "cascade_uuid": {
        "description": "Optional UUID of the plan's open cascade; mutually exclusive with revision.",
        "type": "string",
        "required": False,
    },
}
