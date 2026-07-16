"""Metadata for the command_timing_stats command (C-004, C-011)."""
from __future__ import annotations

from plan_manager.commands.runtime_filtering import filter_metadata_params, pagination_metadata_params

_WINDOW_FILTER_FIELDS = ["created_after", "created_before"]


def get_command_timing_stats_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Reads the append-only command_metric store written by the "
            "registration.py timing hook, optionally filtered to one exact "
            "command_name and/or a created_after/created_before time window, "
            "groups the matching rows by command_name, and computes call "
            "count, p50/p95/max wall-clock latency percentiles (linear "
            "interpolation over the sorted durations), and a direct-vs-queued "
            "invocation count split (mode is tagged by the hook from the "
            "command class's own use_queue declaration at wrap time, never "
            "probed at read time). Per-command rows are sorted by "
            "command_name ascending and paginated via limit/offset."
        ),
        "parameters": {
            "command_name": {
                "description": "Exact command name to filter the metrics store by. Omit to aggregate over every recorded command.",
                "type": "string",
                "required": False,
            },
            **filter_metadata_params(_WINDOW_FILTER_FIELDS),
            **pagination_metadata_params(),
        },
        "return_value": {
            "success": {
                "description": "A page of per-command timing aggregate rows plus the uniform total/limit/offset envelope.",
                "data": {
                    "commands": "Per-command aggregate rows (paginated), each with command_name, call_count, p50_ms, p95_ms, max_ms, direct_count, queued_count.",
                    "total": "Total count of distinct commands in the full (unpaginated) result before pagination.",
                    "limit": "Pagination limit applied to this result.",
                    "offset": "Pagination offset applied to this result.",
                },
                "example": {
                    "commands": [
                        {
                            "command_name": "step_get",
                            "call_count": 42,
                            "p50_ms": 3.2,
                            "p95_ms": 11.7,
                            "max_ms": 18.4,
                            "direct_count": 40,
                            "queued_count": 2,
                        }
                    ],
                    "total": 1,
                    "limit": 50,
                    "offset": 0,
                },
            },
            "error": {
                "description": "Domain error returned when a filter or pagination parameter is invalid.",
                "code": "INVALID_FILTER | INVALID_PAGINATION",
                "message": "Human-readable message identifying the invalid parameter.",
                "details": "Details about the error condition.",
            },
        },
        "usage_examples": [
            {
                "description": "Get timing stats for every command with default pagination.",
                "command": {},
                "explanation": "Returns up to 50 per-command aggregate rows sorted by command_name ascending.",
            },
            {
                "description": "Get timing stats for one command within a time window.",
                "command": {
                    "command_name": "step_get",
                    "created_after": "2026-07-01T00:00:00+00:00",
                    "created_before": "2026-07-16T00:00:00+00:00",
                },
                "explanation": "Returns at most one aggregate row (for step_get) computed only from metrics recorded inside the given window.",
            },
        ],
        "error_cases": {
            "INVALID_FILTER": {
                "description": "created_after or created_before is not a valid ISO-8601 timestamp string.",
                "message": "'created_after' must be a valid ISO-8601 timestamp string, got {value!r}",
                "solution": "Pass an ISO-8601 timestamp string, e.g. '2026-07-01T00:00:00+00:00'.",
            },
            "INVALID_PAGINATION": {
                "description": "limit or offset is out of the allowed range or not an integer.",
                "message": "limit must be between 1 and 200, got {value!r}",
                "solution": "Ensure limit is between 1 and 200, and offset is non-negative.",
            },
        },
        "best_practices": [
            "Omit command_name to see every command's aggregate in one page; pass it to drill into one command's percentiles.",
            "mode (direct vs queued) reflects the command class's own use_queue declaration recorded at invocation time, not a per-call runtime choice.",
            "p50/p95/max are computed by linear interpolation over sorted durations; a command with exactly one recorded call reports that call's duration for all three.",
            "total counts distinct commands in the full filtered result, not the number of raw metric rows; compare offset+limit against total to detect additional pages.",
            "This command never mutates the command_metric store; use it purely for read-only performance observability.",
        ],
    }
