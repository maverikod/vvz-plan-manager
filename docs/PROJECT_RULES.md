<!--
Template: project rules for any repository.
On project bootstrap, fill §0 and keep IDs (CR-*, LAYOUT-*, NAME-*) stable.
Author line above: set to project owner after copy, or remove if unused.
-->

# Project rules (canonical template)

Use rule IDs: `CR-*`, `LAYOUT-*`, `NAME-*` (e.g. `CR-007`, `LAYOUT-02`).

Optional: [`docs/assistant_rules_inventory.md`](assistant_rules_inventory.md) for MCP, transcripts, §24–§25.

Active subagent file in `.cursor/agents/*.md` overrides conflicting rows in this document for that role.

---

## 0. Project profile (fill once per repository)

Replace placeholders when **creating** or **adopting** a project. Models should write this table on first scaffold.

| Key | Example | Description |
|-----|---------|-------------|
| `PROJECT_SLUG` | `acme_api` | Short ASCII id for paths and package naming. |
| `PRIMARY_LANGUAGE` | `Python` | Main implementation language (`Python`, `TypeScript`, …). |
| `PACKAGE_ROOT` | `<PROJECT_SLUG>/` or `lib/` | Root directory for production code (**no `src/`** unless profile explicitly allows). |
| `TEST_FRAMEWORK` | `pytest` | Default test runner for CR-007 analogues. |
| `VENV_DIR` | `.venv` | Virtual environment directory at repo root (if applicable). |
| `CHAT_LOCALE` | `ru` | Language for **chat** with the user. |
| `ARTIFACT_LOCALE` | `en` | Language for code, comments, docstrings, tests, `docs/` unless a named doc specifies otherwise. |
| `HEADER_AUTHOR` | `<Name>` | Required author string in file headers (see CR-012). |
| `HEADER_EMAIL` | `<email>` | Required email in file headers. |
| `DOC_FILENAME_STYLE` | `snake_case` | `snake_case` or `kebab-case` for new Markdown under `docs/` (stay consistent). |
| `USE_CODE_MAP` | `yes` / `no` | If `yes`, run the project’s **code map / index** tool after logical code-structure changes (this template calls it **`code_mapper`** / `code_analysis/` — rename in profile if your stack differs). |

---

## 1. Precedence (highest first)

| Rank | Layer |
|------|--------|
| 1 | **Current user message** — explicit instruction wins. |
| 2 | **Safety / repo boundary** — `CR-002`. |
| 3 | **Active subagent role** — `.cursor/agents/<name>.md` if present. |
| 4 | **This file** — `CR-*`, `LAYOUT-*`, `NAME-*`, and §0 profile. |
| 5 | **`docs/assistant_rules_inventory.md`** — if present. |
| 6 | Tool / IDE defaults. |

---

## 2. Core rules (`CR-*`)

