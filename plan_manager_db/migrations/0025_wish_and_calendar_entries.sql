-- Migration 0025: runtime wish queue and calendar-entry work graph.
-- Adds two new runtime entities:
--   * wish_item: feature-desire records, distinct from todos and bugs
--   * calendar_entry: calendar-day work windows, optionally linked to a wish
-- Strictly additive: creates only the two tables, indexes, and entity_identity
-- triggers; performs no ALTER or DROP of existing objects.

CREATE TABLE wish_item (
    uuid uuid PRIMARY KEY,
    title text NOT NULL,
    description text NOT NULL,
    kind text NOT NULL,
    status text NOT NULL,
    priority_nice integer NOT NULL,
    created_by text NOT NULL,
    assigned_to text NULL,
    target_release text NULL,
    rationale text NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    decided_at timestamptz NULL,
    delivered_at timestamptz NULL,
    primary_anchor_type text NOT NULL,
    anchor_project_id uuid NULL,
    anchor_file_path text NULL,
    anchor_plan_uuid uuid NULL,
    anchor_revision_uuid uuid NULL,
    anchor_step_uuid uuid NULL,
    anchor_step_path text NULL,
    anchor_ref_id uuid NULL,
    deleted_at timestamptz NULL
);

CREATE INDEX wish_item_status_priority ON wish_item (status, priority_nice) WHERE deleted_at IS NULL;
CREATE INDEX wish_item_anchor_step ON wish_item (anchor_plan_uuid, anchor_step_uuid);
CREATE INDEX wish_item_anchor_project ON wish_item (anchor_project_id);

CREATE TRIGGER entity_identity_wish_item_insert
AFTER INSERT ON wish_item
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('wish_item', 'wish');
CREATE TRIGGER entity_identity_wish_item_delete
AFTER DELETE ON wish_item
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TABLE calendar_entry (
    uuid uuid PRIMARY KEY,
    title text NOT NULL,
    description text NOT NULL,
    status text NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    created_by text NOT NULL,
    assigned_to text NULL,
    wish_uuid uuid NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    primary_anchor_type text NOT NULL,
    anchor_project_id uuid NULL,
    anchor_file_path text NULL,
    anchor_plan_uuid uuid NULL,
    anchor_revision_uuid uuid NULL,
    anchor_step_uuid uuid NULL,
    anchor_step_path text NULL,
    anchor_ref_id uuid NULL,
    deleted_at timestamptz NULL
);

CREATE INDEX calendar_entry_range ON calendar_entry (start_date, end_date) WHERE deleted_at IS NULL;
CREATE INDEX calendar_entry_status ON calendar_entry (status) WHERE deleted_at IS NULL;
CREATE INDEX calendar_entry_anchor_step ON calendar_entry (anchor_plan_uuid, anchor_step_uuid);
CREATE INDEX calendar_entry_anchor_project ON calendar_entry (anchor_project_id);
CREATE INDEX calendar_entry_wish ON calendar_entry (wish_uuid) WHERE deleted_at IS NULL;

CREATE TRIGGER entity_identity_calendar_entry_insert
AFTER INSERT ON calendar_entry
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('calendar_entry', 'calendar_entry');
CREATE TRIGGER entity_identity_calendar_entry_delete
AFTER DELETE ON calendar_entry
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();
