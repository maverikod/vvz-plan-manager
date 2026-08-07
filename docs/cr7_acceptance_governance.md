# CR-7 Acceptance Governance: Store/CRUD Migration Closure

Plan `planmgr-cr7-store-crud-migration`, frozen at `eb91888d`, 96 atomic steps
(8 GS + 13 TS + 96 AS across the wave structure), executed 2026-08-06..07 by
orchestrated coder/tester subagents. Every atomic step carries an
`execution_attempt` evidence record in the runtime registry. This document
records the decisions this closure made, not the diffs that implement them,
for the reader who arrives after the fact.

## 1. The four mechanical invariants

CR-7's acceptance rests on four mechanically-checked invariants, each a named
pipeline check in `plan_manager/pipeline_checks/registry.py`, plus an
umbrella that runs all four as one gate:

- **`cr7-identifier-classification`** — every identifier a command accepts is
  mechanically classified (id vs. anchor vs. owner-form) and routed through
  the identity registry rather than ad hoc parsing.
- **`cr7-no-out-of-mechanism-write`** — no registered entity table may be the
  target of an `INSERT` or `DELETE` statement anywhere in the `plan_manager`
  package outside the unified engine mechanism (`entity.py`, `admission.py`,
  `hard_delete_guard.py`, `identity.py`, `identity_audit.py`,
  `relation_index_store.py`, `enumeration_store.py`). The scan
  (`g004_scan` / `g004_scan_main`) treats an unmarked statement as an
  offender and a statement carrying the literal in-code marker
  `"CR-7 G-004 compatibility note"` in the preceding 10 lines as a
  documented, non-failing known exception. Re-run at this document's head
  (`1cd14c4`): **0 offenders, 6 known exceptions**, one apiece in
  `plan_manager/cascade/restore.py:198`, `plan_manager/domain/paragraph_store.py:75`,
  `plan_manager/domain/plan.py:357`, `plan_manager/domain/relation_store.py:130`,
  `plan_manager/domain/step_ops.py:153`, `plan_manager/storage/version_store.py:167`
  — each carries the CR-7 G-004 compatibility marker and is adopted as the
  removal backlog of the bug `c315ff84` guard-rework successor (section 5).
  (A seventh marker sits in `plan_manager/storage/identity.py:275`, on the
  UUID-reservation release path — that file is itself a mechanism file, so
  the scan never visits it; the marker there is a separate, pre-existing
  compatibility note unrelated to the six-file removal backlog and is not
  counted among the six.)
- **`cr7-metadata-projection-equality`** — the metadata a store persists and
  the metadata a projection reads back are asserted equal, closing the class
  of drift where a read-path silently diverges from what was written.
- **`cr7-owner-or-root-declared`** — every registered entity table declares
  either an owner edge or root status in the identity registry; no table may
  be silently unowned. The allowlist of undeclared tables is **empty** after
  the companion fix landed in this campaign.

The umbrella check, **`pipeline cr7`**, runs all four as one dispatch
(`cr7_group_main`) so `plan_manager.pipeline_cli` reports a single RED/GREEN
verdict for G-008/T-001/A-001. All four checks and the umbrella are **GREEN**
at head `1cd14c4`; the full regression suite stands at **2907 passed / 6
skipped** (this document adds no tests and does not change that count).

## 2. Deliberate residuals

Two structural decisions in this campaign break with prior behavior on
purpose. Both are documented here because a future reader diffing the code
would otherwise read them as accidents.

### 2.1 Purge reversal: row-wise refusal → whole-operation refusal

`runtime_purge_batch` moved from v1 (report-one-and-continue: a live
referrer was found, reported, and the target skipped one row at a time) to
**v2.0.0**, which refuses the **whole operation** and names every blocking
referrer at once (`DELETE_BLOCKED`), rather than continuing past unreported
ones. The old behavior's flaw: its referrer lookup only considered *live*
referrers at scan time. A target could be purged while a referrer that was
merely *marked* for deletion but not yet swept stayed unlisted by that scan
— and once the target was gone, that marked-but-unlisted referrer's
reference became permanently dangling, because nothing ever revisited it.
Row-wise, best-effort purging manufactured exactly the dangling references
CR-7's identity/reference discipline exists to prevent. Whole-operation
refusal closes that hole by construction: nothing is removed until nothing
blocks removal. Alongside the reversal, `identifiers` became optional
(default: every marked entity), the `limit` parameter was dropped, and
`entity_type` was demoted from a scoping filter to a non-scoping pre-flight
check. Evidence: `plan_manager/commands/runtime_purge_batch_command.py`
(`version: ClassVar[str] = "2.0.0"`), `tests/test_runtime_purge_batch_command.py`.

