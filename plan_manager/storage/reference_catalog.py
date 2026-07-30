"""Central catalog of every inter-entity reference (C-010).

One declaration site for both kinds of reference:

* FK-backed references, which the database itself enforces. They are listed
  here anyway, because :func:`validate_catalog_against_schema` diffs the
  catalog against ``information_schema`` and a foreign key missing from the
  catalog is reported as a defect rather than tolerated as an exemption.
* Plain, non-FK reference columns. These are the majority: 28 of the 43 tables
  declare no foreign key at all, so almost every runtime-overlay and
  agent-configuration reference is a bare uuid column that only a declaration
  like this one can see.

The catalog replaces two mechanisms that had drifted apart — the
``CENTRAL_REFERENCE_CHECKS`` dict in :mod:`plan_manager.domain.entity` and the
per-entity ``HARD_DELETE_REFERENCE_CHECKS`` class attributes, which declared six
entity kinds twice with identical tuples.

TARGET-COLUMN CAVEAT, the reason ``target_column`` is spelled out on every
entry instead of being defaulted. For bug_report, bug_impact, bug_fix,
execution_attempt, review_result and todo_item the real primary-key column is
literally ``uuid``, while the dataclass field is named ``bug_uuid``,
``fix_uuid``, ``attempt_uuid``, ``review_uuid`` or ``todo_uuid``. Resolving the
target column from the dataclass field produced bug e52daeab (cited in
bug_report.py, bug_impact.py, bug_fix.py, execution_attempt.py,
review_result.py) and bug 113a7888 for todo_item (cited in todo.py). Writing the
DB column explicitly makes that class of mistake impossible here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import psycopg

BLOCKS_HARD_DELETE = "blocks_hard_delete"
"""The referrer must be detached or removed before the target can be deleted."""

CASCADES = "cascades"
"""The database removes the referrer automatically via ON DELETE CASCADE.

