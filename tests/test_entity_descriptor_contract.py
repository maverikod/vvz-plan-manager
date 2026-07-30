"""Descriptor contract regression suite (CR-6 G-003/T-001). No live database."""

from __future__ import annotations

import inspect

import pytest

from plan_manager.domain.calendar_entry import CalendarEntry
from plan_manager.domain.entity import DataclassEntity

_GAP_MARKER = "Descriptor gap:"

# Entities whose descriptor is not populated YET. CR-6 migrates them in
# G-003/T-003 (plan-truth and derived stores) and G-003/T-004 (runtime overlay
# and agent configuration); CalendarEntry is already done and is deliberately
# absent from this list, as the reference exemplar.
#
# This list is the visible record of pending migration, and it only shrinks. A
# migration step removes its entity here, which makes the sweep below start
# enforcing the descriptor contract on that entity: a store cannot be declared
# migrated while its COLUMNS are still empty, and an entity cannot quietly
# regress to an empty descriptor once it has been removed from the list.
#
# An entity that will NEVER carry a descriptor documents that in its own class
# docstring with a "Descriptor gap: ..." line instead of living here forever.
_PENDING_DESCRIPTOR_MIGRATION = frozenset(
    {
        # G-003/T-003 — plan-truth and derived stores.
        "Plan", "Step", "Concept", "Relation", "TodoLink", "WishItem",
        "ProjectDependency", "BugReport", "BugFixPropagation", "BugImpact",
        "CascadeRequestRecord", "SrtSnapshotRecord",
        # G-003/T-004 — runtime overlay and agent configuration.
        "RuntimeLink", "ExecutionAttempt", "ReviewResult",
        "Escalation", "EscalationPolicy", "AnswerEnvelope", "StepAssignment",
        "Model", "ModelBinding", "Provider", "Role", "RoleModelBinding",
        "Toolset", "ToolsetMembership", "InvocationProfile",
        # Derived store. G-003/T-003's description enumerates cascade_request
        # and srt_snapshot among the derived stores but not context_block, so
        # this entity currently has no migration step of its own. Listed here so
        # the omission is visible rather than silent.
        "ContextBlockRecord",
    }
)


def test_validate_descriptor_passes_for_calendar_entry() -> None:
    """CalendarEntry is the reference exemplar the store migrations follow."""
    CalendarEntry.validate_descriptor()

    columns = set(CalendarEntry.COLUMNS)
    assert CalendarEntry.ID_COLUMN == "uuid"
    assert set(CalendarEntry.INSERT_COLUMNS) < columns
    assert set(CalendarEntry.UPDATE_COLUMNS) < columns
    assert CalendarEntry.INSERT_COLUMNS and CalendarEntry.UPDATE_COLUMNS

    # uuid, created_at and updated_at carry no DB default and are supplied by
    # the store, so a create must be allowed to set them.
    assert {"uuid", "created_at", "updated_at"} <= set(CalendarEntry.INSERT_COLUMNS)
    # deleted_at is the only column a create may not set.
    assert columns - set(CalendarEntry.INSERT_COLUMNS) == {"deleted_at"}
    # An update may not touch identity, creation metadata, or the soft-delete
    # marker, which crud_soft_delete writes directly.
    assert not ({"uuid", "created_at", "created_by", "deleted_at"} & set(CalendarEntry.UPDATE_COLUMNS))


def test_validate_descriptor_rejects_insert_columns_outside_columns() -> None:
    class _BadInsert(DataclassEntity):
        ENTITY_TYPE = "bad_insert"
        TABLE_NAME = "some_table"
        COLUMNS = ("col_a", "col_b")
        INSERT_COLUMNS = ("col_a", "col_b", "col_c")
        ID_COLUMN = "col_a"
        SOFT_DELETE_COLUMN = None
        UPDATED_AT_COLUMN = None

    with pytest.raises(ValueError) as excinfo:
        _BadInsert.validate_descriptor()
    assert "INSERT_COLUMNS" in str(excinfo.value)
    assert "col_c" in str(excinfo.value)


def test_validate_descriptor_rejects_empty_columns_with_table_name() -> None:
    class _NoColumns(DataclassEntity):
        ENTITY_TYPE = "no_columns"
        TABLE_NAME = "some_table"
        COLUMNS = ()

    with pytest.raises(ValueError) as excinfo:
        _NoColumns.validate_descriptor()
    assert "COLUMNS" in str(excinfo.value)


