# CR-1 Live Smoke and Blocked-Workflow Re-run Procedure

## Purpose

This document is the live post-deployment smoke and blocked-workflow re-run procedure for CR-1 ("command-surface quality"), the highest-priority group of the plan-manager post-runtime roadmap. It is executed after CR-1 ships to production, entirely through the plan-manager MCP proxy transport (server_id `planmgr`), with no other tooling. It has two parts: Part 1 exercises every command added by CR-1 on one happy path and one negative path each; Part 2 re-runs the three agent workflows that were blocked before CR-1 and proves each now completes using planner commands alone.

## Part 1: Live smoke of every CR-1 command

### Step 0: Resolve the exact command roster

Before smoking individual commands, call `command_catalog_dump` through the MCP proxy (server_id `planmgr`) to obtain the live, authoritative command catalog. Diff this catalog against the pre-CR-1 baseline catalog (the catalog as captured at the runtime-work-layer-integration release, frozen prior to this change request) to obtain the exact set of commands added or materially changed by CR-1. This resolution step is mandatory and is not a static list, because the exact command names are determined by the sibling branches of this change request and are only authoritative once the frozen catalog is queried live. Group the resolved commands under the categories in the checklist below, each traceable to its roadmap source-of-record todo identifier.

### Step 1: Smoke checklist by category

For every command resolved under a category below: (a) call `help` with `cmdname` set to the command name to obtain its parameter schema and its documented `error_cases`; (b) execute one happy-path invocation using arguments that satisfy the schema, through `call_server` with `server_id="planmgr"`, and record success; (c) execute one negative invocation deliberately violating one documented constraint (a missing required parameter, an invalid identifier, or a reference to a non-existent entity) and record the returned `error_code`, confirming it matches one of the entries in that command's `error_cases`.

Checklist categories, each keyed to its roadmap source-of-record todo identifier:

1. Pagination uniformity (todo 14897f7a) — every large-output command resolved in Step 0 as newly paginated.
2. Bulk step listing (todo 25440a28, command family step_list).
3. Content search (todo 7b924c17, command family step_search).
4. File coverage reporting (todo 751b8983, command family files_report).
5. Cross-reference reporting (todo 1cc5da59, command family step_xref).
6. Asynchronous execution mode (todo c1d00e66) — the async mode surface on the commands resolved in Step 0 as supporting it.
7. Command catalog introspection (todo a6600876, command command_catalog_dump; already invoked in Step 0, additionally smoked here for its own happy/negative pair).
8. CRUD completeness and deletion (todo 630cb33c) — every create/read/update/delete command resolved in Step 0 for runtime entities, at minimum the delete commands.
9. Status reachability (todo d1299740) — the commands resolved in Step 0 whose status vocabularies and transition matrices were newly exposed.
10. Newly added missing commands (todo a686dc84) — any command resolved in Step 0 that closes a previously identified command-surface gap and does not belong to another category above.
11. Reachable error codes (todo 7a84c4bf) — confirm, for the commands resolved in Step 0 under this todo, that every documented error code is triggered by at least one negative invocation across this checklist.
12. Dependents graph traversal (todo 887eb8a3, command graph_dependents).
13. Re-anchoring (todo ec772710) — the re-anchor command resolved in Step 0.
14. Metadata truthfulness (todo 991e5c8c) — confirm, for the commands resolved in Step 0 under this todo, that the catalog entry for each command matches its live behavior observed in steps (b) and (c) above.
15. Info reachability (C-016 addendum, user order 2026-07-13) — invoke `info` through the MCP proxy and confirm every command resolved in Step 0 appears in the info.agent_reference operational tables; for the negative invocation, call `info` with an unknown/bad selector and record its documented error code.

### Step 2: Record results

For each category, record: the exact command name(s) resolved in Step 0, the happy-path invocation and its result, the negative invocation and its returned error code, and pass/fail against the expectation that the error code matches a documented entry in that command's error_cases.

## Part 2: Blocked-workflow re-runs

Each of the three workflows below was blocked before CR-1 because it required external tooling (`jq`, `grep`, or hand-built matrices) alongside the planner. Each re-run below must complete using only plan-manager commands invoked through the MCP proxy transport (server_id `planmgr`), with no shell pipeline, no `jq`, no `grep`, and no manually assembled matrix.

### Re-run 1: Bulk step reading without external tooling

Previously, reading many steps of a plan at once required exporting plan data and piping it through `jq` to extract fields. Re-run this workflow using only the bulk step-listing command family resolved in Part 1 Step 0 (step_list) with its pagination parameters (resolved under Part 1 category 1) to retrieve the full set of steps for a target plan across all pages, without any external filtering tool. Record that every step of the target plan was retrieved and that no `jq` invocation or equivalent external filter was used at any point.

### Re-run 2: Content search without external tooling

Previously, searching plan content for a term required exporting plan data and piping it through `grep`. Re-run this workflow using only the content-search command family resolved in Part 1 Step 0 (step_search) to locate every step whose content matches a target term, without any external text-search tool. Record the matched steps returned directly by the command and confirm no `grep` invocation or equivalent external filter was used at any point.

### Re-run 3: Per-file writer matrix without hand-building

Previously, determining which atomic steps write to which files required manually reading every atomic step and hand-assembling a file-to-writer matrix. Re-run this workflow using only the file-coverage reporting command family resolved in Part 1 Step 0 (files_report) to obtain the per-file writer matrix directly from the command's output, without manually enumerating atomic steps or hand-building the matrix. Record the returned matrix and confirm it was produced entirely by the command, with no manual assembly step.

## Completion

This procedure is complete when every category in Part 1 has a recorded happy-path result, a recorded negative result with its matched error code, and all three re-runs in Part 2 are recorded as completed using planner commands alone.
