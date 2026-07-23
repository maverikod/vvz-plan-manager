-- Migration 0020: Escalation routing, answer envelope, escalation policy (CR-5a, G-003).
-- Strictly additive: ALTER TABLE escalation ADD COLUMN (all NULL or DEFAULTed) plus two new tables.
-- No existing object is dropped or destructively altered; existing escalation rows remain valid.
-- All cross-entity reference columns are plain uuid/text with NO foreign keys (soft-delete robust);
-- validity is enforced in the store layer. Each new table carries deleted_at for soft delete.

-- C-009 Escalation Routing: additive routing columns on the existing escalation table.
ALTER TABLE escalation ADD COLUMN addressee_level text NULL;
ALTER TABLE escalation ADD COLUMN addressee_role text NULL;
ALTER TABLE escalation ADD COLUMN forwarded_from_uuid uuid NULL;
ALTER TABLE escalation ADD COLUMN chain_root_uuid uuid NULL;
ALTER TABLE escalation ADD COLUMN sweep_priority integer NULL;
ALTER TABLE escalation ADD COLUMN blocks_subtree boolean NOT NULL DEFAULT false;

CREATE INDEX escalation_forwarded_from ON escalation (forwarded_from_uuid);
CREATE INDEX escalation_chain_root ON escalation (chain_root_uuid);
CREATE INDEX escalation_sweep_priority ON escalation (sweep_priority) WHERE deleted_at IS NULL;

-- C-010 Answer Envelope: stored discriminated answer form of a batch call.
CREATE TABLE answer_envelope (
    uuid uuid PRIMARY KEY,
    kind text NOT NULL,               -- discriminator: result | escalation | tool_call
    schema_version integer NOT NULL,  -- version of the payload record shape
    payload jsonb NOT NULL,           -- typed payload matching the discriminator
    anchor_plan_uuid uuid NULL,
    anchor_step_uuid uuid NULL,
    attempt_uuid uuid NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX answer_envelope_kind ON answer_envelope (kind) WHERE deleted_at IS NULL;
CREATE INDEX answer_envelope_attempt ON answer_envelope (attempt_uuid);

-- C-012 Escalation Policy: standing, versioned policy record.
CREATE TABLE escalation_policy (
    uuid uuid PRIMARY KEY,
    schema_version integer NOT NULL,
    authority_typology jsonb NOT NULL,     -- closed: [interpret_mandate, supplement_context, declare_needs_plan_change, abort_step]
    max_owner_rounds integer NOT NULL,     -- ping-pong guard; standing value 2
    terminal_parks_wave boolean NOT NULL,  -- terminal user escalation parks the whole wave; standing true
    owner_timeout_parks boolean NOT NULL,  -- owner-call timeout parks, never aborts; standing true
    active boolean NOT NULL,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    deleted_at timestamptz NULL
);
CREATE INDEX escalation_policy_active ON escalation_policy (active) WHERE deleted_at IS NULL;
