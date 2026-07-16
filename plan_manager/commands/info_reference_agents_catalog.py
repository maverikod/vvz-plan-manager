"""Operational checklists, catalog tables, and the command category index for
the info agent reference.

Split out of info_reference_agents.py for file-size discipline (CR-1 C-014).
"""

from __future__ import annotations

from typing import Any

from plan_manager.commands.info_reference_agents_status import _vals
from plan_manager.commands.inventory import INVENTORY, MUTATING
from plan_manager.commands.runtime_filtering import DEFAULT_LIMIT, MAX_LIMIT
from plan_manager.domain.bug_impact import BugImpactTargetType
from plan_manager.domain.bug_source import BugSourceType
from plan_manager.domain.comment_visibility import (
    VISIBILITY_CONTEXT_MAP,
    CommentVisibility,
    PromptContextKind,
)
from plan_manager.domain.primary_anchor import PrimaryAnchorType
from plan_manager.domain.runtime_comment import CommentAnchorType


def operational_checklists() -> dict[str, Any]:
    """Per-stage 'what to set at each stage' checklists for the multi-step lifecycles."""
    return {
        "bug_fix_lifecycle": {
            "intended_flow": [
                "bug_create (status reported) -> bug_confirm once triage confirms a real defect (status confirmed).",
                "Assign the fix owner with bug_update(owner=...). NOTE: no command sets bug.status to fixing; use owner + the bug_fix record for progress.",
                "bug_fix_create(status=in_progress|implemented) to open the source fix; implemented stamps implemented_at.",
                "bug_impact_add for each affected downstream target (or bug_impact_discover to auto-suggest from the project dependency graph).",
                "bug_fix_verify(passed=true) to certify the source fix (sets verified_at); the fix status must reach verified for closure.",
                "For each impact, bug_propagation_create the required downstream action, drive it to done/verified/skipped (bug_propagation_update), and optionally bug_propagation_generate_todos to surface the work on the queue.",
                "bug_close once BugClosureDiscipline is satisfied: source fix verified, every impact cleared (unaffected/verified) or ownerly skipped, every propagation finished, mandatory TODOs closed, required cascades finished.",
            ],
            "honesty_note": "bug.status does not auto-advance through fixing/fixed_source/propagating/verified; those values are not written by any command. Treat the bug_fix/bug_impact/bug_propagation records — not bug.status — as the source of truth for fix progress until bug_close.",
        },
        "todo_lifecycle": [
            "todo_create with an initial status (open by default; ready/in_progress/blocked are settable here but cannot be changed later).",
            "todo_update to adjust title/description/priority_nice/assigned_to/blocking_reason/execution_result (status is NOT updatable here).",
            "todo_resolve (-> resolved) or todo_close (-> closed) to terminate; both are unconditional. todo_close accepts execution_result to persist the outcome in the same action. todo_delete removes an item (soft by default; hard=true irreversible; both gated by the inbound-reference integrity check with dry_run preview).",
            "todo_promote_to_cascade_request to escalate a TODO into a normative cascade request (does not itself open/commit the cascade).",
        ],
        "propagation_lifecycle": [
            "bug_propagation_create(action, status=pending|ready) for one impact.",
            "bug_propagation_update to advance status; in_progress stamps started_at, a finished status stamps finished_at.",
            "Drive to a finished status (done, verified, skipped) — required for the parent bug's closure.",
        ],
        "cascade_workflow": [
            "cascade_begin on a plan that is not fully frozen (a fully frozen plan raises FROZEN_TRUTH_WRITE).",
            "For a FULLY frozen plan, call plan_unfreeze(plan, changed_by, reason) instead: it audits the escape and opens the cascade, then transition steps back with a scoped step_transition to_status=draft under the returned cascade_uuid.",
            "Make admitted mutations under the returned cascade_uuid.",
            "cascade_preview to inspect the gate/impact before committing.",
            "cascade_commit (requires a green gate; otherwise GATE_RED and the cascade stays open) or cascade_abort (unconditional; restores base state). Both are terminal.",
        ],
    }


