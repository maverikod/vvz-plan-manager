"""Common entity contract for persisted Plan Manager domain records."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from datetime import timezone
from typing import Any, ClassVar

import psycopg
from psycopg import sql

from plan_manager.storage.identity import (
    EXCLUDED_TABLES,
    ensure_identity_available,
    register_entity_identity,
    resolve_entity_identity,
    unregister_entity_identity,
)


EntityIdentifier = uuid.UUID | str


class EntityReferencedError(RuntimeError):
    """Raised when hard deletion is refused because inbound references exist."""

    def __init__(
        self,
        entity_type: str,
        entity_id: Any,
        references: dict[str, int] | list[dict[str, Any]],
    ) -> None:
        """Accept either payload and expose both.

        Historically this carried only per-column counts, which told a caller
        that something referenced the entity but not WHAT, so the refusal could
        not be acted on. It now also accepts the referrer list the guard
        produces and derives the counts from it, so `.references` keeps working
        for existing consumers while `.referrers` carries the identities.
        """
        self.entity_type = entity_type
        self.entity_id = entity_id
        if isinstance(references, list):
            self.referrers: list[dict[str, Any]] = references
            counts: dict[str, int] = {}
            for referrer in references:
                key = f"{referrer.get('table')}.{referrer.get('column')}"
                counts[key] = counts.get(key, 0) + 1
            self.references: dict[str, int] = counts
        else:
            self.references = references
            self.referrers = []
        super().__init__(
            f"ENTITY_REFERENCED: {entity_type} {entity_id!r} has inbound references: "
            f"{self.references}"
        )


class EntityNotSoftDeletedError(RuntimeError):
    """Raised when physical deletion is attempted for a live row."""

    def __init__(self, entity_type: str, entity_id: Any) -> None:
        self.entity_type = entity_type
        self.entity_id = entity_id
        super().__init__(
            f"ENTITY_NOT_SOFT_DELETED: {entity_type} {entity_id!r} must be soft-deleted before purge"
        )


@dataclass(frozen=True)
class ReferenceCheck:
    """One inbound-reference guard used before physical deletion.

    Each (column, literal) pair in const_filters constrains the probe to
    referencing-table rows where that column equals the literal value.
    """

    table: str
    column: str
    source_column: str | None = None
    scope_columns: tuple[tuple[str, str], ...] = ()
    array: bool = False
    live_column: str | None = None
    const_filters: tuple[tuple[str, str], ...] = ()


CENTRAL_REFERENCE_CHECKS: dict[str, tuple[ReferenceCheck, ...]] = {
    "plan": (
        ReferenceCheck("todo_item", "anchor_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("model_binding", "plan_uuid", live_column="deleted_at"),
        ReferenceCheck("runtime_comment", "anchor_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("execution_attempt", "plan_uuid", live_column="deleted_at"),
        ReferenceCheck("escalation", "anchor_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_report", "source_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_impact", "target_plan_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_fix_propagation", "linked_plan_uuid", live_column="deleted_at"),
    ),
    "step": (
        ReferenceCheck("step", "parent_step_uuid"),
        ReferenceCheck("node_version", "entity_uuid"),
        ReferenceCheck("todo_item", "anchor_step_uuid", live_column="deleted_at"),
        ReferenceCheck("model_binding", "branch_step_uuid", live_column="deleted_at"),
        ReferenceCheck("model_binding", "step_uuid", live_column="deleted_at"),
        ReferenceCheck("runtime_comment", "anchor_step_uuid", live_column="deleted_at"),
        ReferenceCheck("execution_attempt", "step_uuid", live_column="deleted_at"),
        ReferenceCheck("escalation", "anchor_step_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_report", "source_step_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_impact", "target_step_uuid", live_column="deleted_at"),
    ),
    "concept": (
        ReferenceCheck("relation", "from_concept", "concept_id", scope_columns=(("plan_uuid", "plan_uuid"),)),
        ReferenceCheck("relation", "to_concept", "concept_id", scope_columns=(("plan_uuid", "plan_uuid"),)),
        ReferenceCheck("step", "concepts", "concept_id", scope_columns=(("plan_uuid", "plan_uuid"),), array=True),
    ),
    "todo": (
        ReferenceCheck("execution_attempt", "todo_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_fix_propagation", "linked_todo_uuid", live_column="deleted_at"),
        ReferenceCheck("runtime_comment", "anchor_ref_id", live_column="deleted_at", const_filters=(("primary_anchor_type", "todo"),)),
        ReferenceCheck("escalation", "anchor_ref_id", live_column="deleted_at", const_filters=(("primary_anchor_type", "todo"),)),
    ),
    "comment": (
        ReferenceCheck("runtime_comment", "supersedes_comment_uuid", live_column="deleted_at"),
    ),
    "execution_attempt": (
        ReferenceCheck("runtime_comment", "anchor_ref_id", live_column="deleted_at"),
        ReferenceCheck("review_result", "reviewed_attempt_uuid", live_column="deleted_at"),
        ReferenceCheck("execution_attempt", "parent_attempt_uuid", live_column="deleted_at"),
    ),
    "review_result": (
        ReferenceCheck("runtime_audit_log", "linked_review_id"),
    ),
    "bug": (
        ReferenceCheck("runtime_comment", "anchor_ref_id", live_column="deleted_at"),
        ReferenceCheck("bug_report", "duplicate_of_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_report", "parent_bug_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_impact", "bug_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_fix", "bug_uuid", live_column="deleted_at"),
    ),
    "bug_impact": (
        ReferenceCheck("bug_fix_propagation", "impact_uuid", live_column="deleted_at"),
    ),
    "bug_fix": (
        ReferenceCheck("runtime_comment", "anchor_ref_id", live_column="deleted_at"),
        ReferenceCheck("execution_attempt", "bug_fix_uuid", live_column="deleted_at"),
        ReferenceCheck("bug_fix_propagation", "bug_fix_uuid", live_column="deleted_at"),
    ),
    "provider": (
        ReferenceCheck("model", "provider_uuid", live_column="deleted_at"),
    ),
    "tool": (
        ReferenceCheck("toolset_membership", "tool_uuid", live_column="deleted_at"),
    ),
}


class EntityRecord(ABC):
    """Abstract contract shared by addressable Plan Manager entities."""

    # Compact-projection support (bug 8a13977d): the ordered field names a
    # view=summary caller receives, drawn from this entity's own to_payload()
    # keys. Declared per-entity, next to that entity's serialization (its
    # to_payload/dataclass definition) -- empty by default, which makes
    # to_summary_payload() fall back to the full payload (safe default for
    # any entity that has not opted into a summary shape yet).
    SUMMARY_FIELDS: ClassVar[tuple[str, ...]] = ()

    @classmethod
    @abstractmethod
    def entity_type(cls) -> str:
        """Return the stable entity kind used by API, storage, and audits."""

    @abstractmethod
    def entity_id(self) -> EntityIdentifier:
        """Return the stable identifier for this record."""

    @classmethod
    @abstractmethod
    def get_by_id(
        cls,
        conn: psycopg.Connection,
        entity_id: Any,
        *,
        include_deleted: bool = True,
    ) -> dict[str, Any] | None:
        """Fetch one entity by its stable identifier."""

    @abstractmethod
    def to_payload(self) -> dict[str, Any]:
        """Render the record as a JSON-safe API payload."""

    def to_summary_payload(self) -> dict[str, Any]:
        """Render a compact projection of this record, restricted to SUMMARY_FIELDS.

        The single shared implementation every entity gets for free: it
        always starts from this entity's own to_payload() (so any override
        of to_payload is respected) and whitelists SUMMARY_FIELDS from it.
        Falls back to the full payload when SUMMARY_FIELDS is empty (the
        entity has not declared a summary projection yet), so callers always
        get a JSON-safe dict either way.
        """
        full = self.to_payload()
        if not self.SUMMARY_FIELDS:
            return full
        return {name: full.get(name) for name in self.SUMMARY_FIELDS}


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    return value


class DataclassEntity(EntityRecord):
    """Reusable implementation for dataclass-backed entity records.

    Deletion is intentionally two-phase: regular entity deletion marks a row
    via ``crud_soft_delete``; physical deletion is restricted to
    ``crud_purge_soft_deleted_batch`` over rows already carrying the soft-delete
    marker.

    Descriptor contract. The ClassVars below declare the store: the table, the
    identifier column, the readable columns, which of them a create and an
    update may touch, which carry searchable text, and which mark soft deletion
    and update time. ``validate_descriptor`` checks a subclass against that
    contract.

    A descriptor ClassVar left None or empty is allowed, but only as a
    DOCUMENTED gap: the subclass must say so in its own class docstring with a
    line of the form ``Descriptor gap: <NAME> unimplemented -- <reason>``. That
    generalizes the convention CommandMetricRecord, SrtSnapshotRecord and
    CascadeRequestRecord already follow. An undocumented empty ClassVar is a
    defect, not an exemption: it silently disables a guarantee the rest of the
    codebase assumes.
    """

    ENTITY_TYPE: ClassVar[str]
    ENTITY_ID_FIELD: ClassVar[str | None] = None
    ENTITY_ID_FIELDS: ClassVar[tuple[str, ...]] = ()
    TABLE_NAME: ClassVar[str | None] = None
    ID_COLUMN: ClassVar[str | None] = "uuid"
    ID_COLUMNS: ClassVar[tuple[str, ...]] = ()
    COLUMNS: ClassVar[tuple[str, ...]] = ()
    INSERT_COLUMNS: ClassVar[tuple[str, ...]] = ()
    UPDATE_COLUMNS: ClassVar[tuple[str, ...]] = ()
    SEARCH_COLUMNS: ClassVar[tuple[str, ...]] = ()
    SOFT_DELETE_COLUMN: ClassVar[str | None] = "deleted_at"
    UPDATED_AT_COLUMN: ClassVar[str | None] = "updated_at"
    HARD_DELETE_REFERENCE_CHECKS: ClassVar[tuple[ReferenceCheck, ...]] = ()
    REGISTER_IDENTITY: ClassVar[bool] = True

    @classmethod
    def validate_descriptor(cls) -> None:
        """Check this subclass against the declarative store descriptor contract.

        Opt-in: nothing calls this automatically. It is the assertion a
        descriptor test makes, and the check a store migration runs once while
        populating a new descriptor.

        Rules, in the order they are checked:

        1. COLUMNS must be non-empty for any entity that declares TABLE_NAME.
           An entity with no TABLE_NAME may leave COLUMNS empty.
        2. ID_COLUMN, or every member of ID_COLUMNS, must name a column present
           in COLUMNS.
        3. INSERT_COLUMNS must be empty or a subset of COLUMNS.
        4. UPDATE_COLUMNS must be empty or a subset of COLUMNS.
        5. SEARCH_COLUMNS must be empty or a subset of COLUMNS.
        6. SOFT_DELETE_COLUMN, when not None, must be in COLUMNS.
        7. UPDATED_AT_COLUMN, when not None, must be in COLUMNS.

        Rules 2 through 7 are skipped when COLUMNS is empty, because an
        unpopulated descriptor is a documented gap rather than a contradiction.

        Raises:
            ValueError: naming the violated rule and the offending columns.
        """
        name = cls.__name__
        columns = set(cls.COLUMNS)

        if cls.TABLE_NAME is not None and not columns:
            raise ValueError(
                f"{name}: COLUMNS must be non-empty when TABLE_NAME is declared "
                f"(table {cls.TABLE_NAME!r})"
            )
        if not columns:
            return

        id_columns = tuple(cls.ID_COLUMNS) or ((cls.ID_COLUMN,) if cls.ID_COLUMN else ())
        missing_ids = sorted(c for c in id_columns if c not in columns)
        if missing_ids:
            raise ValueError(f"{name}: identifier columns absent from COLUMNS: {missing_ids}")

        for attribute in ("INSERT_COLUMNS", "UPDATE_COLUMNS", "SEARCH_COLUMNS"):
            declared = tuple(getattr(cls, attribute))
            extra = sorted(set(declared) - columns)
            if extra:
                raise ValueError(f"{name}: {attribute} is not a subset of COLUMNS: {extra}")

        for attribute in ("SOFT_DELETE_COLUMN", "UPDATED_AT_COLUMN"):
            value = getattr(cls, attribute)
            if value is not None and value not in columns:
                raise ValueError(f"{name}: {attribute}={value!r} is absent from COLUMNS")

    @classmethod
    def entity_type(cls) -> str:
        return cls.ENTITY_TYPE

    def entity_id(self) -> EntityIdentifier:
        if self.ENTITY_ID_FIELD is not None:
            return getattr(self, self.ENTITY_ID_FIELD)
        if self.ENTITY_ID_FIELDS:
            return "|".join(str(getattr(self, field)) for field in self.ENTITY_ID_FIELDS)
        raise NotImplementedError(f"{type(self).__name__} does not define entity id fields")

    def to_payload(self) -> dict[str, Any]:
        if not is_dataclass(self):
            raise TypeError(f"{type(self).__name__} is not a dataclass entity")
        payload = _json_safe(asdict(self))
        payload.setdefault("uuid", str(self.entity_id()))
        return payload

    @classmethod
    def _table(cls) -> sql.Identifier:
        if cls.TABLE_NAME is None:
            raise NotImplementedError(f"{cls.__name__} does not define TABLE_NAME")
        return sql.Identifier(cls.TABLE_NAME)

    @classmethod
    def _id_columns(cls) -> tuple[str, ...]:
        if cls.ID_COLUMNS:
            return cls.ID_COLUMNS
        if cls.ID_COLUMN is None:
            raise NotImplementedError(f"{cls.__name__} does not define ID_COLUMN or ID_COLUMNS")
        return (cls.ID_COLUMN,)

    @classmethod
    def _select_columns_sql(cls) -> sql.SQL:
        if not cls.COLUMNS:
            return sql.SQL("*")
        return sql.SQL(", ").join(sql.Identifier(column) for column in cls.COLUMNS)

    @classmethod
    def _row_to_dict(cls, cursor: psycopg.Cursor, row: tuple[Any, ...] | Mapping[str, Any]) -> dict[str, Any]:
        if isinstance(row, Mapping):
            return dict(row)
        return {
            column.name: row[index]
            for index, column in enumerate(cursor.description or ())
        }

    @classmethod
    def _normalize_id(cls, entity_id: Any) -> dict[str, Any]:
        columns = cls._id_columns()
        if isinstance(entity_id, Mapping):
            missing = [column for column in columns if column not in entity_id]
            if missing:
                raise ValueError(f"missing id columns for {cls.__name__}: {missing}")
            return {column: entity_id[column] for column in columns}
        if len(columns) != 1:
            raise ValueError(f"{cls.__name__} requires a mapping id with columns {columns}")
        return {columns[0]: entity_id}

    @classmethod
    def _predicate_sql(cls, values: Mapping[str, Any]) -> tuple[sql.SQL, list[Any]]:
        clauses: list[sql.Composable] = []
        params: list[Any] = []
        for column, value in values.items():
            if value is None:
                clauses.append(sql.SQL("{} IS NULL").format(sql.Identifier(column)))
            else:
                clauses.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
                params.append(value)
        return sql.SQL(" AND ").join(clauses), params

    @classmethod
    def _filter_sql(cls, filters: Mapping[str, Any] | None) -> tuple[list[sql.Composable], list[Any]]:
        clauses: list[sql.Composable] = []
        params: list[Any] = []
        for column, value in (filters or {}).items():
            if value is None:
                clauses.append(sql.SQL("{} IS NULL").format(sql.Identifier(column)))
            elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
                items = list(value)
                if not items:
                    clauses.append(sql.SQL("FALSE"))
                else:
                    clauses.append(sql.SQL("{} = ANY(%s)").format(sql.Identifier(column)))
                    params.append(items)
            else:
                clauses.append(sql.SQL("{} = %s").format(sql.Identifier(column)))
                params.append(value)
        return clauses, params

    @classmethod
    def crud_get(
        cls,
        conn: psycopg.Connection,
        entity_id: Any,
        *,
        include_deleted: bool = True,
    ) -> dict[str, Any] | None:
        id_values = cls._normalize_id(entity_id)
        id_predicate, params = cls._predicate_sql(id_values)
        clauses: list[sql.Composable] = [id_predicate]
        if not include_deleted and cls.SOFT_DELETE_COLUMN is not None:
            clauses.append(sql.SQL("{} IS NULL").format(sql.Identifier(cls.SOFT_DELETE_COLUMN)))
        query = sql.SQL("SELECT {} FROM {} WHERE {}").format(
            cls._select_columns_sql(),
            cls._table(),
            sql.SQL(" AND ").join(clauses),
        )
        cur = conn.execute(query, params)
        row = cur.fetchone()
        return None if row is None else cls._row_to_dict(cur, row)

    @classmethod
    def get_by_id(
        cls,
        conn: psycopg.Connection,
        entity_id: Any,
        *,
        include_deleted: bool = True,
    ) -> dict[str, Any] | None:
        return cls.crud_get(conn, entity_id, include_deleted=include_deleted)

    @classmethod
    def crud_list(
        cls,
        conn: psycopg.Connection,
        *,
        filters: Mapping[str, Any] | None = None,
        include_deleted: bool = False,
        order_by: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses, params = cls._filter_sql(filters)
        if not include_deleted and cls.SOFT_DELETE_COLUMN is not None:
            clauses.append(sql.SQL("{} IS NULL").format(sql.Identifier(cls.SOFT_DELETE_COLUMN)))
        where = sql.SQL("")
        if clauses:
            where = sql.SQL(" WHERE {}").format(sql.SQL(" AND ").join(clauses))
        order = sql.SQL("")
        if order_by:
            order = sql.SQL(" ORDER BY {}").format(
                sql.SQL(", ").join(sql.Identifier(column) for column in order_by)
            )
        paging = sql.SQL("")
        if limit is not None:
            paging += sql.SQL(" LIMIT %s")
            params.append(limit)
        if offset is not None:
            paging += sql.SQL(" OFFSET %s")
            params.append(offset)
        query = sql.SQL("SELECT {} FROM {}{}{}{}").format(
            cls._select_columns_sql(),
            cls._table(),
            where,
            order,
            paging,
        )
        cur = conn.execute(query, params)
        return [cls._row_to_dict(cur, row) for row in cur.fetchall()]

    @classmethod
    def _search_sql(
        cls, search: str | None, search_regex: str | None
    ) -> tuple[sql.Composable | None, list[Any]]:
        """Build the content-search predicate group over declared SEARCH_COLUMNS.

        One predicate per declared column, OR-ed together, so a hit in any
        searchable column matches. The caller ANDs the group with the uniform
        attribute filters.

        ``search`` wins when both are given: substring is the cheaper, more
        predictable mode, and silently running a regex the caller did not
        prioritize would be worse than ignoring it.

        Returns:
            (predicate, params), or (None, []) when neither mode is requested.

        Raises:
            ValueError: when a search is requested and the entity declares no
                SEARCH_COLUMNS. Returning every row unfiltered would look like
                "no text matched" while actually meaning "this entity cannot
                search", which is the more dangerous of the two.
        """
        if search is None and search_regex is None:
            return None, []
        if not cls.SEARCH_COLUMNS:
            raise ValueError(
                f"Entity {cls.__name__} does not declare SEARCH_COLUMNS; search not available"
            )
        if search is not None:
            operator, value = sql.SQL("ILIKE"), f"%{search}%"
        else:
            operator, value = sql.SQL("~*"), search_regex
        predicates = [
            sql.SQL("{} {} %s").format(sql.Identifier(column), operator)
            for column in cls.SEARCH_COLUMNS
        ]
        return (
            sql.SQL("({})").format(sql.SQL(" OR ").join(predicates)),
            [value] * len(predicates),
        )

    @staticmethod
    def _snippet(text: str, needle: str, *, window: int = 25) -> str:
        """A bounded excerpt around the first match, with an ellipsis marker."""
        lowered, target = text.lower(), needle.lower()
        position = lowered.find(target)
        if position < 0:
            position = 0
        start = max(0, position - window)
        end = min(len(text), position + len(needle) + window)
        excerpt = text[start:end]
        if start > 0:
            excerpt = f"...{excerpt}"
        if end < len(text):
            excerpt = f"{excerpt}..."
        return excerpt

    @classmethod
    def _annotate_match(cls, row: dict[str, Any], search: str | None) -> dict[str, Any]:
        """Add matched_column and snippet so a hit carries its provenance.

        Without this a caller receives a row and cannot tell which of several
        searchable columns matched. The matched column is the first declared
        SEARCH_COLUMN whose value contains the needle; for a regex search the
        needle is unknown to Python, so the first non-empty searchable column
        is reported and the snippet is its leading window.
        """
        matched_column: str | None = None
        snippet: str | None = None
        for column in cls.SEARCH_COLUMNS:
            value = row.get(column)
            if not isinstance(value, str) or not value:
                continue
            if search is None:
                matched_column, snippet = column, cls._snippet(value, "")
                break
            if search.lower() in value.lower():
                matched_column, snippet = column, cls._snippet(value, search)
                break
        annotated = dict(row)
        annotated["matched_column"] = matched_column
        annotated["snippet"] = snippet
        return annotated

    @classmethod
    def crud_search(
        cls,
        conn: psycopg.Connection,
        *,
        filters: Mapping[str, Any] | None = None,
        include_deleted: bool = False,
        order_by: Sequence[str] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        search: str | None = None,
        search_regex: str | None = None,
    ) -> list[dict[str, Any]]:
        """List rows, optionally narrowed by content search over SEARCH_COLUMNS.

        With neither ``search`` nor ``search_regex`` this behaves exactly like
        ``crud_list``, which keeps every existing caller working unchanged.

        ``search`` matches a substring case-insensitively (ILIKE); the caller's
        value is escaped as a bind parameter, never interpolated.
        ``search_regex`` matches a POSIX regular expression case-insensitively
        (``~*``). Either mode composes with ``filters`` by AND.

        Every returned row additionally carries ``matched_column`` and
        ``snippet``.
        """
        search_predicate, search_params = cls._search_sql(search, search_regex)
        if search_predicate is None:
            return cls.crud_list(
                conn,
                filters=filters,
                include_deleted=include_deleted,
                order_by=order_by,
                limit=limit,
                offset=offset,
            )

        clauses, params = cls._filter_sql(filters)
        clauses.append(search_predicate)
        params.extend(search_params)
        if not include_deleted and cls.SOFT_DELETE_COLUMN is not None:
            clauses.append(sql.SQL("{} IS NULL").format(sql.Identifier(cls.SOFT_DELETE_COLUMN)))
        order = sql.SQL("")
        if order_by:
            order = sql.SQL(" ORDER BY {}").format(
                sql.SQL(", ").join(sql.Identifier(column) for column in order_by)
            )
        paging = sql.SQL("")
        if limit is not None:
            paging += sql.SQL(" LIMIT %s")
            params.append(limit)
        if offset is not None:
            paging += sql.SQL(" OFFSET %s")
            params.append(offset)
        query = sql.SQL("SELECT {} FROM {} WHERE {}{}{}").format(
            cls._select_columns_sql(),
            cls._table(),
            sql.SQL(" AND ").join(clauses),
            order,
            paging,
        )
        cur = conn.execute(query, params)
        return [
            cls._annotate_match(cls._row_to_dict(cur, row), search) for row in cur.fetchall()
        ]

    @classmethod
    def crud_create(
        cls,
        conn: psycopg.Connection,
        values: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> dict[str, Any] | None:
        allowed = set(cls.INSERT_COLUMNS or values.keys())
        extra = set(values) - allowed
        if extra:
            raise ValueError(f"unknown insert columns for {cls.__name__}: {sorted(extra)}")
        columns = tuple(values.keys())
        if not columns:
            raise ValueError("create values must not be empty")
        # Identity registry participation, in three parts.
        #
        # The availability check runs BEFORE the INSERT and the registration
        # AFTER it, both inside the caller's transaction. That ordering is the
        # whole point: a duplicate identifier is refused before any row is
        # written, so the create leaves no partial row, and the registry row is
        # only created once the entity row it describes actually exists. If
        # either call raises, the surrounding transaction rolls back the INSERT
        # with it; nothing here commits.
        #
        # EXCLUDED_TABLES short-circuits both calls for the tables documented
        # as deliberately outside the registry.
        registers_identity = (
            cls.REGISTER_IDENTITY
            and cls.ID_COLUMN is not None
            and cls.ID_COLUMN in values
            and isinstance(values.get(cls.ID_COLUMN), uuid.UUID)
            and cls.TABLE_NAME is not None
            and cls.TABLE_NAME not in EXCLUDED_TABLES
        )
        if registers_identity:
            ensure_identity_available(conn, values[cls.ID_COLUMN])
        query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            cls._table(),
            sql.SQL(", ").join(sql.Identifier(column) for column in columns),
            sql.SQL(", ").join(sql.Placeholder() for _ in columns),
        )
        if returning:
            query += sql.SQL(" RETURNING {}").format(cls._select_columns_sql())
        cur = conn.execute(query, [values[column] for column in columns])
        if registers_identity:
            register_entity_identity(
                conn,
                entity_id=values[cls.ID_COLUMN],
                table_name=cls.TABLE_NAME,
                entity_type=cls.entity_type(),
            )
        if not returning:
            return None
        row = cur.fetchone()
        return None if row is None else cls._row_to_dict(cur, row)

    @classmethod
    def crud_update(
        cls,
        conn: psycopg.Connection,
        entity_id: Any,
        values: Mapping[str, Any],
        *,
        returning: bool = True,
    ) -> dict[str, Any] | None:
        allowed = set(cls.UPDATE_COLUMNS or values.keys())
        extra = set(values) - allowed
        if extra:
            raise ValueError(f"unknown update columns for {cls.__name__}: {sorted(extra)}")
        if not values:
            raise ValueError("update values must not be empty")
        id_values = cls._normalize_id(entity_id)
        id_predicate, params = cls._predicate_sql(id_values)
        columns = tuple(values.keys())
        query = sql.SQL("UPDATE {} SET {} WHERE {}").format(
            cls._table(),
            sql.SQL(", ").join(
                sql.SQL("{} = %s").format(sql.Identifier(column))
                for column in columns
            ),
            id_predicate,
        )
        if returning:
            query += sql.SQL(" RETURNING {}").format(cls._select_columns_sql())
        cur = conn.execute(query, [values[column] for column in columns] + params)
        if not returning:
            return None
        row = cur.fetchone()
        return None if row is None else cls._row_to_dict(cur, row)

    @classmethod
    def crud_soft_delete(
        cls,
        conn: psycopg.Connection,
        entity_id: Any,
        *,
        deleted_at: datetime | None = None,
        updated_at: datetime | None = None,
        returning: bool = True,
    ) -> dict[str, Any] | None:
        return soft_delete_entity(
            cls,
            conn,
            entity_id,
            deleted_at=deleted_at,
            updated_at=updated_at,
            returning=returning,
        )

    @classmethod
    def crud_delete(
        cls,
        conn: psycopg.Connection,
        entity_id: Any,
        *,
        deleted_at: datetime | None = None,
        updated_at: datetime | None = None,
        returning: bool = True,
    ) -> dict[str, Any] | None:
        """Mark one entity for deletion; physical purge is batch-only."""
        return soft_delete_entity(
            cls,
            conn,
            entity_id,
            deleted_at=deleted_at,
            updated_at=updated_at,
            returning=returning,
        )

    @classmethod
    def crud_reference_counts(cls, conn: psycopg.Connection, entity_id: Any) -> dict[str, int]:
        return find_entity_reference_counts(conn, cls, entity_id)

    @classmethod
    def crud_resolve_identity(cls, conn: psycopg.Connection, entity_id: uuid.UUID) -> dict[str, Any]:
        return resolve_entity_identity(conn, entity_id)

    @classmethod
    def _foreign_key_reference_checks(
        cls,
        conn: psycopg.Connection,
        id_values: Mapping[str, Any],
    ) -> tuple[ReferenceCheck, ...]:
        if cls.TABLE_NAME is None:
            return ()
        rows = conn.execute(
            """
            SELECT
                kcu.table_name AS referencing_table,
                kcu.column_name AS referencing_column,
                ccu.column_name AS referenced_column
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_schema = kcu.constraint_schema
             AND tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
              ON ccu.constraint_schema = tc.constraint_schema
             AND ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND ccu.table_name = %s
              AND ccu.column_name = ANY(%s)
            ORDER BY kcu.table_name, kcu.column_name
            """,
            (cls.TABLE_NAME, list(id_values)),
        ).fetchall()
        return tuple(
            ReferenceCheck(
                table=row[0],
                column=row[1],
                source_column=row[2],
            )
            for row in rows
        )

    @classmethod
    def crud_hard_delete(
        cls,
        conn: psycopg.Connection,
        entity_id: Any,
        *,
        returning: bool = True,
        require_soft_deleted: bool = True,
        changed_by: str = "system",
        plan_uuid: Any = None,
        audit_entity_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Physically delete one already-soft-deleted row.

        This is a low-level helper for ``crud_purge_soft_deleted_batch``. Normal
        callers should use ``crud_delete``/``crud_soft_delete``.
        """
        return hard_delete_entity(
            cls,
            conn,
            entity_id,
            returning=returning,
            require_soft_deleted=require_soft_deleted,
            changed_by=changed_by,
            plan_uuid=plan_uuid,
            audit_entity_type=audit_entity_type,
        )

    @classmethod
    def crud_purge_soft_deleted_batch(
        cls,
        conn: psycopg.Connection,
        *,
        limit: int = 1000,
    ) -> dict[str, list[dict[str, Any]]]:
        return purge_soft_deleted_batch(conn, cls, limit=limit)


