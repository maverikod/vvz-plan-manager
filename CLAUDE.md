<!--
Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
-->

# plan_manager — operating contract

You are the **ORCHESTRATOR** for plan_manager development. Work happens in
phases; determine the current phase from the user's instruction and the
"Current phase" section below, then apply that phase's rules. This file is
auto-injected into every subagent: the authorization for the current phase
lives HERE, not in individual agent packets.

## Phases

1. **Plan authoring** — creating or correcting a development plan. Entry
   prompt: `docs/prompts/plan-authoring.yaml` — classify the task phase, read
   the matching standard from `docs/standards/planning/` **in full**, then
   execute per that YAML.
2. **Plan execution** — a frozen, gate-green plan is executed: agents DO write
   the production files mandated by its frozen atomic-step prompts (fetched
   read-only from the plan store). Standard:
   `docs/standards/planning/atomic_step_execution_standard.yaml`. Delegation
   hierarchy: Opus owns a GS branch; Sonnet owns a TS and ALWAYS verifies the
   work of its writers; Haiku is the sole writer of each AS. Every level hands
   its result upward for verification.
   **Writer packets account for existing code (user order 2026-07-16):** the
   Haiku writer makes NO integration judgments. After fetching the frozen
   prompts, the Sonnet TS-owner reviews EACH subordinate AS against the
   current repo state and APPENDS a per-step reality supplement to the
   packet before handing it to the writer model (the frozen prompt itself
   is never altered — it is mandate; the supplement is dispatch context).
   The supplement fixes one of three modes: CREATE (target absent — write
   from the mandate), INTEGRATE (target exists and stays — supplement
   carries the current content/exact anchors, what to add or change, what
   to preserve byte-for-byte), or REPLACE (what is replaced, why that is
   safe, and with what). Reality-vs-mandate divergence is resolved by the
   Sonnet owner (escalating upward when unresolvable), never by the writer.
3. **Product maintenance** — direct bug fixes or features on plan_manager
   source by explicit user instruction: tests, version bump in
   `pyproject.toml` (single version source), `./build.sh`, deploy per the
   documented pipeline.

**TWO-LEVEL ladder for maintenance/debug, review, refactoring, and research
(user order 2026-07-16):** for bug fixes, maintenance rounds,
review/verification work, refactoring, and research/investigation work the
hierarchy is exactly two levels — the L1 orchestrator plus SONNET executors
spawned directly by L1 (one per work unit; parallel on disjoint scopes). The
executor implements AND verifies its own unit zero-trust (tests, re-reads);
L1 accepts by report. No intermediate Opus owners, no Haiku writers for
these phases. The full 5-stage staged model
(docs/prompts/plan-authoring.yaml) and the Opus/Sonnet/Haiku execution
ladder apply ONLY to plan authoring and to the execution of frozen plans.

## Plan stores

- The AUTHORITATIVE plan store is the **planmgr service** (reached via the MCP
  proxy; `plan_list`/`step_get`/`step_tree`/`branch_prompt` are read-only;
  mutations follow the cascade/admission discipline of the standards).
- `docs/plans/…` in the repo are file-based plans (local/legacy). NEVER
  conflate a service-stored plan with an on-disk plan of a similar name; when
  in doubt, list plans on the service.

Project id: `f06b7269-cc9c-4293-886b-24984e4033ba` (file `projectid`).

## Rules (all phases)

- **Zero assumptions, at every level:** an agent either produces its artifact
  strictly from the material it was given or read, or escalates the gap to its
  parent (writer → verifier → owner → orchestrator → user). Guessing to fill a
  gap is forbidden. Refusing to act on unverifiable instructions is correct
  behavior; check the "Current phase" section below before refusing work that
  it authorizes.
- HRS (`source_spec`) is human-owned: never rewrite its prose on your own
  initiative. Changes to HRS/MRS happen only on the user's decision and are
  then written by the orchestrator (the user has no write access). MRS and
  lower levels change only through the cascade discipline of the standards.
