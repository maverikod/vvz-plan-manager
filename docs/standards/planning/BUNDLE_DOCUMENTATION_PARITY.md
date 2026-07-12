# Bundle documentation parity

Source archive: `codex-prompt-bundle-2026-07-10-codex-refactor.tar.gz`

This inventory accounts for every one of the 67 source files as a
prompt, methodology, command-reference, routing-reference, or documentation
artifact. The project-only
`docs/standards/planning/atomic_step_execution_standard.yaml` and this parity
file are outside the source count.

Category totals: installed exact 40, identical existing 1, project superseded 4, merged 21, intentionally not applicable 1. Missing: 0. Unaccounted: 0.

## Installed exact (40)

These files are present at the archive-relative project path and are byte-identical to the extracted source.

- `prompts/codex/command-blocks/README.md`
- `prompts/codex/command-blocks/cas-preview-addressing.md`
- `prompts/codex/command-blocks/cas-research.md`
- `prompts/codex/command-blocks/editor-addressing.md`
- `prompts/codex/command-blocks/editor-lifecycle.md`
- `prompts/codex/command-blocks/embedding-service.md`
- `prompts/codex/command-blocks/mac-model-access.md`
- `prompts/codex/command-blocks/planmgr-authoring.md`
- `prompts/codex/command-blocks/planmgr-execution.md`
- `prompts/codex/command-blocks/svo-chunker.md`
- `prompts/codex/command-blocks/terminal-host.md`
- `prompts/codex/command-blocks/terminal-sandbox.md`
- `prompts/tool-routing/help/ai-editor-mutation.yaml`
- `prompts/tool-routing/help/cas-code-analysis.yaml`
- `prompts/tool-routing/help/cas-cross-search.yaml`
- `prompts/tool-routing/help/cas-detailed-preview.yaml`
- `prompts/tool-routing/help/cas-file-lifecycle.yaml`
- `prompts/tool-routing/help/cas-refactoring.yaml`
- `prompts/tool-routing/help/plan-authoring.yaml`
- `prompts/tool-routing/help/plan-core.yaml`
- `prompts/tool-routing/help/plan-execution.yaml`
- `prompts/tool-routing/help/plan-read.yaml`
- `prompts/tool-routing/help/plan-verification.yaml`
- `prompts/tool-routing/help/server-error-recovery.yaml`
- `prompts/tool-routing/help/terminal-host-emergency.yaml`
- `prompts/tool-routing/help/terminal-project-sandbox.yaml`
- `prompts/tool-routing/manifest.yaml`
- `prompts/tool-routing/triggers/00-server-error-recovery.yaml`
- `prompts/tool-routing/triggers/01-cross-search.yaml`
- `prompts/tool-routing/triggers/02-detailed-view.yaml`
- `prompts/tool-routing/triggers/03-code-analysis.yaml`
- `prompts/tool-routing/triggers/04-project-edit.yaml`
- `prompts/tool-routing/triggers/05-plan-read.yaml`
- `prompts/tool-routing/triggers/06-plan-authoring.yaml`
- `prompts/tool-routing/triggers/07-plan-verification.yaml`
- `prompts/tool-routing/triggers/08-plan-execution.yaml`
- `prompts/tool-routing/triggers/09-refactoring.yaml`
- `prompts/tool-routing/triggers/10-file-lifecycle.yaml`
- `prompts/tool-routing/triggers/11-terminal-project-sandbox.yaml`
- `prompts/tool-routing/triggers/12-terminal-host-emergency.yaml`

## Identical existing (1)

The project already contained the same bytes, so no rewrite was performed.

- `docs/standards/planning/metadatastd.yaml`

## Project superseded (4)

The archive stock file conflicts with an intentional plan_manager specialization. The existing project file is authoritative and retains computed-only coverage, separate atomic-step files, zero-trust verification, and cascade semantics.

- `docs/standards/planning/atomic_step_creation_standard.yaml`
- `docs/standards/planning/hrs_mrs_gs_consistency_verification_standard.yaml`
- `docs/standards/planning/plan_standard_machine.yaml`
- `docs/standards/planning/tactical_step_creation_standard.yaml`

## Merged (21)

These files retain the bundle methodology while incorporating only project identity, runtime-role compatibility, current live command names/session semantics, project-standard indexing, or the required YAML syntax repair.

- `AGENTS.md`
- `docs/standards/planning/README.md`
- `docs/standards/planning/TERMINAL_WORKFLOW.yaml`
- `docs/standards/planning/code_analysis_fs_instructions.yaml`
- `docs/standards/planning/code_analysis_search_instructions.yaml`
- `docs/standards/planning/code_analysis_universal_editing_instructions.yaml`
- `docs/standards/planning/editor_ca_workflow_prompt.yaml`
- `prompts/codex/roles/common.md`
- `prompts/codex/roles/execution-as-executor.md`
- `prompts/codex/roles/execution-gs-owner.md`
- `prompts/codex/roles/execution-root-orchestrator.md`
- `prompts/codex/roles/execution-ts-owner.md`
- `prompts/codex/roles/planning-as-author.md`
- `prompts/codex/roles/planning-gs-owner.md`
- `prompts/codex/roles/planning-hrs-mrs-owner.md`
- `prompts/codex/roles/planning-ts-owner.md`
- `prompts/codex/roles/refactor-haiku-coder.md`
- `prompts/codex/roles/refactor-opus-researcher.md`
- `prompts/codex/roles/refactor-orchestrator.md`
- `prompts/codex/roles/refactor-sonnet-researcher.md`
- `prompts/codex/roles/researcher.md`

## Intentionally not applicable at the archive-relative path (1)

The repository root README is the Plan Manager product README and is not overwritten by the bundle overview. The bundle overview is retained at `prompts/codex/README.md`, and its complete prompt methodology is indexed from `AGENTS.md`.

- `README.md`

## Conflict decisions

- `AGENTS.md`: full bundle baseline plus plan_manager identity, server-project selection, and recommendation-only Codex role translation.
- Four stock planning standards: superseded by project-authoritative variants; normative meaning is not merged across incompatible storage layouts.
- `metadatastd.yaml`: identical existing file.
- Six server-workflow/index files: bundle methodology retained; stale `project_cross_search`, session ownership, server ids, unavailable file-trash/restore commands, and the invalid `UNKNOWN_FORMAT` scalar were reconciled with current prepared help.
- Source root `README.md`: root collision intentionally avoided; overview relocated to `prompts/codex/README.md`.

## Preservation guarantees

- No file under `docs/plans/` is changed.
- Human-owned HRS prose is unchanged.
- Existing project planning standards are not rewritten.
- Model fields in standards remain unchanged and are interpreted as recommendation-only by the compatibility overlay.
- Production code is outside this documentation merge.
