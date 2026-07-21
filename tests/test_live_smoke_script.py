"""Unit tests for scripts/live_smoke.py's pure (network-free) logic.

Covers: catalog classification into pipeline tiers (including the
zero-uncovered-command invariant against the shipped client's own
COMMAND_NAMES catalog), the tier-2 scoped-params builder, the
Summary/exit-code computation, the base-url/protocol parsing helper, the
mTLS auto-upgrade in build_config, and the queue/success envelope
unwrapping (unwrap_envelope + call()) added to fix a real first-live-run
defect against the deployed 0.1.52 server: every command comes back as a
queued-job envelope, sometimes nested one layer deeper than the shipped
adapter's own unwrap handles, and info/help's failure surfaced as a
mis-shaped success rather than a real error. `call()` is exercised here
against a minimal fake client (no real network) via `asyncio.run` --
none of these tests reach an actual server; the script's other networked
coroutines (run_tier0/run_tier1/.../run_pipeline) are exercised only
against a live server, out of scope for this suite.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

import asyncio
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


# --------------------------------------------------------------------------
# unwrap_envelope -- fix for the first-live-run defect against 0.1.52: every
# command comes back as a queued-job envelope (even instant reads like
# info/help), sometimes nested one layer deeper than the shipped adapter's
# own unwrap peels off. Cases below reproduce the exact evidence shapes.
# --------------------------------------------------------------------------


def test_unwrap_envelope_plain_data_passthrough():
    data = {"identity": {"package_version": "0.1.52"}}
    assert ls.unwrap_envelope(data) == (True, data)


def test_unwrap_envelope_non_dict_passthrough():
    assert ls.unwrap_envelope("already-plain-string") == (True, "already-plain-string")
    assert ls.unwrap_envelope(None) == (True, None)


def test_unwrap_envelope_single_success_data_layer():
    envelope = {"success": True, "data": {"uuid": "abc"}}
    assert ls.unwrap_envelope(envelope) == (True, {"uuid": "abc"})


def test_unwrap_envelope_success_false_is_failure_with_error_surfaced():
    envelope = {"success": False, "error": "STEP_NOT_FOUND: no such step"}
    assert ls.unwrap_envelope(envelope) == (False, "STEP_NOT_FOUND: no such step")


def test_unwrap_envelope_success_false_without_error_key_surfaces_whole_envelope():
    envelope = {"success": False}
    assert ls.unwrap_envelope(envelope) == (False, envelope)


def test_unwrap_envelope_queued_completed_single_nested_success_data():
    # One layer of queue wrapper around one layer of success/data -- the
    # shape the shipped adapter's own unwrap already handles correctly.
    envelope = {
        "mode": "queued", "job_id": "j1", "command": "step_get", "queued": True,
        "status": "completed", "result": {"success": True, "data": {"step_id": "G-001"}},
    }
    assert ls.unwrap_envelope(envelope) == (True, {"step_id": "G-001"})


def test_unwrap_envelope_queued_completed_double_nested_reproduces_live_evidence():
    """Exact shape from the first live run against 0.1.52's info command:
    the queue envelope's own job_id/command/status sit ALONGSIDE what should
    have been the plain success/data result -- one layer deeper than the
    shipped adapter's own unwrap check (which only looks for "data" at the
    top of ``result``) expects. Must still fully unwrap to plain data."""
    envelope = {
        "job_id": "47c20a2c-0000-0000-0000-000000000000",
        "command": "info",
        "result": {
            "success": True,
            "data": {
                "identity": {"product": "plan_manager", "package_version": "0.1.52"},
                "build": {"build_date": "2026-07-01"},
            },
        },
        "status": "completed",
        "queued": True,
    }
    ok, data = ls.unwrap_envelope(envelope)
    assert ok is True
    assert data == {
        "identity": {"product": "plan_manager", "package_version": "0.1.52"},
        "build": {"build_date": "2026-07-01"},
    }


def test_unwrap_envelope_queued_non_completed_status_is_failure():
    """Reproduces the "help" catalog_fetch failure shape: a queue envelope
    whose status never reached "completed" must be reported as a failure,
    with the full envelope preserved for diagnosis -- not silently treated
    as success."""
    envelope = {"job_id": "c0bab142-0000", "command": "help", "status": "failed", "result": {}}
    ok, diagnostic = ls.unwrap_envelope(envelope)
    assert ok is False
    assert diagnostic == envelope


def test_unwrap_envelope_queued_pending_status_is_failure_not_success():
    envelope = {"job_id": "j2", "command": "info", "status": "pending", "result": None, "mode": "queued"}
    ok, diagnostic = ls.unwrap_envelope(envelope)
    assert ok is False
    assert diagnostic == envelope


def test_unwrap_envelope_recognizes_command_completed_and_job_completed_aliases():
    for alias in ("command_completed", "job_completed"):
        envelope = {"job_id": "j", "status": alias, "result": {"x": 1}}
        assert ls.unwrap_envelope(envelope) == (True, {"x": 1})


def test_unwrap_envelope_max_depth_guard_never_infinite_loops():
    # A pathological self-referential-looking shape (queue wrapper whose
    # "result" is itself an identical queue wrapper, forever) must terminate
    # as a reported failure rather than hang.
    cyclical = {"job_id": "j", "status": "completed", "result": None}
    cyclical["result"] = cyclical  # type: ignore[assignment]
    ok, diagnostic = ls.unwrap_envelope(cyclical)
    assert ok is False
    assert isinstance(diagnostic, dict)


# --------------------------------------------------------------------------
# call() -- the async wrapper around client._call + unwrap_envelope +
# exception .details surfacing. Exercised against a minimal fake client
# (no real network) via asyncio.run.
# --------------------------------------------------------------------------


class _FakeClient:
    def __init__(self, outcome):
        self._outcome = outcome

    async def _call(self, name, params=None):
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome


class _FakeErrorWithDetails(Exception):
    def __init__(self, message, details=None):
        super().__init__(message)
        self.details = details or {}


def test_call_success_path_unwraps_queued_envelope():
    envelope = {
        "job_id": "j1", "command": "info", "status": "completed", "queued": True,
        "result": {"success": True, "data": {"identity": {"package_version": "0.1.52"}}},
    }
    client = _FakeClient(envelope)
    ok, data = asyncio.run(ls.call(client, "info", {}))
    assert ok is True
    assert data == {"identity": {"package_version": "0.1.52"}}


def test_call_non_completed_status_reports_failure():
    envelope = {"job_id": "j2", "command": "help", "status": "failed", "result": {}}
    client = _FakeClient(envelope)
    ok, message = asyncio.run(ls.call(client, "help", {}))
    assert ok is False
    assert "non-success/incomplete envelope" in message
    assert "'status': 'failed'" in message


def test_call_exception_includes_details_verbatim():
    exc = _FakeErrorWithDetails(
        "Queued command 'help' failed (job_id=c0bab142-0000)",
        details={"terminal_event": {"event": "command_failed"}, "result_status": {"error": "boom"}},
    )
    client = _FakeClient(exc)
    ok, message = asyncio.run(ls.call(client, "help", {}))
    assert ok is False
    assert "Queued command 'help' failed" in message
    assert "terminal_event" in message
    assert "command_failed" in message


def test_call_exception_without_details_still_reports_str():
    client = _FakeClient(RuntimeError("plain transport error"))
    ok, message = asyncio.run(ls.call(client, "plan_list", {}))
    assert ok is False
    assert message == "plain transport error"
