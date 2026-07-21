# live_smoke.py: THE automated real-server test pipeline

## Purpose

`scripts/live_smoke.py` is the ONE automated pre-delivery/real-server test
pipeline for planmgr (`prompts/claude/ops/delivery-release.yaml` invariant:
"exactly ONE pre-delivery/real-server pipeline -- extend it, never multiply
pipelines"). Before this script existed, the only real-server checks were the
manual agent runbooks `docs/delivery/cr{1..4}-live-smoke-procedure.md`. This
script is now the automated baseline that every delivery runs; the manual
runbooks remain as deep, hand-driven procedures for scenarios this script
does not (yet) automate, and as a design reference when extending it.

**Extend this script, do not add a second one.** New commands or new
regression checks are added as new entries in `live_smoke.py`'s tier tables
(see "How to extend" below), never as a separate script.

**First-live-run finding (0.1.52, on-host https):** the deployed server
queues every command, even trivial reads like `info`/`help` -- confirming
`queue_semantics` applies pipeline-wide, not just to slow commands. The
shipped client's own envelope unwrap peels only one conditional layer past
the queue terminal event; a live response nesting one layer deeper left the
full `{job_id, command, result, status}` envelope in place where the script
expected plain data. Fixed with `unwrap_envelope()` (a pure, iteratively
applied unwrap of any nesting/combination of the queue and success/error
envelope shapes) -- see its docstring in `scripts/live_smoke.py` for the
full investigation and exact file:line citations into the adapter package.

**Second-live-run finding (0.1.52, same run family):** with the envelope
fix in place, Tier 0 went fully green, but `help`/catalog fetching still
failed -- `help` is an `mcp_proxy_adapter` framework builtin, registered on
the plain JSON-RPC dispatcher but NOT in the queue-executor registry the
default queued path resolves commands against, so the queue runner reports
"Command 'help' not found". `info`/`health` are plan_manager domain
commands and resolve fine via the queued path. Fixed by routing
`KNOWN_BUILTIN_COMMANDS` (help, echo, config, long_task, job_status, the
`queue_*` family) proactively to the client's plain, non-queued
`execute_command` path, with a one-shot fallback for any other command
whose queued failure looks like an unresolved-command error -- see
`unwrap_envelope`'s neighboring module note (`KNOWN_BUILTIN_COMMANDS` /
`_looks_like_unresolved_command` / `DISPATCH_LOG`) in `scripts/live_smoke.py`
for the full investigation and file:line citations.

**Third-live-run finding (0.1.52, same run family):** 232 passed, 29
failed, 120 skipped, zero server regressions -- R1 and R3 fully green.
Every failure was a script recipe/ordering defect, not a server bug: (1)
every entity-scoped Tier-2 probe failed PLAN_NOT_FOUND (or SKIPped) because
the Tier-3 lifecycles deleted their throwaway plan/todo before those probes
ever ran -- fixed by splitting each lifecycle into a create phase and a
separate cleanup phase, with Tier 2's scoped probes running strictly
between them (`run_tier3_plan_step_create`/`_cleanup`,
`run_tier3_todo_create`/`_cleanup` in `scripts/live_smoke.py`); (2)
`step_search` needs `plan`+`pattern`, not zero params; (3)
`graph_dependents`'s `direction` enum is `["dependents", "dependencies"]`,
not `"downstream"/"upstream"`; (4) `bug_close` requires a verified fix
(`bug_fix_create` -> `bug_fix_verify(passed=True)`) before it succeeds --
`run_tier3_bug_create` now runs the full documented closure chain; (5) the
R2 regression's step builder skipped level 4 (creating level-5 steps
directly under a level-3 parent), which downstream produced
GRAPH_CORRUPTED_CHAIN -- rebuilt to the proven G/T-001/T-002/A-under-each-T
chain with `context_common` recompiled before every single `step_create`
(a stored context block's revision must match the plan's current head
revision exactly, and every `step_create` advances that revision); (6) 19
adapter-builtin/admin/transfer/stub commands got specific
`KNOWN_SKIP_REASONS` entries instead of the generic fallback. See the
docstrings of `run_tier3_plan_step_create`, `run_tier3_bug_create`, and
`run_r2_same_file_order_ambiguity` for the full detail.

