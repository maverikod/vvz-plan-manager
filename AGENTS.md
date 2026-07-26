# plan-manager - Codex operating contract

**Prompts template:** `codex-prompts-v1` rev **1.6.2** (2026-07-26)

This file is the Codex entrypoint. The root must read these files itself at the
start of a task:

- `codex/roles/common.yaml`
- `codex/roles/laws.yaml`
- `codex/roles/orchestrator.yaml`

Do not delegate reading or interpretation of those files. Resolve every
relative prompt-package reference against `codex/`.

## Project profile

- Project: `plan-manager`
- Local checkout: `/home/testuser/projects/plan-manager`
- CAS project ID: `f06b7269-cc9c-4293-886b-24984e4033ba`
- CAS server: `code-analysis-server-vvz`

Use the `codex/` bundle as the authoritative Codex contract for this project.
Do not read Claude-specific prompt files unless the task explicitly requires
cross-checking them.
