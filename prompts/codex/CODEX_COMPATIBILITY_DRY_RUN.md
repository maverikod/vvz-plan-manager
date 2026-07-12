# Codex compatibility dry runs

These are static transport dry runs against the callable surface observed during
the adaptation. They do not claim that a server call or child task was executed.

| Scenario | Transport trace | Expected evidence | Result |
| --- | --- | --- | --- |
| Isolated child dispatch | Build context refs -> put `codex.delegation/v1` in `message` -> `spawn_agent({task_name, fork_turns, message})` | Returned agent id; no unsupported model/role arg | PASS |
| Upward ambiguity | Child sends `codex.level-question/v1` to parent -> parent answers live child with `send_message` | Same task remains active; no user contact by child | PASS |
| Reuse idle child | Parent prepares a fresh bounded envelope -> `followup_task({target, message})` | Existing target receives a newly triggered turn | PASS |
| Completion barrier | Parent repeats `wait_agent` and inspects `list_agents`; receives every child report; verifies `children.active=0` | Timeout is neutral; all reports and descendants terminal before parent completion | PASS |
| Cancellation | Owner uses `interrupt_agent({target})` and records returned status | Interruption recorded as cancellation/failure, never success | PASS |
| Plan read | Discover proxy callable schema -> `list_servers` -> resolve `planmgr` -> downstream help through `call_server` -> plan read command | Plan Manager remains plan truth; no local plan read | PASS |
| CAS structural analysis | Discover proxy adapter -> resolve CAS -> command-specific help if needed -> structural command via `call_server` | CAS remains project-analysis truth | PASS |
| AI Editor mutation | Resolve CAS and editor -> CAS session -> editor open/preview/edit/write preview/write commit/close -> CAS session delete | Full editor lifecycle preserved | PASS |
| Terminal fallback | Record missing CAS execution capability -> resolve MCP Terminal -> sandbox lifecycle through `call_server` | Sandbox only; host route remains separately authorized | PASS |
| Invalid parameter recovery | Failed downstream command -> exact command help through `call_server` -> one schema-corrected retry | No guessed legacy command or local fallback | PASS |

Methodology coverage exercised by the scenarios: orchestration, role prompting,
context isolation, vertical escalation, completion barrier, plan read and
cascade-safe routing, CAS analysis, AI Editor mutation, sandbox fallback, host
separation, and server-error recovery.
