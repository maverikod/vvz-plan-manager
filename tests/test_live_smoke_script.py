"""Unit tests for scripts/live_smoke.py's pure (network-free) logic.

Covers: catalog classification into pipeline tiers (including the
zero-uncovered-command invariant against the shipped client's own
COMMAND_NAMES catalog), the tier-2 scoped-params builder, the
Summary/exit-code computation, the base-url/protocol parsing helper, and
the mTLS auto-upgrade in build_config. None of these tests touch the
network or import asyncio -- the script's networked coroutines
(run_tier0/run_tier1/... /run_pipeline) are exercised only against a live
server, out of scope for this suite.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
CLIENT_SRC = REPO_ROOT / "client"
for _p in (str(SCRIPTS_DIR), str(CLIENT_SRC)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import live_smoke as ls  # noqa: E402
from plan_manager_client.server_api import COMMAND_NAMES  # noqa: E402


# --------------------------------------------------------------------------
# classify_catalog
# --------------------------------------------------------------------------


def test_classify_catalog_excludes_help():
    result = ls.classify_catalog(frozenset({"help", "plan_list"}))
    all_names = (
        result.tier2_static
        + result.tier2_scoped
        + result.tier3_handled
        + result.tier4_handled
        + [n for n, _ in result.skipped]
    )
    assert "help" not in all_names


def test_classify_catalog_static_command_lands_in_tier2_static():
    result = ls.classify_catalog(frozenset({"plan_list", "info"}))
    assert "plan_list" in result.tier2_static
    assert "info" in result.tier2_static
    assert result.tier2_scoped == []
    assert result.skipped == []


def test_classify_catalog_scoped_command_lands_in_tier2_scoped():
    result = ls.classify_catalog(frozenset({"step_get", "bug_get"}))
    assert "step_get" in result.tier2_scoped
    assert "bug_get" in result.tier2_scoped


def test_classify_catalog_handled_command_excluded_from_skip_and_present_in_both_tiers():
    # step_create, plan_create, plan_delete, todo_create are mutating and
    # named in BOTH TIER3_HANDLED and TIER4_HANDLED -- neither should ever
    # appear in the skip list.
    result = ls.classify_catalog(frozenset({"step_create", "plan_create", "plan_delete", "todo_create"}))
    skipped_names = {n for n, _ in result.skipped}
    assert skipped_names.isdisjoint({"step_create", "plan_create", "plan_delete", "todo_create"})
    assert "step_create" in result.tier3_handled and "step_create" in result.tier4_handled
    assert "plan_create" in result.tier3_handled and "plan_create" in result.tier4_handled


def test_classify_catalog_known_skip_gets_specific_reason_not_generic():
    result = ls.classify_catalog(frozenset({"export_cleanup"}))
    assert result.skipped == [("export_cleanup", ls.KNOWN_SKIP_REASONS["export_cleanup"])]
    assert result.skipped[0][1] != ls.GENERIC_SKIP_REASON


def test_classify_catalog_unknown_command_gets_generic_reason():
    result = ls.classify_catalog(frozenset({"some_future_command_not_yet_seen"}))
    assert result.skipped == [("some_future_command_not_yet_seen", ls.GENERIC_SKIP_REASON)]


def test_classify_catalog_covers_every_shipped_command_name():
    """Zero-uncovered invariant: every name the shipped client facade
    declares (plan_manager_client.server_api.COMMAND_NAMES) must land in
    exactly one tier bucket or the skip list with a reason -- never silently
    dropped. project_view is intentionally NOT in COMMAND_NAMES yet (it is
    landing in parallel with this script) and is tested separately below.
    """
    result = ls.classify_catalog(frozenset(COMMAND_NAMES))
    covered = (
        set(result.tier2_static)
        | set(result.tier2_scoped)
        | set(result.tier3_handled)
        | set(result.tier4_handled)
        | {n for n, _ in result.skipped}
    )
    missing = (set(COMMAND_NAMES) - {"help"}) - covered
    assert missing == set(), f"uncategorized commands (would be silently capped): {missing}"


def test_classify_catalog_no_generic_reason_among_shipped_commands():
    """Every shipped command that is skipped should have an explicit,
    specific reason -- the generic fallback is reserved for names this
    script has genuinely never seen (e.g. added after this script was
    written)."""
    result = ls.classify_catalog(frozenset(COMMAND_NAMES))
    generic = [name for name, reason in result.skipped if reason == ls.GENERIC_SKIP_REASON]
    assert generic == [], f"shipped commands falling back to the generic skip reason: {generic}"


def test_classify_catalog_project_view_absent_is_not_silently_dropped():
    # project_view is not yet in COMMAND_NAMES; when present in a live
    # catalog it must be recognized as TIER4_HANDLED (R3), never skipped.
    result = ls.classify_catalog(frozenset(COMMAND_NAMES | {"project_view"}))
    assert "project_view" in result.tier4_handled
    assert "project_view" not in {n for n, _ in result.skipped}


# --------------------------------------------------------------------------
# scoped_params
# --------------------------------------------------------------------------


def test_scoped_params_missing_entity_returns_none():
    assert ls.scoped_params("step_get", {}) is None
    assert ls.scoped_params("step_get", {"plan": "p"}) is None  # missing "step"


def test_scoped_params_non_scoped_command_returns_none():
    assert ls.scoped_params("plan_list", {"plan": "p"}) is None


def test_scoped_params_plan_only_shape():
    assert ls.scoped_params("plan_status", {"plan": "p-uuid"}) == {"plan": "p-uuid"}


def test_scoped_params_step_scoped_shape():
    params = ls.scoped_params("step_get", {"plan": "p-uuid", "step": "G-001"})
    assert params == {"plan": "p-uuid", "step_id": "G-001"}


def test_scoped_params_graph_dependents_includes_direction():
    params = ls.scoped_params("graph_dependents", {"plan": "p-uuid", "step": "G-001"})
    assert params == {"plan": "p-uuid", "step_id": "G-001", "direction": "downstream"}


def test_scoped_params_block_get_shape():
    params = ls.scoped_params("block_get", {"plan": "p-uuid", "block": "blk-1"})
    assert params == {"plan": "p-uuid", "block_id": "blk-1"}


def test_scoped_params_bug_and_todo_shapes():
    assert ls.scoped_params("todo_get", {"todo": "t-uuid"}) == {"todo": "t-uuid"}
    assert ls.scoped_params("bug_get", {"bug": "b-uuid"}) == {"bug_id": "b-uuid"}
    assert ls.scoped_params("bug_impact_list", {"bug": "b-uuid"}) == {"bug_id": "b-uuid"}
    assert ls.scoped_params("bug_fix_list", {"bug": "b-uuid"}) == {"bug": "b-uuid"}


def test_scoped_params_project_dependents_shape():
    assert ls.scoped_params("project_dependents", {"project": "proj-uuid"}) == {"project_id": "proj-uuid"}


# --------------------------------------------------------------------------
# CheckResult / Summary / compute_summary
# --------------------------------------------------------------------------


def test_compute_summary_counts_and_exit_code_all_pass():
    results = [
        ls.CheckResult("0", "a", ls.STATUS_PASS),
        ls.CheckResult("1", "b", ls.STATUS_PASS),
    ]
    summary = ls.compute_summary(results)
    assert summary.exit_code() == 0
    d = summary.to_dict()
    assert d["counts"] == {"pass": 2, "fail": 0, "skip": 0}
    assert d["failed"] == []


def test_compute_summary_any_failure_yields_nonzero_exit_code():
    results = [
        ls.CheckResult("0", "a", ls.STATUS_PASS),
        ls.CheckResult("2", "b", ls.STATUS_FAIL, "boom"),
        ls.CheckResult("2", "c", ls.STATUS_SKIP, "not exercised"),
    ]
    summary = ls.compute_summary(results)
    assert summary.exit_code() == 1
    d = summary.to_dict()
    assert d["counts"] == {"pass": 1, "fail": 1, "skip": 1}
    assert d["failed"] == ["b"]
    assert d["skipped"] == [{"name": "c", "reason": "not exercised"}]


def test_summary_skip_only_does_not_fail_exit_code():
    results = [ls.CheckResult("2", "x", ls.STATUS_SKIP, "reason")]
    summary = ls.compute_summary(results)
    assert summary.exit_code() == 0


def test_summary_render_text_lists_failures_and_skip_reasons():
    results = [
        ls.CheckResult("2", "ok_check", ls.STATUS_PASS),
        ls.CheckResult("2", "bad_check", ls.STATUS_FAIL, "something broke"),
        ls.CheckResult("2", "skipped_check", ls.STATUS_SKIP, "destructive, not run"),
    ]
    text = ls.compute_summary(results).render_text()
    assert "bad_check" in text
    assert "something broke" in text
    assert "skipped_check" in text
    assert "destructive, not run" in text
    assert "1 passed, 1 failed, 1 skipped" in text


def test_check_result_line_omits_empty_detail():
    r = ls.CheckResult("0", "clean_pass", ls.STATUS_PASS)
    assert r.line() == "[PASS] 0      clean_pass"


# --------------------------------------------------------------------------
# unique_suffix
# --------------------------------------------------------------------------


def test_unique_suffix_has_prefix_and_tag():
    value = ls.unique_suffix("plan")
    assert value.startswith(ls.PREFIX)
    assert "plan" in value


def test_unique_suffix_is_unique_across_calls():
    assert ls.unique_suffix("todo") != ls.unique_suffix("todo")


# --------------------------------------------------------------------------
# base-url parsing / build_config (construction only, no connection opened)
# --------------------------------------------------------------------------


def test_protocol_from_base_url_https_default_port():
    protocol, host, port = ls._protocol_from_base_url("https://192.168.1.5:8443")
    assert (protocol, host, port) == ("https", "192.168.1.5", 8443)


def test_protocol_from_base_url_defaults_port_by_scheme():
    protocol, host, port = ls._protocol_from_base_url("https://example.test")
    assert (protocol, host, port) == ("https", "example.test", 443)
    protocol, host, port = ls._protocol_from_base_url("http://example.test")
    assert (protocol, host, port) == ("http", "example.test", 80)


class _Args:
    """Minimal stand-in for argparse.Namespace, only the attrs build_config reads."""

    def __init__(self, **kwargs):
        defaults = dict(
            base_url=None, protocol="https", protocol_override=None,
            host="127.0.0.1", port=8080, cert=None, key=None, ca=None, timeout=30.0,
        )
        defaults.update(kwargs)
        for k, v in defaults.items():
            setattr(self, k, v)


def test_build_config_plain_https_no_cert():
    config = ls.build_config(_Args())
    assert config.protocol == "https"
    assert config.host == "127.0.0.1"
    assert config.port == 8080


def test_build_config_upgrades_https_to_mtls_when_cert_and_key_present():
    config = ls.build_config(_Args(cert="/tmp/c.crt", key="/tmp/c.key"))
    assert config.protocol == "mtls"


def test_build_config_base_url_overrides_host_port_protocol():
    config = ls.build_config(_Args(base_url="http://10.0.0.9:9000"))
    assert (config.protocol, config.host, config.port) == ("http", "10.0.0.9", 9000)


def test_build_config_explicit_override_wins_over_base_url():
    config = ls.build_config(_Args(base_url="http://10.0.0.9:9000", protocol_override="mtls"))
    assert config.protocol == "mtls"


# --------------------------------------------------------------------------
# CLI arg parser sanity (construction only, no execution)
# --------------------------------------------------------------------------


def test_build_arg_parser_defaults():
    parser = ls.build_arg_parser()
    args = parser.parse_args([])
    assert args.protocol == "https"
    assert args.host == "127.0.0.1"
    assert args.port == 8080
    assert args.project == ls.DEFAULT_PROJECT_ID
    assert args.json is False


def test_build_arg_parser_rejects_unknown_protocol():
    parser = ls.build_arg_parser()
    try:
        parser.parse_args(["--protocol", "carrier-pigeon"])
    except SystemExit as exc:
        assert exc.code != 0
    else:
        raise AssertionError("expected argparse to reject an invalid --protocol choice")
