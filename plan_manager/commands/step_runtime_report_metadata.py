"""Metadata for step_runtime_report."""

from __future__ import annotations


def get_step_runtime_report_metadata(cls) -> dict:
    return {
        "name": cls.name,
        "version": cls.version,
        "description": cls.descr,
        "category": cls.category,
        "author": cls.author,
        "email": cls.email,
        "detailed_description": (
            "Merges runtime parameters for one plan step without touching "
            "the step definition, plan revision, cascade state, lifecycle "
            "status, mechanical gate inputs, or semantic scoring inputs. "
            "activations and execution_attempts append by client-generated "
            "ids and are idempotent on retry. journal_aggregates is accepted "
            "only when its last_linked_at is not older than the stored value. "
            "authoring is replaced by the latest reported value. The command "
            "uses row-level atomicity for the step runtime row and no plan-wide "
            "cascade lock."
        ),
        "parameters": {
            "plan": {
                "description": "Plan identifier (name or UUID) resolved against the catalog.",
                "type": "string",
                "required": True,
            },
            "step_id": {
                "description": "Step to merge runtime into, as UUID, canonical path, or unambiguous local step id; a bare local id matching more than one step is rejected with AMBIGUOUS_STEP_ID.",
                "type": "string",
                "required": True,
            },
            "payload": {
                "description": "Partial RuntimeRecord containing any subset of activations, execution_attempts, journal_aggregates, authoring.",
                "type": "object",
                "required": True,
            },
        },
        "return_value": {
            "success": {
                "description": "Merged runtime record after applying the payload.",
                "data": {
                    "step_id": "Resolved step identifier.",
                    "runtime": "Merged RuntimeRecord.",
                },
                "example": {
                    "step_id": "A-001",
                    "runtime": {
                        "activations": [{"activation_id": "act-1", "chat_id": "chat-1", "started_at": "2026-07-06T00:00:00Z"}],
                        "execution_attempts": [],
                        "journal_aggregates": None,
                        "authoring": None,
                    },
                },
            },
            "error": {
                "description": "Plan or step could not be resolved.",
                "code": "PLAN_NOT_FOUND | STEP_NOT_FOUND",
                "message": "Human-readable error message.",
                "details": "Domain error details when available.",
            },
        },
        "usage_examples": [
            {
                "description": "Report one activation.",
                "command": {
                    "plan": "plan_manager",
                    "step_id": "A-001",
                    "payload": {
                        "activations": [
                            {
                                "activation_id": "act-1",
                                "chat_id": "chat-1",
                                "started_at": "2026-07-06T00:00:00Z",
                            }
                        ]
                    },
                },
                "explanation": "Retrying the same activation_id is idempotent.",
            }
        ],
        "error_cases": {
            "PLAN_NOT_FOUND": {
                "description": "The plan identifier does not resolve.",
                "message": "plan not found: {plan}",
                "solution": "Call plan_list and retry with a valid plan.",
            },
            "STEP_NOT_FOUND": {
                "description": "The step_id does not resolve in the plan.",
                "message": "step not found: {step_id}",
                "solution": "Call step_tree to discover valid step ids.",
            },
            "AMBIGUOUS_STEP_ID": {
                "description": "A bare local step_id such as T-001 or A-001 resolves to more than one step.",
                "message": "step_id {step_id} resolves to multiple steps",
                "solution": "Retry with the canonical step path from step_tree or with the step UUID.",
            },
        },
        "best_practices": [
            "Use stable activation_id and attempt_id values from the producer so retries are safe.",
            "Send journal_aggregates as full aggregate values, not deltas.",
            "Do not use runtime values to infer status changes automatically.",
        ],
    }
