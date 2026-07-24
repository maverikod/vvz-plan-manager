-- Migration 0023: attribute specific context blocks to their originating
-- child reference (bug a795ea4d).
--
-- context_bundle registered every child's compiled 'specific' block under
-- an identity keyed only by (node_path, child_level, kind, common_block,
-- scope_concepts, content_hash) -- with no per-child discriminator. When
-- two or more children of the same parent legitimately share an identical
-- concept scope, their compiled delta is byte-identical (worst case:
-- empty, when the scope is already fully covered by the parent's common
-- block) and hashes the same, so every child after the first silently
-- reused the first child's stored row: distinct AS children (e.g.
-- A-001..A-005) were served the SAME specific block_id, losing per-child
-- attribution entirely for the empty-delta case (block_get on the aliased
-- block showed total=0, blocks=[], content=[], with no way to tell which
-- child it belonged to).
--
-- Adds an explicit child_ref column and folds it into the identity index
-- (same DROP+CREATE UNIQUE INDEX pattern migration 0005 used to add
-- scope_concepts to this same index) so each supplied child reference
-- gets its own addressable row even when scope and content are identical
-- to a sibling's. NULL child_ref (common/compile blocks, and the ad-hoc
-- single-child context_specific command) keeps the prior content-addressed
-- reuse behavior unchanged.

ALTER TABLE context_block ADD COLUMN child_ref text NULL;

DROP INDEX context_block_idempotent;

CREATE UNIQUE INDEX context_block_idempotent ON context_block (
    plan_uuid,
    COALESCE(revision_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(cascade_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    node_path,
    child_level,
    kind,
    COALESCE(common_block_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    scope_concepts,
    content_hash,
    COALESCE(child_ref, '')
);
