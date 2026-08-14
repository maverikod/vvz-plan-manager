-- Migration 0031: supersede lifecycle for stale review results and execution
-- attempts (bug 74479c06 group-4 fix).
--
-- PROBLEM: review_result and execution_attempt had no way to record that a
-- stale record (a review verdict rendered against an input that has since
-- changed, or an execution attempt superseded by a re-run) was REPLACED by a
-- specific later record. The only tools available were leaving the stale
-- record looking current forever, or overwriting its own status/fields --
-- which would falsify the outcome it actually recorded (the bug's
-- expected_behavior: "record exact replacement linkage without falsifying
-- the original outcome").
--
-- FIX SHAPE: a forward pointer added to each table, written ONLY on the
-- STALE row, that never touches the row's own `status`. This is the same
-- bare-uuid, no-FK, additive-only technique execution_attempt.parent_attempt_uuid
-- already uses (0012_runtime_annotations_execution_review.sql) for the same
-- reason: soft-deleted or historical rows on either side of the pointer must
-- keep resolving without a constraint violation; validity is enforced at the
-- application/store layer (plan_manager.storage.entity_supersede_store), not
-- by the schema.
--
-- ADDITIVE ONLY: two nullable columns, two supporting indexes. No existing
-- column, table, row, or constraint is altered or dropped.

ALTER TABLE review_result ADD COLUMN IF NOT EXISTS superseded_by_uuid uuid NULL;
ALTER TABLE execution_attempt ADD COLUMN IF NOT EXISTS superseded_by_uuid uuid NULL;

CREATE INDEX IF NOT EXISTS review_result_superseded_by ON review_result (superseded_by_uuid);
CREATE INDEX IF NOT EXISTS execution_attempt_superseded_by ON execution_attempt (superseded_by_uuid);

-- ROLLBACK NOTES
--
-- Both columns are additive and NULL on every pre-existing row (no backfill
-- is performed or needed: a row written before this migration was never
-- superseded, by definition). To roll back: DROP INDEX
-- review_result_superseded_by; DROP INDEX execution_attempt_superseded_by;
-- ALTER TABLE review_result DROP COLUMN superseded_by_uuid; ALTER TABLE
-- execution_attempt DROP COLUMN superseded_by_uuid; then remove this
-- filename from the schema_migration bookkeeping table so the loop can
-- re-apply it.
