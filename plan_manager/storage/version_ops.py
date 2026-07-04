"""Version-store read operations: state reconstruction, log, diff, checkout, revert."""
import uuid

import psycopg

from plan_manager.storage.canonical import canonical_json
from plan_manager.storage.version_store import VersionStoreError, record_revision


def state_at(
    conn: psycopg.Connection, plan_uuid: uuid.UUID, revision_uuid: uuid.UUID
) -> dict[uuid.UUID, uuid.UUID]:
    """Reconstruct the entity state at a revision by walking the parent chain.

    Walks from ``revision_uuid`` back to the root revision (parent_uuid is
    None) via each revision's ``parent_uuid``. For each entity_uuid touched
    by any revision on the walk, the node_version from the FIRST revision
    encountered during the walk is kept (i.e. the most recent revision on
    the walk that touched that entity); node versions from revisions
    encountered later in the walk for the same entity_uuid are ignored.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan to reconstruct state for.
    :param revision_uuid: uuid of the revision to reconstruct state at.
    :return: dict mapping entity_uuid to the node_version uuid holding that
        entity's content at ``revision_uuid``.
    :raises VersionStoreError: if ``revision_uuid`` does not exist for
        ``plan_uuid``.
    """
    state: dict[uuid.UUID, uuid.UUID] = {}
    seen: set[uuid.UUID] = set()
    current_uuid: uuid.UUID | None = revision_uuid
    while current_uuid is not None:
        cur = conn.execute(
            "SELECT parent_uuid, node_version_uuids FROM revision WHERE plan_uuid = %s AND uuid = %s",
            (plan_uuid, current_uuid),
        )
        row = cur.fetchone()
        if row is None:
            raise VersionStoreError(
                f"revision not found: plan_uuid={plan_uuid} uuid={current_uuid}"
            )
        parent_uuid, node_version_uuids = row
        if node_version_uuids:
            nv_cur = conn.execute(
                "SELECT uuid, entity_uuid, content FROM node_version WHERE uuid = ANY(%s)",
                (list(node_version_uuids),),
            )
            for node_version_uuid, entity_uuid, content in nv_cur.fetchall():
                if entity_uuid in seen:
                    continue
                seen.add(entity_uuid)
                if not content.get("deleted"):
                    state[entity_uuid] = node_version_uuid
        current_uuid = parent_uuid
    return state


def get_node_version_content(conn: psycopg.Connection, node_version_uuid: uuid.UUID) -> dict:
    """Fetch the content dict of a node_version row by its uuid.

    :param conn: open database connection.
    :param node_version_uuid: uuid of the node_version row to fetch.
    :return: the JSON content dict stored on that node_version row.
    :raises VersionStoreError: if no node_version row with that uuid exists.
    """
    cur = conn.execute(
        "SELECT content FROM node_version WHERE uuid = %s",
        (node_version_uuid,),
    )
    row = cur.fetchone()
    if row is None:
        raise VersionStoreError(f"node_version not found: uuid={node_version_uuid}")
    return row[0]


def log(conn: psycopg.Connection, plan_uuid: uuid.UUID, revision_uuid: uuid.UUID) -> list[dict]:
    """List revision records from ``revision_uuid`` back to the root revision.

    Walks from ``revision_uuid`` to the root (parent_uuid is None) via each
    revision's ``parent_uuid``, in that order (most recent first).

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan to list revisions for.
    :param revision_uuid: uuid of the revision to start the walk from.
    :return: list of revision record dicts, each with keys ``uuid``,
        ``parent_uuid``, ``author``, ``message``, ``created_at``, and
        ``node_version_uuids``, ordered from ``revision_uuid`` to the root.
    :raises VersionStoreError: if ``revision_uuid`` does not exist for
        ``plan_uuid``.
    """
    records: list[dict] = []
    current_uuid: uuid.UUID | None = revision_uuid
    while current_uuid is not None:
        cur = conn.execute(
            "SELECT uuid, parent_uuid, author, message, created_at, node_version_uuids "
            "FROM revision WHERE plan_uuid = %s AND uuid = %s",
            (plan_uuid, current_uuid),
        )
        row = cur.fetchone()
        if row is None:
            raise VersionStoreError(
                f"revision not found: plan_uuid={plan_uuid} uuid={current_uuid}"
            )
        rev_uuid, parent_uuid, author, message, created_at, node_version_uuids = row
        records.append(
            {
                "uuid": rev_uuid,
                "parent_uuid": parent_uuid,
                "author": author,
                "message": message,
                "created_at": created_at,
                "node_version_uuids": list(node_version_uuids) if node_version_uuids else [],
            }
        )
        current_uuid = parent_uuid
    return records