**Fourth-live-run finding (0.1.52, same run family):** 266 passed, 6
failed, 116 skipped -- all six were script recipe-level, not server bugs.
(1) `branch_weak`/`plan_score` refused with the documented `GATE_RED`
domain error against the deliberately unpolished throwaway plan --
correct, expected behavior, not a probe failure; `interpret_gate_red_probe`
now inverts the usual pass/fail logic for these two (`GATE_RED_EXPECTED`),
labeling them `"<name>(gate_red_contract)"`. (2) `step_xref` needs `text`
or `step`+`field`, not zero params -- fixed to `{"plan":..., "text":
"live-smoke"}`. (3) the R2 regression's curative dependency edge targeted
the two A (level-5) steps directly, but they live under DIFFERENT level-4
parents and so are not siblings -- `-32000 INVALID_DEPENDENCY_SCOPE`
("a dependency must reference a sibling step"); the curative batch now
orders the T-level SIBLINGS instead (`T-002 depends_on [T-001]`, same
parent G, same level 4), which transitively orders the same-file atomic
children beneath them; preview is now run WITH that curative batch (not
`changes=[]`) so its `same_file_order` response carries a non-trivial
`resolved_pairs`, and the check now asserts all four simulation fields are
present. See `interpret_gate_red_probe` and
`run_r2_same_file_order_ambiguity`'s docstrings in `scripts/live_smoke.py`
for the full detail.

## How to run

### On-host (loopback, typical local/dev run)

```bash
python3 scripts/live_smoke.py --base-url https://127.0.0.1:8080
```

### Against the deployed instance (post-deploy verification)

```bash
python3 scripts/live_smoke.py \
  --base-url https://192.168.254.26:8080 \
  --expect-version 0.1.39 \
  --ca /path/to/ca.crt
```

Add `--cert`/`--key` (client certificate/key) if the deployed server's
`server.protocol` in `/etc/planmgr/config.json` is `mtls`
(`packaging/etc/planmgr/config.json.template`); the script auto-upgrades an
`https` request to effective `mtls` transport the moment both `--cert` and
`--key` are supplied (mirroring `docker/healthcheck.sh`'s own three-way
`http`/`https`/`mtls` branch). Plain `http` deployments pass
`--protocol http` (or a `http://` `--base-url`) instead.

### Machine-readable output

Add `--json` to print a JSON summary (`counts`, `failed`, `skipped`, full
per-check `results`, `exit_code`) instead of the human-readable text report.
Exit code is `0` iff there were zero `FAIL`s (`SKIP`s never affect it).

### All CLI flags

| Flag | Default | Meaning |
|---|---|---|
| `--base-url` | none | e.g. `https://127.0.0.1:8080`; overrides `--host`/`--port`/`--protocol` |
| `--protocol` | `https` | `http` \| `https` \| `mtls` |
| `--protocol-override` | none | force this protocol regardless of `--base-url` |
| `--host` | `127.0.0.1` | used when `--base-url` is absent |
| `--port` | `8080` | used when `--base-url` is absent |
| `--cert` / `--key` | none | client certificate/key (mTLS); also auto-upgrades `https` to `mtls` |
| `--ca` | none | CA certificate for verifying the server (https/mtls) |
| `--timeout` | `30.0` | HTTP client timeout in seconds |
| `--expect-version` | none | Tier 0 fails if `info`'s `identity.package_version` differs |
| `--project` | this project's own UUID (`f06b7269-cc9c-4293-886b-24984e4033ba`) | project id used for project-scoped reads (R3, `project_dependents`) |
| `--json` | off | JSON summary instead of text |

## Transport

The script reuses the shipped `client/plan_manager_client` package rather
than reimplementing JSON-RPC (`server_client_law`: a server project's client
hides ALL network interaction; a project built on mcp-proxy-adapter
implements that client as a wrapper over the adapter's client, never
reimplementing transport). `PlanManagerClient` composes (holds, never
inherits) `mcp_proxy_adapter.client.jsonrpc_client.client.JsonRpcClient` on
`self._rpc`, which supplies protocol/TLS/mTLS, token auth, and queued-job
auto-polling. Every command in this script is dispatched through
`PlanManagerClient._call(name, params)` -- the class's own documented single
dispatch primitive used by every one of its five command-family facade
mixins -- rather than through a specific facade method, so the pipeline can
invoke ANY command the *live* server's `help` catalog names, including one
added in parallel with this script (`project_view`) that has no facade
method yet.

## What it covers

- **Tier 0** -- reachability, `health`, `info`; asserts the reported
  `identity.package_version` equals `--expect-version` when given.
- **Tier 1** -- fetches the live `help` catalog (no `cmdname`) and asserts
  `help(cmdname=<name>)` returns a non-empty schema for **every** cataloged
  command. This is the "all commands respond to help" baseline.
- **Tier 2** -- every safe read-only command invoked with minimal valid
  params: `TIER2_STATIC_PARAMS` (zero entity dependency -- catalogs,
  `plan_list`/`todo_list`/`bug_list`/`audit_list` with `limit=1`, `info`,
  `health`, `ops_status`, etc.) plus `TIER2_SCOPED_NEEDS` (plan/step/todo/bug
  or `--project`-scoped reads, run right after Tier 3 creates the entities
  they need, before cleanup).
