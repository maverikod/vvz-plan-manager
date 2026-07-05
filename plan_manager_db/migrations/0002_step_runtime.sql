-- Migration 0002: runtime parameters for plan steps.
-- Runtime data is deliberately separate from definition rows and revisions.

CREATE TABLE step_runtime (
    step_uuid uuid PRIMARY KEY REFERENCES step(uuid) ON DELETE CASCADE,
    plan_uuid uuid NOT NULL REFERENCES plan(uuid) ON DELETE CASCADE,
    data jsonb NOT NULL
);

CREATE INDEX step_runtime_plan_uuid ON step_runtime (plan_uuid);
