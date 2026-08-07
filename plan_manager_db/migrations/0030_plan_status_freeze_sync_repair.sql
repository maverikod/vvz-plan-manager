-- 0030_plan_status_freeze_sync_repair.sql
--
-- Bug 845b43a8: plan.status was written exactly once, by create_plan (always
-- 'draft'), and never synced with the authoritative step lifecycle tree
-- afterwards. cascade.begin._all_steps_frozen carried a comment stating this
-- outright: "Plan-level status is never set to 'frozen' by any command
-- surface." As a result, plan_status and plan_list kept reporting 'draft'
-- forever, even after step_transition(scope='whole_plan', to_status='frozen')
-- had frozen every step and the gate was green.
--
-- The application-layer fix (plan_manager.domain.plan_status_sync) makes
-- step_transition and plan_unfreeze keep plan.status in sync going forward.
-- This migration is the one-time DATA repair for rows written before that
-- fix existed, using the exact same aggregate rule the application layer
-- now enforces (see plan_status_sync.derive_plan_status):
--
--   * a plan with at least one step, all of them 'frozen'      -> 'frozen'
--   * every other plan (empty step set, or any non-frozen step) -> 'draft'
--
-- This never touches plan.completed (bug c3950b83): that lock is an
-- independent mechanism this migration does not read or write. The two
-- UPDATEs below are idempotent (the `AND status != ...` guard makes a
-- re-run over an already-repaired table a no-op) and additive-only: no
-- column, table, or row is added or removed, and no other table's data is
-- touched -- the plain btree index added below is the only additive DDL,
-- supporting plan_list's status filter now that the column is meaningful.

UPDATE plan SET status = 'frozen'
WHERE status != 'frozen'
  AND EXISTS (SELECT 1 FROM step s WHERE s.plan_uuid = plan.uuid)
  AND NOT EXISTS (
      SELECT 1 FROM step s WHERE s.plan_uuid = plan.uuid AND s.status != 'frozen'
  );

UPDATE plan SET status = 'draft'
WHERE status != 'draft'
  AND NOT (
      EXISTS (SELECT 1 FROM step s WHERE s.plan_uuid = plan.uuid)
      AND NOT EXISTS (
          SELECT 1 FROM step s WHERE s.plan_uuid = plan.uuid AND s.status != 'frozen'
      )
  );

CREATE INDEX IF NOT EXISTS plan_status_idx ON plan (status);

-- ROLLBACK NOTES
--
-- No automatic rollback exists. This migration only overwrites the `status`
-- column of `plan` rows whose stored value diverged from the step tree it is
-- supposed to summarize; the pre-repair values were, by definition, already
-- wrong (bug 845b43a8), so there is no meaningful "reverse" repair. If a
-- rollback is genuinely required, restore `plan.status` from a pre-migration
-- backup, run `DROP INDEX IF EXISTS plan_status_idx;`, and delete this
-- filename from the schema_migration bookkeeping table so the loop can
-- re-apply it.
