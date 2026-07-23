# CR-5a Delivery Closeout and Release-Checkpoint Procedure

## Purpose

This document specifies the closeout procedure for change request CR-5a ("agent-configuration data layer"), detailing how its roadmap todos are resolved and closed, and prescribing the ordered, user-gated release-checkpoint sequence through which CR-5a's changes are shipped to production.

## Roadmap Todo Closeout Procedure

Identify the roadmap todos associated with CR-5a's agent-configuration group by re-querying `todo_queue` / `todo_list` on plan `planmgr-post-runtime-roadmap`. The roadmap's live queue is the sole authoritative source of which todos to close. Each identified todo is resolved via `todo_resolve` and then closed via `todo_close`; the `todo_close` call MUST supply its `execution_result` parameter referencing the shipping release that delivers CR-5a.

A todo closed without an `execution_result` reference has not completed this procedure's closeout step. These todos are closed only after the mandatory post-deploy smoke below records completion.

## Release-Checkpoint Discipline

Shipping CR-5a proceeds through four checkpoints, in this exact order. Each checkpoint is a HARD CHECKPOINT and is taken only on the user's explicit order — never inferred from a passed gate, from automated test results, or from a previously taken checkpoint.

1. **Plan freeze** — the plan's frozen artifacts become the immutable input to execution. Requires the user's explicit order.
2. **Version bump** — the project version is incremented in `pyproject.toml`, the single version source for plan-manager. Requires the user's explicit order.
3. **Build** — the project is built by running `./build.sh`. Requires the user's explicit order.
4. **Deploy** — the built artifact is deployed following the documented deployment pipeline for plan-manager. Requires the user's explicit order.

If the user's explicit order for a given checkpoint has not been given, that checkpoint and every checkpoint after it in this ordered sequence remain blocked. No checkpoint is taken on the assumption that the user would want it taken.

## Mandatory Post-Deploy Smoke

After the Deploy checkpoint, `docs/delivery/cr5a-live-smoke-procedure.md` is executed before CR-5a is considered shipped. Only after that procedure records completion are the roadmap todos above closed with their execution_result reference.
