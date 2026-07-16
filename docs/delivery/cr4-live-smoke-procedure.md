# CR-4 Live Smoke Procedure

## Purpose

This is the mandatory post-deployment smoke for CR-4 ("structure integrity"), run after CR-4 ships to production, entirely through the plan-manager MCP proxy transport (server_id `planmgr`), with no other tooling. It proves on a live server that all four structure-integrity mechanisms work against live evidence: the context-block admission guard with its currency model, the context-coverage gate check, the audited subtree unfreeze with its frozen-subtree membership invariant, and the recursive subtree delete.

## Part 1: the context-block admission guard refuses contextless creation and admits creation after context_common

1. On a disposable plan, create a global step with `step_create` (level 3), then attempt `step_create` (level 4) under that global step WITHOUT first calling `context_common` for it. Confirm the call is refused with the stable domain error `CONTEXT_BLOCKS_MISSING`, and that the error message and solution name the `context_common` command, the exact parent node path, and the required child level.
2. Call `context_common` for that global step at child_level 4, then repeat the `step_create` call. Confirm it now succeeds and returns a draft tactical step.
3. Repeat steps 1 and 2 one level down (a tactical-step parent with no context_common block for child_level 5), confirming the same refusal-then-happy-path behavior.

## Part 2: context-block currency is visible and auto-invalidates on an upstream edit

1. Call `block_list` for the global step from Part 1 at child_level 4. Confirm the compiled block is marked as the live one for that node and child level.
2. Call `block_get` on that block's id. Confirm the response states the block is current for the plan's working state.
3. Edit the global step (for example via `step_update` on a non-frozen field) or edit the plan's MRS. Call `block_get` again on the same block id. Confirm the response now states the block is stale, and that a fresh `step_create` attempt under that parent is refused with `CONTEXT_BLOCKS_MISSING` (staleness counts as absence) until `context_common` is called again.

## Part 3: the context-coverage gate check flags a parent with children but no current common block

1. On a disposable plan, construct a tree with a global-step or tactical-step parent that has children but whose common context block is missing or stale (for example by mutating the parent after its block was compiled, as in Part 2).
2. Call `plan_validate` against that plan. Confirm the report contains a finding from the new context-coverage gate check group naming the offending parent node and child level, alongside the plan's other findings, and that a tree whose parent has a current common block and whose children's specific deltas are within scope produces no such finding.

## Part 4: the audited subtree unfreeze records actor, reason, scope, and head revision, and the frozen-subtree membership invariant refuses unadmitted mutation

1. Freeze a scoped subtree (a G-NNN or G-NNN/T-NNN scope) via `step_transition`. Attempt `step_create`, `step_move`, and `step_delete` against a step inside that frozen scope without an open cascade. Confirm each is refused in the established mutation-admission vocabulary (`CASCADE_REQUIRED` or `FROZEN_ARTIFACT`).
2. Reopen that same scope to draft via a scoped `step_transition`, supplying an actor and a reason. Call `audit_list` filtered by that actor and a `created_after` shortly before the call. Confirm the returned record names the actor, the stated reason, the unfrozen scope, and the head revision at the moment of unfreeze.

## Part 5: recursive subtree delete previews the full doomed subtree and deletes it as one atomic revision

1. On a disposable plan, construct a small subtree (a tactical step with at least one atomic step beneath it). Call the non-recursive deletion path against the tactical step. Confirm it is refused because children still exist (the pre-existing refuse-when-children behavior).
2. Call the recursive deletion path in dry-run mode against the same tactical step. Confirm the preview lists every step in the subtree (the tactical step and its atomic step) plus the invalidation impact set, and that nothing is deleted yet.
3. Call the recursive deletion path in real-run mode against the same tactical step. Confirm the whole subtree is removed as one version-store revision, that a tombstone snapshot is recorded for every deleted step, and that re-fetching any of the deleted steps confirms they no longer resolve as live steps.

## Completion

The procedure is complete when Part 1 shows both the refusal and the happy path at both the G and T admission points; Part 2 shows a block's live/current state, its transition to stale after an upstream edit, and the guard re-refusing on that staleness; Part 3 shows the context-coverage gate check flagging a missing/stale-block tree and staying silent on a compliant one; Part 4 shows a scoped unfreeze's audit record with all four required fields and the membership invariant's refusals; and Part 5 shows the recursive delete's full-subtree dry-run preview followed by its atomic real-run deletion with tombstones recorded.
