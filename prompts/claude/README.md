# Claude project prompt template

This archive provides a thin-core, lazy-loaded multi-agent prompt architecture
for Claude. `CLAUDE.md` imports the mandatory common laws and orchestrator role;
children read their own role and triggered operation packs before acting.

## Required substitutions (live values for this project — plan_manager)

- `{{PROJECT_NAME}}` = plan_manager
  `{{PROJECT_ID}}` = f06b7269-cc9c-4293-886b-24984e4033ba (stable project UUID, file `projectid`)
  `{{LOCAL_REPO}}` = /home/vasilyvz/projects/tools/plan_manager (local checkout; branch `local`)
- `{{CA_SERVER_ID}}` = code-analysis-server-vvz (uuid 4fd70962-ac0a-45b8-bd0c-bee666868d0d)
  `{{EDITOR_SERVER_ID}}` = ai-editor-server-vvz (uuid 37830763-f58c-4046-95b5-8daf3ea3f2e0)
  `{{TERMINAL_SERVER_ID}}` = mcp-terminal-vvz (uuid 1015751c-0502-4ffa-95e1-8b25a1c63c0e)
  `{{PLANMGR_SERVER_ID}}` = planmgr (uuid 8820e595-8ed4-43f2-b9bf-c99f48054fa6)
  proxy namespace: `mcp__proxy-lan__call_server` (client-side name `proxy-lan`)
- `{{DEPLOY_TARGET}}` = 192.168.254.26
  `{{BUILD_SCRIPT}}` = ./build.sh (project root)
  `{{LIVE_PIPELINE}}` = the one real-server MCP smoke pipeline, run via proxy-lan
  against the deployed planmgr instance after every deploy
- `{{VERSION_SOURCE}}` = pyproject.toml (root; single version source — client, server,
  docker image, and .deb stay lockstep with it)
- `{{PROJECT_STANDARDS_DIR}}` = docs/standards/planning

copy_number for all four servers = 1 (live as of 2026-07-20; re-verify with
`list_servers` on SERVER_NOT_FOUND — copy_number can flip after a service restart).

## Architecture

- `roles/common.yaml` and `roles/laws.yaml`: universal constraints
- `roles/<role>.yaml`: one role's authority and escalation boundary
- `modes.yaml`: lazy operating-mode triggers
- `servers/*.yaml`: thin registered-server maps
- `ops/*.yaml`: command procedures loaded only on matching triggers

The root orchestrator is the only user-facing agent. Child reports are untrusted
until independently checked against artifacts, tests, live behavior, and the
authoritative server state. Parents remain active until every descendant is
terminal.

## Editor contract

Do not carry historical workarounds forward as facts. Verify current live help,
health, version, and behavior. Maintain regression coverage for edit outcome
correlation, YAML root-key insertion, Python trailing header comments, statements
inside `try/except`, and sibling-import validation.

DEVIATION for this project: native INI/TOML structured editing is NOT yet
live-verified here — CA-layer TOML persistence was confirmed broken on live test
(2026-07-20). Until re-verified, keep using the `.txt`-then-`mv` workaround
(`ops/editor-new-file.yaml`) instead of trusting the template's native-TOML claim.

A long operation may validly enter a queue. Configure the adapter client for
synchronous poll-and-unwrap or asynchronous/message handling. Queue handoff is
not itself a defect; terminal payload or exception determines the outcome.

## Branch transfer

`local` and `cas` are working branches; `main` is transfer-only. Never merge
`local` directly with `cas`. Build, deploy, and run live acceptance from the
active working branch. Merge it into local `main` only after production success,
report the exact commit, and wait for the user to push. After confirmation, the
opposite site pulls `main` and merges it into its own branch.

DEVIATION for this project (standing user order 2026-07-18): `variables.file_access`
stays `local`, not the template default `mcp` — see `roles/laws.yaml`.

## Delivery

Keep exactly one real-server acceptance pipeline. The full chain is reproduce,
prove cause, fix, add focused coverage, run project checks, align versions, build,
deploy, run the live pipeline, verify registration and changed behavior through
MCP Proxy, and record a verified Plan Manager fix before closing a bug.

## Validation

Parse every YAML file, verify referenced package files exist, and limit remaining
`{{...}}` tokens to the substitutions listed above. Confirm live server IDs and
command schemas before first use.
