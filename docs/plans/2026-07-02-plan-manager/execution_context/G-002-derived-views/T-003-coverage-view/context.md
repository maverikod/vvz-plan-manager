# T-003 Coverage View Context

Read first: `docs/standards/planning/atomic_step_execution_standard.yaml`

Inherited contexts:
- Base: `docs/plans/2026-07-02-plan-manager/execution_context/base.md`
- G context: `docs/plans/2026-07-02-plan-manager/execution_context/G-002-derived-views/context.md`

Assigned branch:
- GS: G-002-derived-views
- TS: T-003-coverage-view
- T README: `docs/plans/2026-07-02-plan-manager/G-002-derived-views/T-003-coverage-view/README.yaml`
- Atomic steps: `docs/plans/2026-07-02-plan-manager/G-002-derived-views/T-003-coverage-view/atomic_steps/`

Target file state before execution:
- `plan_manager/views/coverage.py`: missing.
- `plan_manager/views/objects.py`: missing.

Allowed write scope:
- `plan_manager/views/coverage.py`
- `plan_manager/views/objects.py`

Parallelization map entry:
- `coverage.py`: A-001, A-002, A-003, A-004, A-005.
- `objects.py`: A-006, A-007, A-008.
- Independent file chains may be checked separately; each chain is serialized by target file.

Verification commands:
- `python -m py_compile plan_manager/views/coverage.py plan_manager/views/objects.py`
- import smoke for coverage and objects modules.
- hand-built `object_findings` and `module_of` checks.
- unfinished marker scan on both target files.

