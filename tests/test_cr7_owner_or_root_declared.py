"""CR-7 G-008/T-001/A-001: the cr7-owner-or-root-declared pipeline check.

tests/domain/test_entity.py::test_all_shipped_entity_ownership_declarations_are_complete
(CR-7 G-003) already sweeps every DataclassEntity subclass reachable from the
``plan_manager.domain`` package. This module widens that sweep to every
REGISTERED entity class -- "registered" meaning its TABLE_NAME is a member of
plan_manager.storage.identity.ALLOWED_TABLES, the identity registry's own
definition of "every in-scope table" -- which additionally reaches the
DataclassEntity seats living under plan_manager/storage, plan_manager/views
and plan_manager/cascade (version_store, runtime_audit_store,
srt_snapshot_store, cascade_request_store, context_blocks, cascade/record,
cascade/restore, identity's own registry seat).

Fake psycopg connections are never needed here: validate_ownership_declaration
inspects class attributes only, no database access.
"""

from __future__ import annotations

import importlib
import pkgutil

import pytest

from plan_manager.domain.entity import DataclassEntity
from plan_manager.storage.identity import ALLOWED_TABLES

# ---------------------------------------------------------------------------
# Known, tracked ownership gaps.
#
# Widening the sweep beyond the domain package surfaces three registered
# classes that declare no OWNER_COLUMN/OWNER_ROOT/OWNER_GAP today:
# RuntimeAuditRecord, SrtSnapshotRecord and CascadeRequestRecord. Fixing them
# means editing their own module (plan_manager/storage/runtime_audit_store.py,
# srt_snapshot_store.py, cascade_request_store.py) -- out of scope for this
# step (CR-7 G-008/T-001/A-001), whose frozen prompt permits touching only
# plan_manager/pipeline_checks/registry.py. They are named here, explicitly
# and visibly, exactly like plan_manager/storage/reference_catalog.py's
# UNCLASSIFIED_REFERENCE_COLUMNS/EXCLUDED_TABLES discipline: a documented
# decision, not a silent exemption, and the check output below prints every
# one of them so the gap stays visible pipeline run after pipeline run.
#
# THIS DICT MUST ONLY SHRINK. A class that gains a real ownership declaration
# must be removed from here (test_known_ownership_gaps_are_still_real_gaps
# below fails loudly if an entry has actually been fixed but left listed).
# Nothing may be added without a written reason.
# ---------------------------------------------------------------------------

_KNOWN_OWNERSHIP_GAPS: dict[str, str] = {
    "runtime_audit_log": (
        "RuntimeAuditRecord (plan_manager/storage/runtime_audit_store.py): "
        "append-only audit trail seat, no ownership state declared yet"
    ),
    "srt_snapshot": (
        "SrtSnapshotRecord (plan_manager/storage/srt_snapshot_store.py): "
        "content-hash-deduplicated derived snapshot seat, no ownership state "
        "declared yet"
    ),
    "cascade_request": (
        "CascadeRequestRecord (plan_manager/storage/cascade_request_store.py): "
        "cascade request seat, no ownership state declared yet"
    ),
}


def _import_every_registered_seat_module() -> None:
    """Import every module known to define a table-backed DataclassEntity seat.

    _entity_classes() (reference_catalog.py) only auto-imports the domain
    package; the storage/views/cascade seats register as DataclassEntity
    subclasses only once their own module has been imported at least once in
    this process. Importing them explicitly here makes the sweep below see
    the full registered population regardless of test collection order.
    """
    import plan_manager.domain as domain_pkg

    for module in pkgutil.iter_modules(domain_pkg.__path__):
        importlib.import_module(f"{domain_pkg.__name__}.{module.name}")

    import plan_manager.cascade.record  # noqa: F401
    import plan_manager.cascade.restore  # noqa: F401
    import plan_manager.storage.cascade_request_store  # noqa: F401
    import plan_manager.storage.command_metrics_store  # noqa: F401
    import plan_manager.storage.identity as identity_module
    import plan_manager.storage.runtime_audit_store  # noqa: F401
    import plan_manager.storage.srt_snapshot_store  # noqa: F401
    import plan_manager.storage.version_store  # noqa: F401
    import plan_manager.views.context_blocks  # noqa: F401

    identity_module._identity_row_seat()  # forces the lazy nested seat into existence


