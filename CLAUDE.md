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
3. **Product maintenance** — direct bug fixes or features on plan_manager
   source by explicit user instruction: tests, version bump in
   `pyproject.toml` (single version source), `./build.sh`, deploy per the
   documented pipeline.

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

**IDLE — awaiting execution authorization** (updated 2026-07-11). The service
plan `planmgr-runtime-work-layer-integration`
(uuid `fcc11f8e-7d1a-4adb-9175-d765ac10e753`) is FULLY AUTHORED, reviewed
(9 read-only reviewers + fix rounds + adversarial re-review), committed
(cascade ee35a692) and FROZEN at head revision
`720b2e57-f187-4749-886c-988cbec6870a` (200 steps, gate 20/20 green,
user-ordered freeze 2026-07-11). No production implementation is authorized
yet: plan EXECUTION starts only on an explicit user order, which will flip
this section to the execution phase. The parking-lot plan
`planmgr-post-runtime-roadmap` (e4a9fd91, HRS only) holds user-ordered
follow-up work — not for authoring or implementation now. The previously
executed plan `planmgr-semantic-reproduction-tree` is COMPLETE (shipped
through 0.1.24) and stays frozen.
