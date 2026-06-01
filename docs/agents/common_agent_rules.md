<!--
Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
-->

# Common agent rules (all subagents + hierarchy)

**Scope:** every Cursor subagent in `.cursor/agents/*.md`, except where a role file **forbids** an action (e.g. `orchestrator` does not run tests).

**Load order (if not already in context):**

1. [`universal_project_context.md`](universal_project_context.md) → [`PROJECT_RULES.md`](../PROJECT_RULES.md) §0–§5.
2. [`project_overlay.md`](project_overlay.md).
3. **This file** (`common_agent_rules.md`).
4. `docs/agents/spec_<role>.md` if it exists.
5. [`assistant_rules_inventory.md`](../assistant_rules_inventory.md) if required by the task.

---

## A1. Instruction fidelity

Follow user, system, skill, and tool instructions completely. On conflict, use precedence in [PROJECT_RULES.md §1](../PROJECT_RULES.md).

---

## A2. Chat vs repository files

- **Questions** (analysis-only): answer in **chat**; do not create unsolicited explanation files.
- **Durable** docs, plans, structured bugs: write under `docs/` when the task requires it ([inventory §4–§5](../assistant_rules_inventory.md)).

---

## A3. Repository boundary

Do not modify paths **outside this repository** without explicit user permission.

---

## A4. Project id (`projectid`)

If the project uses `projectid` (see CR-003): missing or invalid JSON → **stop and report** to the user.

---

## A5. Virtual environment

Before Python installs, linters, or tests: ensure **`VENV_DIR`** from [PROJECT_RULES §0](../PROJECT_RULES.md) is active (default `.venv`).

If **`ModuleNotFoundError`**, a missing package, wrong `python`/`pip`, or **`pip install` fails**: **stop** and verify the venv (`which python`, `$VIRTUAL_ENV` on Unix, or Windows equivalents); activate and **retry** before installing into another environment.

**CR-015:** do **not** use `pip install --break-system-packages` (or other PEP 668 overrides) **unless** the user explicitly approves **that exact command** in chat.

---

## A6. Code map / indices

If `USE_CODE_MAP` = yes in §0: after a **logically finished** structural change, refresh indices (e.g. `code_mapper` → `code_analysis/`). If the tool is missing, state that.

---

## A7. Language

- **Chat:** `CHAT_LOCALE` from [PROJECT_RULES §0](../PROJECT_RULES.md).
- **Repo artifacts:** `ARTIFACT_LOCALE` (typically English for code and `docs/`).

---

## A8. File headers on outputs

When creating or editing files that require it: use `HEADER_AUTHOR` / `HEADER_EMAIL` from [PROJECT_RULES §0](../PROJECT_RULES.md).

---

## A9. Required specialist or resource missing (**critical**)

If a **required** agent, template, or tool the role depends on is unavailable:

1. **Stop** immediately.
2. Do **not** continue manually, substitute another agent, or bypass the hierarchy.
3. **Ask the user** what to do next.

*(Each `spec_*.md` lists which peers/resources are required for that role.)*

---

## A10. File write verification

After any **write** this role owns:

- **Read back** the file.
- Confirm **substantive** expected content is present (not only that the path exists).
- Do not report “Done” until verified.

For long analysis reports: verify beginning and end of file when appropriate.

---

## A11. Doubt and escalation

Do not proceed on unstated assumptions. **Escalation target** is defined in each role spec (`orchestrator_tactical`, `orchestrator`, user, etc.).

---

## A12. MCP tools

Before calling an MCP tool, read its **schema/descriptor** (Cursor `mcps/` tree for this workspace).

---

## A13. Version control (when the session performs git work)

Commit after a logical batch; **push** only if the user asks.

---

## A14. Hierarchy roles at a glance

| Role | Writes code | Runs tests | Writes tactical/atomic plans | Owns global spec |
|------|-------------|------------|------------------------------|------------------|
| `orchestrator` | no | no | global only | yes |
| `orchestrator_debug` | no | no | none (delegates via chat brief) | no |
| `orchestrator_tactical` | no | no | tactical tasks | no |
| `orchestrator_tactical_debug` | no | no | none (direct commands; no `planner_auto`) | no |
| `planner_auto` | no | no | atomic steps | no |
| `coder_auto` | **yes** | via step only | no | no |
| `tester_auto` | **no** | **yes** | no | no |
| `doc_writer` | no | no | no | no |
| `researcher_code` | no (analysis files OK) | no | no | no |
| `researcher_doc` | no (analysis files OK) | no | no | no |

**Mandatory completion (planning/implementation stream):** not done until **`tester_auto`** reports **all tests pass**, unless the user explicitly narrows scope.

**Parallelism (**[**CR-016**](../PROJECT_RULES.md)**):** orchestrators and leads **maximize concurrent** execution of **independent** units; serialization requires a **stated** dependency or resource reason.

---

## A15. Documentation structure for this planning stack

**Full stack only** (`orchestrator` → `orchestrator_tactical` → `planner_auto`). The **debug** pair (`orchestrator_debug` → `orchestrator_tactical_debug`) does **not** use these paths for planning.

---

## A16. Orchestrator tool envelope (**critical**)

- **`orchestrator`**: tools only for (1) calling **`orchestrator_tactical`**, (2) reading **global** Markdown artifacts and **explicit upward deliverables** from the tactical layer (plus the narrow pre-existing MCP file exception in its role file), (3) writing **thesis `tech_spec.md`**, global implementation plan, and global step documents. **No** direct work on source code, tests as code, or ad-hoc browsing of tactical/atomic subtrees.
- **`orchestrator_tactical`**: tools only for **delegation**, **read/write of tactical-task Markdown**, and **read-only** atomic-step **`.md`** files under its branch. **No** reading/searching/editing **implementation** files; **no** Shell for tests/diagnostics. Primary subagents: **`planner_auto`**, **`coder_auto`**, **`tester_auto`**, **`researcher_code`**, **`researcher_doc`**, **`doc_writer`**. When delegating via **Task** (or equivalent), **must** set **`subagent_type`** to one of those ids — **not** **`auto`**, **not** a generic agent, **not** model-only; see role file for retry (5s, max 3 attempts).
- **`orchestrator_debug`** / **`orchestrator_tactical_debug`**: same **orchestrator / no-code** idea without formal `docs/tech_spec/` tactical files; tactical debug **does not** use repo tools to verify or research code — specialists do. Same **`subagent_type`** rule; debug allows **five** roles (**no** **`planner_auto`**).

Canonical paths:

- `docs/tech_spec/tech_spec.md`
- `docs/tech_spec/implementation_plan.md`
- `docs/tech_spec/steps/<global_step_slug>.md`
- `docs/tech_spec/branches/<global_step_slug>/tasks/<tactical_task_slug>.md`
- `docs/tech_spec/branches/<global_step_slug>/tasks/<tactical_task_slug>/steps/<atomic_step_slug>.md`

Details: if `spec_*.md` files exist in this directory, see `spec_orchestrator_global.md`, `spec_orchestrator_tactical.md`, `spec_planner_auto.md`; otherwise use `.cursor/agents/*.md` full text.
