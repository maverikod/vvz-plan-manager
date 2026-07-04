# Execution Base Context

Plan: `docs/plans/2026-07-02-plan-manager`
Scope: common context shared by all G-level agents.

This file is intentionally lean. It does not embed the full HRS or full MRS.
Each descendant context must add only the relevant slice for its assigned step.

## Source Files

- HRS: `docs/plans/2026-07-02-plan-manager/source_spec.md`
- MRS: `docs/plans/2026-07-02-plan-manager/spec.yaml`
- Parallelization map: `docs/plans/2026-07-02-plan-manager/parallelization_map.yaml`
- Execution standard: `docs/standards/planning/atomic_step_execution_standard.yaml`

## Context Slicing Rule

- Base context contains only rules common to every G-agent.
- A G context adds only the HRS labels, MRS concepts, MRS relations, and G README content relevant to that G step.
- A T context adds only the inherited G context plus the T README content and any additional T-specific referenced concepts/labels.
- An A context adds only the inherited T context plus the exact AS file content, current target-file state, allowed write scope, and verification commands.
- Do not pass whole sibling branches downward.
- Do not pass the full HRS/MRS downward unless the assigned step explicitly requires every part and that requirement is escalated/approved.

## Non-Negotiable Execution Rules

- Assumptions are forbidden.
- Ambiguity, missing contracts, conflicting target state, or scope expansion must be escalated upward.
- The top escalation authority is the user.
- Each step has exactly one responsible agent.
- An agent may add only its own step layer to the inherited context.
- An agent must not finish until all subordinate branches are completed, verified, or explicitly escalated.
- Context passed downward must be complete and self-contained for the receiving level, within the relevant slice.
- Repository artifacts and code are English; user communication is Russian.
- HRS prose is human-owned and must not be rewritten.
- Coverage matrices are computed views only and must not be materialized.
- Preserve unrelated dirty worktree changes.

## Model Assignment

- G-agent: GPT-5.5.
- T-agent: gpt-5.4-mini.
- A-agent: gpt-5.3-codex-spark or the cheapest available coding worker.

## Universal Implementation Constraints

- Production package root is `plan_manager/` at the repository root.
- Python runtime target is 3.12 or newer.
- Database access uses psycopg 3 with plain SQL; runtime code must not emit DDL.
- The plan tree/database is the source of truth; derived artifacts are not read back as truth.
- The server does not execute atomic-step prompts or track external code implementation.
