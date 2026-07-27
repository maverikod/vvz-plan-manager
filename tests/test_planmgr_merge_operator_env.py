"""Regression tests for restoring operator planmgr env after conffile overwrite."""

from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "packaging" / "lib" / "planmgr_merge_operator_env.py"

spec = importlib.util.spec_from_file_location("planmgr_merge_operator_env", MODULE_PATH)
assert spec is not None and spec.loader is not None
merge_env = importlib.util.module_from_spec(spec)
spec.loader.exec_module(merge_env)


CURRENT_DEFAULT = """PLANMGR_IMAGE_REPO=vasilyvz/planmgr
PLANMGR_IMAGE_VERSION=0.1.68
PLANMGR_PORT=8080
PLANMGR_SERVER_PROTOCOL=https
PLANMGR_SERVER_NAME=planmgr
PLANMGR_ADVERTISED_HOST=
PLANMGR_REGISTRATION_ENABLED=false
PLANMGR_REGISTRATION_PROTOCOL=https
PLANMGR_REGISTRATION_URL=
PLANMGR_REGISTRATION_SERVER_ID=planmgr
PLANMGR_HEARTBEAT_INTERVAL=30
PLANMGR_DB_NAME=planmgr
PLANMGR_DB_USER=planmgr
PLANMGR_DB_PORT=5432
PLANMGR_EMBEDDING_URL=
PLANMGR_EMBEDDING_TIMEOUT=60.0
"""

PREVIOUS_OPERATOR = """PLANMGR_IMAGE_REPO=vasilyvz/planmgr
PLANMGR_IMAGE_VERSION=0.1.67
PLANMGR_PORT=15001
PLANMGR_SERVER_PROTOCOL=https
PLANMGR_SERVER_NAME=planmgr
PLANMGR_ADVERTISED_HOST=planmgr
PLANMGR_REGISTRATION_ENABLED=true
PLANMGR_REGISTRATION_PROTOCOL=https
PLANMGR_REGISTRATION_URL=https://mcp-proxy.techsup.od.ua:3004
PLANMGR_REGISTRATION_SERVER_ID=planmgr
PLANMGR_HEARTBEAT_INTERVAL=30
PLANMGR_DB_NAME=planmgr
PLANMGR_DB_USER=planmgr
PLANMGR_DB_PORT=5432
PLANMGR_EMBEDDING_URL=https://192.168.254.26:8001
PLANMGR_EMBEDDING_TIMEOUT=60.0
"""


def test_merge_operator_env_restores_registration_and_port_but_keeps_new_version() -> None:
    merged = merge_env.merge_operator_env_text(CURRENT_DEFAULT, PREVIOUS_OPERATOR)
    values = merge_env.parse_env(merged)

    assert values["PLANMGR_IMAGE_VERSION"] == "0.1.68"
    assert values["PLANMGR_PORT"] == "15001"
    assert values["PLANMGR_ADVERTISED_HOST"] == "planmgr"
    assert values["PLANMGR_REGISTRATION_ENABLED"] == "true"
    assert values["PLANMGR_REGISTRATION_URL"] == "https://mcp-proxy.techsup.od.ua:3004"
    assert values["PLANMGR_EMBEDDING_URL"] == "https://192.168.254.26:8001"


def test_merge_operator_env_is_noop_when_current_file_does_not_match_dangerous_defaults() -> None:
    current = CURRENT_DEFAULT.replace("PLANMGR_REGISTRATION_ENABLED=false", "PLANMGR_REGISTRATION_ENABLED=true")
    assert merge_env.merge_operator_env_text(current, PREVIOUS_OPERATOR) == current


def test_postinst_runs_merge_helper_before_sourcing_envfile() -> None:
    postinst = (REPO_ROOT / "packaging" / "deb" / "postinst").read_text(encoding="utf-8")
    helper_call = "python3 /usr/lib/planmgr/planmgr_merge_operator_env.py"
    source_call = ". /etc/default/planmgr"

    assert helper_call in postinst
    assert postinst.index(helper_call) < postinst.index(source_call)


def test_release_pipeline_stages_merge_helper_into_deb() -> None:
    release = (REPO_ROOT / "scripts" / "release.sh").read_text(encoding="utf-8")
    assert "mkdir -p build/deb/usr/lib/planmgr" in release
    assert "cp packaging/lib/planmgr_merge_operator_env.py build/deb/usr/lib/planmgr/planmgr_merge_operator_env.py" in release
