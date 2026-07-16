# CR-3 Delivery Closeout and Release-Checkpoint Procedure

## Purpose

This document specifies the closeout procedure for change request CR-3 ("verification and observability"), detailing how its five roadmap todos are resolved and closed, and prescribing the ordered, user-gated release-checkpoint sequence through which CR-3's changes are shipped to production.

## Roadmap Todo Closeout Procedure

Each of the following five roadmap todo identifiers, tracked in plan `planmgr-post-runtime-roadmap`, is resolved via `todo_resolve` and then closed via `todo_close`. The `todo_close` call MUST supply its `execution_result` parameter referencing the shipping release that delivers CR-3.

- ed0c6e98
- 5a66040e
- 17573ee7
- 630d6132
- 9f667cd9

No todo in this set is closed without an execution_result reference to the shipping release. A todo closed without that reference has not completed this procedure's closeout step.

## Release-Checkpoint Discipline

Shipping CR-3 proceeds through four checkpoints, in this exact order. Each checkpoint is a HARD CHECKPOINT and is taken only on the user's explicit order — never inferred from a passed gate, from automated test results, or from a previously taken checkpoint.

1. **Plan freeze** — the plan's frozen artifacts become the immutable input to execution. Requires the user's explicit order.
2. **Version bump** — the project version is incremented in `pyproject.toml`, the single version source for plan-manager. Requires the user's explicit order.
3. **Build** — the project is built by running `./build.sh`. Requires the user's explicit order.
4. **Deploy** — the built artifact is deployed following the documented deployment pipeline for plan-manager. Requires the user's explicit order.

If the user's explicit order for a given checkpoint has not been given, that checkpoint and every checkpoint after it in this ordered sequence remain blocked. No checkpoint is taken on the assumption that the user would want it taken.

## Mandatory Post-Deploy Smoke

After the Deploy checkpoint, docs/delivery/cr3-live-smoke-procedure.md is executed before CR-3 is considered shipped. Only after that procedure records completion are the five roadmap todos above closed with their execution_result reference.
