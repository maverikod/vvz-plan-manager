"""Version-store writes: node versions, revisions, and refs."""
import uuid
from datetime import datetime, timezone

import psycopg
from psycopg.types.json import Jsonb

from plan_manager.storage.canonical import content_hash
from plan_manager.domain.plan import set_head_revision

from plan_manager.domain.entity import DataclassEntity


class _VersionSeat(DataclassEntity):
    """Shared traits of the version-store write seats (CR-7 G-004).

    These tables' identities are registered by DB triggers, so the engine's
    Python-side registration stays off and the routed writes keep the exact
    single-INSERT statement profile. ENTITY_TYPE=None keeps the seats out of
    the catalog's entity-type resolver.
    """

    ENTITY_TYPE = None
    SOFT_DELETE_COLUMN = None
    UPDATED_AT_COLUMN = None
    CREATED_AT_COLUMN = None
    REGISTER_IDENTITY = False
    OWNER_COLUMN = "plan_uuid"


class _NodeVersionRow(_VersionSeat):
    TABLE_NAME = "node_version"
    COLUMNS = ("uuid", "plan_uuid", "entity_uuid", "hash", "content")


class _RevisionRow(_VersionSeat):
    TABLE_NAME = "revision"
    COLUMNS = ("uuid", "plan_uuid", "parent_uuid", "author", "message", "created_at", "node_version_uuids")


class _RefRow(_VersionSeat):
    TABLE_NAME = "ref"
    COLUMNS = ("uuid", "plan_uuid", "name", "revision_uuid")
    ID_COLUMN = None
    ID_COLUMNS = ("plan_uuid", "name")



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
    # CR-7 G-004 (C-005, C-012): delegated to the unified creation path.
    _NodeVersionRow.crud_create(
        conn,
        {
            "uuid": new_uuid, "plan_uuid": plan_uuid, "entity_uuid": entity_uuid,
            "hash": hash_value, "content": Jsonb(content),
        },
        returning=False,
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
    # CR-7 G-004 (C-005, C-012): delegated to the unified creation path.
    _RevisionRow.crud_create(
        conn,
        {
            "uuid": new_uuid, "plan_uuid": plan_uuid, "parent_uuid": parent_uuid,
            "author": author, "message": message, "created_at": created_at,
            "node_version_uuids": node_version_uuids,
        },
        returning=False,
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
    # CR-7 G-004 (C-005, C-012): delegated to the unified creation path.
    _RefRow.crud_create(
        conn,
        {"uuid": new_uuid, "plan_uuid": plan_uuid, "name": name, "revision_uuid": revision_uuid},
        returning=False,
    )
    return new_uuid


def delete_ref(conn: psycopg.Connection, plan_uuid: uuid.UUID, name: str) -> None:
    """Delete the ref row named ``name`` for ``plan_uuid``.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan the ref belongs to.
    :param name: name of the ref to delete.
    :return: None.
    """
    # CR-7 G-004 compatibility note: bug 9efa5ec5 - the guarded engine wrapper's
    # audit write cannot carry ref's composite (plan_uuid, name) identity into
    # runtime_audit_log.entity_id, which is NOT NULL on live PG and has no
    # non-UUID representation; routing this DELETE through crud_hard_delete
    # crashed the whole operation there. Reverted to the raw statement until
    # the c315ff84 guard rework adds composite-identity audit support.
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
    *,
    carry_forward_paths: list[str] | None = None,
    cascade_uuid: uuid.UUID | None = None,
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
    :param carry_forward_paths: bug fa15d288 -- canonical step paths this
        mutation writes. When supplied (even as an empty list), the plan's
        context blocks that provably cannot depend on those paths are
        re-tagged from the old working revision pair onto the new one, so
        a scoped step write no longer stales the whole plan's derived
        context. When None (the default), no re-tagging happens and every
        block goes stale exactly as before -- the correct behavior for
        callers whose change scope in step-path terms is not established
        (paragraph edits, import, maintenance normalization).
    :param cascade_uuid: identity of the open cascade this revision is
        recorded under, or None in direct mode; used only to build the
        working revision pair for ``carry_forward_paths``.
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
    if carry_forward_paths is not None:
        # Deferred import: views.context_blocks reaches this module for
        # get_ref, so a module-level import would close a cycle.
        from plan_manager.views.context_blocks import carry_forward_context_blocks

        # parent_revision_uuid IS the working revision this write advances
        # from: the plan head in direct mode, the cascade ref's current
        # target in cascade mode.
        carry_forward_context_blocks(
            conn,
            plan_uuid,
            from_revision=parent_revision_uuid,
            from_cascade=cascade_uuid,
            to_revision=revision_uuid,
            to_cascade=cascade_uuid,
            changed_paths=carry_forward_paths,
        )
    return revision_uuid
