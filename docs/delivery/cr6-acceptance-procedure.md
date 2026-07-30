# CR-6 Acceptance Procedure

Companion to `docs/delivery/cr5a-delivery-runbook.md` (the version/build/deploy
ladder) and `docs/delivery/live-smoke-pipeline.md` (the one real-server
pipeline). This document is the CR-6-specific acceptance contract: what counts
as accepted, per slice, and what does not.

## 1. Scope

CR-6 ("Centralize entity identity, references, CRUD, and deletion lifecycle",
todo `558cd81a`) ships as four independently acceptable slices:

| Slice | Goal | What it delivers | Pipeline check |
| --- | --- | --- | --- |
| Identity / reservation | G-002 | `ALLOWED_TABLES` widened to the full 39-table scope with 4 documented exclusions, migration `0026_identity_registry_full_scope.sql`, the `crud_create` identity-registration gate, and the `project_uuid_reserve` command | `cr6-identity-registry` |
| Contract / search / store migrations | G-003 | `validate_descriptor()`, the real `crud_search` implementation, and seven stores rerouted onto the `crud_*` layer with descriptors on their domain classes | `cr6-entity-contract` |
| Deletion / references | G-004 | `reference_catalog` (71 entries), the central `hard_delete_guard`, wrapper audit deduplication, `runtime_purge_batch`, and `reference_inspect` | `cr6-deletion-references` |
| Migrations / audit | G-005 | Migration-discipline rules and the audit-coverage matrix, with their enforcing suites | `cr6-migrations-audit` |

**Independence rule.** Each slice is accepted on its own fully green run against
the real deployed server. A green unit-test suite is a precondition for
attempting acceptance, never evidence of it. Slices may ship in separate
deployments; a slice whose live run is not green is not accepted, regardless of
how many other slices are.

**Single-transaction rule for the deletion slice.** G-004 changes who writes the
hard-delete audit record. Acceptance of that slice therefore requires live audit
evidence (Section 3), not merely successful deletions: a deletion that succeeds
while writing two audit rows is a failed acceptance.

## 2. Delivery sequence (per slice)

Run this ladder once per slice being delivered. Every step is mandatory; none may
be inferred from the previous one having worked before.

### 2.1 Version bump

Increment `version` in the root `pyproject.toml` by one patch level. This is the
single version source: the client package, the server package, the Docker image
tag and the `.deb` version are all derived from it in lockstep, and derived
version files are never hand-edited.

**Always bump before every deploy.** Reusing a version means the same Docker tag,
and the host then runs the stale image while reporting success.

### 2.2 Build

```bash
./build.sh
```

`build.sh` is a symlink to `scripts/release.sh`. It runs the unit tests, builds
and pushes the Docker image `vasilyvz/planmgr:<VER>`, builds the `.deb`, and — as
its final stage — publishes the client to PyPI (lockstep-checked, idempotent on
"File already exists"). There is no separate manual `twine` step.

### 2.3 Deploy to 192.168.254.26

```bash
dpkg -i planmgr_<VER>_all.deb          # --force-confold keeps the conffile
sed -i 's/^PLANMGR_IMAGE_VERSION=.*/PLANMGR_IMAGE_VERSION=<VER>/' /etc/default/planmgr
systemctl daemon-reload && systemctl restart planmgr
```

`/etc/default/planmgr` is a dpkg **conffile**. `--force-confold` deliberately
keeps the existing `PLANMGR_IMAGE_VERSION` pin, so the `sed` above is not
optional — skipping it restarts the service on the previous image. `planmgr.service`
runs `docker run` reading that file; the host port is **15001**, not 8080.
Migrations auto-apply at container start (`init.sh` logs
`migrations_applied`/`migrations_skipped`), so migration `0026` needs no manual
step — but its application must be confirmed in the container log.

### 2.4 Stage the pipeline on the host

```bash
scp scripts/live_smoke.py root@192.168.254.26:/root/
scp -r scripts/live_smoke_tests root@192.168.254.26:/root/
```

The R-check spec table lives in `scripts/live_smoke_tests/registry.py`, so the
directory must be copied alongside the script; a stale host copy silently runs an
older check set.

```bash
/root/smoke-venv/bin/pip install plan-manager-client==<VER>
```

PyPI's index lags a few minutes behind the upload, so retry this in a loop until
it resolves. Always run the pipeline against the **exact** client version just
built — never an older resident one.

### 2.5 Run the pipeline

