"""CR-7 G-004/T-002/A-002: the cr7-no-out-of-mechanism-write pipeline check.

Unit suite over the scan behind the check: registration in the pipeline
registry, RED on a planted unmarked INSERT/DELETE (tmp fixture trees, per the
cr6 checks' no-subprocess testing convention), the compatibility-marker
window, mechanism-file read-only consumption, and the real tree's current
sweep state.

The check itself is deliberately NOT wired as a pytest suite: G-004 mandates
it be RED while any module still writes beside the mechanism, and a failing
pytest suite would drag the repo-tests check red with it. These tests assert
the scan's behavior; the pipeline check runs the scan as its own subprocess.
"""

from __future__ import annotations

import pathlib

from plan_manager.pipeline_checks.registry import (
    CHECKS,
    G004WriteFinding,
    g004_scan,
    g004_scan_main,
    get_check,
)

_CHECK_NAME = "cr7-no-out-of-mechanism-write"

# NOTE on string literals below: fixture files planted in tmp trees are the
# only place this suite spells a full write statement; tests/ is outside the
# scanned package, so these literals can never turn the real check red.


def _plant(tree: pathlib.Path, rel: str, text: str) -> None:
    target = tree / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def _fixture_package(tmp_path: pathlib.Path) -> pathlib.Path:
    package = tmp_path / "plan_manager"
    package.mkdir()
    return package


def test_check_registered_in_pipeline_registry() -> None:
    spec = get_check(_CHECK_NAME)
    assert spec.description
    # The check runs the scan entrypoint in its own subprocess (see module
    # docstring for why it is not a pytest suite like the cr6-* checks).
    assert any("g004_scan_main" in argument for argument in spec.argv)
    assert spec.name in [check.name for check in CHECKS]


def test_red_on_planted_unmarked_insert(tmp_path, capsys) -> None:
    package = _fixture_package(tmp_path)
    _plant(
        package,
        "storage/rogue_store.py",
        'def create(conn):\n'
        '    conn.execute("INSERT INTO plan (uuid, name) VALUES (%s, %s)")\n',
    )

    offenders, known_exceptions = g004_scan(package)

    assert known_exceptions == []
    assert [finding.path for finding in offenders] == ["plan_manager/storage/rogue_store.py"]
    assert offenders[0].line == 2

    assert g004_scan_main(package) == 1
    out = capsys.readouterr().out
    # G-004: the check fails LISTING every offending file and statement.
    assert "plan_manager/storage/rogue_store.py:2" in out
    assert "INSERT INTO plan" in out
    assert "RED" in out


def test_red_on_planted_unmarked_delete(tmp_path) -> None:
    package = _fixture_package(tmp_path)
    _plant(
        package,
        "domain/rogue_ops.py",
        'def purge(conn, todo_uuid):\n'
        '    conn.execute("DELETE FROM todo_item WHERE uuid = %s", (todo_uuid,))\n',
    )

    offenders, _ = g004_scan(package)

    assert [finding.path for finding in offenders] == ["plan_manager/domain/rogue_ops.py"]
    assert g004_scan_main(package) == 1


def test_marked_write_is_known_exception_not_offender(tmp_path, capsys) -> None:
    package = _fixture_package(tmp_path)
    _plant(
        package,
        "domain/compat_store.py",
        'def replace(conn, plan_uuid):\n'
        '    # CR-7 G-004 compatibility note: documented set-replacement delete.\n'
        '    conn.execute("DELETE FROM paragraph WHERE plan_uuid = %s", (plan_uuid,))\n',
    )

    offenders, known_exceptions = g004_scan(package)

    assert offenders == []
    assert [finding.path for finding in known_exceptions] == ["plan_manager/domain/compat_store.py"]

    assert g004_scan_main(package) == 0
    out = capsys.readouterr().out
    # Known exceptions are reported, and the check still passes.
    assert "known exception" in out
    assert "GREEN" in out


def test_marker_outside_ten_line_window_does_not_shield(tmp_path) -> None:
    package = _fixture_package(tmp_path)
    filler = "\n".join(f"    x{i} = {i}" for i in range(11))
    _plant(
        package,
        "domain/stale_marker.py",
        'def replace(conn, plan_uuid):\n'
        '    # CR-7 G-004 compatibility note: too far above to count.\n'
        f'{filler}\n'
        '    conn.execute("DELETE FROM paragraph WHERE plan_uuid = %s", (plan_uuid,))\n',
    )

    offenders, known_exceptions = g004_scan(package)

    assert known_exceptions == []
    assert [finding.path for finding in offenders] == ["plan_manager/domain/stale_marker.py"]


