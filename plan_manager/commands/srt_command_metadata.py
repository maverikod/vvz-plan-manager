"""Shared metadata builders for semantic-tree-snapshot and semantic-diff commands."""

from __future__ import annotations


ERROR_CASES = {
    "PLAN_NOT_FOUND": {
        "description": "The plan identifier does not resolve.",
        "message": "plan not found: {plan}",
        "solution": "Call plan_list and retry with a valid plan name or UUID.",
    },
    "REVISION_NOT_FOUND": {
        "description": "The requested revision is not available for this plan.",
        "message": "revision not found: {revision}",
        "solution": "Omit revision for current head, or call plan_status for a valid revision.",
    },
    "SNAPSHOT_NOT_FOUND": {
        "description": "The supplied snapshot uuid does not resolve to a stored srt_snapshot record for this plan.",
        "message": "snapshot not found: {snapshot_uuid}",
        "solution": "Call srt_snapshot_list and retry with an existing snapshot uuid.",
    },
}


def srt_metadata(cls, parameters: dict, return_value: dict, examples: list[dict]) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Part of the SRT (Semantic Reproduction Tree) read-only command surface. "
            "All SRT commands are read-only except srt_snapshot_create, which stores "
            "only a derived SemanticTreeSnapshot record and does not modify plan truth: "
            "no HRS, MRS, step, cascade state, or head revision is changed by any SRT "
            "command."
        ),
        "parameters": parameters,
        "return_value": return_value,
        "usage_examples": examples,
        "error_cases": ERROR_CASES,
        "best_practices": [
            "Call srt_snapshot_create after a semantic reproduction tree has been computed for the current head revision.",
            "Call srt_snapshot_list to discover snapshot uuids before calling srt_diff.",
        ],
    }


BASE_PARAMETERS = {
    "plan": {
        "description": "Plan identifier (name or UUID).",
        "type": "string",
        "required": True,
    },
}
