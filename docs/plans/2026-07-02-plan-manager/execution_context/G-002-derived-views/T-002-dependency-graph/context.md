# T-002 Dependency Graph Context

Read first: `docs/standards/planning/atomic_step_execution_standard.yaml`

Inherited contexts:
- Base: `docs/plans/2026-07-02-plan-manager/execution_context/base.md`
- G context: `docs/plans/2026-07-02-plan-manager/execution_context/G-002-derived-views/context.md`

Assigned branch:
- GS: G-002-derived-views
- TS: T-002-dependency-graph
- T README: `docs/plans/2026-07-02-plan-manager/G-002-derived-views/T-002-dependency-graph/README.yaml`
- Atomic steps: `docs/plans/2026-07-02-plan-manager/G-002-derived-views/T-002-dependency-graph/atomic_steps/`

Target file state before execution:
- `plan_manager/views/dependency_graph.py`: missing.

Allowed write scope:
- `plan_manager/views/dependency_graph.py`

Parallelization map entry:
- Target file sequence: A-001 through A-010.
- All waves are serialized because every AS targets the same file.

Verification commands:
- `python -m py_compile plan_manager/views/dependency_graph.py`
- import smoke and hand-built Step graph checks for topological order, cycle edges, waves, prerequisites, dependents, and impact set.
- unfinished marker scan on `plan_manager/views/dependency_graph.py`.

