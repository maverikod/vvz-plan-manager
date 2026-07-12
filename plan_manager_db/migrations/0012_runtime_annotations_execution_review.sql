-- Migration 0012: Runtime annotations, execution attempts, review results, and escalations.
-- This migration is strictly additive: it creates four new tables and their indexes.
-- No existing objects are altered or dropped by this migration.
-- These tables form a runtime overlay layer that records annotations, execution attempts,
-- review results, and escalations without modifying any existing plan truth.
-- All anchor and cross-entity reference identifier columns use plain UUID/text references
-- with no foreign key constraints, allowing robust handling of soft-deleted entities.
-- Validity of references is enforced at the application and store layer.
-- Each table includes a deleted_at column for soft-delete semantics.

CREATE TABLE runtime_comment (
    uuid uuid PRIMARY KEY,
    primary_anchor_type text NOT NULL,
    anchor_project_id uuid NULL,
    anchor_file_path text NULL,
    anchor_plan_uuid uuid NULL,
    anchor_revision_uuid uuid NULL,
    anchor_step_uuid uuid NULL,
    anchor_step_path text NULL,
    anchor_ref_id uuid NULL,
    kind text NOT NULL,
    visibility text NOT NULL,
    author text NOT NULL,
    body text NOT NULL,
    resolved boolean NULL,
    supersedes_comment_uuid uuid NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX runtime_comment_anchor_step ON runtime_comment (anchor_plan_uuid, anchor_step_uuid);
CREATE INDEX runtime_comment_anchor_ref ON runtime_comment (anchor_ref_id);
CREATE INDEX runtime_comment_visibility ON runtime_comment (visibility) WHERE deleted_at IS NULL;

CREATE TABLE execution_attempt (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL,
    revision_uuid uuid NULL,
    step_uuid uuid NOT NULL,
    step_path text NULL,
    todo_uuid uuid NULL,
    bug_fix_uuid uuid NULL,
    assigned_binding_uuid uuid NULL,
    assigned_provider text NULL,
    assigned_model text NULL,
    used_provider text NULL,
    used_model text NULL,
    runtime text NULL,
    vast_instance_id text NULL,
    started_at timestamptz NULL,
    finished_at timestamptz NULL,
    status text NOT NULL,
    input_context_hash text NULL,
    result_summary text NULL,
    changed_files jsonb NULL,
    command_test_results jsonb NULL,
    resource_accounting jsonb NULL,
    error text NULL,
    escalation_reason text NULL,
    parent_attempt_uuid uuid NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX execution_attempt_step ON execution_attempt (plan_uuid, step_uuid);
CREATE INDEX execution_attempt_status ON execution_attempt (status) WHERE deleted_at IS NULL;
CREATE INDEX execution_attempt_parent ON execution_attempt (parent_attempt_uuid);

CREATE TABLE review_result (
    uuid uuid PRIMARY KEY,
    object_type text NOT NULL,
    reviewed_attempt_uuid uuid NULL,
    reviewed_revision_uuid uuid NULL,
    reviewer text NOT NULL,
    status text NOT NULL,
    findings text NULL,
    evidence jsonb NULL,
    verification_commands jsonb NULL,
    escalation_target_uuid uuid NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX review_result_attempt ON review_result (reviewed_attempt_uuid);
CREATE INDEX review_result_status ON review_result (status) WHERE deleted_at IS NULL;

CREATE TABLE escalation (
    uuid uuid PRIMARY KEY,
    primary_anchor_type text NOT NULL,
    anchor_project_id uuid NULL,
    anchor_file_path text NULL,
    anchor_plan_uuid uuid NULL,
    anchor_revision_uuid uuid NULL,
    anchor_step_uuid uuid NULL,
    anchor_step_path text NULL,
    anchor_ref_id uuid NULL,
    reason text NOT NULL,
    from_level text NULL,
    to_level text NULL,
    status text NOT NULL,
    resolution text NULL,
    resolved_by text NULL,
    resolved_at timestamptz NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX escalation_anchor_step ON escalation (anchor_plan_uuid, anchor_step_uuid);
CREATE INDEX escalation_anchor_ref ON escalation (anchor_ref_id);
CREATE INDEX escalation_status ON escalation (status) WHERE deleted_at IS NULL;
