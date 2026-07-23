-- Migration 0018: Agent-configuration entity storage schema and role seed (CR-5a).
-- Strictly additive: creates six new tables (tool, toolset, toolset_membership, role,
-- provider, model), their indexes, and their global entity-identity registration
-- triggers (reusing the register_entity_identity_trigger / unregister_entity_identity_trigger
-- functions defined in migration 0015). Seeds twelve role rows, one per RuntimeRole
-- vocabulary value (the runtime-role vocabulary module). No ALTER or DROP of any
-- existing table, no IF NOT EXISTS, no foreign keys (reference columns are plain uuid;
-- validity is enforced in the store, matching the convention of migration 0011).

CREATE TABLE tool (
    uuid uuid PRIMARY KEY,
    name text NOT NULL,
    server_id text NOT NULL,
    command text NOT NULL,
    pinned_options jsonb NOT NULL,
    description text NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX tool_name_unique ON tool (name) WHERE deleted_at IS NULL;

CREATE TRIGGER entity_identity_tool_insert
AFTER INSERT ON tool
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('tool', 'tool');
CREATE TRIGGER entity_identity_tool_delete
AFTER DELETE ON tool
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TABLE toolset (
    uuid uuid PRIMARY KEY,
    name text NOT NULL,
    description text NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX toolset_name_unique ON toolset (name) WHERE deleted_at IS NULL;

CREATE TRIGGER entity_identity_toolset_insert
AFTER INSERT ON toolset
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('toolset', 'toolset');
CREATE TRIGGER entity_identity_toolset_delete
AFTER DELETE ON toolset
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TABLE toolset_membership (
    uuid uuid PRIMARY KEY,
    toolset_uuid uuid NOT NULL,
    tool_uuid uuid NOT NULL,
    position integer NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX toolset_membership_pair_unique ON toolset_membership (toolset_uuid, tool_uuid) WHERE deleted_at IS NULL;
CREATE INDEX toolset_membership_position ON toolset_membership (toolset_uuid, position) WHERE deleted_at IS NULL;

CREATE TRIGGER entity_identity_toolset_membership_insert
AFTER INSERT ON toolset_membership
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('toolset_membership', 'toolset_membership');
CREATE TRIGGER entity_identity_toolset_membership_delete
AFTER DELETE ON toolset_membership
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TABLE role (
    uuid uuid PRIMARY KEY,
    name text NOT NULL,
    description text NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX role_name_unique ON role (name) WHERE deleted_at IS NULL;

CREATE TRIGGER entity_identity_role_insert
AFTER INSERT ON role
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('role', 'role');
CREATE TRIGGER entity_identity_role_delete
AFTER DELETE ON role
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

INSERT INTO role (uuid, name, description, created_by, created_at, updated_at, deleted_at) VALUES
    ('00000000-0000-0000-0000-100000000001', 'hrs_author', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000002', 'mrs_author', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000003', 'gs_author', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000004', 'ts_author', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000005', 'as_author', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000006', 'code_executor', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000007', 'owner_reviewer', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000008', 'conscience_reviewer', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000009', 'escalation_owner', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000010', 'bug_investigator', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000011', 'bug_fixer', NULL, 'system', now(), now(), NULL),
    ('00000000-0000-0000-0000-100000000012', 'verification_executor', NULL, 'system', now(), now(), NULL);

CREATE TABLE provider (
    uuid uuid PRIMARY KEY,
    name text NOT NULL,
    type text NOT NULL,
    rented_hardware boolean NOT NULL DEFAULT false,
    status text NOT NULL,
    billing_notes text NULL,
    quota_notes text NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX provider_name_unique ON provider (name) WHERE deleted_at IS NULL;

CREATE TRIGGER entity_identity_provider_insert
AFTER INSERT ON provider
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('provider', 'provider');
CREATE TRIGGER entity_identity_provider_delete
AFTER DELETE ON provider
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();

CREATE TABLE model (
    uuid uuid PRIMARY KEY,
    name text NOT NULL,
    provider_uuid uuid NOT NULL,
    level text NOT NULL,
    context_window integer NULL,
    cost_class text NULL,
    availability text NULL,
    execution_mode text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX model_name_provider_unique ON model (name, provider_uuid) WHERE deleted_at IS NULL;
CREATE INDEX model_provider_uuid ON model (provider_uuid) WHERE deleted_at IS NULL;
CREATE INDEX model_level ON model (level) WHERE deleted_at IS NULL;

CREATE TRIGGER entity_identity_model_insert
AFTER INSERT ON model
FOR EACH ROW EXECUTE FUNCTION register_entity_identity_trigger('model', 'model');
CREATE TRIGGER entity_identity_model_delete
AFTER DELETE ON model
FOR EACH ROW EXECUTE FUNCTION unregister_entity_identity_trigger();
