"""Shared runtime validation primitives: identity checks, membership checks, and the frozen-truth mutation guard (C-031, C-002)."""

import uuid

import psycopg


class RuntimeValidationError(Exception):
    """Raised when a candidate runtime write fails a shared runtime validation check (C-031)."""


class FrozenTruthMutationError(RuntimeValidationError):
    """Raised when a candidate runtime write targets a frozen-truth table (C-002)."""


FROZEN_TRUTH_TABLES: frozenset[str] = frozenset(
    {
        "plan",
        "revision",
        "step",
        "concept",
        "relation",
        "paragraph",
        "node_version",
        "ref",
    }
)


def guard_frozen_truth(table: str) -> None:
    """Enforce the frozen-truth mutation guard (C-002).

    The runtime API must not mutate frozen plan truth (C-002); this is the
    enforcement point for that guarantee.

    Parameters:
        table: The table name candidate to check.

    Raises:
        FrozenTruthMutationError: If table is a member of FROZEN_TRUTH_TABLES.
    """
    if table in FROZEN_TRUTH_TABLES:
        raise FrozenTruthMutationError(f"runtime API must not mutate frozen truth table: {table!r}")


def validate_uuid(value: object) -> uuid.UUID:
    """Validate a candidate identifier and realize C-031's UUID-validation guarantee.

    Parameters:
        value: Candidate identifier value.

    Returns:
        The validated uuid.UUID instance.

    Raises:
        RuntimeValidationError: If value is not a valid UUID.
    """
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            raise RuntimeValidationError(f"not a valid UUID: {value!r}")
    raise RuntimeValidationError(f"not a valid UUID: {value!r}")


PRIORITY_NICE_MIN = -20
PRIORITY_NICE_MAX = 19


def validate_priority_nice(value: int) -> int:
    """Validate a candidate priority_nice value against the fixed [-20, 19] range and realize C-031's priority_nice-validation guarantee.

    Parameters:
        value: Candidate priority_nice integer value.

    Returns:
        The validated priority_nice value.

    Raises:
        RuntimeValidationError: If value is not an int or out of range.
    """
    if not isinstance(value, int):
        raise RuntimeValidationError(f"priority_nice must be an int, got {type(value).__name__}")
    if value < PRIORITY_NICE_MIN or value > PRIORITY_NICE_MAX:
        raise RuntimeValidationError(f"priority_nice {value} out of range [{PRIORITY_NICE_MIN}, {PRIORITY_NICE_MAX}]")
    return value


def check_row_exists(
    conn: psycopg.Connection,
    table: str,
    uuid_value: uuid.UUID,
    allowed_tables: frozenset[str],
) -> None:
    """Check anchor existence for a candidate UUID against a caller-supplied table allowlist (C-031).

    This mirrors the table-name allowlist discipline of plan_manager/storage/identity.py's
    ALLOWED_TABLES/resolve_scoped_name, where the table name is validated against the allowlist
    BEFORE it is interpolated into any SQL string, so no unvalidated value ever reaches string
    interpolation.

    Parameters:
        conn: An open psycopg 3 connection.
        table: The table to check; must be a member of allowed_tables.
        uuid_value: The candidate anchor UUID.
        allowed_tables: The caller-supplied allowlist of legal table names for this check.

    Raises:
        RuntimeValidationError: If table is not in allowed_tables or if no row with uuid_value exists in table.
    """
    if table not in allowed_tables:
        raise RuntimeValidationError(f"table not allowed: {table!r}")
    sql = f"SELECT 1 FROM {table} WHERE uuid = %s"
    row = conn.execute(sql, (uuid_value,)).fetchone()
    if row is None:
        raise RuntimeValidationError(f"no row in {table} with uuid={uuid_value}")


def validate_step_in_plan_revision(
    conn: psycopg.Connection,
    plan_uuid: uuid.UUID,
    revision_uuid: uuid.UUID | None,
    step_uuid: uuid.UUID,
) -> None:
    """Validate step-to-plan-and-revision membership (C-031).

    Parameters:
        conn: An open psycopg 3 connection.
        plan_uuid: The plan UUID.
        revision_uuid: Optional revision scoping; when provided, the step must be a member of the plan state
            reconstructed at that revision by walking the revision's parent chain (the version store is a delta store).
        step_uuid: The step UUID to validate.

    Raises:
        RuntimeValidationError: When no matching step row exists, or when revision_uuid is provided but the
            step is not a member of the plan state reconstructed at that revision.
    """
    step_row = conn.execute(
        "SELECT uuid FROM step WHERE uuid = %s AND plan_uuid = %s",
        (step_uuid, plan_uuid),
    ).fetchone()
    if step_row is None:
        raise RuntimeValidationError(
            f"step {step_uuid} does not belong to plan {plan_uuid}"
        )
    if revision_uuid is not None:
        member_row = conn.execute(
            "WITH RECURSIVE ancestry(uuid, parent_uuid, node_version_uuids, depth) AS ( "
            "SELECT r.uuid, r.parent_uuid, r.node_version_uuids, 0 "
            "FROM revision AS r "
            "WHERE r.uuid = %s AND r.plan_uuid = %s "
            "UNION ALL "
            "SELECT r.uuid, r.parent_uuid, r.node_version_uuids, a.depth + 1 "
            "FROM revision AS r "
            "JOIN ancestry AS a ON r.uuid = a.parent_uuid "
            "WHERE r.plan_uuid = %s "
            ") "
            "SELECT nv.content FROM ancestry AS a "
            "JOIN node_version AS nv ON nv.uuid = ANY(a.node_version_uuids) "
            "WHERE nv.entity_uuid = %s "
            "ORDER BY a.depth ASC "
            "LIMIT 1",
            (revision_uuid, plan_uuid, plan_uuid, step_uuid),
        ).fetchone()
        if member_row is None or member_row[0].get("deleted"):
            raise RuntimeValidationError(
                f"step {step_uuid} does not belong to revision {revision_uuid}"
            )


def validate_file_reference(project_id: uuid.UUID, file_path: str) -> None:
    """Validate file-to-project structural membership (C-031) without a local project catalog.

    This is a structural check only (well-formed project id, well-formed project-relative path),
    not an existence check against a file system or catalog.

    Parameters:
        project_id: The project UUID.
        file_path: The file path to validate.

    Raises:
        RuntimeValidationError: If project_id is not a uuid.UUID instance, if file_path is empty or not a str,
            if file_path is an absolute path, or if file_path contains '..' path segments.
    """
    if not isinstance(project_id, uuid.UUID):
        raise RuntimeValidationError(f"project_id must be a UUID, got {project_id!r}")
    if not isinstance(file_path, str) or not file_path:
        raise RuntimeValidationError(f"file_path must be a non-empty str, got {file_path!r}")
    if file_path.startswith("/"):
        raise RuntimeValidationError(f"file_path must be project-relative, got {file_path!r}")
    segments = file_path.split("/")
    if ".." in segments:
        raise RuntimeValidationError(f"file_path must not contain '..' segments, got {file_path!r}")
