# T-004 Prompt Assembly Context

Read first: `docs/standards/planning/atomic_step_execution_standard.yaml`

Inherited contexts:
- Base: `docs/plans/2026-07-02-plan-manager/execution_context/base.md`
- G context: `docs/plans/2026-07-02-plan-manager/execution_context/G-002-derived-views/context.md`

Assigned branch:
- GS: G-002-derived-views
- TS: T-004-prompt-assembly
- T README: `docs/plans/2026-07-02-plan-manager/G-002-derived-views/T-004-prompt-assembly/README.yaml`
- Atomic steps: `docs/plans/2026-07-02-plan-manager/G-002-derived-views/T-004-prompt-assembly/atomic_steps/`

Target file state before execution:
- `plan_manager/views/prompt_assembly.py`: missing.

Allowed write scope:
- `plan_manager/views/prompt_assembly.py`

Escalation:
- The AS prompt for `step_content` quotes `plan_manager.storage.canonical.canonical_json` as returning `str`.
- The current repository file `plan_manager/storage/canonical.py` defines `canonical_json(value: object) -> bytes` and encodes JSON with UTF-8.
- Editing `plan_manager/storage/canonical.py` is outside G-002/T-004 AS target scope.
- Implementing T-004 exactly would produce bytes where the AS signatures require `str`; changing T-004 locally to decode would be a normative deviation from the exact AS body.
- Status for this branch: BLOCKED pending owner decision.

