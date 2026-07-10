-- Migration 0008: NULL-safe SRT snapshot idempotency.
-- The 0007 idempotency index listed revision_uuid as a plain column. Because a
-- unique index treats two NULLs as distinct, a plan with no head revision
-- (revision_uuid NULL) never deduplicated: every srt_snapshot_create inserted a
-- fresh row even for an identical tree. Replace the index with a COALESCE-based
-- one — the same nullable-key precedent as context_block (migration 0004) — so
-- two NULL revisions collapse to one idempotency key.

DROP INDEX srt_snapshot_idempotent;

CREATE UNIQUE INDEX srt_snapshot_idempotent ON srt_snapshot (
    plan_uuid,
    COALESCE(revision_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    algorithm_version,
    summarizer_version,
    embedding_model,
    tree_hash
);
