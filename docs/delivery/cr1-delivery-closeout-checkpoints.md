# CR-1 Delivery Closeout and Release-Checkpoint Procedure

## Purpose

This document specifies the DeliveryAcceptance (C-016) closeout procedure for change request CR-1 "command-surface quality". It details how the fourteen CR-1-scope roadmap todos are resolved and closed, and prescribes the ordered, user-gated release-checkpoint sequence through which CR-1's changes are shipped to production.

## Roadmap Todo Closeout Procedure

Each of the following fourteen roadmap todo identifiers, tracked in plan `planmgr-post-runtime-roadmap`, is resolved via `todo_resolve` and then closed via `todo_close`. The `todo_close` call MUST supply its `execution_result` parameter referencing the shipping release that delivers CR-1. Per CrudDeletionIntegrity (C-008), `todo_close` accepts an execution_result parameter, eliminating the need for a separate call to record the execution result during the resolve-then-close sequence.

- 14897f7a
- 25440a28
- 7b924c17
- 751b8983
- 1cc5da59
- c1d00e66
- a6600876
- 630cb33c
- d1299740
- a686dc84
- 7a84c4bf
- 887eb8a3
- ec772710
- 991e5c8c

No todo in this set is closed without an execution_result reference to the shipping release. A todo closed without that reference has not completed this procedure's closeout step.

## Release-Checkpoint Discipline

Shipping CR-1 proceeds through four checkpoints, in this exact order. Each checkpoint is a HARD CHECKPOINT and is taken only on the user's explicit order—never inferred from a passed gate, from automated test results, or from a previously taken checkpoint.

1. **Plan freeze** — the plan's frozen artifacts become the immutable input to execution. Requires the user's explicit order.
2. **Version bump** — the project version is incremented in `pyproject.toml`, the single version source for plan-manager. Requires the user's explicit order.
3. **Build** — the project is built by running `./build.sh`. Requires the user's explicit order.
4. **Deploy** — the built artifact is deployed following the documented deployment pipeline for plan-manager. Requires the user's explicit order.

If the user's explicit order for a given checkpoint has not been given, that checkpoint and every checkpoint after it in this ordered sequence remain blocked. No checkpoint is taken on the assumption that the user would want it taken.
