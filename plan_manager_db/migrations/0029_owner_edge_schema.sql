-- 0029_owner_edge_schema.sql
--
-- CR-7 G-007/T-001/A-001. Target row-shape of the anchor collapse (C-002,
-- C-006): every discriminated eight-column anchor family in the schema is
-- being replaced by one direct ownership edge. This migration lays down that
-- target shape. It is Phase 1 of a two-phase discipline:
--
--   Phase 1 (this migration): additive DDL only. Add the new `owner` uuid
--     column (NULL-able) to every table that carries the discriminated
--     anchor family, plus the indexes owner-filtered queries need. The old
--     anchor_*/source_* discriminator and identifier columns are left
--     completely untouched -- they remain the live, authoritative anchor
--     representation until Phase 2.
--
--   Phase 2 (a later cutover migration, NOT this one): a transport step
--     (owned by a different atomic step) reads each row's discriminated
--     anchor family, resolves the single UUID it points at through the
--     identity registry (entity_identity, migration 0015) and writes it into
--     the new `owner` column via export/import. Only after that data has
--     moved and the direct state is accepted does the cutover migration
--     DROP COLUMN the old anchor_*/source_* identifier columns. This file
--     performs no data movement and drops nothing.
--
-- Path columns: anchor_file_path (and bug_report's source_file_path) are
-- KEPT, untouched, as descriptive attributes -- they record where the
-- anchor lives in a filesystem sense, which is orthogonal to which entity
-- owns the row, so the collapse does not absorb them into `owner`.
--
-- Table derivation. Every anchored runtime table in the migration chain
-- (0001-0028) was grepped for anchor_project_id / source_anchor_type /
-- primary_anchor_type to find every discriminated eight-column anchor
-- family:
--
--   todo_item          (0010) primary_anchor_type + anchor_project_id,
--                       anchor_file_path, anchor_plan_uuid,
--                       anchor_revision_uuid, anchor_step_uuid,
--                       anchor_step_path, anchor_ref_id  -- full 8-col family
--   wish_item           (0025) same anchor_* shape as todo_item -- full family
--   bug_report          (0013) source_anchor_type + source_project_id,
--                       source_file_path, source_plan_uuid,
--                       source_revision_uuid, source_step_uuid,
--                       source_step_path, source_ref_id  -- full 8-col
--                       family, source_* naming
--   runtime_comment     (0012) same anchor_* shape as todo_item -- full family
--   calendar_entry      (0025) same anchor_* shape as todo_item -- full family
--   escalation          (0012) primary_anchor_type + the same anchor_* shape
--                       -- full family
--   answer_envelope     (0020) anchor_plan_uuid / anchor_step_uuid /
--                       attempt_uuid only -- a PARTIAL family (no
--                       discriminator column, no anchor_project_id, no
--                       anchor_file_path); still collapses to one `owner`
--                       edge per the domain layer's own OWNER_GAP note
--                       (plan_manager/domain/answer_envelope.py): "the owner
--                       column materializes in the G-007 anchor collapse".
--
-- Deliberately EXCLUDED (audited, not part of the discriminated anchor
-- family, so no `owner` column is added by this migration):
--
--   review_result   (0012) object_type discriminates reviewed_attempt_uuid
--                   vs reviewed_revision_uuid. That is a two-column typed
--                   pair, not the anchor_*/source_* family this migration
--                   collapses; its own OWNER_GAP note mentions "the G-007
--                   anchor collapse" generically, but the concrete shape it
--                   awaits is a future, separate step -- excluded here.
--   execution_attempt (0012) plan_uuid / step_uuid / todo_uuid / bug_fix_uuid
--                   are plain typed reference columns with no discriminator
--                   column at all -- not the anchor family -- excluded.
--   bug_fix         (0013) carries only source_project_id (a single scope
--                   column, no discriminator, no sibling anchor_*/source_*
--                   columns) -- not the anchor family -- excluded.
--
-- Naming collision (bug_report only). bug_report already has a column
-- literally named `owner` (text NULL, added in 0013): the human-readable
-- assignee of the bug report, unrelated to this edge. `ADD COLUMN IF NOT
-- EXISTS owner uuid` on bug_report would silently no-op against that
-- existing text column (IF NOT EXISTS matches on name only, not type),
-- which would leave bug_report permanently without its ownership edge while
-- looking like it succeeded. To avoid that collision, bug_report's new
-- column is named `owner_uuid` instead of `owner`; every other table in
-- this migration uses `owner`. A later Python-layer step sets each entity's
-- OWNER_COLUMN accordingly (bug_report -> "owner_uuid", the rest -> "owner").
--
-- Indexes. Until Phase 2 populates `owner`, the column is NULL on every
-- existing row, so a plain btree index would spend its bulk indexing NULLs
-- that owner-filtered queries never touch. Each index below is a PARTIAL
-- btree, `WHERE <column> IS NOT NULL`, matching the low-write-overhead
-- pattern already used in this schema (e.g. execution_attempt_status,
-- migration 0012) and serving exactly the queries that filter or join on a
-- populated owner.
--
-- Safety: DDL-only and additive. No existing column, index, table or row is
-- touched; every statement is idempotent on re-run; no data moves.

ALTER TABLE todo_item ADD COLUMN IF NOT EXISTS owner uuid NULL;
ALTER TABLE wish_item ADD COLUMN IF NOT EXISTS owner uuid NULL;
ALTER TABLE bug_report ADD COLUMN IF NOT EXISTS owner_uuid uuid NULL;
ALTER TABLE runtime_comment ADD COLUMN IF NOT EXISTS owner uuid NULL;
ALTER TABLE calendar_entry ADD COLUMN IF NOT EXISTS owner uuid NULL;
ALTER TABLE escalation ADD COLUMN IF NOT EXISTS owner uuid NULL;
ALTER TABLE answer_envelope ADD COLUMN IF NOT EXISTS owner uuid NULL;

CREATE INDEX IF NOT EXISTS todo_item_owner_idx
    ON todo_item (owner) WHERE owner IS NOT NULL;
CREATE INDEX IF NOT EXISTS wish_item_owner_idx
    ON wish_item (owner) WHERE owner IS NOT NULL;
CREATE INDEX IF NOT EXISTS bug_report_owner_uuid_idx
    ON bug_report (owner_uuid) WHERE owner_uuid IS NOT NULL;
CREATE INDEX IF NOT EXISTS runtime_comment_owner_idx
    ON runtime_comment (owner) WHERE owner IS NOT NULL;
CREATE INDEX IF NOT EXISTS calendar_entry_owner_idx
    ON calendar_entry (owner) WHERE owner IS NOT NULL;
CREATE INDEX IF NOT EXISTS escalation_owner_idx
    ON escalation (owner) WHERE owner IS NOT NULL;
CREATE INDEX IF NOT EXISTS answer_envelope_owner_idx
    ON answer_envelope (owner) WHERE owner IS NOT NULL;

-- ROLLBACK NOTES
--
-- No automatic rollback exists. To reverse this migration by hand, run the
-- inverse statements below in this order, then delete this filename from the
-- schema_migration bookkeeping table so the loop can re-apply it.
--
--   DROP INDEX IF EXISTS answer_envelope_owner_idx;
--   DROP INDEX IF EXISTS escalation_owner_idx;
--   DROP INDEX IF EXISTS calendar_entry_owner_idx;
--   DROP INDEX IF EXISTS runtime_comment_owner_idx;
--   DROP INDEX IF EXISTS bug_report_owner_uuid_idx;
--   DROP INDEX IF EXISTS wish_item_owner_idx;
--   DROP INDEX IF EXISTS todo_item_owner_idx;
--
--   ALTER TABLE answer_envelope DROP COLUMN IF EXISTS owner;
--   ALTER TABLE escalation DROP COLUMN IF EXISTS owner;
--   ALTER TABLE calendar_entry DROP COLUMN IF EXISTS owner;
--   ALTER TABLE runtime_comment DROP COLUMN IF EXISTS owner;
--   ALTER TABLE bug_report DROP COLUMN IF EXISTS owner_uuid;
--   ALTER TABLE wish_item DROP COLUMN IF EXISTS owner;
--   ALTER TABLE todo_item DROP COLUMN IF EXISTS owner;
--
-- Safe at any time before Phase 2 runs: `owner`/`owner_uuid` are new,
-- currently-unpopulated columns with no dependents, so dropping them loses
-- no data. Once a Phase-2 cutover migration has populated and depended on
-- these columns, this rollback is no longer safe and a forward fix should
-- be preferred instead.