def anchor_type_tables() -> dict[str, Any]:
    """The anchor-type vocabularies each anchored entity accepts."""
    return {
        "primary_anchor_types": {
            "purpose": "PrimaryAnchor kinds usable as a TODO/bug/general primary anchor; 'none' means unanchored.",
            "values": _vals(PrimaryAnchorType),
        },
        "comment_anchor_types": {
            "purpose": "RuntimeComment anchor kinds; a comment always attaches to a subject, so 'none' is NOT valid here.",
            "values": _vals(CommentAnchorType),
        },
        "bug_source_types": {
            "purpose": "The single primary source anchor kind of a BugReport (bug_create source_type).",
            "values": _vals(BugSourceType),
        },
        "bug_impact_target_types": {
            "purpose": "The target kind of a BugImpact record (bug_impact_add target_type).",
            "values": _vals(BugImpactTargetType),
        },
    }


def visibility_modes_reference() -> dict[str, Any]:
    """Runtime comment visibility modes and the prompt contexts each reaches."""
    return {
        "purpose": (
            "A RuntimeComment's visibility mode governs which prompt contexts it "
            "may enter. may_reach_context(visibility, context_kind) is the single "
            "predicate; audit_only reaches nothing, public_summary reaches all."
        ),
        "visibility_modes": _vals(CommentVisibility),
        "prompt_context_kinds": _vals(PromptContextKind),
        "reaches": {
            visibility.value: sorted(VISIBILITY_CONTEXT_MAP[visibility.value])
            for visibility in CommentVisibility
        },
    }


def queue_polling_guide() -> dict[str, Any]:
    """How to poll queue-bound commands (correct for mcp-proxy-adapter >=8.10.20)."""
    queued = sorted(name for name in INVENTORY if name in _QUEUED_COMMANDS)
    return {
        "purpose": (
            "Some commands run on the queuemgr job queue (use_queue=True) and "
            "return an enqueue acknowledgement instead of an inline result. This "
            "guide names the correct poll command and the two-store pitfall."
        ),
        "adapter_floor": ">=8.10.20",
        "queued_commands": queued,
        "enqueue_acknowledgement": {
            "job_id": "The queuemgr job id to poll.",
            "store": "queuemgr",
            "poll_with": "queue_get_job_status",
        },
        "poll_command": "queue_get_job_status",
        "poll_response_fields": [
            "job_id", "status", "progress", "description", "result", "error",
            "created_at", "started_at", "completed_at",
        ],
        "two_store_warning": (
            "Do NOT poll with the builtin job_status: it reads a separate "
            "in-memory JobManager store, not the queuemgr store. For a queuemgr "
            "job it returns {exists: false, store: 'job_manager', poll_with: "
            "'queue_get_job_status'}. Follow the poll_with field: use "
            "queue_get_job_status."
        ),
        "unknown_param_note": (
            "The two command surfaces behave differently for a misspelled "
            "parameter — do not assume either behavior of the other. "
            "plan_manager's OWN commands set additionalProperties: false in "
            "their schema, so a misspelled parameter is rejected before "
            "execute() runs: ErrorResult code -32602, message 'Invalid "
            "parameters: <name>. Allowed parameters: [...]'. The adapter's "
            "BUILTIN commands (verified for help) set additionalProperties: "
            "true and accept **kwargs they don't recognize, so a misspelled "
            "parameter (e.g. command= instead of cmdname=) is silently "
            "ignored — help falls back to its no-cmdname behavior and "
            "returns the full command catalog instead of erroring. This is "
            "the adapter behavior behind bug c4281feb (confirmed live "
            "against adapter 8.10.20). Do not rely on an error to catch a "
            "typo when calling an adapter builtin."
        ),
    }


