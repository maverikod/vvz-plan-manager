# CR-6 migration discipline

Produced by G-005/T-001/A-001 of plan `planmgr-cr6-entity-identity-crud`.

This is the normative checklist every migration this plan adds, and every
migration added after it, must satisfy. It documents the convention that
migrations `0001` through `0026` already follow and the auto-apply mechanism in
`plan_manager_db/init.sh` that runs them.

## 1. Numbered-idempotent-SQL convention

Migrations are numbered files under `plan_manager_db/migrations/`, one file per
numeric prefix. `0001_initial_schema.sql` through
`0026_identity_registry_full_scope.sql` exist today. Each file executes exactly
once per database and is recorded by filename in the `schema_migration`
bookkeeping table.

**All DDL is additive.** `CREATE TABLE`, `CREATE INDEX`, `CREATE FUNCTION`,
`CREATE TRIGGER`, and `ALTER TABLE ... ADD COLUMN` are permitted. Dropping a
table, dropping a column, dropping an index, altering a column type, and
truncating are not. The reason is concrete rather than stylistic: old rows must
stay interpretable and the content-addressed version store's refs must stay
resolvable, so nothing a previous revision recorded may become unreadable.

**Idempotency markers are mandatory**, because a migration may be re-attempted
after a partial failure:

- `CREATE TABLE IF NOT EXISTS`
- `CREATE INDEX IF NOT EXISTS` / `CREATE UNIQUE INDEX IF NOT EXISTS`
- `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`
- `INSERT ... ON CONFLICT ... DO NOTHING` for every backfill
- `DROP TRIGGER IF EXISTS` immediately before each `CREATE TRIGGER`, which is
  the repository's conditional-creation idiom for triggers: it removes only a
  trigger the same migration is about to recreate identically, so it is
  idempotent rather than destructive

Repository exemplars:

- `0015_entity_identity_registry.sql` — 25 backfill statements, each
  `INSERT INTO entity_identity ... SELECT ... ON CONFLICT (id) DO NOTHING`,
  plus 50 `CREATE TRIGGER` statements (an AFTER INSERT and AFTER DELETE pair
  for each of those 25 tables).
- `0025_wish_and_calendar_entries.sql` — two new tables together with their
  identity-registration trigger pairs, the pattern a new entity table follows.
- `0026_identity_registry_full_scope.sql` — additive reservation columns, 39
  backfills covering the full in-scope set, and trigger pairs for the five
  tables that `0019` and `0020` never wired.

One exemption is visible in the chain and is deliberate: `"cascade"` must be
written as a quoted identifier because `cascade` is a reserved word. A survey
that matches `ON (\w+)` silently skips its triggers and undercounts the
registry by one.

## 2. Auto-apply mechanism

`plan_manager_db/init.sh` runs at container start and applies pending
migrations. Step by step:

1. The bookkeeping table is created if absent:
   `CREATE TABLE IF NOT EXISTS schema_migration (filename text PRIMARY KEY, applied_at timestamptz NOT NULL)`.
2. Migration files are iterated in ascending filename order, which is why the
   numeric prefix is zero-padded: lexical order and intended order must agree.
3. For each file, `SELECT 1 FROM schema_migration WHERE filename = ...` decides
   whether it has already been applied. If it has, the file is skipped.
4. A pending file is applied with `psql -1 -f <migration>`, a single
   transaction, so the file either applies whole or not at all.
5. Immediately after a successful apply, the filename is recorded with
   `INSERT INTO schema_migration (filename, applied_at) VALUES (..., now())`.
6. The run finishes by reporting
   `migrations_applied=<n> migrations_skipped=<n>`.

Guarantees that follow, and their limits:

- **Re-running init.sh is a no-op** once every migration is recorded.
- **A partial failure resumes** from the first unapplied migration, because the
  bookkeeping row is written only after the apply succeeds.
- **The single-transaction apply is per file, not per run.** A file that fails
  leaves nothing behind, but files applied earlier in the same run stay applied.