Such a reference must NOT block a hard delete. Classifying it as blocking would
refuse deletions the database performs happily today — a plan delete cascades
to its paragraphs, concepts, relations and steps.
"""


@dataclass(frozen=True)
class CatalogEntry:
    """One inbound reference: who points at whom, and what that implies."""

    source_table: str
    source_column: str
    target_table: str
    target_column: str = "uuid"
    blocking: str = BLOCKS_HARD_DELETE
    target_entity_type: str | None = None
    fk_backed: bool = False
    on_delete: str | None = None
    scope_columns: tuple[tuple[str, str], ...] = ()
    array: bool = False
    live_column: str | None = None
    const_filters: tuple[tuple[str, str], ...] = field(default=())


def _entries(*entries: CatalogEntry) -> dict[tuple[str, str], CatalogEntry]:
    """Index entries by (source_table, source_column), refusing a duplicate.

    A duplicate key would silently drop one reference from every guard that
    consumes this catalog, so it fails at import time instead.
    """
    catalog: dict[tuple[str, str], CatalogEntry] = {}
    for entry in entries:
        key = (entry.source_table, entry.source_column)
        if key in catalog:
            raise ValueError(f"duplicate catalog entry for {key}")
        catalog[key] = entry
    return catalog


_LIVE = "deleted_at"

REFERENCE_CATALOG: dict[tuple[str, str], CatalogEntry] = _entries(
    # ---- references to plan -------------------------------------------------
    # FK-backed and cascading: the database removes these with the plan.
    CatalogEntry("paragraph", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("concept", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("relation", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("step", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("node_version", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("revision", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("ref", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("cascade", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("cascade_request", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("context_block", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("srt_snapshot", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("runtime_audit_log", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("step_runtime", "plan_uuid", "plan", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    # Plain references: nothing removes these, so they block.
    CatalogEntry("todo_item", "anchor_plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("model_binding", "plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("runtime_comment", "anchor_plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("execution_attempt", "plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("escalation", "anchor_plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("bug_report", "source_plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("bug_impact", "target_plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("bug_fix_propagation", "linked_plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("invocation_profile", "plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("step_assignment", "plan_uuid", "plan", live_column=_LIVE),
    CatalogEntry("answer_envelope", "anchor_plan_uuid", "plan", live_column=_LIVE),
    # ---- references to revision ---------------------------------------------
    CatalogEntry("plan", "head_revision_uuid", "revision", fk_backed=True, on_delete="NO ACTION"),
    CatalogEntry("revision", "parent_uuid", "revision", fk_backed=True, on_delete="NO ACTION"),
    CatalogEntry("ref", "revision_uuid", "revision", fk_backed=True, on_delete="NO ACTION"),
    CatalogEntry("cascade", "base_revision_uuid", "revision", fk_backed=True, on_delete="NO ACTION"),
    CatalogEntry("cascade_request", "revision_uuid", "revision", fk_backed=True, on_delete="NO ACTION"),
    CatalogEntry("context_block", "revision_uuid", "revision", fk_backed=True, on_delete="NO ACTION"),
    CatalogEntry("srt_snapshot", "revision_uuid", "revision", fk_backed=True, on_delete="NO ACTION"),
    # ---- references to step -------------------------------------------------
    CatalogEntry("step_runtime", "step_uuid", "step", blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("step", "parent_step_uuid", "step"),
    CatalogEntry("node_version", "entity_uuid", "step"),
    CatalogEntry("todo_item", "anchor_step_uuid", "step", live_column=_LIVE),
    CatalogEntry("model_binding", "branch_step_uuid", "step", live_column=_LIVE),
    CatalogEntry("model_binding", "step_uuid", "step", live_column=_LIVE),
    CatalogEntry("runtime_comment", "anchor_step_uuid", "step", live_column=_LIVE),
    CatalogEntry("execution_attempt", "step_uuid", "step", live_column=_LIVE),
    CatalogEntry("escalation", "anchor_step_uuid", "step", live_column=_LIVE),
    CatalogEntry("bug_report", "source_step_uuid", "step", live_column=_LIVE),
    CatalogEntry("bug_impact", "target_step_uuid", "step", live_column=_LIVE),
    # ---- references to concept (scoped by plan, keyed by concept_id) --------
    CatalogEntry("relation", "from_concept", "concept", target_column="concept_id",
                 scope_columns=(("plan_uuid", "plan_uuid"),)),
    CatalogEntry("relation", "to_concept", "concept", target_column="concept_id",
                 scope_columns=(("plan_uuid", "plan_uuid"),)),
    CatalogEntry("step", "concepts", "concept", target_column="concept_id",
                 scope_columns=(("plan_uuid", "plan_uuid"),), array=True),
    # ---- references to todo_item (ENTITY_TYPE 'todo'; bug 113a7888) ---------
    CatalogEntry("todo_link", "from_todo_uuid", "todo_item", target_entity_type="todo",
                 blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("todo_link", "to_todo_uuid", "todo_item", target_entity_type="todo",
                 blocking=CASCADES, fk_backed=True, on_delete="CASCADE"),
    CatalogEntry("execution_attempt", "todo_uuid", "todo_item", target_entity_type="todo",
                 live_column=_LIVE),
    CatalogEntry("bug_fix_propagation", "linked_todo_uuid", "todo_item", target_entity_type="todo",
                 live_column=_LIVE),
    # ---- references to runtime_comment (ENTITY_TYPE 'comment') -------------
    CatalogEntry("runtime_comment", "supersedes_comment_uuid", "runtime_comment",
                 target_entity_type="comment", live_column=_LIVE),
    # ---- polymorphic anchor_ref_id, discriminated by primary_anchor_type ----
    # The same column points at a different table per discriminator value, so
    # each target gets its own entry keyed by the const filter that selects it.
    CatalogEntry("runtime_comment", "anchor_ref_id", "todo_item", target_entity_type="todo",
                 live_column=_LIVE, const_filters=(("primary_anchor_type", "todo"),)),
    CatalogEntry("escalation", "anchor_ref_id", "todo_item", target_entity_type="todo",
                 live_column=_LIVE, const_filters=(("primary_anchor_type", "todo"),)),
    # ---- references to execution_attempt (bug e52daeab) --------------------
    CatalogEntry("review_result", "reviewed_attempt_uuid", "execution_attempt", live_column=_LIVE),
    CatalogEntry("execution_attempt", "parent_attempt_uuid", "execution_attempt", live_column=_LIVE),
    CatalogEntry("answer_envelope", "attempt_uuid", "execution_attempt", live_column=_LIVE),
    # ---- references to review_result (bug e52daeab) ------------------------
    CatalogEntry("runtime_audit_log", "linked_review_id", "review_result"),
    CatalogEntry("runtime_audit_log", "linked_attempt_id", "execution_attempt"),
    # ---- references to bug_report (ENTITY_TYPE 'bug'; bug e52daeab) --------
    CatalogEntry("bug_report", "duplicate_of_uuid", "bug_report", target_entity_type="bug",
                 live_column=_LIVE),
    CatalogEntry("bug_report", "parent_bug_uuid", "bug_report", target_entity_type="bug",
                 live_column=_LIVE),
    CatalogEntry("bug_impact", "bug_uuid", "bug_report", target_entity_type="bug", live_column=_LIVE),
    CatalogEntry("bug_fix", "bug_uuid", "bug_report", target_entity_type="bug", live_column=_LIVE),
    # ---- references to bug_impact / bug_fix (bug e52daeab) ------------------
    CatalogEntry("bug_fix_propagation", "impact_uuid", "bug_impact", live_column=_LIVE),
    CatalogEntry("bug_fix_propagation", "bug_fix_uuid", "bug_fix", live_column=_LIVE),
    CatalogEntry("execution_attempt", "bug_fix_uuid", "bug_fix", live_column=_LIVE),
    # ---- references to wish_item (ENTITY_TYPE 'wish') ----------------------
    CatalogEntry("calendar_entry", "wish_uuid", "wish_item", target_entity_type="wish",
                 live_column=_LIVE),
    # ---- agent configuration ----------------------------------------------
    CatalogEntry("model", "provider_uuid", "provider", live_column=_LIVE),
    CatalogEntry("toolset_membership", "tool_uuid", "tool", live_column=_LIVE),
    CatalogEntry("toolset_membership", "toolset_uuid", "toolset", live_column=_LIVE),
    CatalogEntry("step_assignment", "toolset_uuid", "toolset", live_column=_LIVE),
    # ---- derived stores ----------------------------------------------------
    CatalogEntry("context_block", "common_block_uuid", "context_block", fk_backed=True,
                 on_delete="NO ACTION"),
    CatalogEntry("context_block", "cascade_uuid", "cascade", fk_backed=True, on_delete="NO ACTION"),
)


def entries_targeting(table: str) -> tuple[CatalogEntry, ...]:
    """Every inbound reference to one table, blocking or cascading alike.

    The ``table`` argument is a real DB table name. Callers holding a
    user-facing entity type convert it first with
    :func:`table_name_for_entity_type`.
    """
    return tuple(entry for entry in REFERENCE_CATALOG.values() if entry.target_table == table)


def blocking_entries_targeting(table: str) -> tuple[CatalogEntry, ...]:
    """Only the inbound references that must refuse a hard delete."""
    return tuple(entry for entry in entries_targeting(table) if entry.blocking == BLOCKS_HARD_DELETE)


_FK_QUERY = """
SELECT
    tc.table_name        AS source_table,
    kcu.column_name      AS source_column,
    ccu.table_name       AS target_table,
    ccu.column_name      AS target_column
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
    ON tc.constraint_name = kcu.constraint_name
   AND tc.table_schema = kcu.table_schema
