# CR-5a Live Smoke Procedure

## Purpose

This is the mandatory post-deployment smoke for CR-5a ("agent configuration data layer"), run after CR-5a ships to production, entirely through the plan-manager MCP proxy transport (server_id `planmgr`), with no other tooling. It proves on a live server that the CR-5a entity command surface works against live evidence: six entities (tool, toolset, role, provider, model, and invocation_profile) each exposing a uniform create / read / update / list / soft-delete command family, plus two read-only resolve commands (role-model resolution and invocation-profile resolution). A standing rule that recurs through every Part: a queued "completed" status returned by the proxy transport is NEVER sufficient evidence of success by itself. Every assertion in this procedure must inspect and confirm the INNER command result carried inside that envelope; a queued-but-wrong inner result is a failure of the procedure.

## Part 1: server registration and live command-name enumeration

1. Call `list_servers` through the proxy. Confirm the deployed CR-5a instance is present in the registry (matching its known server_id). Treat failure here as a hard stop: no further step in this procedure may run before this passes.
2. Call the command-catalog inventory command (`command_catalog_dump`, or whichever live command-inventory listing the deployed instance exposes) against the deployed instance via `call_server`. Capture the complete current command roster it returns.
3. Obtain the documented pre-CR-5a baseline command set (the command roster as it existed immediately before this change request's commands were added; source this from the project's own command-catalog documentation or from a command-catalog snapshot taken before deployment). Diff the live roster from step 2 against this baseline set.
4. Record every command name present in the live roster but absent from the baseline as a "new CR-5a command". State explicitly that these new command names are NOT assumed or guessed in advance. The six entities are each expected to expose a uniform create/read/update/list/soft-delete family and two additional read-only resolve commands are expected (one for role-model resolution, one for invocation-profile resolution), following the same per-entity CRUD-plus-resolve naming idiom already used elsewhere in this codebase (an existing example of that idiom is the pre-existing `model_binding_set` / `model_binding_get` / `model_binding_list` / `model_binding_update` / `model_binding_remove` / `model_binding_resolve` command family, which is itself NOT new and is not part of this diff). The EXACT new names for the CR-5a entities are determined only by this live diff, never assumed.
5. State that the diffed set of new command names from step 4 becomes the authoritative coverage checklist for Parts 2 through 5 below: every subsequent Part must be run once for each of the six entities (tool, toolset, role, provider, model, invocation_profile) using that entity's own create/read/update/list/soft-delete commands as identified in the diff, and the two resolve commands as identified in the diff.

## Part 2: entity CRUD and soft-delete happy path (all six entities)

Write these numbered steps, to be run once per entity for each of the six entities enumerated in Part 1 (tool, toolset, role, provider, model, invocation_profile):

1. Using that entity's create command identified in Part 1, call it via `call_server` with a valid payload of that entity's declarative attributes (for tool: server reference, command, and pinned options; for toolset: an ordered list of tool references; for role: a unique name; for provider: type, hardware ownership, activity status, and billing notes; for model: provider reference, capability level, operational attributes, and execution mode; for invocation_profile: the informational call-characteristic fields — generation parameters, reasoning effort or budget, context-window budget, timeout, retry policy, concurrency and rate hints, response-format flag with optional schema, maximum tool iterations, per-call timeout, execution mode, per-step token and cost budgets, reserved dialogue-chain reference — plus the scope-binding fields: system, plan, level, branch, step, role). Assert that the INNER result of the call (not merely a queued-accepted envelope) is a success and returns the persisted record with a stable identifier.
2. Using that entity's read command identified in Part 1, call it with the identifier from step 1. Assert the INNER result returns exactly the record created in step 1, with every field matching the create payload.
3. Using that entity's update command identified in Part 1, call it with the identifier from step 1 and a changed value for at least one mutable declarative field. Assert the INNER result is a success and that a follow-up read (repeat step 2) shows the changed value.
4. Using that entity's list command identified in Part 1, call it with the catalog's standard filters plus pagination (limit, offset) and no include-deleted flag. Assert the INNER result is a paginated page (with total, limit, offset) that includes the record from step 1 in its updated state.
5. Using that entity's soft-delete command identified in Part 1, call it with the identifier from step 1. Assert the INNER result is a success.
6. Repeat the read from step 2 with the same identifier. Assert the INNER result still returns the record (soft-delete does not physically remove it) but marks it as deleted. Repeat the list from step 4 without an include-deleted flag and assert the record is now absent; repeat it with an include-deleted flag set and assert the record is present and marked deleted.