def diff(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    revision_a: uuid.UUID,
    revision_b: uuid.UUID,
) -> dict:
    """Diff two revisions into added, removed, and changed entities.

    Compares ``state_at(revision_a)`` and ``state_at(revision_b)`` on
    entity_uuid keys. An entity present only in ``revision_b`` is added; an
    entity present only in ``revision_a`` is removed; an entity present in
    both but with a different node_version uuid is changed, with
    field-level detail: the sorted list of top-level content keys whose
    canonical JSON differs between the two node versions' content.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan to diff.
    :param revision_a: uuid of the first (base) revision.
    :param revision_b: uuid of the second (compared) revision.
    :return: dict with keys ``added`` (list of entity_uuid), ``removed``
        (list of entity_uuid), and ``changed`` (list of dicts each with
        keys ``entity_uuid`` and ``fields``, ``fields`` being the sorted
        list of differing top-level content keys).
    """
    state_a = state_at(conn, plan_uuid, revision_a)
    state_b = state_at(conn, plan_uuid, revision_b)
    added = sorted(state_b.keys() - state_a.keys(), key=str)
    removed = sorted(state_a.keys() - state_b.keys(), key=str)
    changed = []
    for entity_uuid in sorted(state_a.keys() & state_b.keys(), key=str):
        node_version_a = state_a[entity_uuid]
        node_version_b = state_b[entity_uuid]
        if node_version_a == node_version_b:
            continue
        content_a = get_node_version_content(conn, node_version_a)
        content_b = get_node_version_content(conn, node_version_b)
        all_keys = set(content_a.keys()) | set(content_b.keys())
        fields = sorted(
            key
            for key in all_keys
            if canonical_json(content_a.get(key)) != canonical_json(content_b.get(key))
        )
        changed.append({"entity_uuid": entity_uuid, "fields": fields})
    return {"added": added, "removed": removed, "changed": changed}


def checkout_read(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    revision_uuid: uuid.UUID,
    entity_uuid: uuid.UUID,
) -> dict:
    """Read the content of one entity as it existed at a revision.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan to read from.
    :param revision_uuid: uuid of the revision to read the entity at.
    :param entity_uuid: uuid of the entity to read.
    :return: the content dict of ``entity_uuid`` at ``revision_uuid``.
    :raises VersionStoreError: if ``entity_uuid`` has no node_version at
        ``revision_uuid``.
    """
    state = state_at(conn, plan_uuid, revision_uuid)
    node_version_uuid = state.get(entity_uuid)
    if node_version_uuid is None:
        raise VersionStoreError(
            f"entity not found at revision: plan_uuid={plan_uuid} "
            f"revision_uuid={revision_uuid} entity_uuid={entity_uuid}"
        )
    return get_node_version_content(conn, node_version_uuid)


def revert(conn: psycopg.Connection, plan_uuid: uuid.UUID, revision_uuid: uuid.UUID, author: str) -> uuid.UUID:
    """Append a new revision that restores the state of a prior revision.

    Compares the state at the plan's current head revision against the
    state at ``revision_uuid``. For every entity whose current-head node
    version differs from (or is absent versus) its node version at
    ``revision_uuid``, a change entry is added with the content at
    ``revision_uuid``. The change set is recorded via ``record_revision``
    with ``ref_name=None`` (direct draft editing) and message
    ``f"revert to {revision_uuid}"``. History is never rewritten: this
    appends a new revision rather than modifying any existing one.

    :param conn: open database connection.
    :param plan_uuid: uuid of the plan to revert.
    :param revision_uuid: uuid of the revision whose state is restored.
    :param author: identifier of the author recording the revert.
    :return: uuid of the newly appended revision.
    :raises VersionStoreError: if the plan has no current head revision.
    """
    cur = conn.execute("SELECT head_revision_uuid FROM plan WHERE uuid = %s", (plan_uuid,))
    row = cur.fetchone()
    if row is None or row[0] is None:
        raise VersionStoreError(f"plan has no head revision: plan_uuid={plan_uuid}")
    head_revision_uuid = row[0]
    target_state = state_at(conn, plan_uuid, revision_uuid)
    head_state = state_at(conn, plan_uuid, head_revision_uuid)
    changes = []
    for entity_uuid, node_version_uuid in target_state.items():
        if head_state.get(entity_uuid) != node_version_uuid:
            content = get_node_version_content(conn, node_version_uuid)
            changes.append((entity_uuid, content))
    for entity_uuid, node_version_uuid in head_state.items():
        if entity_uuid not in target_state:
            content = dict(get_node_version_content(conn, node_version_uuid))
            content["deleted"] = True
            changes.append((entity_uuid, content))
    return record_revision(
        conn,
        plan_uuid,
        author,
        f"revert to {revision_uuid}",
        changes,
        head_revision_uuid,
        None,
    )