- **Tier 3** -- CRUD lifecycles on THROWAWAY entities, all named with the
  `live-smoke-` prefix and deleted (verified deleted) in `try/finally` even
  on failure:
  - plan/step: `plan_create` -> `context_common` -> `step_create` (level 3,
    then level 4 under it) -> `graph_order` -> `plan_delete(hard=true)`,
    with a follow-up `plan_list` check that the deleted plan's name is
    really gone.
  - todo: `todo_create(anchor_type="none")` -> `todo_update` ->
    `todo_resolve` -> `todo_close` -> `todo_delete(hard=true)`, with a
    follow-up `todo_get` expected to fail, confirming the delete stuck.
  - bug: `bug_create` -> `bug_confirm` -> `bug_close` on a dedicated
    throwaway plan (bug commands require a `plan` reference). **No
    `bug_delete` command exists on this server's surface**, so the bug
    lifecycle intentionally ends at `bug_close`, not a hard delete; its
    throwaway plan is still hard-deleted at the end.
- **Tier 4** -- the three named bug regressions from the CR-4/roadmap work:
  - **R1** (bug c72e047c): `todo_create` with `anchor_type="none"` (and
    `description="none"`) must succeed (previously failed `-32602 Missing
    required parameters`); the response's `primary_anchor_type` must equal
    `"none"`.
  - **R2** (bug 64107707): builds a dedicated throwaway plan with two
    same-file order-ambiguous step pairs, then asserts
    `step_dependency_preview` always simulates and returns
    `same_file_order.before_findings` rather than raising
    `AS_SAME_FILE_ORDER_AMBIGUOUS` up front; a dry-run `step_dependency_apply`
    mutates nothing; a real, fully-curative batch (an edge added per pair)
    commits (`applied: true`); `graph_order` afterward is clean.
  - **R3** (bug 18951d08): calls `project_view` against `--project` and
    asserts its `todos`/`bugs` UUID sets equal `todo_list`/`bug_list`
    filtered identically, and that every returned item carries
    `match_source`. **If `project_view` is absent from the live catalog,
    this is reported as FAILED, not skipped** -- per the pipeline's design,
    a missing regression-critical command is a real gap, never silently
    waved through.

## Skip-list policy

Nothing is silently capped. Every command named in the live catalog lands in
exactly one of: Tier 1 (always, universally), Tier 2 (static or scoped),
Tier 3/4 (named lifecycle/regression step), or the explicit SKIPPED list
with a **specific** reason (`KNOWN_SKIP_REASONS` in the script) -- typically
because it mutates shared, non-throwaway state (e.g. `model_binding_set`,
`project_dependency_add`, the HRS-mutating `para_*` family which is
human-owned per the root `CLAUDE.md`), needs an externally prepared payload
(`plan_import`, `export_upload_save`), or produces filesystem artifacts
outside this pipeline's scope (`plan_export`, `hrs_export`,
`export_archive`). A command this script has genuinely never seen before
(added to the server after this script was last extended) falls back to a
single generic reason naming exactly that gap, so it is visible in the
summary rather than invisible. `tests/test_live_smoke_script.py` asserts, as
a standing invariant, that every command in the shipped client's own
`COMMAND_NAMES` catalog gets a specific (non-generic) disposition -- extend
the tier tables whenever that test starts failing after a new command ships.

## Output

Per-check `PASS`/`FAIL`/`SKIP` lines followed by a summary block (counts,
failed check names, skipped check names with their reasons). Exit code `0`
only when there are zero `FAIL`s. `--json` emits the same data as structured
JSON for CI/automation consumption. Per `queue_semantics`, a queued
"completed" envelope is not treated as success on its own -- the shipped
client's `auto_poll=True` dispatch already unwraps the terminal queued
result before this script ever sees it.

## How to extend

1. New read-only command with no required params or params derivable from
   `--project`/an already-created throwaway entity: add it to
   `TIER2_STATIC_PARAMS` or `TIER2_SCOPED_NEEDS` (+ a branch in
   `scoped_params` if its param shape isn't `{"plan": ...}`).
2. New mutating command that fits an existing throwaway lifecycle: extend
   the relevant `run_tier3_*` function and add its name to `TIER3_HANDLED`.
3. New regression check: add a `run_r<N>_<slug>` coroutine (own throwaway
   entities, own `try/finally` cleanup), call it from `run_pipeline`, and
   add its command names to `TIER4_HANDLED`.
4. Anything else: add a specific entry to `KNOWN_SKIP_REASONS` explaining
   why it is not safe/in-scope to exercise here -- never leave a command to
   fall through to the generic reason if you know why it's excluded.

Run `python3 -m pytest -q tests/test_live_smoke_script.py` after any tier
table change -- it re-checks the zero-uncovered/zero-generic-reason
invariants against the shipped client's own command catalog.