def pagination_convention_reference() -> dict[str, Any]:
    """The uniform C-001 pagination contract shared by every list-bearing command.

    Shipped wave-1 G-001 feature restored per L1 ruling 2026-07-16; the content
    states exactly the contract encoded in
    plan_manager/commands/runtime_filtering.py (parse_pagination,
    pagination_schema_properties) and enforced by
    tests/test_uniform_pagination_contract.py.
    """
    return {
        "purpose": (
            "Every list-bearing / large-output command on the surface accepts the "
            "identical optional offset/limit pair and returns the identical page "
            "envelope, so agents paginate one way everywhere instead of learning "
            "per-command conventions."
        ),
        "parameters": {
            "limit": (
                f"Maximum number of results to return (default {DEFAULT_LIMIT}, "
                f"max {MAX_LIMIT}). A provided value must be an integer in the "
                f"closed range [1, {MAX_LIMIT}]."
            ),
            "offset": (
                "Number of results to skip before returning results (default 0). "
                "A provided value must be an integer >= 0."
            ),
        },
        "envelope": {
            "page_list": (
                "Each list command returns its page under an entity-named key "
                "(for example 'todos', 'plans', 'escalations')."
            ),
            "total": (
                "The full match count before pagination is applied — compare "
                "offset+limit against total to detect additional pages."
            ),
            "limit": "The applied (validated or defaulted) limit.",
            "offset": "The applied (validated or defaulted) offset.",
        },
        "rejection": (
            "Two layers can reject an out-of-range or non-integer limit/offset, "
            "and callers normally only observe the outer one. Layer 1 "
            "(transport/schema): every command's declared JSON-Schema bounds "
            f"limit to [1, {MAX_LIMIT}] and offset to >= 0 "
            "(pagination_schema_properties()); the MCP adapter validates "
            "JSON-RPC parameters against that schema before the call ever "
            "reaches plan_manager code, and rejects a violation with the "
            "generic JSON-RPC error -32602 (Invalid params) — this is what an "
            "MCP caller normally observes for an out-of-range integer. Layer 2 "
            "(domain): parse_pagination's INVALID_PAGINATION domain code "
            "(plan_manager.commands.runtime_filtering) re-validates the "
            "identical bounds and is defense-in-depth — it is what fires for "
            "any call path that bypasses schema validation (a library-level "
            "call, a test, or a command whose schema omits the bounds), not "
            "for a normal MCP call against a schema-bound command."
        ),
        "uniformity_guard": (
            "Every command enumerated in tests/test_uniform_pagination_contract.py's "
            "_RETROFITTED_COMMANDS list has its schema limit/offset properties "
            "checked byte-for-byte against the shared pagination_schema_properties() "
            "fragment, and its metadata() checked to mention limit, offset, and "
            "total somewhere in the published blob. tests/test_pagination_contract.py "
            "separately enforces the same schema/metadata fragment identity, "
            "dynamically, for every command in INVENTORY whose name ends in "
            "'_list'. tests/test_pagination_envelope_uniformity.py separately "
            "asserts the actual runtime response envelope keys "
            "{<entity>, total, limit, offset} for step_list, step_search, "
            "files_report, and step_xref via each command's execute() path. "
            "No single test enumerates every list-bearing command in one "
            "place; this reference is the closest thing to that index."
        ),
    }


