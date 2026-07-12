-- Migration 0010: todo work items.
-- Extends the runtime work layer with independent todo work entities and their
-- linking structure. This migration is strictly additive: it only creates the
-- todo_item and todo_link tables and their indexes; it performs no ALTER and
-- no DROP on any existing table.
--
-- todo_item is an independent runtime work entity, not a child of the plan
-- table, so it carries no plan foreign key and no ON DELETE CASCADE tied to
-- plan. Its anchor_* identifier columns are plain reference columns with no
-- foreign key constraints; anchor validity is enforced at the application/
-- domain layer, not by the database.
--
-- todo_link rows ARE children of the todo pair they relate: its two endpoint
-- columns (from_todo_uuid, to_todo_uuid) each carry a foreign key to
-- todo_item(uuid) with ON DELETE CASCADE.

CREATE TABLE todo_item (
    uuid uuid PRIMARY KEY,
    title text NOT NULL,
    description text NOT NULL,
    kind text NOT NULL,
    status text NOT NULL,
    priority_nice integer NOT NULL,
    created_by text NOT NULL,
    assigned_to text NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    started_at timestamptz NULL,
    resolved_at timestamptz NULL,
    due_at timestamptz NULL,
    primary_anchor_type text NOT NULL,
    anchor_project_id uuid NULL,
    anchor_file_path text NULL,
    anchor_plan_uuid uuid NULL,
    anchor_revision_uuid uuid NULL,
    anchor_step_uuid uuid NULL,
    anchor_step_path text NULL,
    anchor_ref_id uuid NULL,
    blocking_reason text NULL,
    execution_result text NULL,
    deleted_at timestamptz NULL
);

CREATE INDEX todo_item_status_priority ON todo_item (status, priority_nice);
CREATE INDEX todo_item_anchor_step ON todo_item (anchor_plan_uuid, anchor_step_uuid);
CREATE INDEX todo_item_anchor_project ON todo_item (anchor_project_id);

CREATE TABLE todo_link (
    uuid uuid PRIMARY KEY,
    from_todo_uuid uuid NOT NULL REFERENCES todo_item(uuid) ON DELETE CASCADE,
    to_todo_uuid uuid NOT NULL REFERENCES todo_item(uuid) ON DELETE CASCADE,
    link_type text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX todo_link_active_unique ON todo_link (from_todo_uuid, to_todo_uuid, link_type) WHERE deleted_at IS NULL;
CREATE INDEX todo_link_to ON todo_link (to_todo_uuid);
