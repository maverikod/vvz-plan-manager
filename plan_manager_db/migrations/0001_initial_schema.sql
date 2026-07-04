-- Migration 0001: initial schema for plan_manager.
-- Creates the pgvector extension and all ten core tables with their
-- per-plan uniqueness rules and the two named unique indexes. Applied
-- exactly once by the migration runner. Plain DDL only: no "IF NOT EXISTS"
-- on any CREATE TABLE statement.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE plan (
    uuid uuid PRIMARY KEY,
    name text NOT NULL UNIQUE,
    status text NOT NULL,
    context_budget integer NOT NULL,
    head_revision_uuid uuid NULL
);

CREATE TABLE revision (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    parent_uuid uuid NULL REFERENCES revision(uuid),
    author text NOT NULL,
    message text NOT NULL,
    created_at timestamptz NOT NULL,
    node_version_uuids uuid[] NOT NULL
);

ALTER TABLE plan
    ADD CONSTRAINT plan_head_fk FOREIGN KEY (head_revision_uuid) REFERENCES revision(uuid);

CREATE TABLE paragraph (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    label text,
    text text NOT NULL,
    position integer NOT NULL
);

CREATE TABLE concept (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    concept_id text NOT NULL,
    name text NOT NULL,
    definition text NOT NULL,
    properties text[] NOT NULL,
    source_labels text[] NOT NULL,
    UNIQUE (plan_uuid, concept_id)
);

CREATE TABLE relation (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    from_concept text NOT NULL,
    to_concept text NOT NULL,
    type text NOT NULL
);

CREATE TABLE step (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    parent_step_uuid uuid NULL,
    level integer NOT NULL,
    step_id text NOT NULL,
    slug text NOT NULL,
    fields jsonb NOT NULL,
    depends_on text[] NOT NULL,
    concepts text[] NOT NULL,
    status text NOT NULL
);

CREATE UNIQUE INDEX step_scope_id ON step (
    plan_uuid,
    COALESCE(parent_step_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    level,
    step_id
);

CREATE TABLE node_version (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    entity_uuid uuid NOT NULL,
    hash text NOT NULL,
    content jsonb NOT NULL,
    UNIQUE (plan_uuid, entity_uuid, hash)
);

CREATE TABLE ref (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    name text NOT NULL,
    revision_uuid uuid NOT NULL REFERENCES revision(uuid),
    UNIQUE (plan_uuid, name)
);

CREATE TABLE "cascade" (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    name text NOT NULL,
    base_revision_uuid uuid NULL REFERENCES revision(uuid),
    status text NOT NULL CHECK (status IN ('open', 'committed', 'aborted')),
    created_at timestamptz NOT NULL
);

CREATE UNIQUE INDEX cascade_one_open ON "cascade" (plan_uuid) WHERE status = 'open';

CREATE TABLE embedding_cache (
    uuid uuid PRIMARY KEY,
    content_hash text NOT NULL UNIQUE,
    vector vector NOT NULL,
    created_at timestamptz NOT NULL
);
