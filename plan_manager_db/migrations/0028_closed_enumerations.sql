-- 0028_closed_enumerations.sql
--
-- CR-7 G-001/T-003/A-002. Closed-enumeration storage (C-004): exactly one
-- enumeration table and one value table with stable identifiers. Runtime CRUD
-- reads them through the common engine; creation, modification and deletion
-- of enumerations and values are admitted only to code-and-schema migration
-- paths (plan_manager.storage.enumeration_store.schema_update_enumerations is
-- the single Python entry point; this migration is the schema path).
--
-- Every vocabulary below is copied verbatim from the shipped command
-- metadata / domain Enum classes; nothing is invented here:
--   bug_kind, bug_severity, bug_status   <- plan_manager/domain/bug_report.py
--   todo_status                           <- plan_manager/domain/todo.py
--   wish_kind, wish_status                <- plan_manager/domain/wish.py
--   calendar_entry_status                 <- plan_manager/domain/calendar_entry.py
--   runtime_link_type                     <- plan_manager/domain/runtime_link.py
--
-- Refs are FIXED literals so seeding is deterministic: re-applying this
-- migration to any database yields the same identities and changes nothing.
--
-- Safety: DDL plus idempotent seed only. No existing table or row is
-- touched; every statement is idempotent on re-run.

CREATE TABLE IF NOT EXISTS enumeration (
    ref         uuid PRIMARY KEY,
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT enumeration_name_key UNIQUE (name)
);

COMMENT ON TABLE enumeration IS
    'CR-7 closed-enumeration registry: one row per closed vocabulary. '
    'Runtime CRUD is read-only; mutation is code-and-schema admission only.';

CREATE TABLE IF NOT EXISTS enumeration_value (
    ref              uuid PRIMARY KEY,
    enumeration_ref  uuid NOT NULL REFERENCES enumeration (ref),
    value            text NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT enumeration_value_key UNIQUE (enumeration_ref, value)
);

COMMENT ON TABLE enumeration_value IS
    'CR-7 closed-enumeration values with stable identifiers. Runtime CRUD is '
    'read-only; mutation is code-and-schema admission only.';


