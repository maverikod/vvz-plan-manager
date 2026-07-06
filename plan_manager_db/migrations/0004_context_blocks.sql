-- Migration 0004: derived authoring context blocks.
-- Context blocks are typed, content-addressed derived records. They cache
-- read-only projections of plan truth for model authoring context and never
-- participate in the normative plan revision graph.

CREATE TABLE context_block (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    revision_uuid uuid NULL REFERENCES revision(uuid),
    cascade_uuid uuid NULL REFERENCES "cascade"(uuid),
    node_path text NOT NULL,
    child_level integer NOT NULL CHECK (child_level IN (3, 4, 5)),
    kind text NOT NULL CHECK (kind IN ('common', 'specific', 'compile')),
    common_block_uuid uuid NULL REFERENCES context_block(uuid),
    scope_concepts text[] NOT NULL,
    content jsonb NOT NULL,
    content_hash text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE UNIQUE INDEX context_block_idempotent ON context_block (
    plan_uuid,
    COALESCE(revision_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(cascade_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    node_path,
    child_level,
    kind,
    content_hash
);

CREATE INDEX context_block_plan_node ON context_block (
    plan_uuid,
    node_path,
    kind,
    child_level
);
