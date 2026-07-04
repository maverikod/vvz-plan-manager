"""Version-store writes: node versions, revisions, and refs."""
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.storage.canonical import content_hash
from plan_manager.domain.plan import set_head_revision


class VersionStoreError(ValueError):
    """Raised when a version-store lookup (e.g. a ref or revision) is not found."""


def insert_node_version(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    entity_uuid: uuid.UUID,
    content: dict,
) -> uuid.UUID:
    """Store ``content`` as a node version, reusing an identical existing one.

    Content addressing: the SHA-256 hex digest of the canonical JSON of
    ``content`` (via ``content_hash``) is computed first. If a node_version
    row already exists for the same ``(plan_uuid, entity_uuid, hash)``, its
    uuid is returned and no new row is inserted. Otherwise a new node_version
    row is inserted with a freshly generated uuid.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan the node version belongs to.
    :param entity_uuid: uuid of the domain entity this version snapshots.
    :param content: JSON-serializable content of the node version.
    :return: uuid of the existing or newly inserted node_version row.
    """
    hash_value = content_hash(content)
    cur = conn.execute(
        "SELECT uuid FROM node_version WHERE plan_uuid = %s AND entity_uuid = %s AND hash = %s",
        (plan_uuid, entity_uuid, hash_value),
    )
    row = cur.fetchone()
    if row is not None:
        return row[0]
    new_uuid = uuid.uuid4()
    conn.execute(
        "INSERT INTO node_version (uuid, plan_uuid, entity_uuid, hash, content) "
        "VALUES (%s, %s, %s, %s, %s)",
        (new_uuid, plan_uuid, entity_uuid, hash_value, Jsonb(content)),
    )
    return new_uuid


def insert_revision(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    parent_uuid: uuid.UUID | None,
    author: str,
    message: str,
    node_version_uuids: list[uuid.UUID],
) -> uuid.UUID:
    """Insert a new revision row.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan the revision belongs to.
    :param parent_uuid: uuid of the parent revision, or None for the first
        revision of the plan.
    :param author: identifier of the revision's author.
    :param message: human-readable revision message.
    :param node_version_uuids: uuids of the node_version rows changed by
        this revision.
    :return: uuid of the newly inserted revision row.
    """
    new_uuid = uuid.uuid4()
    created_at = datetime.now(timezone.utc)
    conn.execute(
        "INSERT INTO revision (uuid, plan_uuid, parent_uuid, author, message, created_at, node_version_uuids) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (new_uuid, plan_uuid, parent_uuid, author, message, created_at, node_version_uuids),
    )
    return new_uuid


def create_ref(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    name: str,
    revision_uuid: uuid.UUID,
) -> uuid.UUID:
    """Create a new ref row pointing a named ref at a revision.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan the ref belongs to.
    :param name: name of the ref (e.g. the cascade identifier).
    :param revision_uuid: uuid of the revision the ref points to.
    :return: uuid of the newly inserted ref row.
    """
    new_uuid = uuid.uuid4()
    conn.execute(
        "INSERT INTO ref (uuid, plan_uuid, name, revision_uuid) VALUES (%s, %s, %s, %s)",
        (new_uuid, plan_uuid, name, revision_uuid),
    )
    return new_uuid


def delete_ref(conn: psycopg.Connection, plan_uuid: uuid.UUID, name: str) -> None:
    """Delete the ref row named ``name`` for ``plan_uuid``.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan the ref belongs to.
    :param name: name of the ref to delete.
    :return: None.
    """
    conn.execute("DELETE FROM ref WHERE plan_uuid = %s AND name = %s", (plan_uuid, name))


def get_ref(conn: psycopg.Connection, plan_uuid: uuid.UUID, name: str) -> uuid.UUID:
    """Look up the revision uuid a named ref currently points to.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan the ref belongs to.
    :param name: name of the ref to look up.
    :return: uuid of the revision the ref points to.
    :raises VersionStoreError: if no ref named ``name`` exists for ``plan_uuid``.
    """
    cur = conn.execute(
        "SELECT revision_uuid FROM ref WHERE plan_uuid = %s AND name = %s",
        (plan_uuid, name),
    )
    row = cur.fetchone()
    if row is None:
        raise VersionStoreError(f"ref not found: plan_uuid={plan_uuid} name={name}")
    return row[0]


def record_revision(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    author: str,
    message: str,
    changes: list[tuple[uuid.UUID, dict]],
    parent_revision_uuid: uuid.UUID | None,
    ref_name: str | None,
) -> uuid.UUID:
    """Record one mutation as one revision: write node versions, then the revision, then advance head or ref.

    For each ``(entity_uuid, content)`` pair in ``changes``, a node version is
    written via ``insert_node_version`` (reusing an identical existing node
    version for the same ``(plan_uuid, entity_uuid, hash)`` when present). A
    single revision row is then inserted via ``insert_revision`` with
    ``parent_uuid=parent_revision_uuid`` and the resulting node_version uuids.
    Finally: if ``ref_name`` is None, the plan head is advanced to the new
    revision via ``set_head_revision`` (direct draft editing); otherwise the
    ref row named ``ref_name`` is updated to point at the new revision
    (cascade editing).

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan being mutated.
    :param author: identifier of the revision's author.
    :param message: human-readable revision message.
    :param changes: list of ``(entity_uuid, content)`` pairs, one per changed
        entity; ``content`` is a JSON-serializable dict.
    :param parent_revision_uuid: uuid of the parent revision, or None for the
        first revision of the plan.
    :param ref_name: name of the cascade ref to advance, or None to advance
        the plan head directly.
    :return: uuid of the newly inserted revision row.
    """
    node_version_uuids = [
        insert_node_version(conn, plan_uuid, entity_uuid, content)
        for entity_uuid, content in changes
    ]
    revision_uuid = insert_revision(
        conn, plan_uuid, parent_revision_uuid, author, message, node_version_uuids
    )
    if ref_name is None:
        set_head_revision(conn, plan_uuid, revision_uuid)
    else:
        conn.execute(
            "UPDATE ref SET revision_uuid = %s WHERE plan_uuid = %s AND name = %s",
            (revision_uuid, plan_uuid, ref_name),
        )
    return revision_uuid
