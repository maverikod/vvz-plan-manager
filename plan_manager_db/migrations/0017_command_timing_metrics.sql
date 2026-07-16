-- Migration 0017: command timing metrics.
-- Adds the command_metric table: an append-only, per-invocation timing
-- record written by the command-registration timing hook (C-005) and read
-- by the command_timing_stats aggregate command (C-004). This migration is
-- strictly additive: it only creates the command_metric table and its
-- indexes; it performs no ALTER and no DROP on any existing table.
--
-- Append-only convention: rows are only ever inserted, never updated or
-- deleted; there is no deleted_at or updated_at column. mode distinguishes
-- a directly-dispatched invocation ('direct') from one executed via the
-- background queue ('queued'), mirroring the command class's own
-- use_queue declaration. outcome distinguishes a SuccessResult
-- ('success') from an ErrorResult or a raised exception ('error').

CREATE TABLE command_metric (
    uuid uuid PRIMARY KEY,
    command_name text NOT NULL,
    duration_ms double precision NOT NULL,
    mode text NOT NULL,
    outcome text NOT NULL,
    created_at timestamptz NOT NULL
);

CREATE INDEX command_metric_name_created ON command_metric (command_name, created_at);
CREATE INDEX command_metric_created ON command_metric (created_at);