JOIN information_schema.constraint_column_usage AS ccu
    ON ccu.constraint_name = tc.constraint_name
   AND ccu.table_schema = tc.table_schema
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = current_schema()
"""


def validate_catalog_against_schema(conn: psycopg.Connection) -> tuple[list[str], list[str]]:
    """Diff the static catalog against the live foreign-key inventory.

    Returns:
        (missing_from_catalog, extra_in_catalog). The first lists live foreign
        keys this catalog does not declare; the second lists catalog entries
        marked ``fk_backed`` that the database does not actually enforce, which
        is just as much a defect because a guard would trust the database to
        cascade something it will not.

    Raises:
        ValueError: when a live foreign key is absent from the catalog. A
            reference column the catalog cannot see is invisible to every guard
            built on it, so this is a failure and not a warning.
    """
    rows = conn.execute(_FK_QUERY).fetchall()
    live = {(row[0], row[1]): (row[2], row[3]) for row in rows}

    missing = [
        f"{source}.{column} -> {target}.{target_column}"
        for (source, column), (target, target_column) in sorted(live.items())
        if (source, column) not in REFERENCE_CATALOG
    ]
    extra = [
        f"{entry.source_table}.{entry.source_column} -> {entry.target_table}.{entry.target_column}"
        for entry in REFERENCE_CATALOG.values()
        if entry.fk_backed and (entry.source_table, entry.source_column) not in live
    ]
    if missing:
        raise ValueError(
            "foreign keys absent from REFERENCE_CATALOG: " + ", ".join(missing)
        )
    return missing, extra


EXTERNAL_IDENTIFIER_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        # External project UUIDs. Projects are supplied by outside systems and
        # are deliberately NOT local rows, so there is nothing in this database
        # for these columns to reference and nothing a deletion could orphan.
        # Cataloguing them would make the guard probe a table that does not exist.
        ("bug_fix", "source_project_id"),
        ("bug_impact", "target_project_id"),
        ("bug_report", "source_project_id"),
        ("calendar_entry", "anchor_project_id"),
        ("escalation", "anchor_project_id"),
        ("project_dependency", "dependent_project_id"),
        ("project_dependency", "depends_on_project_id"),
        ("runtime_comment", "anchor_project_id"),
        ("todo_item", "anchor_project_id"),
        ("wish_item", "anchor_project_id"),
    }
)
"""uuid columns holding identifiers of things that are NOT rows of this database.

