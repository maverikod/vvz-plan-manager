# Codex role translation matrix

This matrix is the normative compatibility layer between the source bundle and
the available Codex runtime. The source tiers remain useful descriptions of
responsibility depth; they never prove, require, or select a model.

## Runtime invariants

- Available positions are the user-facing root Orchestrator and ordinary Codex
  subagents. Researcher, tester, owner, mini, spark, and conscience are duties in
  a prompt, not distinct runtime APIs.
- Duties, scope, context, acceptance, tool cards, and escalation are assigned in
  the child prompt.
- `requested_model`, source tier, and reasoning effort are recommendation
  metadata only.
- The child is created only with
  `spawn_agent({task_name, fork_turns, message})`;
  the duty and delegation YAML are carried inside `message`.
- No report may claim an actual model without explicit runtime evidence.
- Escalating from one source tier to another means issuing a different bounded
  duty prompt and context envelope; it does not mean switching models.

## Source tier translation

| Source tier | Source meaning | Codex destination | Dispatch behavior when model selection is unavailable |
| --- | --- | --- | --- |
| Fable | Top owner, global synthesis, final escalation | Root Orchestrator | Root keeps user communication, routing, and completion ownership; no model claim |
| Opus | Complex research or high-complexity child owner | Subagent with high-complexity duty prompt | Parent supplies wider bounded evidence and owner duties; recommendation is not enforced |
| Sonnet | Default research or medium-complexity child owner | Subagent with standard bounded duty prompt | Parent supplies normal bounded research/owner duties; recommendation is not enforced |
| Haiku | Atomic author or coder | Subagent with one atomic duty prompt | Parent supplies one self-contained AS or coding task; recommendation is not enforced |

## Complete role-file translation

| Source role and file | Source tier | Codex position | Prompt-assigned duties | Parent/child mapping | Non-selectable-model behavior |
| --- | --- | --- | --- | --- | --- |
| Common laws — `roles/common.md` | All | Root and every subagent | Isolation, tool boundaries, language, escalation, completion | Loaded with exactly one role file | Applies unchanged to the runtime-assigned model |
| Researcher — `roles/researcher.md` | Sonnet by default; Opus for precision | Read-only subagent | Evidence gathering before authoring, execution, or repair | Child of the current scope owner | Parent changes duty prompt for escalation; no model claim |
| Planning HRS/MRS owner — `roles/planning-hrs-mrs-owner.md` | Fable | Root Orchestrator | Human-intent boundary, HRS/MRS ownership, cascade, GS delegation | Root -> GS owners | Root position implements duties; tier is metadata |
| Planning GS owner — `roles/planning-gs-owner.md` | Opus | Subagent assigned GS-owner duties | One GS, TS partition, TS context formation | HRS/MRS owner -> GS owner -> TS owners | Put the GS-owner envelope in `spawn_agent.message` |
| Planning TS owner — `roles/planning-ts-owner.md` | Sonnet | Subagent assigned TS-owner duties | One TS, AS partition, self-contained AS prompts | GS owner -> TS owner -> AS authors | Put the TS-owner envelope in `spawn_agent.message` |
| Planning AS author — `roles/planning-as-author.md` | Haiku | Subagent assigned one-AS duties | Author exactly one one-file AS artifact | TS owner -> AS author | Put one-AS authoring envelope in `spawn_agent.message` |
| Execution root — `roles/execution-root-orchestrator.md` | Fable | Root Orchestrator | Global admitted scope, dependency waves, completion | Root -> GS owners | Root position implements duties; tier is metadata |
| Execution GS owner — `roles/execution-gs-owner.md` | Opus | Subagent assigned GS execution duties | One GS execution branch and TS delegation | Root -> GS owner -> TS owners | Put GS execution envelope in `spawn_agent.message` |
| Execution TS owner — `roles/execution-ts-owner.md` | Sonnet | Subagent assigned TS execution duties | One TS branch, fresh AS prompts, same-file serialization | GS owner -> TS owner -> AS executors | Put TS execution envelope in `spawn_agent.message` |
| Execution AS executor — `roles/execution-as-executor.md` | Haiku | Subagent assigned one-AS duties | Execute exactly one AS against one target file | TS owner -> AS executor | Put isolated one-AS envelope in `spawn_agent.message` |
| Refactor root — `roles/refactor-orchestrator.md` | Fable | Root Orchestrator | Research routing, complexity decision, user escalation, completion | Root -> researcher/owner -> coder | Root routes by reports; never claims a model switch |
| Refactor default researcher/owner — `roles/refactor-sonnet-researcher.md` | Sonnet | Subagent assigned default researcher/owner duties | Default research; medium-complexity prompt ownership when assigned | Root -> standard researcher/owner | Prompt assigns the duty; runtime model is accepted |
| Refactor escalation researcher/owner — `roles/refactor-opus-researcher.md` | Opus | Subagent assigned escalation researcher/owner duties | Complex research; high-complexity prompt ownership when assigned | Root -> high-complexity researcher/owner | Wider prompt replaces tier-based model selection |
| Refactor coder — `roles/refactor-haiku-coder.md` | Haiku | Subagent assigned one bounded coding duty | Implement one self-contained delegated change | Implementation owner -> bounded coder | Put bounded coding envelope in `spawn_agent.message`; no model identity is inferred |

