# Block ID: planmgr-execution

Server:
- `planmgr`

Use for:
- Executing admitted plan scopes
- Building deduplicated execution context

Confirmed command group:
- `plan_validate`
- `plan_prompt_chain`
- `branch_prompt`
- `graph_order`
- `graph_parallel_map`
- `branch_weak`
- `step_runtime_get`, `step_runtime_list`, `step_runtime_report`

Confirmed laws:
- Run `plan_validate` before relying on execution surfaces
- `plan_prompt_chain` is deduplicated and role-scoped
- For `role=coder`, assembly intentionally reduces to `AS + tool_instructions`
- `branch_prompt` returns token estimate vs context budget
