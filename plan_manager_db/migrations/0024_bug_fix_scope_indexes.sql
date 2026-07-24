-- Migration 0024: scope indexes for bug_fix and bug_fix_propagation (todo 070d7b13).
--
-- Audit of migrations 0009-0023 confirmed most accumulating runtime tables
-- already carry project/plan-scope indexes, but two real gaps remained:
--   * bug_fix.source_project_id (uuid NULL, added in 0013) had no index --
--     only bug_fix_bug and bug_fix_status exist on that table.
--   * bug_fix_propagation.linked_plan_uuid and .linked_todo_uuid (uuid NULL,
--     added in 0013) had no index -- only bug_fix_propagation_fix,
--     bug_fix_propagation_impact, and bug_fix_propagation_status exist on
--     that table.
-- This migration is strictly additive: it creates only the three indexes
-- below and performs no ALTER or DROP of any existing object.

CREATE INDEX bug_fix_source_project ON bug_fix (source_project_id);
CREATE INDEX bug_fix_propagation_plan ON bug_fix_propagation (linked_plan_uuid);
CREATE INDEX bug_fix_propagation_todo ON bug_fix_propagation (linked_todo_uuid);