- The idempotency markers in section 1 are what make step 4 safe to retry. A
  migration that omits them can corrupt on re-run, and nothing in init.sh
  detects that.

## 3. Rollback-notes template

No automatic rollback exists. Every migration MUST therefore close with a
rollback-notes comment block naming the exact inverse of everything it adds.
The block serves three uses: dev and test cleanup, emergency DBA intervention,
and audit traceability of what a change actually touched.

```sql
-- ROLLBACK NOTES
--
-- No automatic rollback exists. To reverse this migration by hand, run the
-- inverse statements below in this order, then delete this filename from the
-- schema_migration bookkeeping table so the loop can re-apply it.
--
--   DROP TRIGGER IF EXISTS <trigger_name> ON <table>;      -- per added trigger
--   DROP INDEX IF EXISTS <index_name>;                     -- per added index
--   ALTER TABLE <table> DROP COLUMN IF EXISTS <column>;    -- per added column
--   DROP TABLE IF EXISTS <table>;                          -- per added table
--   DELETE FROM entity_identity WHERE kind = '<kind>';     -- per added kind
--
-- State explicitly which added rows are NOT reversed and why.
```

The last line is not optional. `0026` is the worked example: its backfill is
deliberately excluded from the rollback list, because those rows only record
mappings for entities that already exist and the `0015` triggers would have
created identical rows at insert time. Deleting them would strip identity from
live entities. Only the reservation rows, which no entity owns, are removed.

## 4. Entity identity trigger wiring

Whenever a migration introduces a new entity table, it MUST register that table
in the identity registry in the same migration, by creating the trigger pair
per the `0015`/`0025` pattern:

```sql
CREATE TRIGGER entity_identity_<table>_insert
AFTER INSERT ON <table>
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('<table>', '<entity_type>');

CREATE TRIGGER entity_identity_<table>_delete
AFTER DELETE ON <table>
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();
```

The `0015` trigger functions are reused unchanged by every later migration and
must stay that way. `register_entity_identity_trigger` inserts only
`(id, table_name, entity_type)`, which is why `0026` gave the `kind` column a
`DEFAULT 'entity'`: the unmodified function keeps producing correct rows.

Two rules about the arguments:

- `<entity_type>` is the user-facing ENTITY_TYPE and is NOT always the table
  name. The shipped divergences are `bug_report -> bug`, `todo_item -> todo`,
  `runtime_comment -> comment`, `wish_item -> wish`, and
  `runtime_audit_log -> runtime_audit`. The triggers are where this vocabulary
  is actually defined.
- A new table must also be classified in `plan_manager/storage/identity.py`, in
  either `ALLOWED_TABLES` or `EXCLUDED_TABLES` with a written reason. A table
  in neither is an unclassified gap.

Migrations `0019` and `0020` omitted this block and left five ordinary
identified tables unregistered — `escalation_policy`, `answer_envelope`,
`role_model_binding`, `invocation_profile`, `step_assignment`. `0026` repairs
that. The omission is the reason this section is normative rather than
advisory.

## 5. Additive-only enforcement

A migration MUST NOT contain `DROP TABLE`, `DROP COLUMN`, `DROP INDEX`,
`ALTER COLUMN`, or `TRUNCATE` outside the trailing rollback-notes comment
block.

Enforcement is mechanical, not a matter of review discipline:
`tests/test_runtime_migrations.py` scans the migration files for those
substrings, checks that one numeric prefix maps to one file, and checks that no
index name is defined twice across the chain. CR-6 extends the same pattern to
its own migrations in
`tests/test_cr6_migration_discipline_and_cascade_compat.py`, which additionally
requires that every new entity table in a CR-6 migration carries both trigger
names, and exercises the migration against a plan holding an open cascade.

That last check exists because open cascades are a normal, tolerated state on
the live server: five were open at inventory time on 2026-07-29 and remain open
by owner decision. A migration is therefore never allowed to assume it runs
against a quiescent database.