-- bug_kind: 14 values.
INSERT INTO enumeration (ref, name) VALUES ('0fb4f10c-be1a-4512-84f7-0cdb2b431ccb', 'bug_kind')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('0fb4f10c-be1a-4512-84f7-0cdb2b431ccb', 'enumeration', 'enumeration')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '050291cf-4713-4b11-9c86-602492b672b3', e.ref, 'functional' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('050291cf-4713-4b11-9c86-602492b672b3', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '8e0f8b2c-e223-4ba3-96c4-5895dca2996b', e.ref, 'wrong_output' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('8e0f8b2c-e223-4ba3-96c4-5895dca2996b', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'c3e87bf2-ac87-4176-8f2d-0e4feee1e991', e.ref, 'data_loss' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('c3e87bf2-ac87-4176-8f2d-0e4feee1e991', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'a1c7b697-5ada-42eb-81df-99d04bc0286a', e.ref, 'regression' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('a1c7b697-5ada-42eb-81df-99d04bc0286a', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '16284da9-aa6e-4931-86c3-87519a25195f', e.ref, 'compatibility' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('16284da9-aa6e-4931-86c3-87519a25195f', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '0751ffdc-1cae-456d-8829-ec7ce9b91ecc', e.ref, 'stale_context' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('0751ffdc-1cae-456d-8829-ec7ce9b91ecc', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '0a95ed0b-761b-41f9-9e34-5bb3cffc9acb', e.ref, 'planning' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('0a95ed0b-761b-41f9-9e34-5bb3cffc9acb', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '9eacbe0b-1d68-4147-8ebc-2c59f5181941', e.ref, 'performance' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('9eacbe0b-1d68-4147-8ebc-2c59f5181941', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '04f56db4-5b53-4c7d-b628-a2efd292dcf9', e.ref, 'security' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('04f56db4-5b53-4c7d-b628-a2efd292dcf9', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'd3316a59-f58d-4a44-9270-c3b596fe12ad', e.ref, 'infrastructure' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('d3316a59-f58d-4a44-9270-c3b596fe12ad', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'ef11896e-4120-4d47-b122-d30587ab2166', e.ref, 'deployment' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('ef11896e-4120-4d47-b122-d30587ab2166', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '1e7ed086-c8fa-4fe2-a425-b23ff089d20b', e.ref, 'configuration' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('1e7ed086-c8fa-4fe2-a425-b23ff089d20b', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'ce97b831-5360-4119-add4-6fde3622758b', e.ref, 'documentation' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('ce97b831-5360-4119-add4-6fde3622758b', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '9ab4bf50-d864-4022-8981-110434621a66', e.ref, 'user_experience' FROM enumeration e WHERE e.name = 'bug_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('9ab4bf50-d864-4022-8981-110434621a66', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;

-- bug_severity: 5 values.
INSERT INTO enumeration (ref, name) VALUES ('bc608719-925d-43b4-ad40-2db22a3b7d69', 'bug_severity')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('bc608719-925d-43b4-ad40-2db22a3b7d69', 'enumeration', 'enumeration')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'd0650fe1-a40f-4582-9ac4-64da67f455b6', e.ref, 'blocker' FROM enumeration e WHERE e.name = 'bug_severity'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('d0650fe1-a40f-4582-9ac4-64da67f455b6', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'd84d7f24-4ce9-4110-a696-b21bf6e60de1', e.ref, 'critical' FROM enumeration e WHERE e.name = 'bug_severity'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('d84d7f24-4ce9-4110-a696-b21bf6e60de1', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'fda84a06-a2bf-4011-a42a-27b67ab52c38', e.ref, 'major' FROM enumeration e WHERE e.name = 'bug_severity'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('fda84a06-a2bf-4011-a42a-27b67ab52c38', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '7ba39c83-2b33-4ebb-968a-aa1cbe977a2e', e.ref, 'minor' FROM enumeration e WHERE e.name = 'bug_severity'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('7ba39c83-2b33-4ebb-968a-aa1cbe977a2e', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'acb3f1cb-efba-4014-986f-801080e02abb', e.ref, 'trivial' FROM enumeration e WHERE e.name = 'bug_severity'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('acb3f1cb-efba-4014-986f-801080e02abb', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;

-- bug_status: 11 values.
INSERT INTO enumeration (ref, name) VALUES ('1575c4c0-c67d-4efb-8f17-f6b683de8a9a', 'bug_status')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('1575c4c0-c67d-4efb-8f17-f6b683de8a9a', 'enumeration', 'enumeration')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'be0d57d0-3b97-4af7-85bc-5418bd6c864a', e.ref, 'reported' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('be0d57d0-3b97-4af7-85bc-5418bd6c864a', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '6794c7ab-728b-481b-a033-872896e6161f', e.ref, 'triaged' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('6794c7ab-728b-481b-a033-872896e6161f', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'c6964880-56c3-4960-9f69-7cf858cf02cb', e.ref, 'confirmed' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('c6964880-56c3-4960-9f69-7cf858cf02cb', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '8b7d7356-c1fa-4cca-802f-bfde6cd38d0b', e.ref, 'rejected' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('8b7d7356-c1fa-4cca-802f-bfde6cd38d0b', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'cb6ccb8d-adae-41dc-abb4-627f7ccf5b2a', e.ref, 'duplicate' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('cb6ccb8d-adae-41dc-abb4-627f7ccf5b2a', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '835540f5-e304-410a-9419-61cfbc8808c1', e.ref, 'fixing' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('835540f5-e304-410a-9419-61cfbc8808c1', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '1f58cf8f-1e6e-43cf-9c98-90cc0e373a34', e.ref, 'fixed_source' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('1f58cf8f-1e6e-43cf-9c98-90cc0e373a34', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '0670abb5-c81f-4f27-8f1c-c935a9a8d628', e.ref, 'propagating' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('0670abb5-c81f-4f27-8f1c-c935a9a8d628', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '491b6f7d-0675-4ee5-8d0a-bd023f6bd111', e.ref, 'verified' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('491b6f7d-0675-4ee5-8d0a-bd023f6bd111', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '4422e09f-5a49-459e-85cd-1acafe5c4f20', e.ref, 'closed' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('4422e09f-5a49-459e-85cd-1acafe5c4f20', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '27cd81f6-bc57-474a-8a8a-0f62b91543c6', e.ref, 'reopened' FROM enumeration e WHERE e.name = 'bug_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('27cd81f6-bc57-474a-8a8a-0f62b91543c6', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;

-- calendar_entry_status: 4 values.
INSERT INTO enumeration (ref, name) VALUES ('d980d44a-4876-48b9-b19b-106797ac2c55', 'calendar_entry_status')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('d980d44a-4876-48b9-b19b-106797ac2c55', 'enumeration', 'enumeration')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '23b05205-cf4e-436f-807c-7b57ece3574b', e.ref, 'planned' FROM enumeration e WHERE e.name = 'calendar_entry_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('23b05205-cf4e-436f-807c-7b57ece3574b', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '8c2800a2-9bd3-4431-93c0-944976ca7e8e', e.ref, 'in_progress' FROM enumeration e WHERE e.name = 'calendar_entry_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('8c2800a2-9bd3-4431-93c0-944976ca7e8e', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'e317e713-4e1f-4fa5-8224-651687d2f2a4', e.ref, 'done' FROM enumeration e WHERE e.name = 'calendar_entry_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('e317e713-4e1f-4fa5-8224-651687d2f2a4', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '7ab12b96-7f74-4c3a-bf43-4220634cbc70', e.ref, 'cancelled' FROM enumeration e WHERE e.name = 'calendar_entry_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('7ab12b96-7f74-4c3a-bf43-4220634cbc70', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;

-- runtime_link_type: 8 values.
INSERT INTO enumeration (ref, name) VALUES ('ddddbcde-1283-4b16-b9fe-2e61b92d58da', 'runtime_link_type')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('ddddbcde-1283-4b16-b9fe-2e61b92d58da', 'enumeration', 'enumeration')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '111743da-9cb2-474e-be93-44858608817e', e.ref, 'relates_to' FROM enumeration e WHERE e.name = 'runtime_link_type'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('111743da-9cb2-474e-be93-44858608817e', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'ab78e8c8-8e12-4c4f-8ffb-e59f02f9961e', e.ref, 'blocks' FROM enumeration e WHERE e.name = 'runtime_link_type'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('ab78e8c8-8e12-4c4f-8ffb-e59f02f9961e', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '9a9940d9-d31e-4605-af25-1ae59ba3f791', e.ref, 'blocked_by' FROM enumeration e WHERE e.name = 'runtime_link_type'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('9a9940d9-d31e-4605-af25-1ae59ba3f791', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '6a8280e6-ac15-4ff4-99c9-23eea0f790e5', e.ref, 'duplicates' FROM enumeration e WHERE e.name = 'runtime_link_type'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('6a8280e6-ac15-4ff4-99c9-23eea0f790e5', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '9e4acbdf-f873-461c-a292-1a8bf1186d6c', e.ref, 'caused_by' FROM enumeration e WHERE e.name = 'runtime_link_type'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('9e4acbdf-f873-461c-a292-1a8bf1186d6c', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '50a87cbd-a254-489c-864b-aca33cbfbdf1', e.ref, 'created_from' FROM enumeration e WHERE e.name = 'runtime_link_type'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('50a87cbd-a254-489c-864b-aca33cbfbdf1', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '6ba6667c-72db-4cce-81fe-b0340baa32a5', e.ref, 'requires' FROM enumeration e WHERE e.name = 'runtime_link_type'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('6ba6667c-72db-4cce-81fe-b0340baa32a5', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'f33e5984-8bd3-4e37-8c03-490a4b60db0b', e.ref, 'followup_for' FROM enumeration e WHERE e.name = 'runtime_link_type'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('f33e5984-8bd3-4e37-8c03-490a4b60db0b', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;

-- todo_status: 6 values.
INSERT INTO enumeration (ref, name) VALUES ('d1f27d47-d36e-4244-909f-f9806eaaa475', 'todo_status')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('d1f27d47-d36e-4244-909f-f9806eaaa475', 'enumeration', 'enumeration')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'ca730dc0-2232-49ae-a472-005f4ae98f42', e.ref, 'open' FROM enumeration e WHERE e.name = 'todo_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('ca730dc0-2232-49ae-a472-005f4ae98f42', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '73c82815-9c8e-43a5-afd7-cd5a3d152c59', e.ref, 'in_progress' FROM enumeration e WHERE e.name = 'todo_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('73c82815-9c8e-43a5-afd7-cd5a3d152c59', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '070139f9-b06c-4153-b24b-784a51785cdc', e.ref, 'blocked' FROM enumeration e WHERE e.name = 'todo_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('070139f9-b06c-4153-b24b-784a51785cdc', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'c5a86906-8637-4615-9217-c1a0f0662d76', e.ref, 'resolved' FROM enumeration e WHERE e.name = 'todo_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('c5a86906-8637-4615-9217-c1a0f0662d76', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '1aaa3104-f657-44de-a8a6-af20630b1ede', e.ref, 'closed' FROM enumeration e WHERE e.name = 'todo_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('1aaa3104-f657-44de-a8a6-af20630b1ede', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'f99419c5-5b4e-4546-9b11-40174c9e4e03', e.ref, 'cancelled' FROM enumeration e WHERE e.name = 'todo_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('f99419c5-5b4e-4546-9b11-40174c9e4e03', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;

-- wish_kind: 7 values.
INSERT INTO enumeration (ref, name) VALUES ('9482be64-ffb8-4c26-96ec-e26bc6169d41', 'wish_kind')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('9482be64-ffb8-4c26-96ec-e26bc6169d41', 'enumeration', 'enumeration')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '78049e11-8b65-459f-ac5b-56e5fae3c23a', e.ref, 'feature' FROM enumeration e WHERE e.name = 'wish_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('78049e11-8b65-459f-ac5b-56e5fae3c23a', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '795c5924-10c4-4550-919a-0a6f2a3c0825', e.ref, 'ux' FROM enumeration e WHERE e.name = 'wish_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('795c5924-10c4-4550-919a-0a6f2a3c0825', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '5814aa0d-86a3-42ac-a916-d4f193d0f06e', e.ref, 'automation' FROM enumeration e WHERE e.name = 'wish_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('5814aa0d-86a3-42ac-a916-d4f193d0f06e', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'ef0a85ea-cbdf-45c0-9f2f-bc8d12bba010', e.ref, 'integration' FROM enumeration e WHERE e.name = 'wish_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('ef0a85ea-cbdf-45c0-9f2f-bc8d12bba010', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '4cdf6ad1-f435-49d8-9a58-9d99259153ca', e.ref, 'reporting' FROM enumeration e WHERE e.name = 'wish_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('4cdf6ad1-f435-49d8-9a58-9d99259153ca', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'b64c9ce9-aec0-4d4b-9e90-805946eb8bed', e.ref, 'tooling' FROM enumeration e WHERE e.name = 'wish_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('b64c9ce9-aec0-4d4b-9e90-805946eb8bed', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '1760f33c-060e-41d8-ac8e-873357291539', e.ref, 'other' FROM enumeration e WHERE e.name = 'wish_kind'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('1760f33c-060e-41d8-ac8e-873357291539', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;

-- wish_status: 7 values.
INSERT INTO enumeration (ref, name) VALUES ('72c216e2-869b-4832-89ed-bd0021c5ab49', 'wish_status')
    ON CONFLICT (name) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('72c216e2-869b-4832-89ed-bd0021c5ab49', 'enumeration', 'enumeration')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'cfbb9ac3-a69e-4b27-9119-dd4eb19a245b', e.ref, 'proposed' FROM enumeration e WHERE e.name = 'wish_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('cfbb9ac3-a69e-4b27-9119-dd4eb19a245b', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '4e1d7c99-c087-45bd-a28e-c050bff0e84c', e.ref, 'triaged' FROM enumeration e WHERE e.name = 'wish_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('4e1d7c99-c087-45bd-a28e-c050bff0e84c', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT 'e464a445-e460-4410-89f9-2892e3324906', e.ref, 'planned' FROM enumeration e WHERE e.name = 'wish_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('e464a445-e460-4410-89f9-2892e3324906', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '7add5d65-857a-4715-8993-7fc32bbca569', e.ref, 'in_progress' FROM enumeration e WHERE e.name = 'wish_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('7add5d65-857a-4715-8993-7fc32bbca569', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '1899ffaa-1935-469a-92ff-89ec529f7407', e.ref, 'delivered' FROM enumeration e WHERE e.name = 'wish_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('1899ffaa-1935-469a-92ff-89ec529f7407', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '7cafe86e-b00f-4cdb-9719-fc86b58bb618', e.ref, 'rejected' FROM enumeration e WHERE e.name = 'wish_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('7cafe86e-b00f-4cdb-9719-fc86b58bb618', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;
INSERT INTO enumeration_value (ref, enumeration_ref, value)
    SELECT '371953e0-938c-4cf4-b293-2d4f4c6db7e5', e.ref, 'cancelled' FROM enumeration e WHERE e.name = 'wish_status'
    ON CONFLICT (enumeration_ref, value) DO NOTHING;
INSERT INTO entity_identity (id, table_name, entity_type)
    VALUES ('371953e0-938c-4cf4-b293-2d4f4c6db7e5', 'enumeration_value', 'enumeration_value')
    ON CONFLICT (id) DO NOTHING;

-- Identity-registry wiring per the CR-6 migration discipline: enumeration and
-- enumeration_value ARE entity tables (immutable ref identities of their own),
-- so both get the 0015-pattern triggers, idempotently.
DROP TRIGGER IF EXISTS entity_identity_enumeration_insert ON enumeration;
CREATE TRIGGER entity_identity_enumeration_insert
AFTER INSERT ON enumeration
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('enumeration', 'enumeration');
DROP TRIGGER IF EXISTS entity_identity_enumeration_delete ON enumeration;
CREATE TRIGGER entity_identity_enumeration_delete
AFTER DELETE ON enumeration
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

DROP TRIGGER IF EXISTS entity_identity_enumeration_value_insert ON enumeration_value;
CREATE TRIGGER entity_identity_enumeration_value_insert
AFTER INSERT ON enumeration_value
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('enumeration_value', 'enumeration_value');
DROP TRIGGER IF EXISTS entity_identity_enumeration_value_delete ON enumeration_value;
CREATE TRIGGER entity_identity_enumeration_value_delete
AFTER DELETE ON enumeration_value
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

-- ROLLBACK NOTES
--
-- No automatic rollback exists. To reverse this migration by hand, run the
-- inverse statements below in this order, then delete this filename from the
-- schema_migration bookkeeping table so the loop can re-apply it.
--
--   DROP TRIGGER IF EXISTS entity_identity_enumeration_value_insert ON enumeration_value;
--   DROP TRIGGER IF EXISTS entity_identity_enumeration_value_delete ON enumeration_value;
--   DROP TRIGGER IF EXISTS entity_identity_enumeration_insert ON enumeration;
--   DROP TRIGGER IF EXISTS entity_identity_enumeration_delete ON enumeration;
--   DELETE FROM entity_identity WHERE table_name IN ('enumeration', 'enumeration_value');
--   DROP TABLE IF EXISTS enumeration_value;
--   DROP TABLE IF EXISTS enumeration;
--
-- The seeded vocabularies are copies of the shipped domain Enum classes;
-- dropping the tables reverts to code-only vocabularies with no data loss.
