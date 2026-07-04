# G-007 Exchange Format Execution Context

Inherited base context: `docs/plans/2026-07-02-plan-manager/execution_context/base.md`

Execution standard: `docs/standards/planning/atomic_step_execution_standard.yaml`

Active plan root: `docs/plans/2026-07-02-plan-manager`

Owner assignment:
- Global step: `G-007`
- Branch: `G-007-exchange-format`
- Scope: exactly `G-007`; no sibling G step is owned by this context.
- T-agent model: `gpt-5.4-mini`.
- A-agent model: `gpt-5.3-codex-spark` or cheapest available coding worker.

Required G-level execution constraints:
- Every child agent must first read the execution standard in full before acting.
- Every T-agent must read this G context file, its own T README, and its own atomic step files.
- Every T-agent must create its own T context file before assigning A work.
- Every A-agent context must be self-contained: inherited base, G, and T context; exact AS file content; current target file state or an explicit missing-file marker; allowed write scope; and verification commands.
- Each A-agent may edit only the `target_file` named by its AS unless it escalates.
- HRS prose is human-owned and must not be rewritten.
- Coverage matrices are computed views only and must not be materialized.
- Preserve unrelated dirty worktree changes and do not revert work from other workers.
- Re-read artifacts from disk before verification passes.
- Do not report completion while child assignments are running or unverified.
- Ambiguity, conflicting target state, missing contracts, dependency cycles, or scope crossing must be escalated.

Parallelization map excerpt for G-007:
- `G-007` depends on `G-001`.
- `T-001` target sequence: `plan_manager/hrs/paragraphs.py` with `A-001`, `A-002`, `A-003`, `A-004` serialized by priority and dependencies.
- `T-002` target sequences: `plan_manager/exchange/importer.py` with `A-001`, `A-002`; `plan_manager/exchange/exporter.py` with `A-003`. Wave 1 is `A-001` + `A-003`; wave 2 is `A-002`.
- `T-003` target sequence: `plan_manager/exchange/exporter.py` with `A-001` through `A-007` serialized by priority and dependencies.
- `T-004` target sequences: `plan_manager/exchange/layout_import.py` with `A-001`, `A-002`, `A-003`, `A-004`; `plan_manager/exchange/importer.py` with `A-005`, `A-006`. Waves: `A-001`; `A-002`; `A-003` + `A-005`; `A-004`; `A-006`.

## Full G-007 README Content

```yaml
step_id: G-007
name: exchange-format
description: >
  This step realizes ExchangeFormat (C-021): the file import/export
  representation of a plan in the standard directory layout of the planning
  standard, retained strictly as an exchange format and never as the
  operational store. File formats are fixed: the HRS is Markdown, and every
  other artifact is YAML — the machine specification, the global and tactical
  step descriptors, and one file per atomic step, named per the exchange
  layout described by PlanSchema (C-006).

  Plan export materializes a plan (C-001) — optionally at a named revision,
  using checkout-read over the version store (C-018) — into that file tree;
  plan import ingests such a tree into the database. HRS import parses a
  human-authored source specification, assigns missing labels, and stores the
  paragraphs; HRS export regenerates the Markdown byte-stable, reproducing
  stored paragraph text byte-identically. Exported files are derived snapshots
  and are never read back as truth except through explicit import — import is
  the single path from files to the source of truth.

  Safe YAML emission on the export path is normative: any scalar containing a
  colon-space, a leading dash, quotes, a hash sign, or other YAML
  metacharacters is emitted as a quoted or block scalar, and every emitted
  file must round-trip through the standard YAML parser to an identical value
  tree before the export completes — a failed round-trip aborts the export.
  Because plan content is stored structurally in the database, YAML quoting
  hazards exist only at export time and are fully handled by this rule.
concepts: [C-021]
relations:
- { from_concept: C-021, to_concept: C-001, type: consumes }
- { from_concept: C-021, to_concept: C-001, type: produces }
- { from_concept: C-021, to_concept: C-006, type: uses }
- { from_concept: C-021, to_concept: C-018, type: uses }
- { from_concept: C-021, to_concept: C-036, type: implements }
source_labels: ["{v1c8}", "{k4u7}", "{p8q4}", "{e2b8}", "{v8y2}"]
depends_on: [G-001]
tactical_steps: [T-001, T-002, T-003, T-004]
status: draft
```