def test_validate_descriptor_rejects_identifier_absent_from_columns() -> None:
    class _BadId(DataclassEntity):
        ENTITY_TYPE = "bad_id"
        TABLE_NAME = "some_table"
        COLUMNS = ("col_a",)
        ID_COLUMN = "missing_id"
        SOFT_DELETE_COLUMN = None
        UPDATED_AT_COLUMN = None

    with pytest.raises(ValueError) as excinfo:
        _BadId.validate_descriptor()
    assert "identifier columns" in str(excinfo.value)


def test_validate_descriptor_rejects_marker_columns_absent_from_columns() -> None:
    class _BadMarker(DataclassEntity):
        ENTITY_TYPE = "bad_marker"
        TABLE_NAME = "some_table"
        COLUMNS = ("uuid",)
        ID_COLUMN = "uuid"
        SOFT_DELETE_COLUMN = "deleted_at"
        UPDATED_AT_COLUMN = None

    with pytest.raises(ValueError) as excinfo:
        _BadMarker.validate_descriptor()
    assert "SOFT_DELETE_COLUMN" in str(excinfo.value)


def test_select_columns_sql_is_explicit_for_calendar_entry() -> None:
    """A populated descriptor makes the SELECT explicit instead of a star."""
    rendered = str(CalendarEntry._select_columns_sql())
    assert "uuid" in rendered
    assert "title" in rendered
    assert "*" not in rendered


def _concrete_subclasses(root: type) -> list[type]:
    found: list[type] = []
    for subclass in root.__subclasses__():
        found.append(subclass)
        found.extend(_concrete_subclasses(subclass))
    return found


def test_every_subclass_validates_or_declares_a_documented_gap() -> None:
    """An empty descriptor ClassVar is allowed only as a documented gap.

    This is the check that keeps the migration honest: a store whose descriptor
    is unpopulated must say so in its own docstring, so 'not migrated yet' can
    never be mistaken for 'nothing to migrate'.
    """
    # Import the domain package so every entity module is loaded and therefore
    # present in __subclasses__; otherwise this test silently checks whatever
    # the earlier imports happened to pull in.
    import importlib
    import pkgutil

    import plan_manager.domain as domain_pkg
    import plan_manager.storage as storage_pkg

    for package in (domain_pkg, storage_pkg):
        for module in pkgutil.iter_modules(package.__path__):
            importlib.import_module(f"{package.__name__}.{module.name}")

    checked = 0
    clean = 0
    offenders: list[str] = []
    seen: set[str] = set()
    for subclass in _concrete_subclasses(DataclassEntity):
        if inspect.isabstract(subclass) or not getattr(subclass, "TABLE_NAME", None):
            continue
        # Synthetic subclasses defined inside test modules are fixtures for the
        # negative cases above, not shipped entities. They leak into
        # __subclasses__ once their test has run, so exclude them by origin
        # rather than by name.
        if (subclass.__module__ or "").startswith("tests"):
            continue
        name = subclass.__name__
        seen.add(name)
        checked += 1
        try:
            subclass.validate_descriptor()
        except ValueError as exc:
            docstring = subclass.__doc__ or ""
            if _GAP_MARKER in docstring or name in _PENDING_DESCRIPTOR_MIGRATION:
                continue
            offenders.append(f"{name}: {exc}")
            continue
        clean += 1
        # A migrated entity must be removed from the pending list, so the list
        # cannot rot into a permanent exemption.
        if name in _PENDING_DESCRIPTOR_MIGRATION:
            offenders.append(
                f"{name}: descriptor now validates but is still listed in "
                "_PENDING_DESCRIPTOR_MIGRATION; remove it there"
            )

    assert offenders == [], (
        "descriptor contract violations (a subclass must validate, declare a "
        f"'{_GAP_MARKER} ...' docstring line, or be listed as pending): {offenders}"
    )
    assert checked, "no DataclassEntity subclass with a TABLE_NAME was discovered"
    assert clean, "no subclass validates cleanly; the exemplar descriptor is missing"

    stale = sorted(_PENDING_DESCRIPTOR_MIGRATION - seen)
    assert stale == [], (
        f"_PENDING_DESCRIPTOR_MIGRATION names entities that no longer exist: {stale}"
    )
