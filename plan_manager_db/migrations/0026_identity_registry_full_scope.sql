-- 0026_identity_registry_full_scope.sql
--
-- Extend the entity_identity registry (created in 0015) to the full scope of
-- entity tables, and give it a kind so that a planning-time namespace
-- reservation can occupy an identifier before any row exists for it.
--
-- Scope decision recorded in docs/db/schema_inventory.md and
-- docs/db/identity_reconciliation.md: 43 tables exist; 39 are in scope and 4
-- are deliberately excluded (step_runtime is keyed by its parent,
-- embedding_cache is content-addressed, command_metric is an append-only
-- measurement log, entity_identity is the registry itself).
--
-- 34 tables already carry 0015-pattern triggers. Five ordinary identified,
-- soft-deletable tables were never wired because migrations 0019 and 0020
-- omitted the trigger block: escalation_policy, answer_envelope,
-- role_model_binding, invocation_profile, step_assignment. This migration
-- wires them and backfills every in-scope table.
--
-- Safety: additive only. No table is rewritten exclusively, no object is
-- dropped, and the 0015 trigger functions are reused unmodified. Safe to run
-- against a live database that holds open cascades and soft-deleted rows:
-- nothing outside entity_identity is written, and every statement is
-- idempotent on re-run.

-- Step 1: reservation support on the registry table (additive columns).
-- kind defaults to 'entity' so the unmodified 0015 trigger function, which
-- inserts only (id, table_name, entity_type), keeps producing correct rows.
ALTER TABLE entity_identity ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT 'entity';
ALTER TABLE entity_identity ADD COLUMN IF NOT EXISTS reserved_by text NULL;
ALTER TABLE entity_identity ADD COLUMN IF NOT EXISTS note text NULL;

UPDATE entity_identity SET kind = 'entity' WHERE kind IS NULL;

CREATE INDEX IF NOT EXISTS entity_identity_kind ON entity_identity (kind);

-- Step 2: backfill every in-scope table. One idempotent INSERT per table,
-- mirroring the 0015 entity_type mapping, including the five divergences
-- (bug_report -> bug, todo_item -> todo, runtime_comment -> comment,
-- wish_item -> wish, runtime_audit_log -> runtime_audit).

-- Plan-truth tables.
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'plan', 'plan', 'entity' FROM plan ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'paragraph', 'paragraph', 'entity' FROM paragraph ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'concept', 'concept', 'entity' FROM concept ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'relation', 'relation', 'entity' FROM relation ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'step', 'step', 'entity' FROM step ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'node_version', 'node_version', 'entity' FROM node_version ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'revision', 'revision', 'entity' FROM revision ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'ref', 'ref', 'entity' FROM ref ON CONFLICT (id) DO NOTHING;
-- cascade is a reserved word and must stay quoted, as it is in 0015.
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'cascade', 'cascade', 'entity' FROM "cascade" ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'cascade_request', 'cascade_request', 'entity' FROM cascade_request ON CONFLICT (id) DO NOTHING;

-- Derived stores that carry an identity.
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'context_block', 'context_block', 'entity' FROM context_block ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'srt_snapshot', 'srt_snapshot', 'entity' FROM srt_snapshot ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'runtime_audit_log', 'runtime_audit', 'entity' FROM runtime_audit_log ON CONFLICT (id) DO NOTHING;

-- Runtime work-layer entities.
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'todo_item', 'todo', 'entity' FROM todo_item ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'todo_link', 'todo_link', 'entity' FROM todo_link ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'runtime_comment', 'comment', 'entity' FROM runtime_comment ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'execution_attempt', 'execution_attempt', 'entity' FROM execution_attempt ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'review_result', 'review_result', 'entity' FROM review_result ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'escalation', 'escalation', 'entity' FROM escalation ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'escalation_policy', 'escalation_policy', 'entity' FROM escalation_policy ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'answer_envelope', 'answer_envelope', 'entity' FROM answer_envelope ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'runtime_link', 'runtime_link', 'entity' FROM runtime_link ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'wish_item', 'wish', 'entity' FROM wish_item ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'calendar_entry', 'calendar_entry', 'entity' FROM calendar_entry ON CONFLICT (id) DO NOTHING;

-- Bug lifecycle entities.
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'bug_report', 'bug', 'entity' FROM bug_report ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'bug_impact', 'bug_impact', 'entity' FROM bug_impact ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'bug_fix', 'bug_fix', 'entity' FROM bug_fix ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'bug_fix_propagation', 'bug_fix_propagation', 'entity' FROM bug_fix_propagation ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'project_dependency', 'project_dependency', 'entity' FROM project_dependency ON CONFLICT (id) DO NOTHING;

-- Agent-configuration entities.
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'provider', 'provider', 'entity' FROM provider ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'model', 'model', 'entity' FROM model ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'model_binding', 'model_binding', 'entity' FROM model_binding ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'role', 'role', 'entity' FROM role ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'role_model_binding', 'role_model_binding', 'entity' FROM role_model_binding ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'tool', 'tool', 'entity' FROM tool ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'toolset', 'toolset', 'entity' FROM toolset ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'toolset_membership', 'toolset_membership', 'entity' FROM toolset_membership ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'invocation_profile', 'invocation_profile', 'entity' FROM invocation_profile ON CONFLICT (id) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type, kind)
SELECT uuid, 'step_assignment', 'step_assignment', 'entity' FROM step_assignment ON CONFLICT (id) DO NOTHING;

