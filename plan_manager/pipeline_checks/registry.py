"""Registry of named checks for the project-wide ``pipeline`` CLI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
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
    PipelineCheckSpec(
        name="soft-delete-owned-column",
        description="Run the soft-delete lifecycle-owned-column regression check (bug 31ba96d5).",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_bug_31ba96d5_soft_delete_owned_column.py",
        ),
    ),
    PipelineCheckSpec(
        name="id-resolve",
        description="Run the partial-identifier resolution suite (id_resolve).",
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_id_resolve_command.py",
        ),
    ),
    PipelineCheckSpec(
        name="bug-1d597a86-done-atomic-survives-invalidation",
        description=(
            "Run the bug 1d597a86 cascade invalidation matrix: atomic execution "
            "statuses survive invalidation while authoring statuses still invalidate."
        ),
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_bug_1d597a86_atomic_status_invalidation.py",
        ),
    ),
    PipelineCheckSpec(
        name="bug-0040585c-step-transition-require-green",
        description=(
            "Run the bug 0040585c real-server regression: step_transition "
            "require_green=true must evaluate the open cascade working tip."
        ),
        argv=(
            sys.executable,
            "scripts/pipeline_bug_0040585c.py",
        ),
    ),
    PipelineCheckSpec(
        name="cr7-roundtrip",
        description=(
            "Run the CR-7 G-005/T-002/A-001 canonical round-trip fidelity suite "
            "(todo 09a4d9af closure evidence): export/import/re-export byte and "
            "semantic equality, identity preservation, same-kind replacement, "
            "cross-kind conflict abort, and the exact excluded-content list."
        ),
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/exchange/test_cr7_roundtrip.py",
        ),
    ),
    PipelineCheckSpec(
        name="cr7-no-out-of-mechanism-write",
        description=(
            "Mechanically assert CR-7 G-004: no INSERT/DELETE statement targets a "
            "registered entity table outside the unified engine mechanism."
        ),
        # CR-7 G-004 (C-005, C-012): the scan runs as its own subprocess, not as a
        # pytest suite like the cr6-* checks, because G-004 mandates this check be
        # RED while any module still writes beside the mechanism -- a pytest-based
        # wiring would drag the repo-tests check red along with it mid-sweep. The
        # scan's behavior is unit-tested in tests/test_cr7_g004_write_scan.py.
        argv=(
            sys.executable,
            "-c",
            "from plan_manager.pipeline_checks.registry import g004_scan_main; "
            "raise SystemExit(g004_scan_main())",
        ),
    ),
    # -----------------------------------------------------------------------
    # CR-7 G-008/T-001/A-001: the four-check acceptance group.
    # -----------------------------------------------------------------------
    PipelineCheckSpec(
        name="cr7-identifier-classification",
        description=(
            "CR-7 G-008: every identifier column of every registered table is "
            "classified in the reference catalogue (extends the CR-6 "
            "total-classification guard to the CR-7 registry scope)."
        ),
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_reference_catalog.py::test_every_uuid_column_of_a_registered_table_is_classified",
            "tests/test_reference_catalog.py::test_the_pending_classification_list_only_shrinks",
        ),
    ),
    PipelineCheckSpec(
        name="cr7-metadata-projection-equality",
        description=(
            "CR-7 G-008: the database projection of the reference metadata "
            "(field catalogue, relation-index triple shape, enumeration "
            "seeds) equals its source of truth in code, byte-comparable in "
            "both directions."
        ),
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_cr7_metadata_projection_equality.py",
        ),
    ),
    PipelineCheckSpec(
        name="cr7-owner-or-root-declared",
        description=(
            "CR-7 G-008: every registered entity class declares exactly one "
            "ownership state (OWNER_COLUMN in COLUMNS, OWNER_ROOT, or a "
            "recorded OWNER_GAP)."
        ),
        argv=(
            sys.executable,
            "-m",
            "pytest",
            "tests/test_cr7_owner_or_root_declared.py",
        ),
    ),
    PipelineCheckSpec(
        name="cr7",
        description=(
            "Run the CR-7 G-008 four-check acceptance group as one command: "
            "cr7-identifier-classification, cr7-no-out-of-mechanism-write, "
            "cr7-metadata-projection-equality, cr7-owner-or-root-declared."
        ),
        # The group runner is itself a subprocess (the same idiom as
        # g004_scan_main above) so ``pipeline cr7`` dispatches through the
        # ordinary get_check(name) exact-name lookup like every other check,
        # with no change to pipeline_cli.py's dispatch logic.
        argv=(
            sys.executable,
            "-c",
            "from plan_manager.pipeline_checks.registry import cr7_group_main; "
            "raise SystemExit(cr7_group_main())",
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


# ---------------------------------------------------------------------------
# CR-7 G-004 (C-005, C-012): the cr7-no-out-of-mechanism-write scan.
#
# G-004's acceptance, asserted mechanically: no registered entity table may be
# the target of an INSERT or DELETE statement anywhere in the plan_manager
# package outside the unified engine mechanism. The mechanism files below are
# consumed read-only by this scan -- they are the allowed writers and are never
# reported. A statement outside them is an offender unless the literal W05
# compatibility marker appears in the preceding 10 source lines, in which case
# it is reported as a known exception without failing the check.
# ---------------------------------------------------------------------------

# The unified engine mechanism: the entity base, the admission collaborator,
# the deletion guard, and the registry/relation-index/enumeration maintenance
# paths (all mechanism-internal per CR-7 G-004).
_G004_MECHANISM_FILES: frozenset[str] = frozenset(
    {
        "plan_manager/domain/entity.py",
        "plan_manager/storage/admission.py",
        "plan_manager/storage/hard_delete_guard.py",
        "plan_manager/storage/identity.py",
        "plan_manager/storage/identity_audit.py",
        "plan_manager/storage/relation_index_store.py",
        "plan_manager/storage/enumeration_store.py",
    }
)

# The literal in-code marker W05 placed on each documented compatibility
# exception; only this exact string, within the 10 lines above a statement,
# downgrades it from offender to known exception.
_G004_COMPAT_MARKER = "CR-7 G-004 compatibility note"
_G004_MARKER_WINDOW = 10

_G004_CHECK_NAME = "cr7-no-out-of-mechanism-write"


@dataclass(frozen=True)
class G004WriteFinding:
    """One source statement that writes a registered entity table directly."""

    path: str  # repo-relative posix path of the source file
    line: int  # 1-based line number of the statement
    statement: str  # the offending source line, stripped


def _g004_statement_pattern(tables: frozenset[str]) -> "re.Pattern[str]":
    """Compile the statement matcher for the registered entity tables.

    Case-sensitive on purpose: every real statement in this package spells the
    keywords in uppercase, while prose in comments and docstrings ("an insert
    into runtime_audit_log") does not, so prose never false-positives. The
    trailing word boundary keeps a registered name from matching a longer
    unregistered one (e.g. "step" inside "step_runtime"). A brace right after
    the keywords catches dynamically-composed targets (f-strings and
    sql.SQL format placeholders); outside the mechanism such a dynamic target
    is conservatively treated as a registered-table write.
    """
    alternation = "|".join(re.escape(name) for name in sorted(tables, key=len, reverse=True))
    return re.compile(
        r"(INSERT INTO|DELETE FROM)\s+(?:\"?(?:%s)\"?\b|\{)" % alternation
    )


def g004_scan(
    package_dir: Path | None = None,
) -> tuple[list[G004WriteFinding], list[G004WriteFinding]]:
    """Scan package sources for out-of-mechanism writes on registered tables.

    Args:
        package_dir: The ``plan_manager`` package directory to scan; defaults
            to this repository's package. Tests point this at a fixture tree.

    Returns:
        ``(offenders, known_exceptions)`` -- statements without and with the
        W05 compatibility marker respectively, each as a G004WriteFinding
        with repo-relative path, line number, and statement text.
    """
    # Imported lazily: the closed registry lives beside psycopg-importing
    # storage code, and the pipeline CLI must stay importable without it.
    from plan_manager.storage.identity import ALLOWED_TABLES

    root = package_dir if package_dir is not None else _REPO_ROOT / "plan_manager"
    base = root.parent
    pattern = _g004_statement_pattern(ALLOWED_TABLES)
    offenders: list[G004WriteFinding] = []
    known_exceptions: list[G004WriteFinding] = []
    for source in sorted(root.rglob("*.py")):
        rel = source.relative_to(base).as_posix()
        if rel in _G004_MECHANISM_FILES:
            continue  # the mechanism's own writers; consumed read-only here
        lines = source.read_text(encoding="utf-8").splitlines()
        for index, text in enumerate(lines):
            if not pattern.search(text):
                continue
            finding = G004WriteFinding(path=rel, line=index + 1, statement=text.strip())
            window = lines[max(0, index - _G004_MARKER_WINDOW):index]
            if any(_G004_COMPAT_MARKER in prior for prior in window):
                known_exceptions.append(finding)
            else:
                offenders.append(finding)
    return offenders, known_exceptions


def g004_scan_main(package_dir: Path | None = None) -> int:
    """Subprocess body of the cr7-no-out-of-mechanism-write pipeline check.

    Prints every known exception and every offender (file, line, statement)
    and returns a nonzero exit code when any offender exists, so the check is
    RED while any module still writes beside the mechanism and GREEN only
    when the removal sweep is complete.
    """
    offenders, known_exceptions = g004_scan(package_dir)
    for finding in known_exceptions:
        print(
            f"[known exception] {finding.path}:{finding.line}: {finding.statement}"
        )
    for finding in offenders:
        print(f"[OFFENDER] {finding.path}:{finding.line}: {finding.statement}")
    if offenders:
        print(
            f"{_G004_CHECK_NAME}: RED -- {len(offenders)} unmarked out-of-mechanism "
            "write(s) on registered entity tables (listed above)."
        )
        return 1
    print(
        f"{_G004_CHECK_NAME}: GREEN -- no out-of-mechanism writes "
        f"({len(known_exceptions)} documented compatibility exception(s))."
    )
    return 0


# ---------------------------------------------------------------------------
# CR-7 G-008/T-001/A-001: the ``cr7`` acceptance-group umbrella.
#
# G-008's acceptance is carried by four named checks, each mechanically
# runnable and RED/GREEN-legible on its own. This umbrella wires them into one
# group runnable as ``pipeline cr7``, the same subprocess-body idiom as
# g004_scan_main above: each member check runs as its own subprocess (its own
# argv, unmodified), so running the group is equivalent to running the four
# checks individually in sequence, and a failure in any one fails the group.
# ---------------------------------------------------------------------------

_CR7_GROUP_CHECK_NAMES: tuple[str, ...] = (
    "cr7-identifier-classification",
    "cr7-no-out-of-mechanism-write",
    "cr7-metadata-projection-equality",
    "cr7-owner-or-root-declared",
)


def cr7_group_main() -> int:
    """Subprocess body of the ``cr7`` pipeline check: run the four G-008 checks.

    Runs every check named in _CR7_GROUP_CHECK_NAMES, in order, each as its
    own subprocess under its own argv (unchanged from its individual
    registration), and continues through all four even after a failure so one
    run reports every failing check, not just the first. Returns 0 only when
    every one of the four returned 0.
    """
    exit_code = 0
    for name in _CR7_GROUP_CHECK_NAMES:
        spec = get_check(name)
        print(f"[cr7] {name}: {' '.join(spec.argv)}", flush=True)
        completed = subprocess.run(spec.argv, cwd=_REPO_ROOT)
        if completed.returncode != 0:
            print(f"[cr7] FAILED: {name} (exit {completed.returncode})", flush=True)
            if exit_code == 0:
                exit_code = completed.returncode
        else:
            print(f"[cr7] OK: {name}", flush=True)
    if exit_code:
        print("cr7: RED -- one or more of the four G-008 acceptance checks failed.", flush=True)
    else:
        print("cr7: GREEN -- all four G-008 acceptance checks passed.", flush=True)
    return exit_code
