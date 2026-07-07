-- Migration 0006: soft deletion for plans.
--
-- A plan is soft-deleted by stamping deleted_at with the deletion time; a
-- NULL deleted_at marks a live plan. Soft-deleted plans are hidden from the
-- default plan catalog (plan_list) but otherwise behave normally and remain
-- resolvable by uuid or name. Hard deletion removes the plan row outright and
-- cascades to every child table through the existing ON DELETE CASCADE
-- foreign keys; it needs no schema change.

ALTER TABLE plan
    ADD COLUMN deleted_at timestamptz NULL;

CREATE INDEX plan_not_deleted ON plan (name) WHERE deleted_at IS NULL;
