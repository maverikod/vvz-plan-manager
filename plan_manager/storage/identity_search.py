"""Fragment search over the entity identity registry.

Kept out of ``identity.py`` deliberately: that module is a frozen plan artifact
under a 400-line cap, and this is an additive read surface rather than part of the
registry's own write contract.

The registry is the only index spanning every entity the service owns, so one
query here answers what would otherwise be a guess-the-scope hunt through
per-entity list commands -- a hunt that returns nothing when the guess is wrong
and so reads as "no such identifier" rather than "looked in the wrong place".
"""

from __future__ import annotations

from typing import Any

import psycopg


_FRAGMENT_ALLOWED = set("0123456789abcdefABCDEF-")

MIN_FRAGMENT_LENGTH = 2


def search_entity_identities(
    conn: psycopg.Connection,
    fragment: str,
    *,
    entity_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    """Find registered identifiers whose UUID text CONTAINS ``fragment``.

    The registry is the only index that spans every entity the service owns, so
    one query here answers what would otherwise be a guess-the-scope hunt through
    per-entity list commands — a hunt that returns nothing when the guess is wrong
    and so reads as "no such identifier" rather than "looked in the wrong place".

    Substring rather than prefix on purpose: identifiers get quoted in prose,
    commits and chat as any convenient slice, not always the leading one.

    Parameters:
        fragment: hex/dash characters only, at least MIN_FRAGMENT_LENGTH of them.
            LIKE wildcards cannot appear in a UUID, and are rejected by the
            character check rather than escaped.
        entity_type: optional exact filter on the registered entity type.
        limit, offset: pagination over a deterministic order.

    Returns:
        (matches, total) where total is the full match count before the window,
        so a caller can tell a unique hit from an ambiguous fragment.

    Raises:
        ValueError: the fragment is too short or carries characters no UUID has.
    """
    cleaned = (fragment or "").strip()
    if len(cleaned) < MIN_FRAGMENT_LENGTH:
        raise ValueError(
            f"identifier fragment must be at least {MIN_FRAGMENT_LENGTH} characters, "
            f"got {cleaned!r}"
        )
    illegal = sorted(set(cleaned) - _FRAGMENT_ALLOWED)
    if illegal:
        raise ValueError(
            f"identifier fragment carries characters no UUID contains: {illegal}"
        )

    clauses = ["id::text LIKE %s"]
    params: list[Any] = [f"%{cleaned.lower()}%"]
    if entity_type is not None:
        clauses.append("entity_type = %s")
        params.append(entity_type)
    where = " AND ".join(clauses)

    total = conn.execute(
        f"SELECT COUNT(*) FROM entity_identity WHERE {where}", params
    ).fetchone()[0]
    rows = conn.execute(
        "SELECT id, table_name, entity_type, kind, reserved_by, note, created_at "
        f"FROM entity_identity WHERE {where} "
        "ORDER BY created_at DESC, id ASC LIMIT %s OFFSET %s",
        params + [limit, offset],
    ).fetchall()
    return (
        [
            {
                "id": row[0],
                "table_name": row[1],
                "entity_type": row[2],
                "kind": row[3],
                "reserved_by": row[4],
                "note": row[5],
                "created_at": row[6],
            }
            for row in rows
        ],
        total,
    )