## Triggered auxiliary translations

| Source auxiliary role | Codex destination | Owner/child position | Duties | Model behavior |
| --- | --- | --- | --- | --- |
| Conscience/adversarial reviewer | Independent read-only subagent | Child of artifact owner | Challenge architecture, scope expansion, freeze readiness, or unresolved alternatives | Independence comes from context isolation, not model identity |
| Tester | Independent read-only subagent | Child of executor or branch owner | Run exact checks and report evidence; never edit | Any runtime-assigned subagent performs the tester prompt |
| Owner bridge for spawn-unavailable AS work | Root- or higher-owner-spawned bounded subagent | Child of the nearest owner with spawn capacity | Execute prepared child prompt without absorbing lower-level work | Bridge changes parent position only, not model |

## Project execution-standard aliases

`docs/standards/planning/atomic_step_execution_standard.yaml` predates this
compatibility layer and contains concrete `model` fields. Those fields are
explicitly non-binding source-role recommendations under this matrix.

| Execution-standard role | Codex destination | Owner/child position | Preserved duties | Treatment of the standard's model field |
| --- | --- | --- | --- | --- |
| `owner` / `primary_orchestrator` | Root Orchestrator | Root | Global wave map, branch assignment, escalation, completion | Semantic label only; no model is selected or claimed |
| `mini` | Ordinary subagent assigned TS context-former/verifier duties | Child of owner, parent of AS executors | One GS/TS branch, per-TS context, AS dispatch, wait, verification | `gpt-5.4-mini` is recommendation metadata only and may be ignored |
| `spark` | Ordinary subagent assigned one bounded AS executor duty | Child of mini or owner bridge | One AS, one target file, exact checks and report | `gpt-5.3-codex-spark` is recommendation metadata only and may be ignored |

The owner/mini/spark hierarchy and methodology remain normative; their model
strings do not create an entry condition or blocker.

## Invocation translation

Use the bundle `codex.delegation/v1` envelope with both fields:

```yaml
source_role:
  tier: "Fable | Opus | Sonnet | Haiku | none"
  semantics: "<source responsibility description>"
  recommendation_only: true
codex_role:
  position: "root_orchestrator | subagent"
  duties: "<exact prompt-assigned role>"
runtime_model:
  selection_required: false
  actual_identity: unknown_unless_runtime_proves
```

The YAML above is embedded in `spawn_agent.message`; none of its fields are
additional tool arguments. Lifecycle control uses `send_message`,
`followup_task`, `wait_agent`, `list_agents`, and `interrupt_agent` exactly as
defined in `CODEX_RUNTIME_COMPATIBILITY.md`. The parent must not delay, fail, or
misreport dispatch because a source tier cannot be selected.