-- Step 3: registration triggers for the five in-scope tables that lack them.
-- The 0015 trigger functions are reused unchanged. DROP TRIGGER IF EXISTS
-- before CREATE is the repository's conditional-creation idiom for triggers;
-- it drops only a trigger this migration is about to recreate identically, so
-- it is idempotent rather than destructive.

DROP TRIGGER IF EXISTS entity_identity_escalation_policy_insert ON escalation_policy;
CREATE TRIGGER entity_identity_escalation_policy_insert
AFTER INSERT ON escalation_policy
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('escalation_policy', 'escalation_policy');
DROP TRIGGER IF EXISTS entity_identity_escalation_policy_delete ON escalation_policy;
CREATE TRIGGER entity_identity_escalation_policy_delete
AFTER DELETE ON escalation_policy
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

DROP TRIGGER IF EXISTS entity_identity_answer_envelope_insert ON answer_envelope;
CREATE TRIGGER entity_identity_answer_envelope_insert
AFTER INSERT ON answer_envelope
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('answer_envelope', 'answer_envelope');
DROP TRIGGER IF EXISTS entity_identity_answer_envelope_delete ON answer_envelope;
CREATE TRIGGER entity_identity_answer_envelope_delete
AFTER DELETE ON answer_envelope
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

DROP TRIGGER IF EXISTS entity_identity_role_model_binding_insert ON role_model_binding;
CREATE TRIGGER entity_identity_role_model_binding_insert
AFTER INSERT ON role_model_binding
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('role_model_binding', 'role_model_binding');
DROP TRIGGER IF EXISTS entity_identity_role_model_binding_delete ON role_model_binding;
CREATE TRIGGER entity_identity_role_model_binding_delete
AFTER DELETE ON role_model_binding
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

DROP TRIGGER IF EXISTS entity_identity_invocation_profile_insert ON invocation_profile;
CREATE TRIGGER entity_identity_invocation_profile_insert
AFTER INSERT ON invocation_profile
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('invocation_profile', 'invocation_profile');
DROP TRIGGER IF EXISTS entity_identity_invocation_profile_delete ON invocation_profile;
CREATE TRIGGER entity_identity_invocation_profile_delete
AFTER DELETE ON invocation_profile
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

DROP TRIGGER IF EXISTS entity_identity_step_assignment_insert ON step_assignment;
CREATE TRIGGER entity_identity_step_assignment_insert
AFTER INSERT ON step_assignment
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('step_assignment', 'step_assignment');
DROP TRIGGER IF EXISTS entity_identity_step_assignment_delete ON step_assignment;
CREATE TRIGGER entity_identity_step_assignment_delete
AFTER DELETE ON step_assignment
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

-- Step 4: the reservation kind.
--
-- RESERVED_KIND = 'project_reservation', used by
-- plan_manager.storage.identity.reserve_project_uuid. A row with this kind
-- occupies an identifier without any local row existing for it anywhere, so a
-- future external project UUID cannot collide with an entity, a plan, or
-- another reservation. External project identifiers remain external; no local
-- project table is created to own them.
--
-- For kind = 'project_reservation':
--   reserved_by  holds the actor that claimed the identifier (never NULL).
--   note         holds the optional free-text justification.
--   table_name   is the empty string, because no table owns the identifier.
--   entity_type  repeats 'project_reservation'.
-- For kind = 'entity' both reserved_by and note are NULL.

-- ROLLBACK NOTES
--
-- No automatic rollback exists. To reverse this migration by hand, run the
-- inverse statements below in this order, then delete this filename from the
-- schema_migration bookkeeping table so the loop can re-apply it.
--
--   DROP TRIGGER IF EXISTS entity_identity_escalation_policy_insert ON escalation_policy;
--   DROP TRIGGER IF EXISTS entity_identity_escalation_policy_delete ON escalation_policy;
--   DROP TRIGGER IF EXISTS entity_identity_answer_envelope_insert ON answer_envelope;
--   DROP TRIGGER IF EXISTS entity_identity_answer_envelope_delete ON answer_envelope;
--   DROP TRIGGER IF EXISTS entity_identity_role_model_binding_insert ON role_model_binding;
--   DROP TRIGGER IF EXISTS entity_identity_role_model_binding_delete ON role_model_binding;
--   DROP TRIGGER IF EXISTS entity_identity_invocation_profile_insert ON invocation_profile;
--   DROP TRIGGER IF EXISTS entity_identity_invocation_profile_delete ON invocation_profile;
--   DROP TRIGGER IF EXISTS entity_identity_step_assignment_insert ON step_assignment;
--   DROP TRIGGER IF EXISTS entity_identity_step_assignment_delete ON step_assignment;
--
--   DELETE FROM entity_identity WHERE kind = 'project_reservation';
--
--   DROP INDEX IF EXISTS entity_identity_kind;
--   ALTER TABLE entity_identity DROP COLUMN IF EXISTS note;
--   ALTER TABLE entity_identity DROP COLUMN IF EXISTS reserved_by;
--   ALTER TABLE entity_identity DROP COLUMN IF EXISTS kind;
--
-- The Step 2 backfill is deliberately NOT listed above. It is non-destructive:
-- it only records mappings for rows that already exist, and the 0015 triggers
-- would have created the same rows had they been present at insert time.
-- Deleting those mappings would strip identity from live entities, so the
-- backfill is intentionally left in place on rollback. Only the reservation
-- rows, which no entity owns, are removed.
