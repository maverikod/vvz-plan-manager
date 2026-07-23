# CR-5a Delivery Runbook

## 1. Version Bump

Increment the project version by 1 in the root `pyproject.toml`, the single source of truth for plan-manager's version. The current version is 0.1.56, so this step bumps 0.1.56 to the next version.

The version-lockstep law: the client package, server package, docker image tag, and .deb package version must all equal this same version. Sync scripts run as part of the build enforce this — derived version files are never hand-edited.

## 2. Build

Run `./build.sh` at the project root. It must:

- Run the local unit tests
- Build the docker image, tag it with the same version, and push it to Docker Hub
- Build the .deb package

A missing `./build.sh` would be a gap to close, not ignore.

## 3. Client Publish

Publish the server's client package to PyPI at the same version, using `~/.pypirc` credentials via `twine`. Inline tokens and interactive prompts are never used.

## 4. Transfer / Deploy

Deploy to the single testing/production server, following the documented deployment pipeline for this project. If the transfer/deploy method were not already established, it would require asking the user first — this is the standing rule.

## 5. Real-Server Pipeline and Post-Deploy Smoke

Exactly one pre-delivery test pipeline runs against the freshly deployed instance, built on the server's own client (or the adapter's client if none). It confirms the server is present in the mcp-proxy registry via `list_servers`, and that every changed/added command and its related commands respond correctly through the proxy via `call_server`, not only in isolation. The pipeline must be green.

For the detailed mandatory post-deploy MCP smoke procedure, see `docs/delivery/cr5a-live-smoke-procedure.md`.

## 6. Post-Deploy Propagation

Merge the site/working branch into `main`, push `main` to GitHub. On a site without push credentials, prepare the merge and ask the user to push. Then update the server repository from GitHub using `git_pull` or `git_pull_safe`.

The deploy is NOT finished until the server repository contains the deployed commit.
