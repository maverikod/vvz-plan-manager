-- Migration 0019: Resolution and assignment persistence schema.
-- Strictly additive: creates ONLY three tables (role_model_binding, step_assignment,
-- invocation_profile) and their indexes. No ALTER, no DROP, no IF NOT EXISTS.
--
-- role_model_binding realizes C-006 (Role-Model Resolution) storage: the manual
-- role-to-required-model-level relation, optionally scoped per phase. In CR-5a
-- assignment is MANUAL only; automatic ratings are deferred to a future CR.
-- step_assignment realizes C-007 (Per-Step Assignment) storage: the per-step
-- role-and-toolset assignment resolved through the six-scope specificity ladder
-- (system, plan, level, branch, step, role) reused from the model_binding pattern
-- (see 0011_model_bindings.sql).
-- invocation_profile realizes C-008 (Invocation Profile) storage: the informational
-- record of call characteristics beyond the model, attached along the same scope
-- ladder and resolved with the same specificity rules; nothing in this migration
-- enforces these values — they are purely informational.
--
-- All reference columns (role, assigned_role, toolset_uuid, and the anchor uuids
-- plan_uuid/branch_step_uuid/revision_uuid/step_uuid) are plain reference columns
-- with NO database foreign keys, matching 0011_model_bindings.sql: validity is
-- enforced in the storage layer, keeping these tables robust to soft-deleted
-- referents. The deleted_at column implements soft delete (never physical DELETE).

CREATE TABLE role_model_binding (
    uuid uuid PRIMARY KEY,
    role text NOT NULL,
    phase text NULL,
    required_level text NOT NULL,
    active boolean NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX role_model_binding_role_phase_unique ON role_model_binding (
    role,
    COALESCE(phase, '')
) WHERE deleted_at IS NULL;

CREATE INDEX role_model_binding_role ON role_model_binding (role) WHERE deleted_at IS NULL;

CREATE TABLE step_assignment (
    uuid uuid PRIMARY KEY,
    scope text NOT NULL,
    role text NULL,
    plan_uuid uuid NULL,
    spec_level text NULL,
    branch_step_uuid uuid NULL,
    revision_uuid uuid NULL,
    step_uuid uuid NULL,
    step_path text NULL,
    assigned_role text NULL,
    toolset_uuid uuid NULL,
    active boolean NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX step_assignment_scope_unique ON step_assignment (
    scope,
    COALESCE(role, ''),
    COALESCE(plan_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(spec_level, ''),
    COALESCE(branch_step_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(step_uuid, '00000000-0000-0000-0000-000000000000'::uuid)
) WHERE deleted_at IS NULL;

CREATE INDEX step_assignment_plan_scope ON step_assignment (plan_uuid, scope) WHERE deleted_at IS NULL;
CREATE INDEX step_assignment_role ON step_assignment (role) WHERE deleted_at IS NULL;

CREATE TABLE invocation_profile (
    uuid uuid PRIMARY KEY,
    scope text NOT NULL,
    role text NULL,
    plan_uuid uuid NULL,
    spec_level text NULL,
    branch_step_uuid uuid NULL,
    revision_uuid uuid NULL,
    step_uuid uuid NULL,
    step_path text NULL,
    temperature double precision NULL,
    top_p double precision NULL,
    max_output_tokens integer NULL,
    reasoning_effort text NULL,
    context_window_budget integer NULL,
    timeout integer NULL,
    retry_policy jsonb NULL,
    concurrency integer NULL,
    rate_hint jsonb NULL,
    response_format text NULL,
    response_schema jsonb NULL,
    max_tool_iterations integer NULL,
    per_call_timeout integer NULL,
    execution_mode text NULL,
    token_budget integer NULL,
    cost_budget double precision NULL,
    dialogue_chain_ref uuid NULL,
    active boolean NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX invocation_profile_scope_unique ON invocation_profile (
    scope,
    COALESCE(role, ''),
    COALESCE(plan_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(spec_level, ''),
    COALESCE(branch_step_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(step_uuid, '00000000-0000-0000-0000-000000000000'::uuid)
) WHERE deleted_at IS NULL;

CREATE INDEX invocation_profile_plan_scope ON invocation_profile (plan_uuid, scope) WHERE deleted_at IS NULL;