| ID | P | Rule |
|----|---|------|
| **CR-001** | 0 | Execute the **current task** literally; do not skip or dilute stacked instructions. |
| **CR-002** | 0 | **Do not modify paths outside this repository** without explicit user permission. |
| **CR-003** | 0 | If the profile requires a **project id file** (e.g. `projectid` JSON with `id` UUID4 + `description`): it must exist and be valid. Missing/invalid → **stop and report** to the user. |
| **CR-004** | 0 | **Questions** (analysis-only): answer in **chat**, not unsolicited files. Durable docs/bugs/plans only when the task is to write them. |
| **CR-005** | 1 | **Python / venv:** use **`VENV_DIR`** (default `.venv` in repo root). It must be **active** before `python`, `pip`, tests, and linters. On **`ModuleNotFoundError`**, missing dependency, wrong interpreter path, or **`pip install` / environment errors**: **first** verify activation (`which python`, `$VIRTUAL_ENV` on Unix, or Windows equivalents); activate (`source <VENV_DIR>/bin/activate` or project script) and **retry** — do not treat “package missing” as proven until the interpreter is confirmed to be the venv’s. |
| **CR-015** | 0 | **Forbidden:** `pip install --break-system-packages` and other **PEP 668** / externally-managed-environment **override** flags **unless** the user **explicitly authorizes that exact shell command** in this conversation (silence or “fix it” is **not** permission). |
| **CR-006** | 1 | If `USE_CODE_MAP` = `yes`: after each **logically finished** structural change (split file, remove symbol + references, new package), refresh the project index (e.g. `code_mapper` → `code_analysis/`). If the tool is missing, state that clearly. |
| **CR-007** | 1 | After changing production code, run the repo’s **required linters/formatters/typecheckers** on touched paths (for Python template defaults: `black`, `flake8`, `mypy`) and fix findings. Adjust in §0 if the stack differs. |
| **CR-008** | 1 | **Module size (Python default):** ~**350** lines → prefer split; **≤ ~400** → acceptable; **≥ ~450** → **must** split. For other languages, define limits in §0. |
| **CR-009** | 1 | **Documentation in code:** modules, classes, and public functions/methods need docstrings (or equivalent); parameters and returns typed or described; non-obvious logic: short comments. **Abstract** API → language-appropriate failure (`NotImplementedError`, `abc.abstractmethod`, etc.) — not a silent stub. |
| **CR-010** | 1 | **Chat** in `CHAT_LOCALE`; **repository artifacts** in `ARTIFACT_LOCALE` unless the user specifies a document language. |
| **CR-011** | 2 | **Version control:** commit after a logical batch; **push** only when the user asks. |
| **CR-012** | 2 | **Headers:** in each required file type, include `HEADER_AUTHOR` and `HEADER_EMAIL` (or project’s standard header block). |
| **CR-013** | 2 | **Imports / includes** at top of file unless lazy-loading is intentional. |
| **CR-014** | 3 | If the project defines numeric **log importance** (0–10), use the project scale consistently. |
| **CR-016** | 1 | **Parallelism:** where **dependencies allow**, run **independent** work **in parallel** (parallel delegations, parallel specialist tasks, parallel waves). **Do not** serialize independent subtasks without a **stated** dependency or resource reason. Orchestrators **must** decompose so unrelated units can execute **concurrently** when the runtime supports it (see also full-stack caps in `.cursor/agents/orchestrator.md` where applicable). |

**P:** **0** governance / stop, **1** quality, **2** hygiene, **3** optional classification.

---

## 3. Repository layout (`LAYOUT-*`)

Default for new projects; adjust in §0 if monorepo or polyglot requires extra roots.

| ID | Rule |
|----|------|
| **LAYOUT-01** | **No `src/` by default.** Production code lives under **`PACKAGE_ROOT`** at repository root (e.g. `<slug>/`, `app/`). Add `src/` only if §0 explicitly allows. |
| **LAYOUT-02** | **Automated tests** under **`tests/`** (or profile path), mirroring package structure where helpful. |
| **LAYOUT-03** | **Runtime logs** under **`logs/`** (gitignore by default); no secrets in tracked logs. |
| **LAYOUT-04** | **Sample / non-secret configuration** under **`configs/`**; production secrets not in git. |
| **LAYOUT-05** | **Durable documentation** under **`docs/`** (guides, specs, stable references). |
| **LAYOUT-06** | **Working AI outputs** (reports, in-progress bugs, session dumps the user asked to save) under **`docs/ai_reports/`**. Promote finished write-ups into the appropriate `docs/` subtree. |
| **LAYOUT-07** | **`scripts/`** — **All** operational and maintenance tooling (CI helpers, local dev utilities, one-off migrations, smoke runners, wrappers). **Non-pytest** checks and manual / integration harnesses belong here, **not** under **`tests/`** (pytest suite stays in **`tests/`** per LAYOUT-02). |

```text
<repo>/
  <PACKAGE_ROOT>/      # production code (no src/ unless profile says otherwise)
  tests/
  scripts/             # ops, maintenance, non-pytest harnesses (LAYOUT-07)
  logs/
  configs/
  docs/
    ai_reports/
  projectid            # if CR-003 enabled for this project
  <VENV_DIR>/          # local, usually not committed
```

Optional generated indices (if `USE_CODE_MAP` = yes): e.g. `code_analysis/` — name in profile.

