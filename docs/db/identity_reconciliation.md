# Identity foundation reconciliation

Produced by G-001/T-001/A-002 of plan `planmgr-cr6-entity-identity-crud`.

This document reconciles the four provisional identity artifacts that ship today
against the per-table facts recorded in `schema_inventory.md` and against the
full-scope requirement of this plan. It records facts and decisions. It contains
no code.

Every statement is drawn from the shipped sources named in each section.

---

## 1. `plan_manager/storage/identity.py`

### What it guarantees today

The module is 163 lines and exposes exactly one constant and six functions:

- `ALLOWED_TABLES` — a frozenset of eight plan-truth table names: `plan`,
  `paragraph`, `concept`, `relation`, `step`, `node_version`, `revision`, `ref`.
- `new_entity_uuid()` — returns `uuid.uuid4()`.
- `register_entity_identity(conn, *, entity_id, table_name, entity_type, created_at=None)`
- `unregister_entity_identity(conn, entity_id)`
- `resolve_entity_identity(conn, entity_id)` — raises `NotFoundError` when absent.
- `resolve_entity_identities_batch(conn, ids)`
- `resolve_scoped_name(conn, ...)`

Two properties of this module are load-bearing for the rest of the plan and both
differ from what the module's name suggests.

**`ALLOWED_TABLES` does not gate registration.** The constant is referenced in
exactly one executable place, `identity.py` line 153, inside
`resolve_scoped_name`, where it validates a caller-supplied table name before it
is interpolated into a scoped-name query. `register_entity_identity` never
consults it. `plan_manager/domain/runtime_validation.py` line 104 mentions it
only in a docstring. The eight-table list is therefore an allowlist for one
lookup helper, not the scope of the registry.

**A colliding identifier is swallowed, not rejected.** The INSERT in
`register_entity_identity` is:

```
INSERT INTO entity_identity (id, table_name, entity_type, created_at)
VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING
```

When the id is already registered for a different table or kind, the statement
succeeds, changes nothing, and returns normally. The caller receives no signal,
the first mapping survives, and the second entity's own INSERT proceeds. There
is today no deterministic duplicate-identifier failure anywhere in the module.

### Gap versus the full-scope requirement

- The registry must cover every entity kind, not one lookup helper's eight
  tables. `ALLOWED_TABLES` currently describes neither what is registered (the
  database registers 34 tables) nor what could be.
- Registration must reject a cross-kind collision deterministically instead of
  absorbing it. `ON CONFLICT DO NOTHING` is the exact opposite behaviour.
- There is no reservation kind, so a project UUID cannot be claimed before the
  entity exists.
- There is no single guard function that a create path can call to ask "is this
  identifier free for any kind".

### Decision: **extend**

Keep the module, the table, and all six existing signatures; they are consumed
by `plan_manager/domain/entity.py` and are correct as far as they go. Extend it
with the full-scope table set, an explicit exclusion map carrying a reason per
excluded table, a collision guard, and the reservation kind. Replacing the
module would break the four call sites in `entity.py` for no benefit, because
the defect is missing behaviour rather than wrong behaviour.

---

## 2. `plan_manager_db/migrations/0015_entity_identity_registry.sql`

### What it guarantees today

The migration creates:

- Table `entity_identity (id uuid PRIMARY KEY, table_name text NOT NULL,
  entity_type text NOT NULL, created_at timestamptz NOT NULL DEFAULT now())`.
  Note the primary key column is named `id`, not `uuid`.
- Two indexes: `entity_identity_table` on `table_name`,
  `entity_identity_type` on `entity_type`.
- Two trigger functions: `register_entity_identity_trigger()`, which inserts the
  mapping using arguments supplied per trigger, and
  `unregister_entity_identity_trigger()`, which deletes it.
- A backfill of **25 tables**, each as one
  `INSERT INTO entity_identity ... SELECT ... ON CONFLICT DO NOTHING`.
- **50 `CREATE TRIGGER` statements**, an AFTER INSERT and an AFTER DELETE pair
  for each of those 25 tables.

Later migrations extend the same pattern: `0016_runtime_link.sql` adds
`runtime_link`; `0018_agent_config_entities.sql` adds `model`, `provider`,
`role`, `tool`, `toolset`, `toolset_membership`; `0025_wish_and_calendar_entries.sql`
adds `wish_item` and `calendar_entry`. The shipped total is **34 registered
tables**, enumerated in `schema_inventory.md`. `cascade` is among them: its
triggers target the quoted identifier `"cascade"`, so a survey matching
`ON (\w+)` undercounts the registry by one.

