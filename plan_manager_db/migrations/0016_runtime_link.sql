-- Migration 0016: generic runtime link surface.
-- Adds the runtime_link table: a cycle-safe, audited, typed link between two
-- runtime records whose endpoints are each independently a bug_report or a
-- todo_item row (the four ordered/unordered pairs bug x bug, bug x todo,
-- todo x bug, todo x todo). This migration is strictly additive: it only
-- creates the runtime_link table, its indexes, and its entity_identity
-- registration triggers; it performs no ALTER and no DROP on any existing
-- table.
--
-- Unlike todo_link (whose two endpoints are always todo_item and therefore
-- carry real foreign keys), runtime_link's two endpoints can each reference
-- either bug_report or todo_item, so each endpoint is a plain reference pair
-- (an entity_type discriminator plus an entity_uuid column) with no foreign
-- key constraint; endpoint-type validity, endpoint-existence, self-reference,
-- duplicate, and cycle guards are all enforced at the application/domain
-- layer, not by the database, matching the bug_impact precedent for
-- polymorphic references.

CREATE TABLE runtime_link (
    uuid uuid PRIMARY KEY,
    from_entity_type text NOT NULL,
    from_entity_uuid uuid NOT NULL,
    to_entity_type text NOT NULL,
    to_entity_uuid uuid NOT NULL,
    link_type text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX runtime_link_active_unique ON runtime_link (from_entity_type, from_entity_uuid, to_entity_type, to_entity_uuid, link_type) WHERE deleted_at IS NULL;
CREATE INDEX runtime_link_to ON runtime_link (to_entity_type, to_entity_uuid);
CREATE INDEX runtime_link_from ON runtime_link (from_entity_type, from_entity_uuid);

-- Register runtime_link rows in the global entity_identity registry, reusing
-- the trigger functions created by migration 0015_entity_identity_registry.sql.
CREATE TRIGGER entity_identity_runtime_link_insert
AFTER INSERT ON runtime_link
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('runtime_link', 'runtime_link');
CREATE TRIGGER entity_identity_runtime_link_delete
AFTER DELETE ON runtime_link
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();
