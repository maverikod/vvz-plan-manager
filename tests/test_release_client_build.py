"""Regression checks for the client packaging stage in ``scripts/release.sh``."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
import tomllib


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_root_dev_extra_includes_release_tooling() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = pyproject["project"]["optional-dependencies"]["dev"]

    assert "pytest>=9" in dev
    assert "build>=1" in dev
    assert "twine>=6" in dev


def test_release_script_fails_fast_when_release_tooling_is_missing() -> None:
    release = (REPO_ROOT / "scripts" / "release.sh").read_text(encoding="utf-8")

    assert 'echo "== stage: verify release tooling =="' in release
    assert '("build", "twine")' in release
    assert "install with pip install -e '\\''.[dev]'\\''" in release
    assert release.index('echo "== stage: verify release tooling =="') < release.index('echo "== stage: run test suite =="')


def test_release_script_builds_client_from_isolated_cwd_without_repo_pythonpath() -> None:
    release = (REPO_ROOT / "scripts" / "release.sh").read_text(encoding="utf-8")

    assert 'CLIENT_BUILD_CWD="$(mktemp -d)"' in release
    assert 'cd "${CLIENT_BUILD_CWD}"' in release
    assert 'PYTHONPATH="" "${PYTHON}" -m build --wheel --sdist' in release
    assert re.search(r'--outdir "\$\{REPO_ROOT\}/client/dist" "\$\{REPO_ROOT\}/client"', release)


def test_client_pyproject_uses_dynamic_version_from_root_source() -> None:
    pyproject = tomllib.loads((REPO_ROOT / "client" / "pyproject.toml").read_text(encoding="utf-8"))
    project = pyproject["project"]

    assert "version" not in project
    assert project["dynamic"] == ["version"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {
        "attr": "plan_manager_client._version.__version__"
    }


def test_client_version_helper_reads_root_pyproject_version_in_checkout() -> None:
    version_file = REPO_ROOT / "client" / "plan_manager_client" / "_version.py"
    spec = importlib.util.spec_from_file_location("test_plan_manager_client_version", version_file)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    root_version = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    assert module.version_from_source_tree(version_file) == root_version


def test_release_script_checks_distributions_and_uses_verbose_twine_upload() -> None:
    release = (REPO_ROOT / "scripts" / "release.sh").read_text(encoding="utf-8")

    assert 'echo "-- checking client distributions --"' in release
    assert '"${PYTHON}" -m twine check "client/dist/plan_manager_client-${VERSION}"*' in release
    assert '"${PYTHON}" -m twine upload --verbose "client/dist/plan_manager_client-${VERSION}"*' in release


def test_release_script_uses_root_version_as_client_version_source() -> None:
    release = (REPO_ROOT / "scripts" / "release.sh").read_text(encoding="utf-8")

    assert 'CLIENT_VERSION="${VERSION}"' in release
    assert 'client/pyproject.toml' not in release
    assert 'version mismatch: root pyproject.toml=' not in release
