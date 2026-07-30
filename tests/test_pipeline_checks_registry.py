"""Pipeline-check registry suite (CR-6 G-006/T-001/A-002).

Assertions over the registry data structure only: no subprocess runs, no pytest
recursion, no database.
"""

from __future__ import annotations

import importlib
import pathlib
import subprocess

import pytest

from plan_manager.pipeline_checks import registry
from plan_manager.pipeline_checks.registry import CHECKS, PipelineCheckSpec, get_check

_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

_CR6_CHECKS = (
    "cr6-identity-registry",
    "cr6-entity-contract",
    "cr6-deletion-references",
    "cr6-migrations-audit",
)

# Baseline copied from the registry as it stood before CR-6 added its slice
# checks. A name disappearing from here means a check the pipeline used to run
# silently stopped running.
_PRE_CR6_CHECKS = frozenset(
    {
        "context-block-rebuild",
        "gate-object-inventory",
        "gate-object-concepts",
        "graph-parallel-map",
        "object-declaration-shape",
        "release-client-build",
        "repo-tests",
        "pagination-contract",
        "command-surface",
        "pipeline-cli",
        "live-smoke-r7",
        "wish-calendar",
        "runtime-record-updates",
    }
)


def _names() -> list[str]:
    return [spec.name for spec in CHECKS]


def test_cr6_checks_registered() -> None:
    registered = _names()
    missing = [name for name in _CR6_CHECKS if name not in registered]
    assert missing == [], f"CR-6 slice checks absent from the registry: {missing}"
    for name in _CR6_CHECKS:
        spec = get_check(name)
        assert isinstance(spec, PipelineCheckSpec)
        assert spec.description, f"{name} carries no description"


@pytest.mark.parametrize("name", _CR6_CHECKS)
def test_cr6_checks_map_to_existing_suites(name: str) -> None:
    spec = get_check(name)
    suites = [argument for argument in spec.argv if argument.startswith("tests/")]
    assert suites, f"{name} names no test suite"
    for suite in suites:
        assert (_REPO_ROOT / suite).is_file(), (
            f"{name} points at {suite}, which does not exist; the check would pass "
            "vacuously or error on collection"
        )


def test_every_cr6_suite_is_claimed_by_exactly_one_check() -> None:
    """No suite may be run twice by the slice checks, and none may be orphaned."""
    claimed: dict[str, str] = {}
    for name in _CR6_CHECKS:
        for suite in get_check(name).argv:
            if not suite.startswith("tests/"):
                continue
            assert suite not in claimed, (
                f"{suite} is claimed by both {claimed[suite]} and {name}"
            )
            claimed[suite] = name
    assert claimed, "the CR-6 checks claim no suites at all"


def test_no_existing_check_lost() -> None:
    registered = set(_names())
    lost = sorted(_PRE_CR6_CHECKS - registered)
    assert lost == [], f"pre-CR-6 checks removed from the registry: {lost}"


def test_check_names_are_unique_and_ordered_after_the_baseline() -> None:
    names = _names()
    assert len(names) == len(set(names)), "duplicate check names in the registry"
    # The CR-6 checks were appended; the pre-existing order is untouched.
    baseline_positions = [names.index(name) for name in names if name in _PRE_CR6_CHECKS]
    cr6_positions = [names.index(name) for name in _CR6_CHECKS]
    assert max(baseline_positions) < min(cr6_positions), (
        "the CR-6 checks must be appended, not interleaved with the baseline"
    )


def test_registry_importable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Importing the registry must not run anything."""

    def _forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("the registry executed a subprocess at import time")

    monkeypatch.setattr(subprocess, "run", _forbidden)
    monkeypatch.setattr(subprocess, "Popen", _forbidden)

    reloaded = importlib.reload(registry)
    assert reloaded.CHECKS, "the reloaded registry is empty"
    assert reloaded.repo_root().is_dir()
    assert reloaded.default_checks() == reloaded.CHECKS
