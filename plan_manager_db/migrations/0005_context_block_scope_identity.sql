-- Migration 0005: include common block and narrowed scope in context-block identity.
-- Specific blocks may have identical delta content while intentionally carrying
-- different scope_concepts. The derived-record identity must preserve that
-- narrowed scope instead of reusing a sibling record with the same empty delta.

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
    content_hash
);