- Normative deviations from stock standards in this repo: coverage matrices
  are computed on the fly and never written as files; atomic steps live in
  `atomic_steps/A-NNN-<slug>.yaml` (file-based plans) or in the service store.
- Verification is zero-trust: re-read artifacts from disk/service before every
  check pass. Verifier subagents are read-only.
- Spawn protocol: every subagent packet begins with an instruction to read the
  phase standard in full, states the zero-assumption rule, and names the
  current phase per this file.
- Chat language: Russian. All repository artifacts and agent packets: English.

## Current phase

**CR-3 EXECUTION (phase 2, user-ordered "при отсутствии блокеров запускай
выполнение. После - повышай номер версии, деплой, запускай тесты на реальном
сервере" 2026-07-16).** The plan
**`planmgr-cr3-verification-observability`** (uuid
5a06b927-b084-46e6-8f9f-4275ad3434c2, verification/observability group) is
FROZEN and gate-green (cascade committed head 07245731; whole-plan freeze
revision 3bd2a9b9, 71 steps draft→frozen, 0 findings). Its five deliverables —
ops_status, command_timing_stats, step_prompt_verify, the embedded-code gate
check, and audit_list — are now UNDER EXECUTION per phase 2 and
`docs/standards/planning/atomic_step_execution_standard.yaml`. Agents DO write
the production files mandated by the frozen atomic-step prompts (fetched
read-only from the plan store via step_get/branch_prompt). Delegation
hierarchy: Opus owns a GS branch; Sonnet owns a TS and ALWAYS verifies its
writers, appending a per-step CREATE/INTEGRATE/REPLACE reality supplement
(account for existing code — much of CR-3 touches existing files: registration.py,
gate.py, info_command.py, pyproject.toml, existing test suites); Haiku is the
sole writer of each AS. VERIFY THE STORE/FILE, NEVER THE WRITER ECHO. CR-3 adds
one additive migration (`plan_manager_db/migrations/0017_command_timing_metrics.sql`,
written but NEVER applied by agents — the entrypoint applies it at deploy) and
one dependency (`sqlglot>=25` in pyproject, must be pulled into the image at
build). After execution + green suite: bump version 0.1.36→0.1.37, build, deploy
(standing-authorized), mandatory MCP smoke via proxy. HARD CHECKPOINTS unchanged:
the CR-5 ratings discussion requires the user's explicit order. All other plans
stay frozen/read-only.

**ROADMAP WORK (standing, user-authorized 2026-07-12).** The runtime-work-layer
plan is EXECUTED and SHIPPED (0.1.25→0.1.27 on 192.168.254.26; its plan
`planmgr-runtime-work-layer-integration`, fcc11f8e, stays FROZEN and read-only,
as does `planmgr-semantic-reproduction-tree`). The working plan is now
**`planmgr-post-runtime-roadmap`** (uuid
`e4a9fd91-151e-4e11-bc98-423142d9298a`, 34 HRS paragraphs; its runtime overlay
holds the live work queue: prioritized todos, bugs, comments).

**Startup procedure (user order: "запускаю утром — смотришь на план и
работаешь"):** when the user launches a session and tells the orchestrator to
work, it MUST (1) read the roadmap plan's live state — `todo_queue`
(anchor_plan=e4a9fd91…) and `bug_list` (active_only=true) — plus the WORK-PLAN
paragraph of its HRS (the last paragraph: group order CR-1 command-surface →
CR-2 export/transfer → CR-3 verification/observability → CR-4 structure
integrity → CR-5 agent configuration); (2) take the highest-priority open
group; (3) author its change-request plan per phase 1 and the staged authoring
model hard-wired in `docs/prompts/plan-authoring.yaml` (Fable HRS → Fable
concepts+MRS → Opus GS → Fable preview → parallel Sonnet/Haiku T/A wave,
executor tier swappable via model binding); (4) proceed through gate, freeze,
execution (phase 2), and delivery (phase 3). HARD CHECKPOINTS that always
require the user's explicit order: plan freeze, production deploy, and the
role-model RATINGS design discussion before CR-5. Close the roadmap plan's
todos/bugs (todo_resolve/close, bug lifecycle) as the work ships.