The triggers are where the entity-type vocabulary is actually defined, and it
diverges from the table names in five places:
`bug_report -> bug`, `todo_item -> todo`, `runtime_comment -> comment`,
`wish_item -> wish`, `runtime_audit_log -> runtime_audit`.

### Gap versus the full-scope requirement

- Nine tables carry no triggers at all: `step_runtime`,
  `command_metric`, `embedding_cache`, `entity_identity`, `escalation_policy`,
  `answer_envelope`, `role_model_binding`, `invocation_profile`,
  `step_assignment`. Four of them are genuine non-entities: `step_runtime`
  (keyed by its parent), `embedding_cache` (content-addressed),
  `command_metric` (append-only), and `entity_identity` (the registry itself).
  The remaining five — `escalation_policy`, `answer_envelope`,
  `role_model_binding`, `invocation_profile` and `step_assignment` — are
  ordinary identified, soft-deletable records that were simply never wired,
  because migrations `0019` and `0020` omitted the trigger block.
- The table has no `kind` column, so a namespace reservation cannot be
  distinguished from a live entity mapping.
- There is no `reserved_by` or `note` column, so a reservation cannot record who
  claimed it or why.

### Decision: **extend**

Keep `0015` and its two trigger functions untouched; they are correct and every
later migration reuses them unchanged. Add a new numbered migration that widens
the trigger coverage to the remaining in-scope tables, adds the reservation
columns additively, and backfills existing rows. Rewriting `0015` is not an
option: it has been applied on the live database, and the migration discipline
is additive-only.

---

## 3. `plan_manager/domain/entity.py` — `DataclassEntity`

### What it guarantees today

`DataclassEntity` is the shared base contract. **37 modules** under
`plan_manager/` reference it. It declares the descriptor ClassVars
`ENTITY_TYPE`, `TABLE_NAME`, `ID_COLUMN`, `ID_COLUMNS`, `COLUMNS`,
`INSERT_COLUMNS`, `UPDATE_COLUMNS`, `SEARCH_COLUMNS`, `SOFT_DELETE_COLUMN`
(default `'deleted_at'`), `UPDATED_AT_COLUMN` (default `'updated_at'`), and
`REGISTER_IDENTITY` (default `True`), and it provides the `crud_*` family.

Its identity behaviour is concentrated in three places:

- `crud_create` registers the identity **before** executing the INSERT. The
  guard is `if cls.REGISTER_IDENTITY and cls.ID_COLUMN is not None and
  cls.ID_COLUMN in values`, then a further `isinstance(entity_id, uuid.UUID)`
  and `cls.TABLE_NAME is not None` check. `ALLOWED_TABLES` is not consulted, so
  registration scope is governed entirely by the per-class `REGISTER_IDENTITY`
  flag.
- `crud_get_identity` delegates to `resolve_entity_identity`.
- The physical-deletion path calls `unregister_entity_identity` for
  single-column-keyed entities.

`INSERT_COLUMNS` is a whitelist: `crud_create` raises
`ValueError("unknown insert columns for ...")` for any key outside it when the
tuple is non-empty.

### Gap versus the full-scope requirement

- Registration happens before the INSERT and can therefore leave a registry row
  behind if the INSERT fails and the surrounding transaction is not rolled back
  by the caller. The invariant "register in the same transaction as the insert"
  is real but undocumented on the function.
- There is no availability pre-check, so the collision is swallowed exactly as
  described in section 1.
- There is no exclusion mechanism: an entity either registers or sets
  `REGISTER_IDENTITY = False`, with no recorded reason.

### Decision: **extend**

Keep `DataclassEntity` and every `crud_*` signature; 37 consuming modules depend
on them and none needs to change. Extend `crud_create` with an availability
pre-check placed before the INSERT, move registration to after the INSERT, and
short-circuit both for deliberately excluded tables. This is additive: no
consumer module is edited.

---

## 4. `plan_manager/storage/runtime_hard_delete.py` and the reference-check tables

### What it guarantees today

A correction of record: the reference-check tables named
`HARD_DELETE_REFERENCE_CHECKS` are **not defined in**
`plan_manager/storage/runtime_hard_delete.py`. The name appears there once, in
prose at line 213, pointing at the domain modules that own the declarations;
the module itself declares none. That module contains exactly six
thin audited wrappers — `hard_delete_todo`, `hard_delete_comment`,
`hard_delete_bug`, `hard_delete_bug_impact`, `hard_delete_bug_fix`,
`hard_delete_bug_fix_propagation` — each of which calls the entity base and then
writes its own `record_runtime_change` audit row.

