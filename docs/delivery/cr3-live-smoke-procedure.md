# CR-3 Live Smoke Procedure

## Purpose

This is the mandatory post-deployment smoke for CR-3 ("verification and observability"), run after CR-3 ships to production, entirely through the plan-manager MCP proxy transport (server_id `planmgr`), with no other tooling. It proves on a live server that all five deliverables work against live evidence: ops_status, command_timing_stats, step_prompt_verify, the embedded-code gate check, and audit_list.

## Part 1: ops_status reports live version, health, and migration rows together

Call `ops_status` with no parameters. Confirm the response carries `version.image_tag` and `version.build_date` matching the deployed release, `health.status` and `health.services.database`/`health.services.embedding`, and `schema_migration.rows` with at least one row (filename, applied_at) ordered newest-first, plus `schema_migration.count` matching the row count.

## Part 2: command_timing_stats accrues rows with a truthful direct/queued split

1. Call a handful of read commands directly (for example `step_get`, `plan_list`) and at least one queued command (for example `plan_validate`), noting each call's expected mode.
2. Call `command_timing_stats` with no filter; confirm the invoked command names appear in `commands`, each row's `call_count` reflects the number of calls made, and `direct_count`/`queued_count` reflect the actual direct-versus-queued split observed in step 1.
3. Call `command_timing_stats` again with `command_name` set to one of the invoked commands; confirm the filtered result contains only that command's row.

## Part 3: step_prompt_verify matches a real frozen block and diffs a mutated one

1. Pick a frozen atomic step from a shipped, frozen plan. Call `step_prompt_verify` with that step's `plan`/`step`, `field="prompt"`, and `candidate_base64` set to the base64 encoding of the step's actual current prompt text (read via `step_get`). Confirm `match` is `true`.
2. Repeat with `candidate_base64` set to a deliberately mutated copy of that prompt text (for example one changed character). Confirm `match` is `false`, `unified_diff` is present and shows the mutation, and `first_divergence_offset` points at the mutated byte.

## Part 4: audit_list shows a just-run mutating command's audit record

1. Run one mutating command against a throwaway or disposable plan (for example `todo_create`), recording its `changed_by` identity and approximate timestamp.
2. Call `audit_list` filtered by that `actor` and a `created_after` shortly before the call; confirm the returned `items` include a record for that action with a `created_at` at or after the call.

## Part 5: the embedded-code gate check is exercised by a malformed block

1. Create a disposable plan and author one atomic step whose `prompt` field contains a deliberately malformed fenced code block (for example a Python fence with unbalanced parentheses, or a SQL fence with a syntactically invalid statement).
2. Call `plan_validate` against that plan. Confirm the report contains an error-severity finding naming the offending step and the parser error, alongside the plan's other findings, and that a syntactically valid fenced block elsewhere in the same plan produces no such finding.

## Completion

The procedure is complete when Part 1 shows live version, health, and migration rows together; Part 2 shows timing rows accruing with a truthful direct/queued split; Part 3 shows both a real match and a real mismatch-with-diff; Part 4 shows a just-run mutating command's audit record; and Part 5 shows the embedded-code gate catching a deliberately malformed block while leaving valid blocks unflagged.
