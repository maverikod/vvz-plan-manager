# G-006 Runtime Config Execution Context

Inherited base context: `docs/plans/2026-07-02-plan-manager/execution_context/base.md`

Execution standard: `docs/standards/planning/atomic_step_execution_standard.yaml`

Active plan root: `docs/plans/2026-07-02-plan-manager`

## G-Agent Scope

- Responsible branch: `G-006-runtime-config`.
- No sibling G branch is in scope.
- User communication is Russian; repository artifacts and code are English.
- Assumptions are forbidden. Ambiguity, conflict, missing contract, or required scope outside `G-006` must be escalated upward.
- HRS prose must not be rewritten.
- Coverage matrices must not be materialized.
- Preserve unrelated dirty worktree changes.
- T-agent model: `gpt-5.4-mini`.
- A-agent model: `gpt-5.3-codex-spark` or cheapest available coding worker.
- Every T-agent must begin by reading `docs/standards/planning/atomic_step_execution_standard.yaml` in full before acting.
- Every A-agent context must include inherited base, G, and T context, exact AS file content, current target-file state or an explicit missing-file marker, allowed write scope, and verification commands.
- Every A-agent may edit only its AS `target_file` unless it escalates.

## Full G-006 README

```yaml
step_id: G-006
name: runtime-config
description: >
  This step realizes ServerRuntime (C-027): the server is built on the
  mcp-proxy-adapter platform (version 8.10.15 or newer), which owns the entire
  external surface — the JSON-RPC endpoint with single and batch calls, the
  asynchronous endpoint, health, command listing, heartbeat, WebSocket job push,
  and OpenAPI and help output. The server registers command classes only; it
  must not patch platform internals and must not add custom HTTP routes.
  Supported protocols are http, https, and mtls exactly as provided by the
  platform configuration. The implementation context is fixed: Python 3.12 or
  newer, with the production package root `plan_manager/` at the repository
  root and modules as dotted paths beneath it.

  The bootstrap sequence is fixed: the entry point receives a configuration file
  path, validates configuration, creates the application through the platform
  application factory, and runs it with the platform's server engine. Commands
  enter the registry through the platform hook mechanism — a registration
  callback registers every command class under the custom category — and the
  modules needed by spawned worker processes are declared through the platform
  auto-import facility. Long-running operations (full-plan scoring, large
  cascade previews) opt into the platform queue manager with job-id and polling
  semantics, while quick navigation and single-node reads stay synchronous.

  Configuration (C-028) is a single JSON file. Platform-owned sections (server,
  registration, auth, queue manager, and optional ssl/transport/security) follow
  platform semantics unchanged; the server adds exactly one custom top-level
  section, which the platform tolerates by design (unknown sections produce
  warnings only). That section is validated at startup by an own Pydantic model
  with an allowed-keys check, following the reference consumer pattern: JSON
  parsing stays platform-native dictionary access, while the Pydantic model is
  the single definition of allowed fields, types, and defaults. Invalid
  configuration aborts startup with an explicit report.

  The custom section carries: the required database connection parameters for
  the in-container PostgreSQL (C-035) — socket or host, port, database name,
  user — with the password taken only from a mounted secrets file and never from
  configuration; the optional embedding service settings (URL, model, timeout);
  optional scoring settings carrying published defaults — threshold 85,
  aggregation minimum, concept_weights uniform 1.0, embedding_serialization
  definition-only, estimator_weights (deterministic coverage 1.0, the
  embedding-based pair sharing a single vote of 1.0, executor simulation 1.0),
  and trust_floor 0.2; optional PlanSchema overrides for the exchange layout;
  and the default export root used when a caller passes a relative path. The
  per-plan context budget is plan data supplied by the user, not a configuration
  field. No field of this section is ever taken from request parameters. Proxy participation is configured through the platform
  registration section (registration URL, heartbeat URL and interval, server
  id, instance UUID); registration and heartbeat run automatically on startup
  when enabled, and the server functions identically with registration
  disabled. The runtime also includes the reader of the build-time embedded
  package data — the build information and the operator documentation
  (C-025) — serving the server self-description; the payloads themselves are
  produced by the release pipeline.
concepts: [C-027, C-028, C-025]
relations:
- { from_concept: C-027, to_concept: C-024, type: owns }
- { from_concept: C-027, to_concept: C-028, type: consumes }
- { from_concept: C-027, to_concept: C-035, type: uses }
source_labels: ["{h9s1}", "{f2x7}", "{g5j8}", "{w7l3}", "{u1p9}", "{n6a4}", "{c3k8}", "{d8o2}", "{e5m7}", "{y1j5}"]
depends_on: [G-001]
tactical_steps: [T-001, T-002, T-003, T-004]
status: draft
```