def crud_matrix() -> dict[str, Any]:
    """Create/Read/Update/Delete reality per entity, including documented immutability."""
    return {
        "purpose": (
            "The actual create/read/update/delete surface per entity. Several "
            "entities are immutable-by-design or lack a delete/update command; "
            "this states each explicitly so callers do not assume a missing verb."
        ),
        "entities": {
            "plan": {"create": "plan_create", "read": "plan_list/plan_status", "update": "none (plan.status is fixed at 'draft'; the frozen state is derived from step statuses; plan_unfreeze reopens a fully-frozen plan by opening an audited cascade, not by mutating plan.status)", "delete": "plan_delete (soft, hidden-but-preserved; or hard, irreversible cascade)"},
            "step": {"create": "step_create", "read": "step_get/step_tree", "update": "step_update/step_move; status via step_set_status/step_transition", "delete": "step_delete (also purges the step's step_runtime row via ON DELETE CASCADE)"},
            "concept": {"create": "concept_add", "read": "concept_get/concept_list", "update": "concept_update (concept_id is immutable; no rename)", "delete": "concept_remove (does not clean up relations referencing it; dangling relation endpoints are possible)"},
            "relation": {"create": "relation_add", "read": "relation_list", "update": "relation_update (changes a relation's type; endpoints remain fixed — remove + add to change an endpoint)", "delete": "relation_remove"},
            "paragraph": {"create": "via hrs_import", "read": "para_list/para_get", "update": "para_label_assign/para_mark_non_binding (direction=wrap marks a paragraph non-binding; direction=unwrap restores it — a reversible round-trip)", "delete": "none exposed; wrap keeps the row but hides it from para_list, and unwrap restores it"},
            "todo": {"create": "todo_create", "read": "todo_get/todo_list", "update": "todo_update (not status); todo_resolve/todo_close for terminal status; todo_close(execution_result=...) persists the outcome while closing in one action", "delete": "todo_delete (soft by default: recoverable, hidden from listings; hard=true irreversible and cascade-removes the item's todo_link rows; both modes gated by the inbound-reference integrity check - live anchored comments, execution attempts, escalations, or bug-fix propagations refuse with DELETE_BLOCKED; dry_run previews references)"},
            "todo_link": {"create": "todo_link_add", "read": "via todo_get", "update": "none", "delete": "todo_link_remove (soft, idempotent)"},
            "comment": {"create": "comment_add", "read": "comment_get/comment_list", "update": "none (comments are immutable; comment_supersede appends a new record; comment_resolve toggles resolved)", "delete": "comment_delete (soft by default: recoverable, hidden from listings; hard=true irreversible; both modes gated by the inbound-reference integrity check - a live superseding comment refuses with DELETE_BLOCKED; dry_run previews references)"},
            "model_binding": {"create": "model_binding_set (create-only; not an upsert)", "read": "model_binding_get/model_binding_list/model_binding_resolve", "update": "model_binding_update (patches an existing binding's fields in place)", "delete": "model_binding_remove (soft)"},
            "execution_attempt": {"create": "execution_attempt_create", "read": "execution_attempt_get/execution_attempt_list", "update": "execution_attempt_report (append/patch outcome fields)", "delete": "none (append-only history)"},
            "review_result": {"create": "review_result_create", "read": "review_result_get/review_result_list", "update": "none (immutable verdict)", "delete": "none"},
            "escalation": {"create": "escalation_create", "read": "escalation_get/escalation_list", "update": "escalation_resolve (open->resolved)", "delete": "none"},
            "bug": {"create": "bug_create", "read": "bug_get/bug_list", "update": "bug_update (non-lifecycle fields); status via bug_confirm/bug_reject/bug_mark_duplicate/bug_reopen/bug_close", "delete": "none (reject/mark_duplicate/reopen preserve history)"},
            "bug_impact": {"create": "bug_impact_add/bug_impact_discover", "read": "bug_impact_list", "update": "bug_impact_update", "delete": "none"},
            "bug_fix": {"create": "bug_fix_create", "read": "bug_fix_list", "update": "bug_fix_update/bug_fix_verify", "delete": "none"},
            "bug_fix_propagation": {"create": "bug_propagation_create", "read": "bug_propagation_list", "update": "bug_propagation_update", "delete": "none"},
            "project_dependency": {"create": "project_dependency_add/project_dependency_discover", "read": "project_dependency_list/project_dependents", "update": "project_dependency_update/project_dependency_confirm (confirm raises a discovered edge's confidence to confirmed)", "delete": "project_dependency_remove (soft)"},
            "cascade_request": {"create": "todo_promote_to_cascade_request (the sole command that creates a cascade_request)", "read": "none exposed; read via export_runtime_overlay (C-034, 'cascade_requests' section, filtered by plan_uuid)", "update": "none", "delete": "none (supersede-immutable audit-trail record; the normative change it requests is carried out through the ordinary cascade discipline against the target HRS/MRS/GS/TS/AS artifact, not by mutating or deleting this record)"},
        },
    }


