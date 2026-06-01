<!--
Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
-->

# Project overlay — `plan_manager`

Repository-specific paths, behavior, and restrictions.
Universal layout: [`PROJECT_RULES.md`](../PROJECT_RULES.md) §3 (`LAYOUT-*`).

---

## Functional context

- **Role:** MCP server for managing project development plans as a structured tree.
- **Production package:** [`plan_manager/`](../../plan_manager/) — commands, config, core logic.
- **Framework:** `mcp_proxy_adapter` — handles JSON-RPC routing, validation, serialization, help output, and proxy registration. `plan_manager` must not patch adapter internals.
- **Plans on disk:** each plan is a git repository. Node IDs are stable string identifiers mapped to files/directories by numeric prefix (`G-NNN-*`, `T-NNN-*`, `A-NNN-*`).
- **Buffer model:** editing sessions use git worktrees on tmpfs. Buffer commands are prefixed `buf_*`. Navigation commands are prefixed `plan_*` and are read-only on disk.
- **Vectors:** each `.md` node file has a sibling `.md.vec` binary float32 embedding file committed alongside it in the plan git repo.
- **Config:** JSON only. `plan_manager` extends the adapter config system with `PlanManagerConfigSection` (Pydantic). `plans_root` is resolved from config — never passed as an MCP parameter.
- **Tests:** pytest suite under [`tests/`](../../tests/).
- **Non-pytest harnesses and ops scripts:** under [`scripts/`](../../scripts/) per LAYOUT-07.

---

## Repository layout (project-specific additions)

| Path | Note |
|------|------|
| `plan_manager/` | Production package root. Commands, config, core subsystems. |
| `plan_manager/commands/` | MCP command classes, one per command or grouped by family. |
| `plan_manager/core/` | Shared internals: session management, git worktree, node ID resolution, vectorization, config. |
| `tests/` | pytest suite, mirrors `plan_manager/` structure. |
| `scripts/` | Ops, maintenance, non-pytest harnesses (LAYOUT-07). |
| `configs/` | Sample JSON configs; production secrets not in git. |
| `docs/plans/` | Active and archived development plans (YAML tree). |
| `docs/agents/` | Agent rules and overlays (this file and siblings). |
| `docs/aireports/` | Working AI session outputs (LAYOUT-06). |
| `projectid` | Project identity file (CR-003, must exist and be valid UUID4 JSON). |
| `mypy.ini` | mypy configuration. |
| `code_analysis/` | Generated code index (`USE_CODE_MAP = yes`). Do not hand-edit. |

---

## Command naming rules

| Prefix | Scope | Notes |
|--------|-------|-------|
| `buf_*` | Buffer commands | Operate on git worktree on tmpfs. Require an active session. |
| `plan_*` | Navigation / structure commands | Read-only on disk (except `plan_create`, `plan_add_*`). No session required. |

Full command surface is defined in the active plan under `docs/plans/`, G-001.

---

## Command class conventions

Every MCP command class must follow the adapter standard:

```
name, version, descr, category, author, email
get_schema()     — machine-readable JSON-Schema input spec
metadata()       — AI/doc-facing extended description
validate_params() — semantic validation beyond schema
execute()        — returns SuccessResult or ErrorResult
```

Complex commands: split into `<cmd>_command.py`, `<cmd>_schema.py`, `<cmd>_metadata.py`.
See `metadatastd.md` in project files for the full metadata and schema standard.

---

## Project-specific restrictions

- **Do not patch `mcp_proxy_adapter` internals.** `plan_manager` implements command classes only; the adapter owns routing and serialization.
- **Do not pass `plans_root` as an MCP parameter.** It is resolved from config automatically in every command.
- **Buffer commands must operate on tmpfs worktree only.** Never write buffer state directly to the plan main branch.
- **`buf_flush` commits to the session branch only.** It does not merge into the plan main branch and does not release the lock.
- **Session branches are ephemeral.** Flushed commits on an unmerged session branch are lost when `buf_discard` or `expire_session` deletes that branch. This is by design.
- **Vectors are committed to git** as `.md.vec` siblings alongside `.md` files. Do not store vectors outside the plan git repo.
- **Config format is JSON only.** Do not introduce YAML or TOML config files.
- **Secrets:** never commit credentials, API keys, or private TLS keys.
- **Scope:** changes must stay within this repository (CR-002).
- **Generated artifacts:** do not hand-edit `code_analysis/` — regenerate via `code_mapper`.

---

## Filled profile pointer

Concrete profile values for this repo: [`PROJECT_RULES.md`](../PROJECT_RULES.md) **§0** / **§7**.