Membership is a documented decision, not an oversight: an external identifier has
no local target, so it can neither block a deletion nor be orphaned by one.
"""

UNCLASSIFIED_REFERENCE_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {
        # Bug f7b9cebf. Each of these is a uuid column of a registered table that
        # is NOT in REFERENCE_CATALOG and is NOT an external identifier, so
        # lookup_referrers issues no probe for it and a deletion referenced only
        # through it is admitted. Measured 2026-07-30 against shipped 0.1.90:
        # 113 uuid columns in registered tables, 66 catalogued, 10 external,
        # these 37 unclassified.
        #
        # THIS LIST ONLY SHRINKS. A column leaves it by being catalogued with its
        # blocking/on_delete/discriminator metadata, or by being exempted with a
        # written reason. Nothing may be added without classifying it, and the
        # accompanying tests refuse both a stale entry and one already resolved.
        #
        # Classification is not mechanical: each column needs a decision on
        # whether the reference blocks a hard delete or cascades, what the
        # discriminator is for a polymorphic column, and whether it is nullable
        # and therefore clearable. That work is the first goal of the successor
        # plan, not a mechanical sweep.
        ("answer_envelope", "anchor_step_uuid"),
        ("bug_fix_propagation", "linked_cascade_uuid"),
        ("bug_impact", "target_ref_id"),
        ("bug_impact", "target_revision_uuid"),
        ("bug_report", "source_ref_id"),
        ("bug_report", "source_revision_uuid"),
        ("calendar_entry", "anchor_plan_uuid"),
        ("calendar_entry", "anchor_ref_id"),
        ("calendar_entry", "anchor_revision_uuid"),
        ("calendar_entry", "anchor_step_uuid"),
        ("cascade_request", "origin_id"),
        ("escalation", "anchor_revision_uuid"),
        ("escalation", "chain_root_uuid"),
        ("escalation", "forwarded_from_uuid"),
        ("execution_attempt", "assigned_binding_uuid"),
        ("execution_attempt", "revision_uuid"),
        ("invocation_profile", "branch_step_uuid"),
        ("invocation_profile", "dialogue_chain_ref"),
        ("invocation_profile", "revision_uuid"),
        ("invocation_profile", "step_uuid"),
        ("model_binding", "revision_uuid"),
        ("review_result", "escalation_target_uuid"),
        ("review_result", "reviewed_revision_uuid"),
        ("revision", "node_version_uuids"),
        ("runtime_audit_log", "entity_id"),
        ("runtime_comment", "anchor_revision_uuid"),
        ("runtime_link", "from_entity_uuid"),
        ("runtime_link", "to_entity_uuid"),
        ("step_assignment", "branch_step_uuid"),
        ("step_assignment", "revision_uuid"),
        ("step_assignment", "step_uuid"),
        ("todo_item", "anchor_ref_id"),
        ("todo_item", "anchor_revision_uuid"),
        ("wish_item", "anchor_plan_uuid"),
        ("wish_item", "anchor_ref_id"),
        ("wish_item", "anchor_revision_uuid"),
        ("wish_item", "anchor_step_uuid"),
    }
)
"""uuid reference columns awaiting classification (bug f7b9cebf). Shrinks only."""


def _entity_classes() -> list[type]:
    """Every table-backed DataclassEntity subclass, discovered once per call.

    One walk shared by every consumer below, so the resolver and the type
    enumerations cannot disagree about what exists.
    """
    # Imported lazily: this module must stay free of import cycles and must not
    # touch a database at import time.
    import importlib
    import pkgutil

    from plan_manager.domain.entity import DataclassEntity

    import plan_manager.domain as domain_package

    for module in pkgutil.iter_modules(domain_package.__path__):
        importlib.import_module(f"{domain_package.__name__}.{module.name}")

    def walk(root: type) -> list[type]:
        found: list[type] = []
        for subclass in root.__subclasses__():
            found.append(subclass)
            found.extend(walk(subclass))
        return found

    return [
        subclass
        for subclass in walk(DataclassEntity)
        if getattr(subclass, "ENTITY_TYPE", None) and getattr(subclass, "TABLE_NAME", None)
    ]


def known_entity_types() -> list[str]:
    """Sorted user-facing entity types that resolve_entity_class accepts."""
    return sorted({subclass.ENTITY_TYPE for subclass in _entity_classes()})


def purge_capable_entity_types() -> list[str]:
    """Sorted entity types whose class declares a soft-delete column.

    An entity with SOFT_DELETE_COLUMN=None (concept, relation, step) cannot take
    part in a two-phase purge at all, so it must never appear in a purge command's
    enum. Derived from the live registry rather than a hand-kept list, so a new
    entity is admitted or excluded by its own declaration.
    """
    return sorted(
        {
            subclass.ENTITY_TYPE
            for subclass in _entity_classes()
            if getattr(subclass, "SOFT_DELETE_COLUMN", None) is not None
        }
    )


def resolve_entity_class(entity_type: str) -> type:
    """Resolve a user-facing entity type to its DataclassEntity subclass.

    The single sanctioned resolution mechanism for this goal. Every consumer
    uses it so that two commands cannot drift into two different answers for
    the same entity type.

    Raises:
        ValueError: when no subclass claims the type, or when two do.
    """
    classes = _entity_classes()
    matches = [
        subclass for subclass in classes if getattr(subclass, "ENTITY_TYPE", None) == entity_type
    ]
    if not matches:
        known = sorted({subclass.ENTITY_TYPE for subclass in classes})
        raise ValueError(f"unknown entity type: {entity_type!r}; known types are {known}")
    if len(matches) > 1:
        raise ValueError(
            f"entity type {entity_type!r} is claimed by more than one class: "
            f"{sorted(cls.__name__ for cls in matches)}"
        )
    return matches[0]


def table_name_for_entity_type(entity_type: str) -> str:
    """Turn a user-facing entity type into its real DB table name.

    The ONLY sanctioned conversion. For todo, bug, comment and wish the table
    name differs from the entity type (todo_item, bug_report, runtime_comment,
    wish_item), and passing the entity type straight to a reference lookup
    silently returns zero referrers — which reads as "nothing blocks this
    deletion" when in truth everything does.
    """
    table_name: Any = resolve_entity_class(entity_type).TABLE_NAME
    return str(table_name)
