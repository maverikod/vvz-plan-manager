-- 0027_relation_index_and_field_catalog.sql
--
-- CR-7 G-001/T-002/A-003. Two derived/protected structures of the uniform
-- storage contract (C-003, C-004):
--
--   reference_field  - the minimal protected field catalogue: one immutable
--                      field UUID per source property name plus a predefined
--                      flag. It does not constrain the target entity kind and
--                      never classifies UUID columns in advance; a record is
--                      ensured when a relation first arises and outlives the
--                      relations that used it, so a rebuild reuses the same
--                      field ref for the property name it rediscovers.
--
--   relation_index   - the derived index of immutable source-target-field
--                      triples projected from canonical scalar UUID columns.
--                      A derived speed structure, never canonical truth: it
--                      must stay atomically replaceable by rebuild, which is
--                      why neither table carries foreign keys onto entity
--                      tables - refs resolve through the identity registry.
--
-- The (source_ref, field_ref) primary key encodes that one source property
-- holds at most one reference: changing a reference deletes the old triple
-- and inserts the new one in the same CRUD transaction.
--
-- Safety: DDL-only and additive. No existing table is touched, no data is
-- moved, and every statement is idempotent on re-run.

-- Step 1: the protected reference-field catalogue.
CREATE TABLE IF NOT EXISTS reference_field (
    field_ref      uuid PRIMARY KEY,
    property_name  text NOT NULL,
    predefined     boolean NOT NULL DEFAULT FALSE,
    created_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT reference_field_property_name_key UNIQUE (property_name)
);

COMMENT ON TABLE reference_field IS
    'CR-7 protected field catalogue: immutable field UUID per source property '
    'name. Ordinary CRUD may ensure but never delete a record; schema-update '
    'admission deletes non-predefined records only; predefined records are '
    'undeletable.';

-- Step 2: the derived relation index over immutable triples.
CREATE TABLE IF NOT EXISTS relation_index (
    source_ref  uuid NOT NULL,
    target_ref  uuid NOT NULL,
    field_ref   uuid NOT NULL REFERENCES reference_field (field_ref),
    PRIMARY KEY (source_ref, field_ref)
);

COMMENT ON TABLE relation_index IS
    'CR-7 derived relation index: immutable (source_ref, target_ref, '
    'field_ref) triples projected from canonical scalar UUID columns. '
    'Replace-on-change only, atomically rebuildable, never canonical truth.';

-- Step 3: the lookups deletion and repair need.
CREATE INDEX IF NOT EXISTS relation_index_target_ref_idx
    ON relation_index (target_ref);
CREATE INDEX IF NOT EXISTS relation_index_source_ref_idx
    ON relation_index (source_ref);

-- Step 4: identity-registry decision, expressed as executable statements.
--
-- DELIBERATE EXCLUSION. Both tables of this migration are declared in
-- EXCLUDED_TABLES (plan_manager/storage/identity.py): reference_field is
-- protected catalogue metadata keyed by property name, and relation_index is
-- a derived projection that must stay atomically replaceable by rebuild.
-- Registering either in the registry would make the derived layer
-- identity-bearing, which C-004 forbids. The idempotent DROPs below are the
-- executable form of that decision: these tables must carry NO registry
-- triggers, now or after any earlier experiment.
DROP TRIGGER IF EXISTS entity_identity_reference_field_insert ON reference_field;
DROP TRIGGER IF EXISTS entity_identity_reference_field_delete ON reference_field;
DROP TRIGGER IF EXISTS entity_identity_relation_index_insert ON relation_index;
DROP TRIGGER IF EXISTS entity_identity_relation_index_delete ON relation_index;

-- ROLLBACK NOTES
--
-- No automatic rollback exists. To reverse this migration by hand, run the
-- inverse statements below in this order, then delete this filename from the
-- schema_migration bookkeeping table so the loop can re-apply it.
--
--   DROP INDEX IF EXISTS relation_index_source_ref_idx;
--   DROP INDEX IF EXISTS relation_index_target_ref_idx;
--   DROP TABLE IF EXISTS relation_index;
--   DROP TABLE IF EXISTS reference_field;
--
-- Both tables are derived/protected records: dropping them loses no
-- canonical truth, and the index is rebuilt from base tables on demand.
