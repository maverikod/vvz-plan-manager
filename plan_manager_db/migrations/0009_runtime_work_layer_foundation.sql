-- Migration 0009: runtime work layer foundation.
-- Establishes the foundational storage substrate of the runtime work layer:
-- a separate working layer that accompanies execution of frozen plans
-- without altering their normative content (HRS, MRS, GS, TS, AS). This
-- migration is strictly additive: it only creates the two tables below and
-- their indexes; it performs no ALTER and no DROP on any existing table.
-- A plan with no runtime records is unaffected by this migration.
--
-- Shared runtime table convention (binding on every runtime table this
-- branch introduces, including tables added by later migrations in this
-- branch):
--   * every runtime table carries created_by text, created_at timestamptz,
--     and updated_at timestamptz columns;
--   * records that allow deletion use soft delete via a nullable
--     deleted_at timestamptz column, or a separate archived status,
--     rather than physical DELETE;
--   * runtime_audit_log (defined below) is append-only: rows are only
--     ever inserted, never updated or deleted;
--   * accepted tension: the append-only guarantee governs the runtime API
--     only. plan_uuid carries ON DELETE CASCADE, so an ADMIN hard
--     plan-delete removes that plan's audit rows at the storage level.

CREATE TABLE cascade_request (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    revision_uuid uuid NULL REFERENCES revision(uuid),
    target_artifact text NOT NULL,
    target_step_path text NULL,
    origin_kind text NOT NULL,
    origin_id uuid NULL,
    reason text NOT NULL,
    status text NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL
);

CREATE INDEX cascade_request_plan_history ON cascade_request (
    plan_uuid,
    created_at
);

CREATE TABLE runtime_audit_log (
    uuid uuid PRIMARY KEY,
    plan_uuid uuid NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    entity_type text NOT NULL,
    entity_id uuid NOT NULL,
    action text NOT NULL,
    changed_by text NOT NULL,
    change_reason text NULL,
    changed_fields jsonb NULL,
    linked_attempt_id uuid NULL,
    linked_review_id uuid NULL,
    created_at timestamptz NOT NULL
);

CREATE INDEX runtime_audit_log_plan_history ON runtime_audit_log (
    plan_uuid,
    created_at
);

CREATE INDEX runtime_audit_log_entity ON runtime_audit_log (
    entity_type,
    entity_id,
    created_at
);
