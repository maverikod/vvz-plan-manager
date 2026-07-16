"""Consolidated Create/Read/Update/Delete posture reference for runtime entities (C-008)."""

from __future__ import annotations

from typing import Any


def crud_deletion_posture_reference() -> dict[str, Any]:
    """Return the consolidated CRUD posture reference for every documented runtime entity."""
    return {
        "purpose": (
            "Consolidated Create/Read/Update/Delete posture reference (C-008) "
            "for the twelve documented runtime entities: for each entity, "
            "which command creates it, which command(s) read it, which "
            "command(s) update it, and whether a delete command exists — and "
            "when delete is absent, why the absence is intentional (see "
            "deletion_absence_reasons)."
        ),
        "deletion_absence_reasons": {
            "terminal_status_replacement": (
                "The entity carries a mutable status field that reaches a "
                "terminal value (e.g. closed, verified, resolved, cancelled, "
                "skipped, done) instead of being deleted; the terminal status "
                "itself records the outcome and preserves history rather than "
                "removing the row."
            ),
            "supersede_immutability": (
                "The entity is an immutable audit-trail record of a fact that "
                "occurred; instead of being deleted or corrected in place, a "
                "superseding record is filed, or (for link-shaped entities) "
                "the record is removed and a corrected one is added, so the "
                "history of what was recorded is never destroyed."
            ),
        },
        "entities": {
            "execution_attempt": {
                "create": "execution_attempt_create",
                "read": "execution_attempt_get, execution_attempt_list",
                "update": "execution_attempt_report",
                "delete": {
                    "absent": True,
                    "reason": "terminal_status_replacement",
                    "detail": (
                        "is_terminal_status(status) is true only for succeeded, "
                        "failed, cancelled, or timed_out; execution_attempt_report "
                        "moves an attempt to one of these terminal statuses "
                        "instead of the attempt being deleted."
                    ),
                },
            },
            "review_result": {
                "create": "review_result_create",
                "read": "review_result_get, review_result_list",
                "update": "none",
                "delete": {
                    "absent": True,
                    "reason": "supersede_immutability",
                    "detail": (
                        "A ReviewResult is an immutable audit record of one "
                        "reviewer's verdict on an execution attempt or "
                        "revision; it carries no update command either — it "
                        "is filed once and never mutated or deleted."
                    ),
                },
            },
            "escalation": {
                "create": "escalation_create",
                "read": (
                    "no dedicated get/list command; escalations are read via "
                    "the runtime overlay export (export_runtime_overlay, "
                    "C-034, 'escalations' section)"
                ),
                "update": "escalation_resolve",
                "delete": {
                    "absent": True,
                    "reason": "terminal_status_replacement",
                    "detail": (
                        "escalation_statuses are open and resolved; "
                        "escalation_resolve transitions an open escalation to "
                        "the terminal resolved status instead of deleting it."
                    ),
                },
            },
            "model_binding": {
                "create": "model_binding_set",
                "read": "model_binding_get, model_binding_list, model_binding_resolve",
                "update": "model_binding_set",
                "delete": "model_binding_remove (soft-remove/deactivate)",
            },
            "bug_report": {
                "create": "bug_create",
                "read": "bug_get, bug_list",
                "update": (
                    "bug_update, bug_confirm, bug_reject, bug_mark_duplicate, "
                    "bug_reopen, bug_close"
                ),
                "delete": {
                    "absent": True,
                    "reason": "terminal_status_replacement",
                    "detail": (
                        "bug_close transitions a bug to the terminal closed "
                        "status (refused unless BugClosureDiscipline is "
                        "satisfied); bug_reopen preserves prior fix/impact/"
                        "propagation history rather than deleting it."
                    ),
                },
            },
            "bug_impact": {
                "create": "bug_impact_add, bug_impact_discover",
                "read": "bug_impact_list",
                "update": "bug_impact_update",
                "delete": {
                    "absent": True,
                    "reason": "terminal_status_replacement",
                    "detail": (
                        "bug_impact_statuses include the cleared terminal "
                        "values unaffected, resolved, verified, and skipped; "
                        "bug_impact_update moves an impact to one of these "
                        "instead of deleting the record."
                    ),
                },
            },
            "bug_fix": {
                "create": "bug_fix_create",
                "read": "bug_fix_list",
                "update": "bug_fix_update, bug_fix_verify",
                "delete": {
                    "absent": True,
                    "reason": "terminal_status_replacement",
                    "detail": (
                        "bug_fix_statuses include the terminal values "
                        "verified, reverted, and rejected; a failed or "
                        "superseded fix attempt is transitioned to one of "
                        "these instead of being deleted."
                    ),
                },
            },
            "bug_fix_propagation": {
                "create": "bug_propagation_create, bug_propagation_generate_todos",
                "read": "bug_propagation_list",
                "update": "bug_propagation_update",
                "delete": {
                    "absent": True,
                    "reason": "terminal_status_replacement",
                    "detail": (
                        "propagation_statuses include the terminal values "
                        "done, verified, and skipped; bug_propagation_update "
                        "moves a propagation to one of these instead of "
                        "deleting the record."
                    ),
                },
            },
            "project_dependency": {
                "create": "project_dependency_add, project_dependency_discover",
                "read": "project_dependency_list, project_dependents",
                "update": (
                    "none (no project_dependency_update command; a "
                    "dependency edge's type or confidence is corrected by "
                    "removing and re-adding the edge, not by in-place update)"
                ),
                "delete": "project_dependency_remove (soft-delete)",
            },
            "cascade_request": {
                "create": (
                    "todo_promote_to_cascade_request (the sole command that "
                    "creates a cascade_request)"
                ),
                "read": (
                    "no dedicated get/list command; cascade_requests are read "
                    "via the runtime overlay export (export_runtime_overlay, "
                    "C-034, 'cascade_requests' section, filtered by plan_uuid)"
                ),
                "update": "none",
                "delete": {
                    "absent": True,
                    "reason": "supersede_immutability",
                    "detail": (
                        "A cascade_request is a supersede-immutable "
                        "audit-trail record of a raised need; its status is "
                        "not advanced by any exposed command, and the actual "
                        "normative change is carried out through the "
                        "ordinary cascade discipline (cascade_begin, "
                        "cascade_preview, cascade_commit, cascade_abort) "
                        "against the target HRS/MRS/GS/TS/AS artifact, not "
                        "by mutating or deleting this record."
                    ),
                },
            },
            "todo_link": {
                "create": "todo_link_add",
                "read": (
                    "no dedicated get/list command; todo_links are read via "
                    "the runtime overlay export (export_runtime_overlay, "
                    "C-034, 'todo_links' section)"
                ),
                "update": (
                    "none (a link is corrected by removing it and adding a "
                    "new one, not by in-place update)"
                ),
                "delete": "todo_link_remove (soft-delete)",
            },
            "runtime_link": {
                "create": "runtime_link_add",
                "read": "runtime_link_list",
                "update": (
                    "none (a runtime_link is updated by removing it and "
                    "adding a new one, not by in-place update)"
                ),
                "delete": "runtime_link_remove (soft; dry_run preview)",
            },
        },
    }
