-- Migration 0014: paragraph binding flag (bug f253b08d — para_mark_non_binding unwrap).
-- This migration is strictly additive: it adds a single column with a default and performs no
-- ALTER COLUMN, DROP, or TRUNCATE of any existing object. It uses no IF NOT EXISTS.
--
-- Background: only binding HRS paragraphs (C-002) are ever surfaced. Before this migration,
-- para_mark_non_binding wrap HARD-DELETED the paragraph row, which made the operation lossy and
-- left direction=unwrap a permanent dead path (nothing to restore). This column lets wrap mark a
-- paragraph non-binding (binding = false) while KEEPING the row so unwrap can restore it (binding
-- = true) — a byte-identical wrap -> unwrap round-trip. Every existing paragraph row is a binding
-- paragraph, so the column defaults to true and all current data is unchanged. Every reader that
-- surfaces binding paragraphs (paragraph listing, coverage, the mechanical gate, label estimators)
-- filters on binding = true, so a wrapped (non-binding) paragraph is excluded from labeling and
-- coverage exactly as a deleted one used to be, without breaking the "only binding paragraphs are
-- surfaced" invariant.

ALTER TABLE paragraph ADD COLUMN binding boolean NOT NULL DEFAULT true;
