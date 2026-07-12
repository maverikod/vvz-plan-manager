-- Migration 0011: Model bindings and runtime configuration policy.
-- Strictly additive: creates ONLY the model_binding table and its three indexes.
-- No ALTER, no DROP, no IF NOT EXISTS.
-- model_binding is runtime CONFIGURATION (C-009 ModelBinding), never a normative change to step content.
-- The scope column realizes the six-level binding inheritance order (C-010 ModelBindingInheritance).
-- The role column holds a RuntimeRole value (C-011 RuntimeRole) or is NULL to mean 'applies to all roles'.
-- The anchor identifier columns (plan_uuid, revision_uuid, branch_step_uuid, step_uuid) are plain reference columns with NO foreign keys,
-- making the table robust to soft-deleted plans and steps; validity is enforced in the store, not by the database.
-- The deleted_at column implements soft delete (never physical DELETE).

CREATE TABLE model_binding (
    uuid uuid PRIMARY KEY,
    scope text NOT NULL,                 -- one of: system, plan, level, branch, step, role
    role text NULL,                      -- a RuntimeRole value, or NULL = applies to all roles
    plan_uuid uuid NULL,                 -- NULL for system; set for plan/level/branch/step; optional for role
    spec_level text NULL,                -- HRS|MRS|GS|TS|AS, set only when scope='level'
    branch_step_uuid uuid NULL,          -- the branch (GS) step uuid, set only when scope='branch'
    revision_uuid uuid NULL,             -- optional, for scope='step' (anchor convention, C-006)
    step_uuid uuid NULL,                 -- set only when scope='step'
    step_path text NULL,                 -- diagnostic display snapshot for scope='step'
    provider text NOT NULL,
    model text NOT NULL,
    fallback_provider text NULL,
    fallback_model text NULL,
    max_retries integer NOT NULL,
    timeout integer NOT NULL,            -- seconds
    context_budget integer NULL,
    active boolean NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);

CREATE UNIQUE INDEX model_binding_scope_unique ON model_binding (
    scope,
    COALESCE(role, ''),
    COALESCE(plan_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(spec_level, ''),
    COALESCE(branch_step_uuid, '00000000-0000-0000-0000-000000000000'::uuid),
    COALESCE(step_uuid, '00000000-0000-0000-0000-000000000000'::uuid)
) WHERE deleted_at IS NULL;

CREATE INDEX model_binding_plan_scope ON model_binding (plan_uuid, scope) WHERE deleted_at IS NULL;
CREATE INDEX model_binding_role ON model_binding (role) WHERE deleted_at IS NULL;