# Category index of the whole command surface. Every INVENTORY command appears
# in exactly one bucket; test_command_index_covers_inventory_exactly guards this.
_COMMAND_CATEGORIES: dict[str, list[str]] = {
    "plan_core": [
        "plan_create", "plan_list", "plan_status", "plan_delete",
        "plan_export", "plan_snapshot", "plan_import", "plan_validate", "plan_score",
    ],
    "project_binding": [
        "plan_project_attach", "plan_project_detach", "plan_project_list",
        "plan_project_set_primary", "plan_project_clear_primary",
    ],
    "transfer": ["export_upload_save", "export_read", "export_archive", "hrs_import", "hrs_export", "export_cleanup"],
    "paragraph": ["para_list", "para_get", "para_label_assign", "para_mark_non_binding"],
    "concept_relation": [
        "concept_get", "concept_list", "concept_add", "concept_update", "concept_remove",
        "relation_list", "relation_add", "relation_remove", "relation_update", "concept_coverage",
    ],
    "step": [
        "step_get", "step_tree", "step_create", "step_update", "step_move",
        "step_delete", "step_set_status", "step_transition",
        "step_runtime_get", "step_runtime_report", "step_runtime_list",
    ],
    "step_report": ["step_list", "step_search", "files_report", "step_xref"],
    "graph": ["graph_deps", "graph_order", "graph_parallel_map", "graph_impact", "graph_dependents"],
    "step_dependency": [
        "step_dependency_list", "step_dependency_add", "step_dependency_remove",
        "step_dependency_set", "step_dependency_clear", "step_dependency_preview",
        "step_dependency_apply",
    ],
    "context_prompt": [
        "branch_prompt", "plan_prompt_chain", "context_compile", "context_common",
        "context_specific", "context_bundle", "block_get", "block_list",
        "branch_dump", "branch_weak",
    ],
    "cascade": ["cascade_begin", "cascade_preview", "cascade_commit", "cascade_abort", "plan_unfreeze"],
    "srt": ["srt_snapshot_create", "srt_snapshot_list", "srt_diff"],
    "system": ["info", "command_catalog_dump"],
    "todo": [
        "todo_create", "todo_get", "todo_list", "todo_update", "todo_reanchor",
        "todo_resolve", "todo_close", "todo_delete", "todo_link_add", "todo_link_remove",
        "todo_queue", "todo_promote_to_cascade_request",
    ],
    "runtime_link": [
        "runtime_link_add", "runtime_link_list", "runtime_link_remove",
    ],
    "comment": ["comment_add", "comment_get", "comment_list", "comment_supersede", "comment_resolve", "comment_delete"],
    "model_binding": [
        "model_binding_set", "model_binding_get", "model_binding_list",
        "model_binding_remove", "model_binding_resolve", "model_binding_update",
    ],
    "execution_attempt": [
        "execution_attempt_create", "execution_attempt_report",
        "execution_attempt_get", "execution_attempt_list",
    ],
    "review_escalation": [
        "review_result_create", "review_result_get", "review_result_list",
        "escalation_create", "escalation_resolve", "escalation_get", "escalation_list",
    ],
    "bug": [
        "bug_create", "bug_get", "bug_list", "bug_update", "bug_reanchor", "bug_triage",
        "bug_confirm", "bug_reject", "bug_mark_duplicate", "bug_reopen", "bug_close",
    ],
    "bug_impact": ["bug_impact_add", "bug_impact_update", "bug_impact_list", "bug_impact_discover"],
    "bug_fix": ["bug_fix_create", "bug_fix_update", "bug_fix_list", "bug_fix_verify"],
    "bug_propagation": [
        "bug_propagation_create", "bug_propagation_list",
        "bug_propagation_update", "bug_propagation_generate_todos",
    ],
    "project_dependency": [
        "project_dependency_add", "project_dependency_remove",
        "project_dependency_list", "project_dependency_discover", "project_dependents",
        "project_dependency_update", "project_dependency_confirm",
    ],
}

# The queue-bound commands (use_queue=True); consumed by queue_polling_guide().
_QUEUED_COMMANDS: frozenset[str] = frozenset({
    "plan_export", "plan_snapshot", "plan_import", "hrs_import",
    "plan_prompt_chain", "branch_weak", "plan_validate", "plan_score",
    "srt_snapshot_create",
})


def command_index() -> dict[str, Any]:
    """A category index of the entire command surface, with mutation and queue flags."""
    # The per-entry "queued" flag mirrors _QUEUED_COMMANDS (shipped wave-1 G-001
    # feature restored per L1 ruling 2026-07-16; guarded by
    # tests/test_async_execution_contract.py).
    return {
        "purpose": "Every command grouped by category, with a mutates flag drawn from the normative MUTATING set (authoring-truth mutations) and a queued flag mirroring the queue-bound command set.",
        "total_commands": len(INVENTORY),
        "categories": {
            category: [
                {
                    "name": name,
                    "mutates_plan_truth": name in MUTATING,
                    "queued": name in _QUEUED_COMMANDS,
                }
                for name in names
            ]
            for category, names in _COMMAND_CATEGORIES.items()
        },
    }
