-- Migration 0022: plan-level completion lock (bug c3950b83).
--
-- L1 design ruling (2026-07-23, overruling an earlier per-step-status carve-out
-- attempt): execution bookkeeping on a shipped, frozen plan is recorded at the
-- PLAN level, not per atomic step. Adds two columns to `plan`:
--   * completed  -- when true, every mutating command that resolves its
--                   `plan` parameter to this plan refuses with the
--                   PLAN_COMPLETED domain code, except the two dedicated
--                   setter commands (plan_completed_set, plan_comment_set),
--                   which remain reachable at all times so the flag itself
--                   can always be unset.
--   * comment    -- a free-form note attached to the plan, always mutable
--                   regardless of freeze or completion state.
-- ADDITIVE ONLY: no ALTER COLUMN, no DROP, no TRUNCATE of any existing object.

ALTER TABLE plan
    ADD COLUMN completed boolean NOT NULL DEFAULT false,
    ADD COLUMN comment text NULL;
