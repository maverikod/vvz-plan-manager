# Source bundle parity accounting

Source archive:
`/home/vasilyvz/projects/prompts/new-prompts/codex-prompt-bundle-2026-07-10-codex-refactor.tar.gz`

## Root files

- Source `AGENTS.md`: installed in full as the baseline, with a project overlay,
  server-project selection, and agent-runtime compatibility translation.
- Source root `README.md`: relocated to `prompts/codex/README.md` because the
  repository root README documents the Plan Manager product.

## Role prompts

All 14 source role files are installed under `prompts/codex/roles/`. Their
planning, execution, refactor, isolation, tool, escalation, and completion duties
are preserved. Only model-class declarations and model-named dispatch wording are
translated through `ROLE_TRANSLATION.md`.

No role file is omitted.

## Command blocks and routing

- All 12 source command-block files are installed under
  `prompts/codex/command-blocks/` without methodological reduction.
- The routing manifest, all 13 triggers, and all 14 help packs are installed
  under `prompts/tool-routing/`.
- Server error recovery, CAS search/preview/AST analysis, refactor impact
  preflight, AI Editor lifecycle, file lifecycle, Plan Manager authoring and
  execution, sandbox terminal, and host emergency routes are retained.

No command block, trigger, or help pack is omitted.

## Standards

The repository's existing planning standards replace the stock copies because
they are the project-authoritative specializations:

- `plan_standard_machine.yaml`: computed coverage views and separate AS files
- `hrs_mrs_gs_consistency_verification_standard.yaml`: computed verification views
- `tactical_step_creation_standard.yaml`: computed TS coverage
- `atomic_step_creation_standard.yaml`: computed traceability and separate AS files
- `metadatastd.yaml`: byte-equivalent to the source bundle

The project-only `atomic_step_execution_standard.yaml` is retained and referenced.
Its owner/mini/spark hierarchy remains normative, while its concrete `model`
fields are explicitly superseded by the recommendation-only policy and the
alias table in `ROLE_TRANSLATION.md`; the tracked standard itself is unchanged.

The source server-workflow methodology is installed as additional files:

- `README.md`
- `TERMINAL_WORKFLOW.yaml`
- `code_analysis_search_instructions.yaml`
- `code_analysis_fs_instructions.yaml`
- `code_analysis_universal_editing_instructions.yaml`
- `editor_ca_workflow_prompt.yaml`

The invalid plain scalar in source `editor_ca_workflow_prompt.yaml` at the
`UNKNOWN_FORMAT` entry is quoted so the installed YAML parses. This is a syntax
repair only; the lifecycle methodology is unchanged.

Current prepared help also supersedes stale command references in the source
workflow documents: `project_cross_search` is translated to `search` plus its
status/page/close lifecycle; AI Editor uses the Code Analysis client session;
server ids use their `-vvz` registrations; unavailable file-trash and backup
restore commands are documented as capability gaps instead of callable routes.
These are command-schema consistency repairs, not methodological omissions.

No source standard is silently omitted. Stock planning files are superseded by
the named project specializations rather than duplicated.

## Codex runtime compatibility accounting

The source methodology is preserved and the following prompt/control-plane files
implement the actual Codex transport:

- `AGENTS.md`: exact collaboration lifecycle, delegation-message transport,
  completion evidence, and namespace-neutral MCP Proxy bootstrap.
- `prompts/codex/CODEX_RUNTIME_COMPATIBILITY.md`: authoritative mapping for
  `spawn_agent`, `send_message`, `followup_task`, `wait_agent`, `list_agents`,
  `interrupt_agent`, and the proxy logical operations.
- `prompts/codex/CODEX_COMPATIBILITY_DRY_RUN.md`: scenario-based static transport
  evidence and methodology coverage.
- `prompts/codex/README.md`: compatibility entry points.
- `prompts/codex/ROLE_TRANSLATION.md`: source tiers and owner/mini/spark names
  mapped to prompt duties rather than invented runtime role APIs.
- Role files changed only in runtime wording: `prompts/codex/roles/common.md`,
  `planning-as-author.md`, `planning-gs-owner.md`, `planning-ts-owner.md`,
  `execution-as-executor.md`, `execution-gs-owner.md`,
  `execution-ts-owner.md`, `refactor-haiku-coder.md`,
  `refactor-opus-researcher.md`, `refactor-sonnet-researcher.md`, and
  `researcher.md`. They now describe ordinary children with prompt-assigned
  duties; substantive role duties are unchanged. The three root-role files and
  `planning-hrs-mrs-owner.md` needed no compatibility edit.
- `prompts/tool-routing/manifest.yaml` and
  `prompts/tool-routing/CODEX_MCP_PROXY_ADAPTER.yaml`: per-session callable
  discovery before lazy trigger loading.
- `prompts/tool-routing/triggers/08-plan-execution.yaml` and
  `prompts/tool-routing/help/plan-execution.yaml`: model selection removed as an
  executable claim while Plan Manager execution methodology remains intact.

Methodology categories retained: root ownership, role and level confinement,
context isolation, machine-readable delegation and reporting, vertical
escalation, descendant completion barrier, planning hierarchy, cascade,
mechanical and semantic plan gates, dependency waves, CAS research and
structural analysis, AI Editor lifecycle, file lifecycle, sandbox fallback,
host-emergency authorization, and live help/health recovery.

No production source, plan artifact, HRS, or normative planning standard was
modified for this compatibility layer.
