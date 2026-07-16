# CR-1 Registry Hygiene Purge Procedure

## Purpose

This document is the operational procedure for RegistryHygiene (MRS concept C-015): purging the acceptance-testing litter accumulated in the plan-manager roadmap registry during CR-1 live testing, using the deletion commands shipped by CrudDeletionIntegrity (C-008) as their first real use. This procedure does not implement deletion commands; it invokes them once they exist.

## Precondition

This procedure depends on CrudDeletionIntegrity (C-008), implemented in the sibling global step G-004 of this plan. Before running this procedure, confirm the following deletion commands are live on the planmgr service: a TODO-item deletion command, a runtime-comment deletion command, and the existing `plan_delete` command (already live) covering plan-level soft/hard deletion. If any of the TODO or comment deletion commands is not yet present on the service, this procedure halts and escalates rather than approximating deletion through any other means. Bug reports are excluded from this precondition by design: CrudDeletionIntegrity's CRUD-posture reference documents bug_report's delete column as intentionally absent (`terminal_status_replacement` — a rejected, closed, or duplicate bug report is retained as an audit record, not deleted), so no bug-report deletion command exists or is expected; bug-report litter is purged by confirming terminal status, not by deletion.

## Litter Enumerated (C-015)

The following registry litter, accumulated during CR-1 acceptance testing, is purged by this procedure:

1. The superseded TODO work item with identifier `e00de017` (full UUID resolved via `todo_list`/`todo_get` at execution time).
2. The two rejected bug reports left over from post-cutover deploy smokes, purged by confirming their terminal status rather than by deletion (no bug-report deletion command exists in this CR's surface; see Precondition):
   - `b1c04465-cb3e-45f6-92bd-d333260164a6` ("deploy smoke bug 0.1.26")
   - `b2d55e80-c09a-474e-ade4-ac39318a2ece` ("deploy smoke bug 0.1.27")
3. The residual runtime comments left attached to throwaway anchors by load-test activity (discovered via `comment_list` filtered to the throwaway anchor plans/steps named below).
4. The runtime overlays (TODO items, runtime comments, bug reports, and any other runtime entities anchored to them) carried by the soft-deleted throwaway plans whose names match these patterns:
   - `load-test-0125-*`
   - `diag-96329ae5-*`
   - `throwaway-smoke-*`

## Deletion-Integrity Rule Applied

Every deletion performed by this procedure follows the universal deletion-integrity rule of CrudDeletionIntegrity (C-008):

- An object cannot be deleted while inbound references exist. A deletion attempt against a referenced object is refused, and the refusal lists the referencing records (UUIDs and kinds).
- When a refusal occurs, the referencing records (referrers) are themselves detached/deleted first, then the original deletion is retried.
- Deletion defaults to soft (recoverable, hidden from default listings). A hard (irreversible) deletion is only performed after a dry-run preview confirms the impact set is the expected one.

This rule governs the TODO, runtime-comment, and plan-overlay deletions performed by this procedure; bug-report litter is handled separately per the Precondition section, since no bug-report deletion command exists in this CR's surface.

## Purge Procedure

Execute the following steps in order. Each step records its outcome (deleted, already_deleted, refused-then-retried, or, for bug reports, confirmed_terminal_not_deleted) in the purge_execution_record output.

### Step 1: Purge the superseded TODO

1. Resolve the full UUID of TODO `e00de017` via `todo_list` (search active and inactive items; the short identifier is a UUID prefix).
2. Invoke the TODO deletion command (soft, default mode) against the resolved UUID.
3. If refused for inbound references, list the referencing records from the refusal, delete/detach each referrer via its own deletion/detach command, then retry the TODO deletion.
4. Record the outcome.

### Step 2: Confirm the rejected bug reports as retained litter

1. Confirm both bug reports are in terminal status `rejected` via `bug_get` (uuids `b1c04465-cb3e-45f6-92bd-d333260164a6` and `b2d55e80-c09a-474e-ade4-ac39318a2ece`).
2. No bug-report deletion command exists in this CR's surface (CrudDeletionIntegrity documents bug_report's delete posture as intentionally absent, `terminal_status_replacement`); do not attempt to delete these records. Confirm each is excluded from a `bug_list` call with `active_only=true`, which is how a terminal bug report is kept out of active registry views.
3. Record the outcome for each bug report as `confirmed_terminal_not_deleted`, noting the CRUD-posture reason.

### Step 3: Purge residual load-test comments

1. Call `comment_list` filtered to the throwaway anchor plans/steps used by load-test activity to enumerate the residual comments.
2. Invoke the runtime-comment deletion command (soft, default mode) against each enumerated comment UUID.
3. If refused for inbound references, delete/detach each referrer first, then retry.
4. Record the outcome for each comment.

### Step 4: Purge runtime overlays of soft-deleted throwaway plans

1. Call `plan_list` with `show_deleted=true` and select every plan whose name matches `load-test-0125-*`, `diag-96329ae5-*`, or `throwaway-smoke-*`.
2. For each matched plan, enumerate its runtime overlay: TODO items via `todo_list` with `anchor_plan`, and runtime comments via `comment_list` with `anchor_plan`. Delete each enumerated TODO item and runtime comment via its deletion command (soft, default mode), applying the referrer-first rule on any refusal.
3. Separately enumerate bug reports anchored to the plan via `bug_list` with `anchor_plan`. No bug-report deletion command exists in this CR's surface (see Step 2); leave these bug reports in place and record their identifiers and statuses as retained litter, not purged by deletion.
4. After the TODO and comment portions of a matched plan's runtime overlay are empty, hard-delete the plan itself with `plan_delete` (`hard=true`) only if the plan is intended for permanent removal; otherwise leave the plan soft-deleted with its overlay purged of TODOs and comments and its bug reports retained.
5. Record the outcome for each matched plan and its overlay entities.

## Verification

After the purge procedure completes, perform the following verification pass and record its result as `registry_clean_verification`:

1. Call `todo_get` (or `todo_list`) for the TODO `e00de017`: it must no longer resolve (soft-deleted TODOs are indistinguishable from nonexistent ones on `todo_get`).
2. Call `bug_get` for `b1c04465-cb3e-45f6-92bd-d333260164a6` and `b2d55e80-c09a-474e-ade4-ac39318a2ece`: both must still resolve (they are retained, not deleted) with status `rejected`, and neither must appear in a `bug_list` call with `active_only=true`.
3. Call `comment_list` against the throwaway anchors used in Step 3: the result must contain none of the purged comment UUIDs.
4. Call `plan_list` (default, `show_deleted` omitted or false): none of the plans matching `load-test-0125-*`, `diag-96329ae5-*`, or `throwaway-smoke-*` may appear.
5. If any check in steps 1-4 finds residual litter, the verification fails and the procedure escalates rather than being marked complete.
