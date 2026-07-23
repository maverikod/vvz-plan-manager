"""Semantic tree snapshot persistence: content-hash-deduplicated derived records."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.domain.entity import DataclassEntity
from plan_manager.storage.canonical import content_hash


@dataclass(frozen=True)
class SrtSnapshotRecord(DataclassEntity):
    ENTITY_TYPE = "srt_snapshot"
    ENTITY_ID_FIELD = "snapshot_uuid"
    TABLE_NAME = "srt_snapshot"
    SOFT_DELETE_COLUMN = None
    # Compact view=summary projection (bug 8a13977d): drops tree_content, the
    # whole semantic tree, which dominates this record's size.
    SUMMARY_FIELDS = ("uuid", "plan_uuid", "revision_uuid", "tree_hash", "created_at")

    snapshot_uuid: uuid.UUID
    plan_uuid: uuid.UUID
    revision_uuid: uuid.UUID
    algorithm_version: str
    summarizer_version: str
    embedding_model: str
    tree_hash: str
    tree_content: dict[str, Any]
    created_at: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "uuid": str(self.snapshot_uuid),
            "plan_uuid": str(self.plan_uuid),
            "revision_uuid": str(self.revision_uuid),
            "algorithm_version": self.algorithm_version,
            "summarizer_version": self.summarizer_version,
            "embedding_model": self.embedding_model,
            "tree_hash": self.tree_hash,
            "tree_content": self.tree_content,
            "created_at": self.created_at,
        }


def _row_to_record(row: tuple[Any, ...]) -> SrtSnapshotRecord:
    return SrtSnapshotRecord(
        snapshot_uuid=row[0],
        plan_uuid=row[1],
        revision_uuid=row[2],
        algorithm_version=row[3],
        summarizer_version=row[4],
        embedding_model=row[5],
        tree_hash=row[6],
        tree_content=row[7],
        created_at=row[8].isoformat(),
    )


def insert_srt_snapshot(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    revision_uuid: uuid.UUID,
    algorithm_version: str,
    summarizer_version: str,
    embedding_model: str,
    tree_content: dict[str, Any],
) -> SrtSnapshotRecord:
    tree_hash = content_hash(tree_content)
    # revision_uuid is nullable (a snapshot of a plan with no head revision),
    # and ``= NULL`` never matches, so the dedup probe uses IS NOT DISTINCT
    # FROM to treat two NULL revisions as equal — mirroring the COALESCE-based
    # idempotency index (migration 0008). Without this a NULL-revision plan got
    # a fresh row on every call instead of deduplicating.
    row = conn.execute(
        "SELECT uuid, plan_uuid, revision_uuid, algorithm_version, summarizer_version, "
        "embedding_model, tree_hash, tree_content, created_at FROM srt_snapshot "
        "WHERE plan_uuid = %s AND revision_uuid IS NOT DISTINCT FROM %s AND algorithm_version = %s "
        "AND summarizer_version = %s AND embedding_model = %s AND tree_hash = %s",
        (plan_uuid, revision_uuid, algorithm_version, summarizer_version, embedding_model, tree_hash),
    ).fetchone()
    if row is not None:
        return _row_to_record(row)

    snapshot_uuid = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO srt_snapshot "
        "(uuid, plan_uuid, revision_uuid, algorithm_version, summarizer_version, "
        "embedding_model, tree_hash, tree_content, created_at) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            snapshot_uuid,
            plan_uuid,
            revision_uuid,
            algorithm_version,
            summarizer_version,
            embedding_model,
            tree_hash,
            Jsonb(tree_content),
            created_at,
        ),
    )
    return SrtSnapshotRecord(
        snapshot_uuid=snapshot_uuid,
        plan_uuid=plan_uuid,
        revision_uuid=revision_uuid,
        algorithm_version=algorithm_version,
        summarizer_version=summarizer_version,
        embedding_model=embedding_model,
        tree_hash=tree_hash,
        tree_content=tree_content,
        created_at=created_at.isoformat(),
    )


def list_srt_snapshots(conn: psycopg.Connection, plan_uuid: uuid.UUID) -> list[SrtSnapshotRecord]:
    rows = conn.execute(
        "SELECT uuid, plan_uuid, revision_uuid, algorithm_version, summarizer_version, "
        "embedding_model, tree_hash, tree_content, created_at FROM srt_snapshot "
        "WHERE plan_uuid = %s ORDER BY created_at ASC",
        (plan_uuid,),
    ).fetchall()
    return [_row_to_record(row) for row in rows]


def get_srt_snapshot(conn: psycopg.Connection, snapshot_uuid: uuid.UUID) -> SrtSnapshotRecord | None:
    row = conn.execute(
        "SELECT uuid, plan_uuid, revision_uuid, algorithm_version, summarizer_version, "
        "embedding_model, tree_hash, tree_content, created_at FROM srt_snapshot "
        "WHERE uuid = %s",
        (snapshot_uuid,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_record(row)
