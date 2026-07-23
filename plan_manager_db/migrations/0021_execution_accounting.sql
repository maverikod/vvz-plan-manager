-- Migration 0021: execution accounting sub-schema (C-013 "Execution Accounting").
-- ADDITIVE ONLY. Adds typed accounting columns and a reserved transcript
-- reference to execution_attempt. Performs no ALTER COLUMN, no DROP, and no
-- TRUNCATE of any existing object. The existing resource_accounting jsonb
-- column is retained untouched as the canonical free-form accounting bag;
-- the new columns are a typed, validated, queryable projection of a subset
-- of that bag plus a transcript provenance reference.

ALTER TABLE execution_attempt
    ADD COLUMN acct_tokens_in integer,
    ADD COLUMN acct_tokens_out integer,
    ADD COLUMN acct_provider text,
    ADD COLUMN acct_model text,
    ADD COLUMN acct_wall_ms bigint,
    ADD COLUMN acct_cost_estimate numeric,
    ADD COLUMN transcript_ref text;

CREATE INDEX execution_attempt_acct_provider_model
    ON execution_attempt (acct_provider, acct_model)
    WHERE deleted_at IS NULL;