```bash
/root/smoke-venv/bin/python /root/live_smoke.py \
  --host 127.0.0.1 --port 15001 --protocol https \
  --expect-version <VER> \
  --project f06b7269-cc9c-4293-886b-24984e4033ba
```

**Do not pass `--ca`.** The server certificate reports "unsuitable certificate
purpose", so verification is impossible; even the systemd healthcheck uses
`curl -k`. `--expect-version` is what makes a stale-image deploy fail loudly at
Tier 0 instead of passing a green run against the wrong build.

## 3. Green criteria

A slice is accepted only when **both** halves below are green.

### 3.1 Local: every named pipeline check

```bash
.venv/bin/pipeline
```

All registered checks must pass, including the four CR-6 slice checks:
`cr6-identity-registry`, `cr6-entity-contract`, `cr6-deletion-references`,
`cr6-migrations-audit`. Individual slices may be checked in isolation
(`pipeline cr6-deletion-references`), but acceptance requires the full run: a
slice that greens its own check while breaking another's has not been accepted.

### 3.2 Live: `live_smoke.py` fully green

Zero `FAIL` results (`SKIP` never affects the exit code, but every skip must
carry a named, explicit reason — a generic-reason fallback is itself a defect,
enforced by `tests/test_live_smoke_script.py`). Compare the counts against the
recorded baseline for the previous version; a drop in passes with no
corresponding code removal is a regression to investigate, not a rounding error.

The two CR-6 checks that must be `PASS`, not `SKIP`, on a server carrying this
change request:

- **R33 `project_uuid_reserve`** — reserve, the deterministic `DUPLICATE_ID`
  collision refusal, resolve with `kind=project_reservation`, release, and the
  `RESERVATION_NOT_FOUND` post-release resolve that proves the identifier was
  actually freed.
- **R34 `reference_inspect`** — direct referrers over a `plan -> todo -> comment`
  fixture with the four-key `{table, column, referrer_kind, referrer_id}` shape,
  plus a recursive traversal reaching hop two and reporting its traversal
  metadata.

A `SKIP` on either of these means the deployed server predates the command —
that is a deploy failure (wrong image), not an acceptable outcome.

**Inner-result rule.** A queued "completed" envelope returned by the mcp-proxy
transport is never sufficient evidence. Every assertion must inspect the INNER
command result carried inside that envelope. This is not theoretical: the
deployed server queues every command, including trivial reads, and the envelope
can nest deeper than the client unwraps (`unwrap_envelope()` in
`scripts/live_smoke.py`).

### 3.3 Slice-specific live evidence

Beyond the pipeline's own verdict, each slice needs its own live confirmation:

- **Identity / reservation.** Confirm from the container log that migration
  `0026` applied. Confirm `audit_list(action='project_uuid_reserve')` and
  `audit_list(action='project_uuid_release')` return the records R33 wrote.
- **Contract / search / store migrations.** Confirm a `wish_list` search call
  returns `matched_column` and `snippet` on a live row: the search layer is the
  one part of this slice that fake-based tests cannot prove, because psycopg has
  no dumper for a bare `dict`/`list` and only a live connection exercises the
  `Jsonb` wrapping.
- **Deletion / references.** After R34's cleanup, confirm via
  `audit_list(entity_type='todo', action='hard_delete')` that the deletion left
  **exactly one** audit row, not two. This is the direct live check on the
  wrapper-audit deduplication; unit tests assert it against fakes, and only the
  live trail proves it end to end.
- **Migrations / audit.** Confirm the audit-coverage matrix in
  `docs/delivery/cr6-audit-coverage-matrix.md` still describes the deployed
  surface: every mutating command it lists produces the action it claims.

## 4. Closure gate

Todo `558cd81a` closes **only** after the full battery in Section 3 is green on
the deployed server, for every slice in scope. Specifically:

1. `pipeline` green locally, all named checks including the four `cr6-*` ones.
2. `live_smoke.py` green on 192.168.254.26 at the exact deployed version, with
   R33 and R34 both `PASS`.
3. The slice-specific live evidence of Section 3.3 gathered and recorded.
4. The live baseline counts recorded for the new version, so the next delivery
   has a number to regress against.

Until all four hold, the todo stays open regardless of how complete the code is.

**Freeze and production deploy happen only on the user's explicit order.** The
same applies to pushing `main`: the working branch is `local`, `main` is a
transfer-only branch, and the merge into it happens after deploy and live green —
never before, and the push itself waits for the order.