def _registered_entity_classes() -> list[type]:
    """Every DataclassEntity subclass whose TABLE_NAME is in ALLOWED_TABLES.

    Excludes classes defined by this test module's own fixtures (the
    tests-origin exclusion idiom shared with
    tests/domain/test_entity.py::test_all_shipped_entity_ownership_declarations_are_complete).
    """
    _import_every_registered_seat_module()

    def _walk(root: type) -> list[type]:
        found: list[type] = []
        for subclass in root.__subclasses__():
            found.append(subclass)
            found.extend(_walk(subclass))
        return found

    classes = []
    for cls in _walk(DataclassEntity):
        if (cls.__module__ or "").startswith("tests"):
            continue
        table_name = getattr(cls, "TABLE_NAME", None)
        if table_name and table_name in ALLOWED_TABLES:
            classes.append(cls)
    return classes


def test_every_registered_entity_class_declares_ownership_or_is_a_tracked_gap() -> None:
    classes = _registered_entity_classes()
    assert len(classes) >= 34, (
        f"expected at least 34 registered entity classes (30+ domain kinds plus the "
        f"storage/views/cascade seats); found {len(classes)} -- did an import go missing?"
    )

    offenders: list[str] = []
    known_gaps_hit: set[str] = set()
    for cls in classes:
        try:
            cls.validate_ownership_declaration(require_ownership=True)
        except ValueError as exc:
            if cls.TABLE_NAME in _KNOWN_OWNERSHIP_GAPS:
                known_gaps_hit.add(cls.TABLE_NAME)
                print(f"[cr7-owner-or-root-declared] known gap: {cls.__module__}.{cls.__name__}: {exc}")
                continue
            offenders.append(f"{cls.__module__}.{cls.__name__} ({cls.TABLE_NAME}): {exc}")

    assert offenders == [], (
        "registered entity classes with no ownership state declared and no tracked-gap "
        f"entry: {offenders}"
    )
    stale_gap_entries = sorted(set(_KNOWN_OWNERSHIP_GAPS) - known_gaps_hit)
    assert stale_gap_entries == [], (
        f"_KNOWN_OWNERSHIP_GAPS lists tables that are no longer registered or no longer "
        f"actually missing a declaration -- shrink the dict: {stale_gap_entries}"
    )


def test_known_ownership_gaps_are_still_real_gaps() -> None:
    """The pending list only shrinks: a class that got fixed must leave it (bug f7b9cebf idiom)."""
    classes_by_table = {cls.TABLE_NAME: cls for cls in _registered_entity_classes()}
    for table_name in _KNOWN_OWNERSHIP_GAPS:
        assert table_name in classes_by_table, (
            f"{table_name} is listed in _KNOWN_OWNERSHIP_GAPS but is no longer a "
            "registered entity class at all -- remove the stale entry"
        )
        cls = classes_by_table[table_name]
        with pytest.raises(ValueError, match="no ownership state declared"):
            cls.validate_ownership_declaration(require_ownership=True)


# ---------------------------------------------------------------------------
# RED-path proof: a synthetic undeclared class is caught by
# validate_ownership_declaration, and is filtered out of the real sweep above
# purely because it originates from this "tests" module.
# ---------------------------------------------------------------------------


class _SyntheticUndeclaredProbe(DataclassEntity):
    ENTITY_TYPE = "cr7_g008_probe_owner_undeclared"
    TABLE_NAME = "plan"  # a real ALLOWED_TABLES name, reused harmlessly for the probe
    ID_COLUMN = "uuid"
    COLUMNS = ("uuid",)


def test_red_path_a_synthetic_undeclared_class_fails_the_completeness_check() -> None:
    with pytest.raises(ValueError, match="no ownership state declared"):
        _SyntheticUndeclaredProbe.validate_ownership_declaration(require_ownership=True)


def test_red_path_the_synthetic_probe_is_excluded_from_the_real_sweep_by_module_origin() -> None:
    assert _SyntheticUndeclaredProbe.__module__.startswith("tests")
    swept_classes = _registered_entity_classes()
    assert _SyntheticUndeclaredProbe not in swept_classes, (
        "the tests-origin exclusion idiom failed to filter the synthetic probe out of "
        "the real sweep -- it would have doubled up on the real 'plan' entry"
    )
