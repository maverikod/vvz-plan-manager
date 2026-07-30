"""Registry of named checks for the project-wide ``pipeline`` CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys


_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PipelineCheckSpec:
    """One named check runnable through the project ``pipeline`` CLI."""

    name: str
    description: str
    argv: tuple[str, ...]


CHECKS: tuple[PipelineCheckSpec, ...] = (
    PipelineCheckSpec(
        name="context-block-rebuild",
        description="Run the batch context-block rebuild regression check.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_todo_60c3a375_block_rebuild_batch.py",
        ),
    ),
    PipelineCheckSpec(
        name="gate-object-inventory",
        description="Run the mechanical-gate object inventory regression check.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_todo_2b6d295d_gate_object_inventory.py",
        ),
    ),
    PipelineCheckSpec(
        name="gate-object-concepts",
        description="Run the mechanical-gate object concept coverage regression check.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_todo_299c1037_gate_object_concepts.py",
        ),
    ),
    PipelineCheckSpec(
        name="graph-parallel-map",
        description="Run the inherited-wave regression check for graph_parallel_map.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_bug_85a9d14b_graph_parallel_map_inherited_waves.py",
        ),
    ),
    PipelineCheckSpec(
        name="object-declaration-shape",
        description="Run the level-5 object declaration shape regression check.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_bug_6625a6eb_object_declaration_shape.py",
        ),
    ),
    PipelineCheckSpec(
        name="release-client-build",
        description="Run the release-script regression check for isolated client wheel/sdist builds.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_release_client_build.py",
        ),
    ),
    PipelineCheckSpec(
        name="repo-tests",
        description="Run the full repository pytest suite.",
        argv=(sys.executable, "-m", "pytest"),
    ),
    PipelineCheckSpec(
        name="pagination-contract",
        description="Run the pagination-contract and response-envelope regression checks.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_uniform_pagination_contract.py",
            "tests/test_pagination_contract.py",
            "tests/test_pagination_envelope_uniformity.py",
            "tests/test_bug_85b180bf_command_catalog_dump_pagination.py",
            "tests/test_paginated_command_registry.py",
        ),
    ),
    PipelineCheckSpec(
        name="command-surface",
        description="Run command registration, metadata, and client-facade synchronisation checks.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_command_registration.py",
            "tests/test_metadata_vocabulary_contract.py",
            "tests/test_info_command_inclusion_contract.py",
            "client/tests/test_client_server_api_sync.py",
        ),
    ),
    PipelineCheckSpec(
        name="pipeline-cli",
        description="Run the pipeline CLI regression checks, including live-smoke argument forwarding.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_pipeline_cli.py",
        ),
    ),
    PipelineCheckSpec(
        name="live-smoke-r7",
        description="Run the R7 live-smoke regression checks for the agent-config lifecycle.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_live_smoke_script.py",
            "-k",
            "run_r7",
        ),
    ),
    PipelineCheckSpec(
        name="wish-calendar",
        description="Run the new runtime CRUD command checks for wish and calendar-entry entities.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_wish_commands.py",
            "tests/test_calendar_entry_commands.py",
        ),
    ),
    PipelineCheckSpec(
        name="runtime-record-updates",
        description="Run runtime record helper and bug/todo guarded-update regression checks.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_runtime_record_command_helpers.py",
            "tests/test_runtime_list_command_helpers.py",
            "tests/test_runtime_catalog_update_commands.py",
            "tests/test_bug_32755092_append_and_3eec33f2_optional_plan.py",
            "tests/test_bug_a5ec9c1a_impact_propagation_optional_plan.py",
            "tests/test_bug_c3950b83_plan_completed_lock.py",
        ),
    ),
    PipelineCheckSpec(
        name="cr6-identity-registry",
        description="Run the CR-6 identity-registry and project-uuid-reservation suites.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_identity_registry_full_scope.py",
            "tests/test_project_uuid_reserve_command.py",
        ),
    ),
    PipelineCheckSpec(
        name="cr6-entity-contract",
        description="Run the CR-6 entity-descriptor contract, content-search and store-migration suites.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_entity_descriptor_contract.py",
            "tests/test_content_search_layer.py",
            "tests/test_store_descriptor_migration_plan_truth.py",
            "tests/test_store_descriptor_migration_overlay.py",
        ),
    ),
    PipelineCheckSpec(
        name="cr6-deletion-references",
        description="Run the CR-6 reference-catalog, hard-delete guard, purge and inspection suites.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_reference_catalog.py",
            "tests/test_hard_delete_guard.py",
            "tests/test_runtime_purge_batch_command.py",
            "tests/test_reference_inspection_command.py",
        ),
    ),
    PipelineCheckSpec(
        name="cr6-migrations-audit",
        description="Run the CR-6 migration-discipline and audit-compatibility suites.",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_cr6_migration_discipline_and_cascade_compat.py",
            "tests/test_cr6_compat_audit_contract.py",
        ),
    ),
    PipelineCheckSpec(
        name="work-queue-timestamps",
        description="Run the work-queue timestamp-type regression check (bug 4375c341).",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_bug_4375c341_work_queue_timestamp_types.py",
        ),
    ),
)


def get_check(name: str) -> PipelineCheckSpec:
    """Return the registered check spec for ``name``."""
    for spec in CHECKS:
        if spec.name == name:
            return spec
    raise KeyError(name)


def default_checks() -> tuple[PipelineCheckSpec, ...]:
    """Return the checks run by ``pipeline`` with no explicit check name."""
    return CHECKS


def repo_root() -> Path:
    """Return the repository root used as cwd for every pipeline subprocess."""
    return _REPO_ROOT
