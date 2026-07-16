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


def srt_metadata(
    cls,
    parameters: dict,
    return_value: dict,
    examples: list[dict],
    error_cases: dict[str, dict[str, str]] | None = None,
    extra_best_practices: list[str] | None = None,
) -> dict:
    """Build the standard metadata dict for an SRT command, merging optional command-specific error_cases over the shared ERROR_CASES and appending optional extra_best_practices to the default best-practices list. Existing callers passing only the first four positional arguments are unaffected."""
    merged_error_cases = dict(ERROR_CASES)
    if error_cases:
        merged_error_cases.update(error_cases)
    best_practices = [
        "Call srt_snapshot_create after a semantic reproduction tree has been computed for the current head revision.",
        "Call srt_snapshot_list to discover snapshot uuids before calling srt_diff.",
    ]
    if extra_best_practices:
        best_practices.extend(extra_best_practices)
    meta = {
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
        "error_cases": merged_error_cases,
        "best_practices": best_practices,
    }
    if cls.name == "srt_snapshot_create":
        meta["detailed_description"] += (
            " This command is queue-bound (use_queue = True) because computing a "
            "semantic reproduction tree over a large plan, including its embedding "
            "warm-up and summarization passes, can exceed the interactive request "
            "budget. The stored snapshot is a derived record; verify the result with "
            "the separate read command srt_snapshot_list after the job completes."
        )
        meta["best_practices"].append(
            "This command runs on the queue: srt_snapshot_create returns an "
            "enqueue acknowledgement with job_id, store='queuemgr', and "
            "poll_with='queue_get_job_status'. Poll completion with "
            "queue_get_job_status, which reaches a terminal state reporting the "
            "created_at/started_at/completed_at timestamps; do NOT poll with the "
            "builtin job_status, which reads a separate in-memory JobManager store "
            "and will report the job as not found (returning its own "
            "poll_with='queue_get_job_status' hint)."
        )
    return meta


BASE_PARAMETERS = {
    "plan": {
        "description": "Plan identifier (name or UUID).",
        "type": "string",
        "required": True,
    },
}