**Also read for this repo:** [`docs/agents/project_overlay.md`](agents/project_overlay.md). **Section map:** [`docs/agents/universal_project_context.md`](agents/universal_project_context.md).

---

## 4. Naming conventions (`NAME-*`)

**Default below = Python** (PEP 8). If `PRIMARY_LANGUAGE` is not Python, add a **§0 override row** or attach a short annex; until then, apply the closest idiomatic standard for that language.

| ID | Scope | Rule |
|----|--------|------|
| **NAME-01** | **Files (Python modules)** | `snake_case.py`; one conceptual module per file; avoid redundant words (`utils_helpers.py` → narrow the name). |
| **NAME-02** | **Test files** | `test_<module_or_feature>.py` under `tests/` (pytest style); mirror path of code under test when practical (`tests/pkg/test_foo.py` ↔ `pkg/foo.py`). |
| **NAME-03** | **Packages (directories)** | Lowercase, short; prefer single word; multi-word → `snake_case` (no hyphens in import path). |
| **NAME-04** | **Classes / exceptions** | `PascalCase`. Exception classes end with `Error` where applicable. |
| **NAME-05** | **Functions / methods** | `snake_case`; verb-led (`get_`, `create_`, `parse_`). |
| **NAME-06** | **Variables / parameters / attributes** | `snake_case`; avoid 1–2 character names except loop indices (`i`, `j`, `k`) and well-known math symbols in scope. |
| **NAME-07** | **Constants** | `UPPER_SNAKE_CASE` at module or class level for true constants. |
| **NAME-08** | **Privacy** | One leading `_` for **internal** module API not meant for importers; **never** use trailing underscore unless avoiding a keyword clash. |
| **NAME-09** | **Properties (`@property`)** | Same as public attributes: `snake_case`; avoid Java-style `get_foo()` **and** a `foo` property duplicating the same — pick one style per class. |
| **NAME-10** | **Type aliases / TypeVars** | `PascalCase` for `TypeAlias` names; `TypeVar` names short `T`, `T_co`, or descriptive `PascalCase`. |
| **NAME-11** | **Enums** | Class `PascalCase`; members `UPPER_SNAKE_CASE` if they behave as constants. |
| **NAME-12** | **Markdown / docs filenames** | Use **`DOC_FILENAME_STYLE`** from §0 consistently (`design_notes.md` vs `design-notes.md`). |
| **NAME-13** | **Config keys (JSON/YAML)** | `snake_case` keys unless integrating an external schema that requires another convention (then document in §0). |

---

## 5. Anti-patterns (naming & layout)

- Mixed `camelCase` / `snake_case` for Python **module-level** public APIs without documented reason.
- Generic names: `data`, `info`, `handle`, `manager` without qualifier.
- Abbreviations only clear to one author (`usr_mgr_cfg`); prefer readable length over cryptic short names.
- Test files that do not start with `test_` (pytest discovery) unless configured otherwise in §0.

---

## 6. Where to duplicate in tooling

- Prefer **one line** in IDE User Rules: “Follow `docs/PROJECT_RULES.md` IDs; fill §0 profile.”
- Keep **5–10 line** emergency checklist in User Rules only if files are not always loaded.

---

## 7. Filled profile — this repository (example)

**When copying this file to a new project, delete §7** and fill only §0.

| Key | Value |
|-----|-------|
| `PROJECT_SLUG` | `svo_client` |
| `PRIMARY_LANGUAGE` | `Python` |
| `PACKAGE_ROOT` | `svo_client/` |
| `TEST_FRAMEWORK` | `pytest` |
| `VENV_DIR` | `.venv` |
| `CHAT_LOCALE` | `ru` (user preference) |
| `ARTIFACT_LOCALE` | `en` |
| `HEADER_AUTHOR` | `Vasiliy Zdanovskiy` |
| `HEADER_EMAIL` | `vasilyvz@gmail.com` |
| `DOC_FILENAME_STYLE` | `snake_case` (existing `docs/` may mix legacy names) |
| `USE_CODE_MAP` | `yes` (`code_mapper` → `code_analysis/`) |
