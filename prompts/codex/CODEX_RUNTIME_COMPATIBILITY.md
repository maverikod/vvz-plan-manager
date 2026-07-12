# Codex runtime compatibility contract

This file is the executable adapter between the bundle's orchestration
methodology and the collaboration surface currently exposed by Codex. It changes
only transport. Role boundaries, context isolation, vertical escalation,
completion barriers, Plan Manager cascade discipline, and downstream server
workflows remain unchanged.

## Runtime facts and limits

- The runtime does not expose model selection or reasoning-effort arguments for
  child creation. Source tiers and model fields are recommendation metadata.
- A child role is a duty assigned by prompt. There is no separate researcher,
  tester, owner, mini, spark, or conscience API.
- Only the root Orchestrator communicates with the user. Child questions,
  blockers, and results travel to the direct parent.
- Official Codex-manual lookup was attempted during this adaptation, but the
  helper was unavailable because the response lacked the required integrity
  header (`x-content-sha256`). No capability was inferred from that failure.
  The callable tools exposed in the current session are the runtime authority.

## Exact collaboration-tool mapping

`spawn_agent` is the only child-creation operation:

```text
spawn_agent({task_name, fork_turns, message})
```

- `task_name` is a stable lowercase task label.
- `fork_turns` is `"none"`, `"all"`, or a positive integer string. Prefer
  `"none"` when the complete context is referenced in the delegation envelope;
  use the smallest positive turn count when recent conversation is required.
- `message` contains one `codex.delegation/v1` YAML mapping as plain text plus
  only the minimal boot instruction needed to read its referenced context.
- Model, reasoning effort, role class, tool permissions, and acceptance are not
  `spawn_agent` parameters. They belong in the message as metadata or duties.
- Record the returned agent id or canonical task path as the lifecycle target.

The remaining lifecycle operations are:

```text
send_message({target, message})
followup_task({target, message})
wait_agent({timeout_ms})
list_agents({path_prefix?})
interrupt_agent({target})
```

- `send_message` delivers a context amendment, owner answer, or correction to a
  live child. It does not create a new task and must not be treated as a restart.
- `followup_task` gives a reusable existing child a new bounded message and
  triggers a turn if it is idle. The message must carry a fresh delegation
  envelope or an explicit amendment tied to the existing task id.
- `wait_agent` waits for mailbox updates. A timeout means only that no update
  arrived; it is not failure or child completion. The parent remains active and
  waits again or inspects status.
- `list_agents` inspects live descendants, optionally under a task-path prefix.
  A child is accepted as terminal only after its final report/status notification
  is received; disappearance from the live list alone is not completion proof.
- `interrupt_agent` stops an active turn when the owner must cancel or replace
  it. Interruption is not success; preserve the returned status and obtain or
  synthesize a factual terminal record before closing the parent task.

Machine-readable upward questions and `codex.child-report/v1` reports are placed
inside message/final text. The collaboration API transports those payloads; it
does not interpret their schemas.

## Executable parent lifecycle

1. Create common and child-specific context according to the selected mode.
2. Call `spawn_agent` once per admitted bounded child and record every target.
3. Enter `waiting_for_children`; use `wait_agent` for updates and `list_agents`
   when status inspection is needed.
4. Answer a live child's machine-readable question with `send_message`. Use
   `followup_task` only to start another turn on an idle reusable child.
5. Receive a `codex.child-report/v1` report for every direct child. A report with
   `children.active > 0` is not terminal.
6. Verify reports against parent acceptance criteria and descendant counts.
7. Complete only when all required reports are terminal, no descendant is live,
   and no escalation remains.

If the required child cannot be created because the collaboration surface or a
concurrency slot is unavailable, return `SPAWN_UNAVAILABLE`. A higher owner may
bridge the already-prepared child envelope through its own `spawn_agent` call or
reuse a suitable idle child with `followup_task`; it must not absorb the lower
level's implementation.

## MCP Proxy adapter

Codex tool namespaces and generated function names are session-specific. Never
hardcode a namespace such as `mcp__...` as universally available. Before the
first proxy-backed action in a session:

1. Inspect the callable tool catalog supplied to the current agent.
2. Identify the MCP Proxy provider and the exact exposed schema for the required
   logical operation.
3. Use the exposed operation exactly as described. Do not invent a wrapper,
   namespace, positional argument, or JSON shape.
4. If the required operation is absent, report the exact capability gap; do not
   fall back to local project or plan access.

The current compatibility target provides these logical proxy operations:

| Logical operation | Purpose |
| --- | --- |
| `list_servers` | Resolve registered downstream server id and copy |
| `help` | Read MCP Proxy command help/schema |
| `health_check` | Check proxy or registered-server health |
| `search_commands` | Discover candidate downstream commands; never substitutes for exact help |
| `call_server` | Call a resolved downstream server command with its exact parameter object |

These names describe the currently observed logical surface, not a guaranteed
Codex namespace. The exact callable function and argument schema must still be
discovered in the active session.

For Plan Manager, Code Analysis Server, AI Editor Server, and MCP Terminal:

1. Discover the proxy callable schema.
2. Check proxy health when needed and call `list_servers` to resolve the target
   server and copy.
3. Use `call_server` for downstream general `help`, then command-specific `help`
   before a mutation or when a prepared card conflicts with live truth.
4. Execute the downstream command through `call_server` using only the live
   schema. `search_commands` may locate a command family but cannot authorize
   guessed parameters.
5. On invalid parameters, command absence, or server unavailability, follow
   `prompts/tool-routing/help/server-error-recovery.yaml` through the same proxy
   adapter and retry at most once where that contract allows it.

Prepared triggers and help packs remain concise routing intent. Live proxy and
downstream help always win when server identity, version, catalog, or schema
differs.

## Compatibility checklist

- [ ] No child-creation call includes model, effort, role, or permissions args.
- [ ] Every child message contains a bounded delegation envelope.
- [ ] Children report and ask only through their direct parent.
- [ ] `wait_agent` timeout is not treated as completion or failure.
- [ ] Every required child report and descendant terminal state is verified.
- [ ] Exact MCP Proxy callable names and schemas are discovered per session.
- [ ] Downstream server identity and command help are live-verified when required.
- [ ] Plan Manager, CAS, AI Editor, and Terminal methodologies remain on their
      authoritative proxy routes.
- [ ] Source model fields remain metadata and never block dispatch.
