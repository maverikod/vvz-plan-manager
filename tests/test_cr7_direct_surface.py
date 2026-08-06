"""CR-7 wave W07 (G-004/T-002/A-001): entity.py direct-surface completeness pin.

Direct surface audit outcome (grep evidence recorded in the wave report):

Removed (zero callers anywhere outside plan_manager/domain/entity.py, including
its own tests):
  - ``DataclassEntity.crud_resolve_identity`` -- a pure pass-through to
    ``plan_manager.storage.identity.resolve_entity_identity`` that no caller
    anywhere in plan_manager/tests/scripts ever invoked; every real caller of
    identity resolution (plan_manager/commands/project_uuid_reserve_command.py,
    tests/test_identity_registry_full_scope.py, ...) imports and calls
    ``resolve_entity_identity`` directly, bypassing this classmethod entirely.

Kept despite looking like duplication (BOTH have real callers, per the frozen
prompt's explicit rule: "if BOTH have callers, keep both - renaming callers is
out of scope"):
  - ``DataclassEntity.crud_delete`` forwards to the same ``soft_delete_entity``
    helper as ``crud_soft_delete``. Production storage modules exclusively use
    ``crud_soft_delete`` (calendar_entry_store.py, tool_store.py,
    runtime_comment_store.py, todo_store.py, bug_fix_store.py, wish_store.py),
    but ``tests/test_runtime_audit_record_entity.py::
    test_append_only_mutations_refused`` calls ``RuntimeAuditRecord.crud_delete``
    directly, so it is a real caller outside entity.py and its own tests.
  - ``DataclassEntity.get_by_id`` / ``crud_get`` -- both have real callers
    (plan_manager/storage/hard_delete_guard.py and
    plan_manager/commands/id_resolve_command.py call ``get_by_id``; every
    storage module's read path calls ``crud_get`` directly), and ``get_by_id``
    is also the abstract method every ``EntityRecord`` subclass must implement.

Kept despite looking unused from a same-module grep: the module-level
``unregister_entity_identity`` import is never CALLED from within entity.py,
but it is re-exported through this module -- ``plan_manager/storage/
hard_delete_guard.py`` imports it with ``from plan_manager.domain.entity
import ... unregister_entity_identity`` (a deliberate cycle-breaking
function-local import, see that module's docstring), not from
``plan_manager.storage.identity`` directly. Removing it breaks that real
caller, which the initial grep pass (matching only call sites, not import
sites) missed; this was caught by the pytest gate before being finalized as a
removal.

Every other public name defined by entity.py (EntityRecord, DataclassEntity,
ReferenceCheck, CENTRAL_REFERENCE_CHECKS, EntityReferencedError,
EntityNotSoftDeletedError, EntityIdentifier, find_entity_reference_counts,
soft_delete_entity, hard_delete_entity, purge_soft_deleted_batch, and every
crud_* member not named above) has real callers outside entity.py and stays.

The direct surface itself was already complete before this wave: crud_create
(recovery_mode=True is the restore admission -- see
plan_manager/cascade/restore.py) / crud_get / crud_list / crud_search /
crud_update / crud_soft_delete / crud_hard_delete (single-row purge) /
crud_purge_soft_deleted_batch (batch purge) all already existed as public
classmethods, so this wave adds no new members.
"""
from __future__ import annotations

import inspect

import pytest

import plan_manager.domain.entity as entity_module
from plan_manager.domain.entity import DataclassEntity


# --- Removed: must be absent -------------------------------------------------

def test_crud_resolve_identity_removed_from_dataclass_entity() -> None:
    """Dead compatibility-only wrapper: zero callers anywhere (see module docstring)."""
    with pytest.raises(AttributeError):
        getattr(DataclassEntity, "crud_resolve_identity")


# --- Kept re-export: must remain present -------------------------------------

def test_unregister_entity_identity_still_exported_for_hard_delete_guard() -> None:
    """plan_manager/storage/hard_delete_guard.py imports this name from
    entity.py (not from plan_manager.storage.identity directly); it looks
    unused from a same-module grep but is a real re-export, not dead code."""
    assert callable(getattr(entity_module, "unregister_entity_identity"))


# --- Direct surface: must be present and callable ----------------------------

DIRECT_SURFACE_MEMBERS = (
    "crud_create",
    "crud_get",
    "crud_list",
    "crud_search",
    "crud_update",
    "crud_soft_delete",
    "crud_hard_delete",
    "crud_purge_soft_deleted_batch",
)


@pytest.mark.parametrize("name", DIRECT_SURFACE_MEMBERS)
def test_direct_surface_member_present_and_callable(name: str) -> None:
    member = getattr(DataclassEntity, name)
    assert callable(member), f"{name} must be a callable classmethod"
    # classmethod descriptors resolve to bound methods on the class itself
    assert inspect.ismethod(member), f"{name} must be a classmethod, not a plain function"


def test_kept_duplicate_write_admissions_both_present() -> None:
    """crud_delete and crud_soft_delete both have real callers (see module
    docstring) and both stay per the frozen prompt's explicit duplication rule."""
    assert callable(DataclassEntity.crud_delete)
    assert callable(DataclassEntity.crud_soft_delete)
    assert callable(DataclassEntity.get_by_id)
    assert callable(DataclassEntity.crud_get)
