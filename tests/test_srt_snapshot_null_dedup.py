"""Regression (F5): NULL-revision SRT snapshots must deduplicate.

A plan with no head revision stores revision_uuid = NULL. The 0007 idempotency
index listed revision_uuid as a plain column and the dedup SELECT used
``revision_uuid = %s``; because SQL treats NULL as distinct from NULL, an
identical tree got a fresh row on every call. Migration 0008 replaces the index
with a COALESCE-based one, and the store's dedup probe uses IS NOT DISTINCT
FROM, so two NULL revisions collapse to one idempotency key.
"""

import inspect
from pathlib import Path

from plan_manager.storage import srt_snapshot_store

MIGRATIONS = Path(__file__).resolve().parents[1] / "plan_manager_db" / "migrations"


def test_migration_0008_replaces_index_with_coalesce_key() -> None:
    matches = sorted(MIGRATIONS.glob("0008_*.sql"))
    assert matches, "migration 0008 is missing"
    sql = matches[0].read_text()

    # The old plain-column unique index is dropped and rebuilt COALESCE-based.
    assert "DROP INDEX srt_snapshot_idempotent" in sql
    assert "CREATE UNIQUE INDEX srt_snapshot_idempotent" in sql
    assert "COALESCE(revision_uuid" in sql
    # The sentinel UUID mirrors the context_block nullable-key precedent.
    assert "00000000-0000-0000-0000-000000000000" in sql
    # The rest of the idempotency tuple is preserved.
    for column in (
        "plan_uuid",
        "algorithm_version",
        "summarizer_version",
        "embedding_model",
        "tree_hash",
    ):
        assert column in sql


def test_insert_dedup_select_is_null_safe() -> None:
    source = inspect.getsource(srt_snapshot_store.insert_srt_snapshot)
    # The dedup probe must be NULL-safe on revision_uuid, never a plain "=".
    assert "revision_uuid IS NOT DISTINCT FROM %s" in source
    assert "revision_uuid = %s" not in source