## Relevant Parallelization Map Entry

```yaml
- branch_id: G-006
  name: runtime-config
  status: draft
  depends_on:
  - G-001
  tactical_steps:
  - branch_id: G-006/T-001
    name: config-model
    status: draft
    mini_assignment:
      model: gpt-5.4-mini
      context:
      - docs/plans/2026-07-02-plan-manager/G-006-runtime-config/README.yaml
      - docs/plans/2026-07-02-plan-manager/G-006-runtime-config/T-001-config-model/README.yaml
      - docs/plans/2026-07-02-plan-manager/G-006-runtime-config/T-001-config-model/atomic_steps
      forbidden_context:
      - sibling TS directories
      - other GS directories unless owner escalates
    counts:
      atomic_steps: 7
      target_files: 1
      parallel_waves: 7
    target_file_sequences:
    - target_file: plan_manager/runtime/config.py
      sequence:
      - G-006/T-001/A-001
      - G-006/T-001/A-002
      - G-006/T-001/A-003
      - G-006/T-001/A-004
      - G-006/T-001/A-005
      - G-006/T-001/A-006
      - G-006/T-001/A-007
    parallel_waves:
    - - G-006/T-001/A-001
    - - G-006/T-001/A-002
    - - G-006/T-001/A-003
    - - G-006/T-001/A-004
    - - G-006/T-001/A-005
    - - G-006/T-001/A-006
    - - G-006/T-001/A-007
    unresolved_cycles: []
  - branch_id: G-006/T-002
    name: runtime-accessors
    status: draft
    counts:
      atomic_steps: 7
      target_files: 1
      parallel_waves: 7
    target_file_sequences:
    - target_file: plan_manager/runtime/context.py
      sequence:
      - G-006/T-002/A-001
      - G-006/T-002/A-002
      - G-006/T-002/A-003
      - G-006/T-002/A-004
      - G-006/T-002/A-005
      - G-006/T-002/A-006
      - G-006/T-002/A-007
    parallel_waves:
    - - G-006/T-002/A-001
    - - G-006/T-002/A-002
    - - G-006/T-002/A-003
    - - G-006/T-002/A-004
    - - G-006/T-002/A-005
    - - G-006/T-002/A-006
    - - G-006/T-002/A-007
    unresolved_cycles: []
  - branch_id: G-006/T-003
    name: build-info-reader
    status: draft
    counts:
      atomic_steps: 5
      target_files: 2
      parallel_waves: 5
    target_file_sequences:
    - target_file: plan_manager/_build/__init__.py
      sequence:
      - G-006/T-003/A-001
    - target_file: plan_manager/runtime/build_info.py
      sequence:
      - G-006/T-003/A-002
      - G-006/T-003/A-003
      - G-006/T-003/A-004
      - G-006/T-003/A-005
    parallel_waves:
    - - G-006/T-003/A-001
    - - G-006/T-003/A-002
    - - G-006/T-003/A-003
    - - G-006/T-003/A-004
    - - G-006/T-003/A-005
    unresolved_cycles: []
  - branch_id: G-006/T-004
    name: bootstrap
    status: draft
    counts:
      atomic_steps: 4
      target_files: 1
      parallel_waves: 4
    target_file_sequences:
    - target_file: plan_manager/main.py
      sequence:
      - G-006/T-004/A-001
      - G-006/T-004/A-002
      - G-006/T-004/A-003
      - G-006/T-004/A-004
    parallel_waves:
    - - G-006/T-004/A-001
    - - G-006/T-004/A-002
    - - G-006/T-004/A-003
    - - G-006/T-004/A-004
    unresolved_cycles: []
```

## G-Level Execution Constraints

- `G-006` depends on `G-001`; this assignment is limited to executing `G-006` as provided.
- All T branches under `G-006` are in scope: `T-001`, `T-002`, `T-003`, `T-004`.
- Inside each T branch, AS waves are serialized because every listed wave contains a single AS and explicit dependencies form a chain.
- T-agent contexts must not include sibling TS directories.
- `T-001` target file sequence: `plan_manager/runtime/config.py`.
- `T-002` target file sequence: `plan_manager/runtime/context.py`.
- `T-003` target file sequences: `plan_manager/_build/__init__.py`, then `plan_manager/runtime/build_info.py`.
- `T-004` target file sequence: `plan_manager/main.py`.