### 2.2 The seventeen-command anchor-parameter contract break

`plan_manager/domain/primary_anchor.py` collapsed the anchor-family
parameter contract in a documented **TRANSITION** posture, deliberately
placed **last** in the execution order because it breaks the
seventeen-command anchor-parameter contract in one coordinated release
rather than incrementally. During transition: the legacy anchor family is
still accepted and normalized rather than rejected, so callers on the old
parameter shape keep working. Alongside it, an owner-form surface was added:
`resolve_owner` — routed through the identity registry, which **outranks**
the caller's claimed discriminator when the two disagree —
`owner_form_to_columns` (dual-writes into the legacy columns so both old and
new readers see consistent data), `validate_owner_change` (delegates to
`admission.ensure_owner_acyclic`, so an owner edge can never be pointed into
a cycle), and `owner_filter_predicate`. The `0029_owner_edge_schema.sql`
migration lays down the new `owner` columns additively (`owner_uuid` on
`bug_report` specifically, to avoid colliding with that table's
pre-existing human-assignee `owner` text column added in migration 0013;
plain `owner` on every other anchor-family table). These columns are
populated only by the `plan_manager/maintenance/anchor_cutover.py`
transport — dry-run by default, with canonical verification and rollback on
the caller's own transaction — and stay unpopulated (NULL) until that
transport is run live. The legacy anchor columns remain authoritative until
a successor drops them after the transport runs live (section 5).
`reanchor_guard.guard_owner_update` unifies re-anchoring as an owner update
for the shared anchor family of four (`todo`, `wish`, `calendar_entry`,
`escalation`); `bug_report` keeps its own pre-existing `source_*` route
rather than joining that unification, because its vocabulary split predates
this campaign. Evidence: `plan_manager/domain/primary_anchor.py`,
`plan_manager/domain/reanchor_guard.py`, `plan_manager_db/migrations/0029_owner_edge_schema.sql`,
`tests/test_primary_anchor_owner_form.py`, `tests/maintenance/test_anchor_cutover.py`.

## 3. Two-release cutover evidence

CR-7's live acceptance ran across three deployed releases, each a full live
regression pass rather than a unit-test-only gate:

- **Compatibility-state pipeline, 0.1.95**: **563 passed / 0 failed / 121
  skipped of 684** live checks, with the legacy anchor/parameter surface
  still accepted.
- **Direct-state pipeline, 0.1.96**: **563 passed / 0 failed / 121 skipped
  of 684** — numerically identical to 0.1.95. This equality is the explicit
  acceptance criterion of G-004/T-002/A-003: the two states must be
  behaviorally indistinguishable to a live client, proving the transition
  posture in section 2.2 changes internals without changing observable
  contract.
- **G-005/G-006 live acceptance, 0.1.98**: **586 passed / 0 failed / 117
  skipped of 703**, with every spec runner dispatched (guarded by the
  `spec_runner_dispatch` structural check added in this campaign
  specifically to catch silent runner truncation — see section 5's sibling
  note on regressions added).

During these live campaigns, four defects were found and closed within the
same execution, each with a full reproduce → RED → fix → live-verify → close
chain recorded in the runtime registry: `396ea09b` (R27, pagination
data-dependency), `ac4e1ae7` (R28, plan-delete guard regression), `9efa5ec5`
(R31, composite-id audit NULL — a duplicate report `c35d5e0d` filed from
another session against the same defect was closed alongside it, since a
trapped green cascade had made the underlying commit look re-committable),
and `1cbe201e` (R38, paragraph seat registration NULL). None of the four
remain open.

## 4. Runtime-registry closures this plan carries

- **todo `09a4d9af`** (export/import round trip) — **closed**. Evidence:
  `cr7-roundtrip` pipeline check, `tests/exchange/test_cr7_roundtrip.py` (10
  tests, including 4 deliberate RED paths).
- **todo `4bb0f85b`** (null removes key) — **partially closed**. The
  runtime-entity update semantics (a field update carrying `null` removes
  the key rather than storing a null value) is proven live via regression
  `R37` on both 0.1.95 and 0.1.96
  (`R37_4bb0f85b_null_removes_key` in `tests/test_live_smoke_script.py`).
  The `step_update.fields` side of this same todo is explicitly **not**
  closed by this campaign and remains open — state this precisely, since the
  todo's title covers both surfaces and only one closed here.
