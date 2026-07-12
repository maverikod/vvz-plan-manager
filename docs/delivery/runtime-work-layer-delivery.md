# Runtime Work Layer Delivery Runbook

## Purpose

This runbook documents PlanFirstDeliveryDiscipline, the delivery-process invariant for any implementation work produced under the plan-manager runtime-work-layer-integration effort: work is organized as a separate refactoring-and-extension plan of plan-manager, bound to the planner's project; a full artifact cascade is developed; implementation is gated on verified completeness; and atomic-step authoring follows a fixed rule set. This paragraph is the executive summary of the sections below.

## Plan-first organization

Per the plan-first delivery discipline (C-036): "The work must be organized as a separate refactoring-and-extension plan of plan-manager, bound to the planner's project." This means any implementation work is never done as ad hoc, unplanned changes — it is always the execution of a distinct, formally tracked plan that is bound (associated) to the project of the planner (the entity requesting the work).

## Full cascade requirement

Per the plan-first delivery discipline (C-036): "A full cascade must be developed: HRS; MRS; GS; TS; AS." HRS (source spec), MRS (machine spec), GS (global step), TS (tactical step), and AS (atomic step) are the five levels of the plan artifact hierarchy, and every one of the five levels must be authored for the plan before any implementation begins — no level may be skipped.

## MRS-completeness gate

Per the plan-first delivery discipline (C-036): "Implementation must not start before the semantic completeness of the MRS and the decomposition are verified." This is a hard gate: coding/implementation work is forbidden to start until the machine spec (MRS) has been checked for semantic completeness against the source spec, and its decomposition into global/tactical/atomic steps has likewise been verified complete.

## Atomic-step authoring rules

Per the plan-first delivery discipline (C-036): "When creating AS, observe: one AS — one file; exact target_file; exact operation; autonomous prompt; verification; dependencies; priority; project; no duplication of work."

- One AS touches exactly one file (one-AS-one-file rule)
- Exact target_file: the file path the AS creates or modifies is stated precisely
- Exact operation: one of create_file, modify_file, delete_file, rename_file, stated precisely
- Autonomous prompt: the AS prompt is fully self-contained, requiring no other file or step to be read
- Verification: the AS specifies how its result is verified
- Dependencies: the AS states which other atomic steps, if any, must complete first
- Priority: the AS states its execution order among atomic steps touching the same file
- Project: the AS is bound to the project of the plan it belongs to
- No duplication of work: no two atomic steps perform the same action on the same target

## Delivery pipeline

Once a plan's cascade reaches the gates above, delivery proceeds through these ordered stages:

1. Plan complete — the full HRS through AS cascade has been authored for the plan
2. MRS completeness verified — the semantic completeness of the MRS and its decomposition has been checked and passed
3. Cascade authored — every global step, tactical step, and atomic step required by the plan exists
4. Mechanical gate green — the plan's automated consistency/coverage checks pass with no findings
5. Commit and freeze — the plan's artifacts are committed and frozen, becoming immutable inputs to execution
6. Execution — the frozen atomic steps are executed, producing the actual code/file changes
7. Version bump — the project version is incremented in `pyproject.toml`, the single version source for plan-manager
8. Build — the project is built by running `./build.sh`
9. Deploy — the built artifact is deployed following the documented deployment pipeline for plan-manager
