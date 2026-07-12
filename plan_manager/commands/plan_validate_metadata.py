"""Extended AI/documentation metadata for PlanValidateCommand."""
from __future__ import annotations

from typing import Any, Dict, Type


def get_plan_validate_metadata(cls: Type[Any]) -> Dict[str, Any]:
    """Return the extended documentation metadata for PlanValidateCommand.

    :param cls: The command class object (PlanValidateCommand), used to
        source the identity fields name, version, descr, category, author,
        and email from the class attributes so this dictionary never
        contradicts the class or its get_schema().
    :type cls: Type[Any]
    :returns: A metadata dictionary with the required keys name, version,
        description, category, author, email, detailed_description,
        parameters, return_value, usage_examples, error_cases, and
        best_practices.
    :rtype: Dict[str, Any]
    """
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Runs the mechanical gate (fixed check order: parse, identity, "
            "uniqueness, references, coverage) as a pure read over one plan "
            "or one branch of that plan. The gate is deterministic and "
            "byte-identical for the same tree state; it never mutates plan "
            "data and never stores its report. The result binds to the "
            "exact revision that was measured. fail_fast stops the run only "
            "at check-group boundaries, never mid-group, so a single "
            "group's findings are always reported together. format selects "
            "between a PASS/FAIL text report and a machine-checkable JSON "
            "form; both are rendered from the same underlying report object."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique plan name) to validate.",
                "type": "string",
                "required": True,
            },
            "scope": {
                "description": "Validation scope: the whole plan or one branch named by its three step ids.",
                "type": "string",
                "required": False,
                "default": "plan",
                "enum": ["plan", "branch"],
            },
            "gs_step_id": {
                "description": "Global step id (e.g. G-005) of the branch. Required and non-empty when scope is 'branch'; must be absent when scope is 'plan'.",
                "type": "string",
                "required": False,
            },
            "ts_step_id": {
                "description": "Tactical step id (e.g. T-009) of the branch. Required and non-empty when scope is 'branch'; must be absent when scope is 'plan'.",
                "type": "string",
                "required": False,
            },
            "as_step_id": {
                "description": "Atomic step id (e.g. A-101) of the branch. Required and non-empty when scope is 'branch'; must be absent when scope is 'plan'.",
                "type": "string",
                "required": False,
            },
            "fail_fast": {
                "description": "Stop at the first failing check group boundary instead of running all check groups.",
                "type": "boolean",
                "required": False,
                "default": False,
            },
            "format": {
                "description": "Output format of the rendered report.",
                "type": "string",
                "required": False,
                "default": "json",
                "enum": ["text", "json"],
            },
        },
        "return_value": {
            "success": {
                "description": "The gate report bound to the measured revision.",
                "data": {
                    "green": "Boolean: whether the report has zero findings across all checks.",
                    "scope": "The verdict scope that was measured: 'plan' or 'branch'.",
                    "revision_uuid": "String UUID of the exact revision the report was computed for, or null.",
                    "format": "The output format actually used: 'text' or 'json'.",
                    "report": "The rendered report body as a string, in the requested format.",
                },
                "example": {
                    "green": True,
                    "scope": "plan",
                    "revision_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "format": "json",
                    "report": "{\"checks\": [], \"green\": true}",
                },
            },
            "error": {
                "description": "A domain error result.",
                "code": "Stable domain error code string.",
                "message": "Human-readable error message.",
                "details": "Additional diagnostic fields when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Validate an entire plan and get a JSON report.",
                "command": {"plan": "plan_manager", "scope": "plan", "format": "json"},
                "explanation": "Runs the mechanical gate over the whole plan and returns the JSON report bound to the current revision.",
            },
            {
                "description": "Validate one branch with a text report, stopping at the first failing check group.",
                "command": {
                    "plan": "plan_manager",
                    "scope": "branch",
                    "gs_step_id": "G-005",
                    "ts_step_id": "T-009",
                    "as_step_id": "A-101",
                    "fail_fast": True,
                    "format": "text",
                },
                "explanation": "Runs the mechanical gate over one branch only, halting at the first failing check-group boundary, and returns a PASS/FAIL text report.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to any plan in the database.",
                "message": "Plan not found: {plan}",
                "solution": "Verify the plan identifier against the plan catalog and retry.",
            },
            "STEP_NOT_FOUND": {
                "description": "scope is 'branch' but one of gs_step_id, ts_step_id, as_step_id does not resolve within the plan.",
                "message": "Step not found: {step_id}",
                "solution": "Verify the three branch step ids against the plan tree and retry.",
            },
        },
        "best_practices": [
            "Run plan_validate before plan_score: scoring refuses any scope that has not passed the gate in the same tree state.",
            "Use format='text' for human review and format='json' when the result feeds another automated step.",
            "Use scope='branch' with fail_fast=True for fast iteration while fixing a single branch.",
            "This command is read-only: it never mutates or stores anything, so it is always safe to call.",
            "Record the returned revision_uuid alongside the report; it identifies the exact tree state that was measured.",
            "This command runs on the queue: the plan_validate call returns an enqueue acknowledgement with job_id, store='queuemgr', and poll_with='queue_get_job_status'. Poll completion with queue_get_job_status (which reports status plus created_at/started_at/completed_at); do NOT poll with the builtin job_status, which reads a separate in-memory JobManager store and will report the job as not found (returning its own poll_with='queue_get_job_status' hint).",
        ],
    }