The reference-check declarations are split across two locations:

- `CENTRAL_REFERENCE_CHECKS` in `plan_manager/domain/entity.py`, keyed by twelve
  entity types: `plan`, `step`, `concept`, `todo`, `comment`,
  `execution_attempt`, `review_result`, `bug`, `bug_impact`, `bug_fix`,
  `provider`, `tool`.
- Per-entity `HARD_DELETE_REFERENCE_CHECKS` class attributes in eleven domain
  modules: `bug_fix.py`, `bug_impact.py`, `bug_report.py`, `concept.py`,
  `entity.py`, `execution_attempt.py`, `plan.py`, `review_result.py`, `step.py`,
  `todo.py`, `wish.py`.

Six entity types are declared in both places with identical tuples.

The admission check itself is `find_entity_reference_counts` in the entity base,
which returns `dict[str, int]` — per-column counts, with no referrer identities.
`hard_delete_entity` raises `EntityReferencedError` carrying those counts.

### Gap versus the full-scope requirement

- Coverage is partial. `schema_inventory.md` shows **28 of 43 tables declare no
  foreign key at all**, so almost every runtime-overlay and agent-config
  reference is a plain column that only these hand-written tables can see. Any
  column missing from them is invisible to the guard.
- The declarations are duplicated in two mechanisms that can drift apart.
- The refusal payload carries counts, not identities, so a caller cannot act on
  it.
- Refusals are never audited: `EntityReferencedError` is caught and mapped in
  `plan_manager/commands/errors.py` and nowhere else.
- Six wrappers write their own audit rows, so any future centralization of the
  audit into a shared guard must remove them or every deletion is counted twice.

### Decision: **replace**

Replace both declaration mechanisms with one static catalog module, and replace
`find_entity_reference_counts`/`hard_delete_entity` with a guard whose lookup SQL
is structurally separate from its delete SQL. The duplication and the
counts-only payload are wrong behaviour rather than missing behaviour, so
extension would preserve the defect. This work belongs to G-004, not to G-002;
it is recorded here only so the reconciliation is complete.

---

## Ordered extension plan for G-002

G-002 executes the identity half of this reconciliation in the following order.
Each item names the artifact it changes.

1. **`plan_manager/storage/identity.py`** — widen `ALLOWED_TABLES` to the
   in-scope table set from `schema_inventory.md`; add `EXCLUDED_TABLES` mapping
   each deliberately excluded table to a written reason; add
   `ensure_identity_available` as the single cross-kind collision guard, raising
   deterministically instead of absorbing the conflict; add
   `RESERVED_KIND = 'project_reservation'` with `reserve_project_uuid` and
   `release_project_reservation`, and make `resolve_entity_identity` report the
   reservation kind. Keep all six existing signatures backward-compatible.

2. **A new numbered migration** — add the `kind`, `reserved_by` and `note`
   columns to `entity_identity` additively; set `kind = 'entity'` for existing
   rows; backfill every in-scope table not yet present; create the missing
   `entity_identity_<table>_insert` and `entity_identity_<table>_delete` trigger
   pairs using the unchanged `0015` trigger functions; close with rollback
   notes. Idempotent on re-run and safe against the five open cascades.

3. **`plan_manager/domain/entity.py` `crud_create`** — call
   `ensure_identity_available` before the INSERT, register after it, skip both
   for `EXCLUDED_TABLES`, and document the same-transaction invariant. No
   consumer module changes.

4. **`plan_manager/storage/runtime_audit_store.py`** — register the two
   reservation audit actions, since `record_runtime_change` validates its
   `action` argument against `ALLOWED_ACTIONS` and rejects unknown values.

5. **`plan_manager/commands/errors.py`** — register the reservation
   not-found domain code, since the existing reachability contract suite
   asserts that every code a command advertises is registered.

6. **`plan_manager/commands/project_uuid_reserve_command.py`** — the reserve,
   release and resolve surface over the reservation API, audited on both
   mutating actions.

7. **`plan_manager/commands/inventory.py`**, the regression suites, and the
   live-smoke R-check — registration, test coverage, and live verification.

Items 4 and 5 are prerequisites of item 6 and are sequenced before it in the
plan's dependency graph.