def find_entity_reference_counts(
    conn: psycopg.Connection,
    entity_cls: type[DataclassEntity],
    entity_id: Any,
) -> dict[str, int]:
    """Count inbound references that would block physical purge.

    Delegates to the guard's lookup surface and folds its referrer list into the
    historical per-column counts, so the return type is unchanged for callers
    that only need to know whether anything blocks.

    TABLE_NAME is passed, never _table(): that helper returns a composed SQL
    identifier, while the catalog is keyed by plain table-name strings. Handing
    it the identifier would match no catalog entry and silently report zero
    referrers, turning the guard into a no-op.
    """
    from plan_manager.storage.hard_delete_guard import lookup_referrers

    counts: dict[str, int] = {}
    for referrer in lookup_referrers(conn, entity_cls.TABLE_NAME, entity_id):
        key = f"{referrer['table']}.{referrer['column']}"
        counts[key] = counts.get(key, 0) + 1
    return counts


def soft_delete_entity(
    entity_cls: type[DataclassEntity],
    conn: psycopg.Connection,
    entity_id: Any,
    *,
    deleted_at: datetime | None = None,
    updated_at: datetime | None = None,
    returning: bool = True,
) -> dict[str, Any] | None:
    """Centrally mark one entity row for later batch purge."""
    if entity_cls.SOFT_DELETE_COLUMN is None:
        raise NotImplementedError(f"{entity_cls.__name__} does not support soft delete")
    now = datetime.now(timezone.utc)
    values: dict[str, Any] = {entity_cls.SOFT_DELETE_COLUMN: deleted_at or now}
    if entity_cls.UPDATED_AT_COLUMN is not None:
        values[entity_cls.UPDATED_AT_COLUMN] = updated_at or now
    return entity_cls.crud_update(conn, entity_id, values, returning=returning)