- **bug `5c0ddc16`** (wish reanchor-by-owner) — **closed by construction**
  via `reanchor_guard.guard_owner_update` (section 2.2). Evidence:
  `tests/test_bug_5c0ddc16_wish_reanchor_guard.py`. The dedicated
  `wish_reanchor` **command** surface is not exposed by this campaign — it
  is an open residual, listed in section 5.
- **wish `74ee352d`** (closed vocabularies as schema enums, not
  rejection-message folklore) — delivered as a **pinned contract**, not yet
  as shipped schema. `plan_manager/pipeline_checks/expected_openapi.py`
  pins the eight closed vocabularies (bug kind: 14, bug severity: 5, bug
  status: 11, todo status: 6, wish kind: 7, wish status: 7, calendar_entry
  status: 4, runtime_link type: 8) as literal `frozenset`s copied from the
  domain Enums at write time — deliberately not re-derived from the Enum at
  compare time, so an accidental future Enum edit disagrees with the pin and
  `tests/test_expected_openapi.py` catches it. Per-carrier enum state is
  recorded per (command, parameter): `runtime_link_add.link_type` is
  `"full"` (already declares the whole enum); the rest are recorded
  `"absent"` — pinned as the documented current truth, not as the desired
  end state. Exposing those enums in the live JSON schemas is the successor
  change this pin makes safe to make (section 5).
- **bug `b230a02b`** / **wish `2f995f07`**, schema-surface part (unified
  create-parameter vocabulary) — **pinned, not unified**. `bug_create`'s
  divergent parameter shape versus `todo_create`/`wish_create`'s shared
  `description` + eight `anchor_*` fields is recorded in
  `expected_openapi.py` as a named, GREEN, known exception
  (`is_known_exception: bool # True only for bug_create`). Evidence:
  `tests/test_expected_openapi.py` (`bug b230a02b: bug_create's divergent
  shape is a documented, GREEN exception`). Unifying `bug_create` onto the
  shared shape is a later deliberate contract change; when made, it will
  show as a RED check against this pin until the pin itself is updated in
  the same release — that is by design, so the unification cannot land
  silently.

## 5. Open after execution

- **Bug `c315ff84`** — the hard-delete guard cannot probe composite/scoped
  identities; this is the reason the six `cr7-no-out-of-mechanism-write`
  compatibility exceptions in section 1 still exist. Recommend a dedicated
  mechanics bugfix cycle whose acceptance criterion is retiring all six
  markers to zero.
- **The anchor-cutover transport has not been run live.** Running
  `plan_manager/maintenance/anchor_cutover.py` against the live database,
  then dropping the legacy anchor columns, then exposing the `wish_reanchor`
  command and the owner-form surfaces described in section 2.2, is
  recommended as a dedicated successor CR — the transition posture in
  section 2.2 is intentionally reversible only until that CR ships.
- **Bug `5d923c91`** (prompt-chain waves) — open, unrelated to this
  campaign's scope; carried forward.
- **Bug `845b43a8`** (aggregate `plan.status`) — open; carried forward.
- **Bug `fa15d288`** plus wishes `01cdd729`, `78575724`, `e6924bbc` — the
  context-economy CR; open, recommend grouping into one successor cycle as
  previously scoped.
- **Wishes `03f4518b`, `85c4b673`** plus todos `2b6d295d`, `299c1037` — the
  authoring namespace-closure CR; open, recommend grouping into one
  successor cycle as previously scoped.
- **Bug `b230a02b` / wish `2f995f07` unification release** — the schema-
  surface part is pinned (section 4); the actual unification of
  `bug_create` onto the shared parameter shape is not done and is
  recommended as its own release, gated by the pin flip described above.
- **`todo_get` / `comment_get` metadata prose** still describes a
  pre-G-006 visibility model; recommend a documentation-only follow-up to
  bring the prose in line with G-006's shipped behavior.
- **`scripts/live_smoke.py`'s `pyyaml` dependency** is not documented in the
  pipeline doc; recommend a one-line addition to the live-smoke pipeline
  documentation noting the dependency.
- **Wish `66651591`** (export preservation surface) — filed during this
  campaign because `plan_delete(hard)` purges the export directory by
  design and no public surface preserves an export across a hard delete;
  regression `R38` was downgraded to dry-run-valid plus `DUPLICATE_ID`
  refusal plus byte-stable re-export to work around the gap rather than
  cover the original round-trip claim. Recommend closing the wish before
  attempting to restore the full round-trip regression.
