"""Structure-integrity reference data for the info command (CR-4, C-001, C-005).

Describes, for an executing agent, the CR-4 structure-integrity deliverable
group: the context-block admission guard on step creation, the context-block
currency model, the additive context-coverage gate check group, the audited
subtree-unfreeze behavior, the frozen-subtree membership invariant, and the
recursive subtree-delete extension of step_delete. Consumed by
plan_manager.commands.info_command for both the capabilities section and the
agent_reference section.
"""

from __future__ import annotations

from typing import Any


def structure_integrity_capabilities() -> dict[str, Any]:
    """The capabilities-section descriptor for the CR-4 structure-integrity group."""
    return {
        "summary": "Four mechanisms harden plan-store structural integrity, each strictly additive to the CR-1..CR-3 command surface: an admission guard that refuses contextless child-step creation, a retrospective gate check group that catches trees mutated around the guard, an audited form of subtree unfreeze with a frozen-subtree membership invariant, and a recursive extension of step deletion that removes a whole subtree atomically.",
        "deliverables": {
            "context_block_admission_guard": {
                "commands": ["step_create"],
                "mutates": True,
                "summary": "step_create and every bulk child-creation path refuse to create a child step under a global-step or tactical-step parent that lacks a CURRENT compiled context_common block for the child's level. A block compiled against a superseded revision counts as absent. The refusal is the stable domain error CONTEXT_BLOCKS_MISSING, whose message and solution name the context_common command, the exact parent node path, and the required child level. The guard applies only to global-step and tactical-step parents; the plan-to-global-step boundary stays governed by authoring prompts.",
            },
            "context_block_currency": {
                "commands": ["block_list", "block_get"],
                "mutates": False,
                "summary": "block_list marks which block is the live one for a node and child level. block_get states whether the returned block is current or stale for the plan's working state. An edit to the HRS, the MRS, or a parent step marks affected descendant blocks stale within the same transaction that records the edit, so no window exists in which a stale block still presents as current.",
            },
            "context_coverage_gate_check": {
                "commands": None,
                "mutates": False,
                "summary": "Not a standalone command: an additive mechanical-gate check group, reached through plan_validate, asserting that every global-step or tactical-step parent with children holds a current common context block for its children's level, and that every child's specific context delta has scope concepts that are a subset of the parent common block's scope. All pre-existing gate check groups and their identifiers are unchanged.",
            },
            "subtree_unfreeze_audit": {
                "commands": ["step_transition", "audit_list"],
                "mutates": True,
                "summary": "Whenever frozen steps are reopened to draft through a scoped step_transition, an immutable audit record is written naming the actor, the stated reason, the unfrozen scope, and the head revision at the moment of unfreeze, equivalent to the whole-plan plan_unfreeze audit. The record is readable through the shipped audit_list command; no new audit-write command is added.",
            },
            "frozen_subtree_membership_invariant": {
                "commands": ["step_create", "step_move", "step_delete"],
                "mutates": True,
                "summary": "While an ancestor step is frozen, creating a new descendant beneath it, moving a step into or out of it, and deleting any step within it are admitted only under an open cascade. Every mutation path is checked against this invariant, with refusals expressed in the established mutation-admission vocabulary (CASCADE_REQUIRED / FROZEN_ARTIFACT).",
            },
            "recursive_subtree_delete": {
                "commands": ["step_delete"],
                "mutates": True,
                "summary": "The recursive form is a parameter of the existing step_delete operation, not a separate command. Its default, non-recursive invocation keeps the refuse-when-children behavior. Under a dry run the recursive form previews the entire doomed subtree -- every step that would be deleted plus the full invalidation impact set. Under a real run it deletes the whole subtree as one version-store revision, recording a tombstone snapshot for every deleted step, and obeys the same mutation-admission regime as ordinary deletion.",
            },
        },
    }


def structure_integrity_agent_reference() -> dict[str, Any]:
    """The agent_reference-section table for the CR-4 structure-integrity group."""
    return {
        "purpose": "Closes three structural-integrity gaps surfaced by the CR-2 and CR-3 authoring sessions: contextless child-step creation was previously caught only by manual orchestrator audit, subtree unfreeze lacked the audit trail the whole-plan escape already had, and subtree deletion had no atomic recursive form. All four mechanisms are strictly additive to the CR-1..CR-3 surface.",
        "admission_guard": "step_create (and every bulk child-creation path) refuses a child step under a global-step or tactical-step parent when that parent has no CURRENT context_common block for the child's level. Staleness counts as absence: a block compiled against a superseded revision does not satisfy the guard. The refusal is documented in step_create's metadata error_cases under the stable code CONTEXT_BLOCKS_MISSING.",
        "compile_order_rule": "Context blocks for a level are compiled LAST, after the layer above is settled -- an existence-only currency check would otherwise pass a block that went stale one parent edit later. This ordering rule governs both context_common and context_specific authoring at every level.",
        "gate_check_group": "Reached only through plan_validate / cascade_commit's mechanical gate, not through a standalone command: the additive check group flags a global-step or tactical-step parent with children but no current common block for the child level, and flags a child specific delta whose scope concepts are not a subset of the parent common block's scope. All pre-existing gate check groups and their identifiers are unchanged; this group is additive.",
        "subtree_freeze_semantics": "Scoped step_transition already provides draft-to-frozen and frozen-to-draft for G-NNN and G-NNN/T-NNN scopes with a scoped green-gate requirement. CR-4 adds: an immutable audit record (actor, reason, unfrozen scope, head revision) written for every scoped frozen-to-draft transition, readable through audit_list; and the frozen-subtree membership invariant, under which creating, moving, or deleting a step inside a frozen subtree is admitted only under an open cascade.",
        "recursive_delete": "Realized as a parameter of step_delete, not a dedicated command. The non-recursive call keeps the existing refuse-when-children behavior. The recursive call's dry run previews the complete doomed subtree plus the invalidation impact set; its real run deletes the whole subtree as one version-store revision with a tombstone snapshot recorded per deleted step, under the same admission regime as ordinary deletion.",
        "write_surfaces": "No new command is added by this group: the admission guard and membership invariant are integrated into step_create, step_move, and step_delete; the audit obligation is integrated into step_transition and read back through the existing audit_list; the recursive extension is a step_delete parameter; and the gate check group is reached only through the existing plan_validate/cascade_commit path.",
    }
