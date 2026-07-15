-- Migration 0015: global entity identity registry.
-- Adds one UUID identity registry for Plan Manager entities. Existing entity
-- tables remain authoritative for their data; this table records the global
-- UUID-to-table mapping used by generic CRUD dispatch and future cross-entity
-- foreign keys.

CREATE TABLE entity_identity (
    id uuid PRIMARY KEY,
    table_name text NOT NULL,
    entity_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX entity_identity_table ON entity_identity (table_name);
CREATE INDEX entity_identity_type ON entity_identity (entity_type);

CREATE FUNCTION register_entity_identity_trigger() RETURNS trigger AS $$
BEGIN
    INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES (NEW.uuid, TG_ARGV[0], TG_ARGV[1])
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION unregister_entity_identity_trigger() RETURNS trigger AS $$
BEGIN
    DELETE FROM entity_identity WHERE id = OLD.uuid;
    RETURN OLD;
END;
$$ LANGUAGE plpgsql;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'plan', 'plan' FROM plan
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'paragraph', 'paragraph' FROM paragraph
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'concept', 'concept' FROM concept
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'relation', 'relation' FROM relation
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'step', 'step' FROM step
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'node_version', 'node_version' FROM node_version
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'revision', 'revision' FROM revision
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'ref', 'ref' FROM ref
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'cascade', 'cascade' FROM "cascade"
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'context_block', 'context_block' FROM context_block
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'srt_snapshot', 'srt_snapshot' FROM srt_snapshot
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'cascade_request', 'cascade_request' FROM cascade_request
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'runtime_audit_log', 'runtime_audit' FROM runtime_audit_log
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'todo_item', 'todo' FROM todo_item
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'todo_link', 'todo_link' FROM todo_link
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'model_binding', 'model_binding' FROM model_binding
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'runtime_comment', 'comment' FROM runtime_comment
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'execution_attempt', 'execution_attempt' FROM execution_attempt
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'review_result', 'review_result' FROM review_result
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'escalation', 'escalation' FROM escalation
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'bug_report', 'bug' FROM bug_report
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'bug_impact', 'bug_impact' FROM bug_impact
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'project_dependency', 'project_dependency' FROM project_dependency
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'bug_fix', 'bug_fix' FROM bug_fix
ON CONFLICT (id) DO NOTHING;

INSERT INTO entity_identity (id, table_name, entity_type)
SELECT uuid, 'bug_fix_propagation', 'bug_fix_propagation' FROM bug_fix_propagation
ON CONFLICT (id) DO NOTHING;

CREATE TRIGGER entity_identity_plan_insert
AFTER INSERT ON plan
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('plan', 'plan');
CREATE TRIGGER entity_identity_plan_delete
AFTER DELETE ON plan
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_paragraph_insert
AFTER INSERT ON paragraph
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('paragraph', 'paragraph');
CREATE TRIGGER entity_identity_paragraph_delete
AFTER DELETE ON paragraph
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_concept_insert
AFTER INSERT ON concept
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('concept', 'concept');
CREATE TRIGGER entity_identity_concept_delete
AFTER DELETE ON concept
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_relation_insert
AFTER INSERT ON relation
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('relation', 'relation');
CREATE TRIGGER entity_identity_relation_delete
AFTER DELETE ON relation
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_step_insert
AFTER INSERT ON step
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('step', 'step');
CREATE TRIGGER entity_identity_step_delete
AFTER DELETE ON step
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_node_version_insert
AFTER INSERT ON node_version
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('node_version', 'node_version');
CREATE TRIGGER entity_identity_node_version_delete
AFTER DELETE ON node_version
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_revision_insert
AFTER INSERT ON revision
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('revision', 'revision');
CREATE TRIGGER entity_identity_revision_delete
AFTER DELETE ON revision
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_ref_insert
AFTER INSERT ON ref
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('ref', 'ref');
CREATE TRIGGER entity_identity_ref_delete
AFTER DELETE ON ref
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_cascade_insert
AFTER INSERT ON "cascade"
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('cascade', 'cascade');
CREATE TRIGGER entity_identity_cascade_delete
AFTER DELETE ON "cascade"
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_context_block_insert
AFTER INSERT ON context_block
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('context_block', 'context_block');
CREATE TRIGGER entity_identity_context_block_delete
AFTER DELETE ON context_block
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_srt_snapshot_insert
AFTER INSERT ON srt_snapshot
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('srt_snapshot', 'srt_snapshot');
CREATE TRIGGER entity_identity_srt_snapshot_delete
AFTER DELETE ON srt_snapshot
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_cascade_request_insert
AFTER INSERT ON cascade_request
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('cascade_request', 'cascade_request');
CREATE TRIGGER entity_identity_cascade_request_delete
AFTER DELETE ON cascade_request
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_runtime_audit_insert
AFTER INSERT ON runtime_audit_log
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('runtime_audit_log', 'runtime_audit');
CREATE TRIGGER entity_identity_runtime_audit_delete
AFTER DELETE ON runtime_audit_log
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_todo_item_insert
AFTER INSERT ON todo_item
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('todo_item', 'todo');
CREATE TRIGGER entity_identity_todo_item_delete
AFTER DELETE ON todo_item
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_todo_link_insert
AFTER INSERT ON todo_link
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('todo_link', 'todo_link');
CREATE TRIGGER entity_identity_todo_link_delete
AFTER DELETE ON todo_link
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_model_binding_insert
AFTER INSERT ON model_binding
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('model_binding', 'model_binding');
CREATE TRIGGER entity_identity_model_binding_delete
AFTER DELETE ON model_binding
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_runtime_comment_insert
AFTER INSERT ON runtime_comment
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('runtime_comment', 'comment');
CREATE TRIGGER entity_identity_runtime_comment_delete
AFTER DELETE ON runtime_comment
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_execution_attempt_insert
AFTER INSERT ON execution_attempt
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('execution_attempt', 'execution_attempt');
CREATE TRIGGER entity_identity_execution_attempt_delete
AFTER DELETE ON execution_attempt
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_review_result_insert
AFTER INSERT ON review_result
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('review_result', 'review_result');
CREATE TRIGGER entity_identity_review_result_delete
AFTER DELETE ON review_result
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_escalation_insert
AFTER INSERT ON escalation
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('escalation', 'escalation');
CREATE TRIGGER entity_identity_escalation_delete
AFTER DELETE ON escalation
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_bug_report_insert
AFTER INSERT ON bug_report
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('bug_report', 'bug');
CREATE TRIGGER entity_identity_bug_report_delete
AFTER DELETE ON bug_report
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_bug_impact_insert
AFTER INSERT ON bug_impact
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('bug_impact', 'bug_impact');
CREATE TRIGGER entity_identity_bug_impact_delete
AFTER DELETE ON bug_impact
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_project_dependency_insert
AFTER INSERT ON project_dependency
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('project_dependency', 'project_dependency');
CREATE TRIGGER entity_identity_project_dependency_delete
AFTER DELETE ON project_dependency
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_bug_fix_insert
AFTER INSERT ON bug_fix
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('bug_fix', 'bug_fix');
CREATE TRIGGER entity_identity_bug_fix_delete
AFTER DELETE ON bug_fix
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TRIGGER entity_identity_bug_fix_propagation_insert
AFTER INSERT ON bug_fix_propagation
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('bug_fix_propagation', 'bug_fix_propagation');
CREATE TRIGGER entity_identity_bug_fix_propagation_delete
AFTER DELETE ON bug_fix_propagation
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();
