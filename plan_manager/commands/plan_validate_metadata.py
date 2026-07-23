"""Extended AI/documentation metadata for PlanValidateCommand."""
from __future__ import annotations

from typing import Any, Dict, Type

from plan_manager.verify.gate import GATE_CHECK_SEMANTICS


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
            "or one hierarchical branch scope of that plan. A branch scope "
            "is named by precedence: gs_step_id alone checks the whole GS "
            "subtree; gs_step_id + ts_step_id narrows to one TS subtree; "
            "adding as_step_id narrows to one atomic branch. Every depth "
            "validates over the descendants that actually exist -- a GS or "
            "TS with zero AS descendants is valid input, not an error. The "
            "gate is deterministic and byte-identical for the same tree "
            "state; it never mutates plan data and never stores its report. "
            "The result binds to the exact revision that was measured. "
            "fail_fast stops the run only at check-group boundaries, never "
            "mid-group, so a single group's findings are always reported "
            "together. format selects between a PASS/FAIL text report and "
            "a machine-checkable JSON form; both are rendered from the same "
            "underlying report object."
        ),
        "gate_check_semantics": dict(GATE_CHECK_SEMANTICS),
        "parameters": {
            "plan": {
                "description": "Plan identifier (UUID or unique plan name) to validate.",
                "type": "string",
                "required": True,
            },
            "scope": {
                "description": (
                    "Validation scope: the whole plan, or one hierarchical branch "
                    "selected by gs_step_id alone (whole GS subtree), gs_step_id + "
                    "ts_step_id (that TS subtree), or all three (one atomic branch)."
                ),
                "type": "string",
                "required": False,
                "default": "plan",
                "enum": ["plan", "branch"],
            },
            "gs_step_id": {
                "description": (
                    "Global step id (e.g. G-005) of the branch. Required and "
                    "non-empty when scope is 'branch' -- selects that GS's whole "
                    "subtree unless narrowed by ts_step_id/as_step_id below. Must be "
                    "absent when scope is 'plan'."
                ),
                "type": "string",
                "required": False,
            },
            "ts_step_id": {
                "description": (
                    "Tactical step id (e.g. T-009): optional narrowing of the "
                    "gs_step_id subtree to one TS subtree. Required whenever "
                    "as_step_id is given (skipping this level is rejected "
                    "deterministically). Must be absent when scope is 'plan'."
                ),
                "type": "string",
                "required": False,
            },
            "as_step_id": {
                "description": (
                    "Atomic step id (e.g. A-101): optional narrowing to exactly one "
                    "atomic branch. Requires ts_step_id to also be given (as_step_id "
                    "without ts_step_id is a rejected skipped-level selector). Must "
                    "be absent when scope is 'plan'."
                ),
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
                    "revision_uuid": (
                        "String UUID of the plan's last COMMITTED head "
                        "revision (plan.head_revision_uuid), or null. This "
                        "is a metadata LABEL of what is officially "
                        "committed -- it does NOT identify which rows the "
                        "checks scanned: the gate always evaluates the "
                        "plan's live, current data (including any open "
                        "cascade's working tip), never a revision-pinned "
                        "snapshot. When the plan has an open cascade, "
                        "compare against tip_revision_uuid/cascade_uuid "
                        "below (both null when there is no open cascade) "
                        "to see the state identity that was actually "
                        "scanned."
                    ),
                    "tip_revision_uuid": (
                        "String UUID of the open cascade's current working "
                        "tip (same value cascade_preview reports as "
                        "tip_revision_uuid), or null when the plan has no "
                        "open cascade. This is the state the gate actually "
                        "evaluated whenever it is non-null."
                    ),
                    "cascade_uuid": (
                        "String UUID of the plan's open cascade, or null "
                        "when the plan has no open cascade."
                    ),
                    "format": "The output format actually used: 'text' or 'json'.",
                    "report": (
                        "The rendered report body as a string, in the "
                        "requested format. See the top-level "
                        "'gate_check_semantics' metadata field for a "
                        "one-line gloss of what each check_id actually "
                        "means before interpreting a finding -- in "
                        "particular, coverage.gs findings name a concept "
                        "declared on the GS itself that is not yet covered "
                        "by a TS child, not a concept absent from the GS "
                        "row."
                    ),
                },
                "example": {
                    "green": True,
                    "scope": "plan",
                    "revision_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
                    "tip_revision_uuid": None,
                    "cascade_uuid": None,
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
                "description": "Validate a whole GS subtree with gs_step_id alone, e.g. a GS with TS children but no AS descendants yet.",
                "command": {
                    "plan": "plan_manager",
                    "scope": "branch",
                    "gs_step_id": "G-007",
                    "format": "json",
                },
                "explanation": "Checks G-007 and every TS/AS descendant that currently exists under it; zero AS descendants is valid input, not an error.",
            },
            {
                "description": "Validate one TS subtree with gs_step_id + ts_step_id.",
                "command": {
                    "plan": "plan_manager",
                    "scope": "branch",
                    "gs_step_id": "G-007",
                    "ts_step_id": "T-002",
                    "format": "json",
                },
                "explanation": "Checks G-007, T-002, and every AS descendant of T-002 that currently exists.",
            },
            {
                "description": "Validate one atomic branch with a text report, stopping at the first failing check group.",
                "command": {
                    "plan": "plan_manager",
                    "scope": "branch",
                    "gs_step_id": "G-005",
                    "ts_step_id": "T-009",
                    "as_step_id": "A-101",
                    "fail_fast": True,
                    "format": "text",
                },
                "explanation": "Runs the mechanical gate over exactly that one atomic branch, halting at the first failing check-group boundary, and returns a PASS/FAIL text report.",
            },
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve to any plan in the database.",
                "message": "Plan not found: {plan}",
                "solution": "Verify the plan identifier against the plan catalog and retry.",
            },
            "STEP_NOT_FOUND": {
                "description": "scope is 'branch' and gs_step_id, ts_step_id, or as_step_id does not resolve within the plan, or a given ts_step_id/as_step_id does not belong to its addressed parent.",
                "message": "Step not found / step does not belong to addressed parent (message names the offending step_id).",
                "solution": "Verify the supplied step ids and their parentage against the plan tree and retry.",
            },
        },
        "best_practices": [
            "Run plan_validate before plan_score: scoring refuses any scope that has not passed the gate in the same tree state (plan_score's branch scope remains the full gs_step_id+ts_step_id+as_step_id atomic triple; only plan_validate's scope='branch' supports the gs-only/gs+ts narrowings).",
            "Use format='text' for human review and format='json' when the result feeds another automated step.",
            "Use scope='branch' with gs_step_id alone to check a whole GS subtree in progress (including one with TS children but no AS descendants yet), narrow with ts_step_id for one TS subtree, and add as_step_id with fail_fast=True for fast iteration on a single atomic branch.",
            "This command is read-only: it never mutates or stores anything, so it is always safe to call.",
            "revision_uuid is a committed-head LABEL, not a statement of which rows were scanned (the gate always reads live data). When the plan has an open cascade, record tip_revision_uuid/cascade_uuid instead to identify the exact state that was measured; both are null when there is no open cascade.",
            "This command runs on the queue: the plan_validate call returns an enqueue acknowledgement with job_id, store='queuemgr', and poll_with='queue_get_job_status'. Poll completion with queue_get_job_status (which reports status plus created_at/started_at/completed_at); do NOT poll with the builtin job_status, which reads a separate in-memory JobManager store and will report the job as not found (returning its own poll_with='queue_get_job_status' hint).",
        ],
    }