def test_mechanism_files_are_consumed_read_only(tmp_path) -> None:
    package = _fixture_package(tmp_path)
    # The engine's own INSERT never counts: mechanism files are allowed writers.
    _plant(
        package,
        "domain/entity.py",
        'def crud_create(conn):\n'
        '    conn.execute("INSERT INTO plan (uuid, name) VALUES (%s, %s)")\n',
    )

    offenders, known_exceptions = g004_scan(package)

    assert offenders == []
    assert known_exceptions == []
    assert g004_scan_main(package) == 0


def test_unregistered_table_is_not_flagged(tmp_path) -> None:
    package = _fixture_package(tmp_path)
    # embedding_cache is in EXCLUDED_TABLES, not the closed entity registry.
    _plant(
        package,
        "scoring/cache.py",
        'def store(conn):\n'
        '    conn.execute("INSERT INTO embedding_cache (uuid, vector) VALUES (%s, %s)")\n',
    )

    offenders, known_exceptions = g004_scan(package)

    assert offenders == []
    assert known_exceptions == []


def test_registered_prefix_of_longer_table_name_is_not_flagged(tmp_path) -> None:
    package = _fixture_package(tmp_path)
    # "step" is registered; "step_runtime" is excluded -- the trailing word
    # boundary must keep the shorter name from matching inside the longer one.
    _plant(
        package,
        "domain/step_runtime_seat.py",
        'def upsert(conn):\n'
        '    conn.execute("INSERT INTO step_runtime (step_uuid) VALUES (%s)")\n',
    )

    offenders, known_exceptions = g004_scan(package)

    assert offenders == []
    assert known_exceptions == []


def test_prose_mentions_never_match(tmp_path) -> None:
    package = _fixture_package(tmp_path)
    # Case-sensitivity guard: real statements are uppercase; prose is not.
    _plant(
        package,
        "storage/documented_store.py",
        'def create(conn):\n'
        '    # INSERT into review_result table happens in the engine now.\n'
        '    """This function used to issue an insert into todo_item."""\n',
    )

    offenders, known_exceptions = g004_scan(package)

    assert offenders == []
    assert known_exceptions == []


def test_dynamic_target_outside_mechanism_needs_the_marker(tmp_path) -> None:
    package = _fixture_package(tmp_path)
    # A dynamically-composed target in a non-mechanism file is conservatively
    # a registered-table write; without the marker it is an offender.
    _plant(
        package,
        "cascade/rollback.py",
        'def wipe(conn, table, node_uuid):\n'
        '    conn.execute(f"DELETE FROM {table} WHERE uuid = %s", (node_uuid,))\n',
    )

    offenders, _ = g004_scan(package)

    assert [finding.path for finding in offenders] == ["plan_manager/cascade/rollback.py"]


def test_findings_are_value_objects() -> None:
    finding = G004WriteFinding(path="plan_manager/x.py", line=3, statement="s")
    assert (finding.path, finding.line, finding.statement) == ("plan_manager/x.py", 3, "s")


# ---------------------------------------------------------------------------
# Real-tree assertions: the scan's view of THIS repository.
# ---------------------------------------------------------------------------


def test_real_tree_reports_the_w05_documented_exceptions() -> None:
    _, known_exceptions = g004_scan()
    paths = {finding.path for finding in known_exceptions}
    # Three of W05's four documented exceptions carry the in-code marker; the
    # fourth (identity.py unregister_entity_identity) lives inside a mechanism
    # file, which the scan consumes read-only and never reports.
    assert {
        "plan_manager/domain/paragraph_store.py",
        "plan_manager/domain/step_ops.py",
        "plan_manager/cascade/restore.py",
    } <= paths


def test_real_tree_current_sweep_state() -> None:
    """Truthful sweep-complete snapshot.

    W05 ("route all 32 write modules") left two direct writes that appeared in
    neither its routed list nor its four documented compatibility exceptions:
    step_store.create_step and context_blocks.store_context_block. Both are
    now routed through the unified engine's crud_create (todo a01520c9), so
    the sweep is complete and this set is empty; the check is GREEN and this
    test keeps guarding against new offenders.
    """
    offenders, _ = g004_scan()
    assert {finding.path for finding in offenders} == set(), [
        f"{finding.path}:{finding.line}: {finding.statement}" for finding in offenders
    ]
