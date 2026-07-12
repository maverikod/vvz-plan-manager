-- Migration 0013: Bug lifecycle, impact, project dependency graph, fixes and propagation.
-- This migration is strictly additive: it creates only the five tables and indexes below
-- and performs no ALTER or DROP of any existing object.
-- It uses no IF NOT EXISTS.
-- These are runtime overlay tables that change NO existing plan truth; they sit alongside,
-- not on top of, plan data.
-- All anchor/reference identifier columns (e.g., columns ending in _uuid, _id, or naming
-- a plan/step/revision/project) are PLAIN references with NO foreign keys. This is deliberate,
-- so the overlay stays robust even when a referenced plan/step is soft-deleted; validity of
-- these references is validated in the application store layer, not by the database.
-- Project ids stored in this schema (e.g., source_project_id, dependent_project_id,
-- depends_on_project_id, target_project_id) are external analysis-server UUIDs (identifiers
-- of projects known to a separate code-analysis system, not rows of any local project table)
-- stored here purely as opaque reference values.
-- deleted_at on every table means soft delete: rows are never physically deleted, only marked
-- via a non-null deleted_at timestamp.

CREATE TABLE bug_report (
    uuid uuid PRIMARY KEY,
    title text NOT NULL,
    short_description text NOT NULL,
    detailed_description text NOT NULL,
    expected_behavior text NULL,
    actual_behavior text NULL,
    reproduction text NULL,
    evidence jsonb NULL,
    environment text NULL,
    kind text NOT NULL,
    severity text NOT NULL,
    priority_nice integer NOT NULL,
    status text NOT NULL,
    reporter text NOT NULL,
    owner text NULL,
    duplicate_of_uuid uuid NULL,
    parent_bug_uuid uuid NULL,
    source_anchor_type text NOT NULL,
    source_project_id uuid NULL,
    source_file_path text NULL,
    source_plan_uuid uuid NULL,
    source_revision_uuid uuid NULL,
    source_step_uuid uuid NULL,
    source_step_path text NULL,
    source_ref_id uuid NULL,
    source_command text NULL,
    source_service text NULL,
    confirmed_at timestamptz NULL,
    closed_at timestamptz NULL,
    reopened_at timestamptz NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX bug_report_status_severity ON bug_report (status, severity) WHERE deleted_at IS NULL;
CREATE INDEX bug_report_source_project ON bug_report (source_project_id);
CREATE INDEX bug_report_priority ON bug_report (priority_nice);
CREATE INDEX bug_report_duplicate_of ON bug_report (duplicate_of_uuid);
CREATE INDEX bug_report_parent ON bug_report (parent_bug_uuid);

CREATE TABLE bug_impact (
    uuid uuid PRIMARY KEY,
    bug_uuid uuid NOT NULL,
    target_type text NOT NULL,
    target_project_id uuid NULL,
    target_file_path text NULL,
    target_plan_uuid uuid NULL,
    target_revision_uuid uuid NULL,
    target_step_uuid uuid NULL,
    target_step_path text NULL,
    target_ref_id uuid NULL,
    target_identifier text NULL,
    impact_type text NOT NULL,
    status text NOT NULL,
    reason text NULL,
    skip_decided_by text NULL,
    discovery_method text NULL,
    resolution_evidence jsonb NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    resolved_at timestamptz NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX bug_impact_bug ON bug_impact (bug_uuid);
CREATE INDEX bug_impact_status ON bug_impact (status) WHERE deleted_at IS NULL;
CREATE INDEX bug_impact_target_project ON bug_impact (target_project_id);

CREATE TABLE project_dependency (
    uuid uuid PRIMARY KEY,
    dependent_project_id uuid NOT NULL,
    depends_on_project_id uuid NOT NULL,
    dependency_type text NOT NULL,
    version_constraint text NULL,
    discovery_source text NOT NULL,
    confidence text NOT NULL,
    active boolean NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE UNIQUE INDEX project_dependency_edge_unique ON project_dependency (
    dependent_project_id, depends_on_project_id, dependency_type
) WHERE deleted_at IS NULL;
CREATE INDEX project_dependency_reverse ON project_dependency (depends_on_project_id) WHERE deleted_at IS NULL AND active;
CREATE INDEX project_dependency_forward ON project_dependency (dependent_project_id) WHERE deleted_at IS NULL AND active;

CREATE TABLE bug_fix (
    uuid uuid PRIMARY KEY,
    bug_uuid uuid NOT NULL,
    status text NOT NULL,
    fix_type text NOT NULL,
    summary text NOT NULL,
    implementation_notes text NULL,
    source_project_id uuid NULL,
    branch text NULL,
    commit_hash text NULL,
    pull_request text NULL,
    changed_files jsonb NULL,
    tests jsonb NULL,
    author text NOT NULL,
    reviewer text NULL,
    started_at timestamptz NULL,
    implemented_at timestamptz NULL,
    verified_at timestamptz NULL,
    verification_method text NULL,
    expected_result text NULL,
    actual_result text NULL,
    passed boolean NULL,
    revert_info jsonb NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX bug_fix_bug ON bug_fix (bug_uuid);
CREATE INDEX bug_fix_status ON bug_fix (status) WHERE deleted_at IS NULL;

CREATE TABLE bug_fix_propagation (
    uuid uuid PRIMARY KEY,
    bug_fix_uuid uuid NOT NULL,
    impact_uuid uuid NOT NULL,
    target_type text NULL,
    target_identifier text NULL,
    action text NOT NULL,
    status text NOT NULL,
    assigned_to text NULL,
    linked_todo_uuid uuid NULL,
    linked_plan_uuid uuid NULL,
    linked_cascade_uuid uuid NULL,
    started_at timestamptz NULL,
    finished_at timestamptz NULL,
    evidence jsonb NULL,
    verification_result text NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX bug_fix_propagation_fix ON bug_fix_propagation (bug_fix_uuid);
CREATE INDEX bug_fix_propagation_impact ON bug_fix_propagation (impact_uuid);
CREATE INDEX bug_fix_propagation_status ON bug_fix_propagation (status) WHERE deleted_at IS NULL;