def hard_delete_entity(
    entity_cls: type[DataclassEntity],
    conn: psycopg.Connection,
    entity_id: Any,
    *,
    returning: bool = True,
    require_soft_deleted: bool = True,
    changed_by: str = "system",
    plan_uuid: Any = None,
    audit_entity_type: str | None = None,
) -> dict[str, Any] | None:
    """Centrally perform physical deletion for one already-soft-deleted row.

    The admission check, the DELETE and the audit record all live in
    plan_manager.storage.hard_delete_guard now. This function stays as the
    entity-layer entry point so no caller changes; changed_by is an additive
    defaulted keyword so a caller that knows the actor can name it in the audit
    trail, and every existing caller keeps working untouched.
    """
    # Function-level import by construction: the guard imports this module's
    # error types, so a module-level import here would close the cycle.
    from plan_manager.storage.hard_delete_guard import guarded_hard_delete

    return guarded_hard_delete(
        conn,
        entity_cls,
        entity_id,
        changed_by=changed_by,
        returning=returning,
        require_soft_deleted=require_soft_deleted,
        plan_uuid=plan_uuid,
        audit_entity_type=audit_entity_type,
    )


def purge_soft_deleted_batch(
    conn: psycopg.Connection,
    entity_cls: type[DataclassEntity],
    *,
    limit: int = 1000,
) -> dict[str, list[dict[str, Any]]]:
    """Centrally purge a batch of rows that were already marked deleted."""
    if entity_cls.SOFT_DELETE_COLUMN is None:
        raise NotImplementedError(f"{entity_cls.__name__} does not support soft-delete purge")
    id_columns = entity_cls._id_columns()
    query = sql.SQL("SELECT {} FROM {} WHERE {} IS NOT NULL ORDER BY {} LIMIT %s").format(
        sql.SQL(", ").join(sql.Identifier(column) for column in id_columns),
        entity_cls._table(),
        sql.Identifier(entity_cls.SOFT_DELETE_COLUMN),
        sql.Identifier(entity_cls.SOFT_DELETE_COLUMN),
    )
    rows = conn.execute(query, (limit,)).fetchall()
    deleted: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for row in rows:
        entity_id: Any
        if len(id_columns) == 1:
            entity_id = row[0]
            id_payload = {id_columns[0]: row[0]}
        else:
            id_payload = {column: row[index] for index, column in enumerate(id_columns)}
            entity_id = id_payload
        try:
            removed = hard_delete_entity(
                entity_cls,
                conn,
                entity_id,
                returning=True,
                require_soft_deleted=True,
            )
        except EntityReferencedError as exc:
            refused.append({"id": _json_safe(id_payload), "references": dict(exc.references)})
            continue
        if removed is not None:
            deleted.append(removed)
    return {"deleted": deleted, "refused": refused}