## Part 3: inbound-reference-integrity delete rejection

1. Using the tool create command and the toolset create command (both identified in Part 1), create one tool record and one toolset record.
2. Using the toolset update command, set the toolset's ordered tool-reference list to include the tool created in step 1, so the toolset now references that tool.
3. Using the tool's soft-delete command (identified in Part 1), attempt to delete the tool created in step 1. Assert that the INNER result is a rejection (not a success) because the tool is still referenced by the live toolset from step 2, and that the rejection identifies the referencing toolset.
4. Using the toolset update command, remove the tool reference from the toolset's tool-reference list, so no live record references the tool any longer.
5. Repeat the tool soft-delete from step 3 with the same identifier. Assert the INNER result now succeeds, since no inbound reference remains.

## Part 4: runtime audit records for every mutation performed so far

1. For every create, update, and soft-delete call made across Part 2 and Part 3, call `audit_list` through the proxy, filtered by the actor identity used to make those calls and by a `created_after` timestamp shortly before this procedure began.
2. Assert that the returned audit records include one entry per mutating call made in Part 2 and Part 3 (create, update, and soft-delete each produce their own entry), each naming the actor, the mutated entity, and the action performed.
3. Confirm from these records, together with the read-after-delete checks already performed in Part 2 step 6, that soft-delete is the default deletion behavior for every one of the six entities: the underlying record persists and is marked deleted rather than being physically removed.

## Part 5: resolve commands and scope-specificity inheritance

1. Using the pre-existing `model_binding_set` command (already shipped in this codebase, not part of the Part 1 diff), create a role-model binding at the system scope for a chosen role, binding it to a chosen model.
2. Using `model_binding_set` again (or `model_binding_update` on the same role at a different scope), create or set a second role-model binding for the SAME role at a plan-specific scope, binding it to a DIFFERENT model than the system-scope binding from step 1.
3. Using the role-model resolution command identified in Part 1's diff, call it via `call_server` for the chosen role with a resolution target that matches both the system scope and the plan scope from steps 1 and 2. Assert the INNER result returns the model bound at the plan scope (the more specific of the two active bindings), names the source in the resolution order that selected it, and returns an inheritance path that lists both the plan-scope binding and the overridden system-scope binding.
4. Using the invocation_profile create command identified in Part 1's diff (from Part 2), create one invocation_profile record at the system scope and a second invocation_profile record at a more specific scope (for example branch or step) for the same target coordinates.
5. Using the invocation-profile resolution command identified in Part 1's diff, call it via `call_server` for that target. Assert the INNER result returns the more specific of the two profiles created in step 4, and returns an inheritance path across the six-scope specificity ladder (system, plan, level, branch, step, role) that lists both candidate profiles with the more specific one marked as the winner.

## Part 6: command discoverability and mutation marking

1. Call the command help/metadata surface through the proxy (the same discovery surface used by `command_catalog_dump` in Part 1, or its accompanying per-command help call) for every new command name enumerated in Part 1 step 4.
2. Assert that every one of the six entities' create, read, update, list, and soft-delete commands is present in this metadata surface with its own input schema and documentation, and that every one of the two resolve commands is likewise present with its own input schema and documentation.
3. Assert that every create, update, and soft-delete command among the six entity families is marked as a mutation in its metadata, that every read and list command among them is marked as non-mutating, and that both resolve commands are marked as non-mutating (read-only).

## Completion

The procedure is complete when Part 1 shows the deployed server registered and the live-vs-baseline command diff producing the exact new-command coverage set used by every later Part; Part 2 shows every one of the six entities completing its create/read/update/list/soft-delete happy path with correct inner results at every step; Part 3 shows the inbound-reference-integrity rejection followed by the successful delete once the reference is cleared; Part 4 shows an audit record for every mutating call made in Parts 2 and 3, and confirms soft-delete is the default; Part 5 shows both resolve commands returning the correct, more-specific-wins result together with a full inheritance path across the six-scope ladder; and Part 6 shows every new command discoverable in the metadata surface with correct mutation marking. The whole procedure is green only when every inner command result asserted across all six Parts is correct — a queued "completed" transport status alone is never treated as passing evidence at any step.
