-- Migration 0007: semantic tree snapshot history.
-- A semantic tree snapshot is a derived per-revision record that retains a
-- computed Semantic Reproduction Tree. It changes no plan truth (HRS, MRS,
-- steps, cascade state, or head revision) and is bound to the plan identity,
-- the revision identity, the algorithm version, the summarizer version, the
-- embedding model, a tree hash, and its creation time.

CREATE TABLE srt_snapshot (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    revision_uuid uuid NULL REFERENCES revision(uuid),
    algorithm_version text NOT NULL,
    summarizer_version text NOT NULL,
    embedding_model text NOT NULL,
    tree_hash text NOT NULL,
    tree_content jsonb NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE UNIQUE INDEX srt_snapshot_idempotent ON srt_snapshot (
    plan_uuid,
    revision_uuid,
    algorithm_version,
    summarizer_version,
    embedding_model,
    tree_hash
);

CREATE INDEX srt_snapshot_plan_history ON srt_snapshot (
    plan_uuid,
    created_at
);