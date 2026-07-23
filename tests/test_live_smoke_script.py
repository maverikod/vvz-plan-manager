"""Unit tests for scripts/live_smoke.py's pure (network-free) logic.

Covers: catalog classification into pipeline tiers (including the
zero-uncovered-command invariant against the shipped client's own
COMMAND_NAMES catalog), the tier-2 scoped-params builder, the
Summary/exit-code computation, the base-url/protocol parsing helper, the
mTLS auto-upgrade in build_config, the queue/success envelope unwrapping
(unwrap_envelope + call()) added to fix the FIRST-live-run defect (every
command comes back as a queued-job envelope, sometimes nested one layer
deeper than the shipped adapter's own unwrap handles), the builtin-vs-
domain dispatch routing (KNOWN_BUILTIN_COMMANDS, _looks_like_unresolved_
command, the direct-path fallback, DISPATCH_LOG) added to fix the SECOND
live-run defect (`help` is an adapter-framework builtin not registered in
the server's queue-executor registry), and the THIRD-live-run fixes:
create/cleanup phase splitting for the plan/step and todo lifecycles (so
Tier-2-scoped reads run while their throwaway entities are still alive,
instead of after Tier 3's own cleanup had already deleted them --
PLAN_NOT_FOUND across every plan-scoped probe live), the corrected
step_search/graph_dependents recipes, the bug_fix_create/bug_fix_verify
chain bug_close actually requires, the corrected R2 level-3/4/5 step
chain (a prior attempt skipped level 4, live evidence: GRAPH_CORRUPTED_
CHAIN), and specific (non-generic) skip reasons for adapter-builtin/admin/
transfer/stub commands. `call()` and the tier-3/regression coroutines are
exercised here against fake clients (no real network) via `asyncio.run` --
none of these tests reach an actual server; run_pipeline's own top-level
orchestration is exercised only against a live server, out of scope for
this suite.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com
"""

from __future__ import annotations

import asyncio
import json
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


def test_classify_catalog_bug_fix_and_step_update_moved_out_of_skip():
    # Third live run: bug_close needs the full documented close path
    # (bug_fix_create -> bug_fix_verify) and R2 needs step_update to set
    # target_file -- all three are now actively invoked, not skipped.
    result = ls.classify_catalog(frozenset({"bug_fix_create", "bug_fix_verify", "step_update"}))
    skipped_names = {n for n, _ in result.skipped}
    assert skipped_names.isdisjoint({"bug_fix_create", "bug_fix_verify", "step_update"})
    assert {"bug_fix_create", "bug_fix_verify", "step_update"} <= set(result.tier3_handled) | set(result.tier4_handled)


# --------------------------------------------------------------------------
# Third-live-run "cosmetic" fix: every adapter-builtin/admin/transfer/stub
# command must have a SPECIFIC skip reason, not the generic fallback --
# and each such command has exactly one disposition (it must NOT also be
# in TIER2_STATIC_PARAMS/TIER2_SCOPED_NEEDS, which would silently mask its
# skip reason since classify_catalog checks those first).
# --------------------------------------------------------------------------

_THIRD_RUN_COSMETIC_COMMANDS = (
    "proxy_registration",
    "queue_add_job", "queue_delete_job", "queue_get_job_logs", "queue_get_job_status",
    "queue_health", "queue_list_jobs", "queue_start_job", "queue_stop_job",
    "reload", "roletest", "settings",
    "transfer_download_begin", "transfer_download_status",
    "transfer_upload_begin", "transfer_upload_complete", "transfer_upload_status",
    "transport_management", "unload",
)


def test_third_run_cosmetic_commands_have_specific_not_generic_skip_reasons():
    result = ls.classify_catalog(frozenset(_THIRD_RUN_COSMETIC_COMMANDS))
    reasons = dict(result.skipped)
    assert set(reasons) == set(_THIRD_RUN_COSMETIC_COMMANDS)
    for name, reason in reasons.items():
        assert reason != ls.GENERIC_SKIP_REASON, f"{name} still falls back to the generic reason"


def test_third_run_cosmetic_commands_have_exactly_one_disposition():
    # None of these may ALSO appear in TIER2_STATIC_PARAMS/TIER2_SCOPED_NEEDS
    # (queue_health in particular was flagged live as appearing in both a
    # routing set and the skip list -- KNOWN_BUILTIN_COMMANDS is a separate,
    # orthogonal routing concern from classify_catalog's tiers, but a name
    # must never ALSO be actively probed while also carrying a skip reason).
    for name in _THIRD_RUN_COSMETIC_COMMANDS:
        assert name not in ls.TIER2_STATIC_PARAMS, f"{name} is both skipped and actively probed (tier2_static)"
        assert name not in ls.TIER2_SCOPED_NEEDS, f"{name} is both skipped and actively probed (tier2_scoped)"


def test_queue_family_reasons_reference_builtin_routing():
    for name in (
        "queue_add_job", "queue_delete_job", "queue_get_job_logs", "queue_get_job_status",
        "queue_health", "queue_list_jobs", "queue_start_job", "queue_stop_job",
    ):
        assert "queue" in ls.KNOWN_SKIP_REASONS[name].lower()
        assert name in ls.KNOWN_BUILTIN_COMMANDS


def test_admin_surface_reasons_mention_exclusion_by_design():
    for name in ("reload", "unload", "settings", "transport_management", "proxy_registration"):
        assert "admin" in ls.KNOWN_SKIP_REASONS[name].lower()


def test_transfer_reasons_mention_peer_endpoint_or_existing_session():
    for name in (
        "transfer_download_begin", "transfer_download_status",
        "transfer_upload_begin", "transfer_upload_complete", "transfer_upload_status",
    ):
        reason = ls.KNOWN_SKIP_REASONS[name].lower()
        assert "peer" in reason or "session" in reason


def test_roletest_reason_names_it_a_diagnostic_stub():
    assert "diagnostic" in ls.KNOWN_SKIP_REASONS["roletest"].lower()


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
    # Confirmed live: -32602 invalid enum value for "downstream"/"upstream" --
    # the actual enum is ["dependents", "dependencies"].
    params = ls.scoped_params("graph_dependents", {"plan": "p-uuid", "step": "G-001"})
    assert params == {"plan": "p-uuid", "step_id": "G-001", "direction": "dependents"}


def test_scoped_params_block_get_shape():
    params = ls.scoped_params("block_get", {"plan": "p-uuid", "block": "blk-1"})
    assert params == {"plan": "p-uuid", "block_id": "blk-1"}


def test_scoped_params_bug_and_todo_shapes():
    assert ls.scoped_params("todo_get", {"todo": "t-uuid"}) == {"todo": "t-uuid"}
    assert ls.scoped_params("bug_get", {"bug": "b-uuid"}) == {"bug_id": "b-uuid"}
    assert ls.scoped_params("bug_impact_list", {"bug": "b-uuid"}) == {"bug_id": "b-uuid"}
    assert ls.scoped_params("bug_fix_list", {"bug": "b-uuid"}) == {"bug": "b-uuid"}


def test_scoped_params_step_search_shape():
    # Confirmed live: -32602 Missing required parameters: plan, pattern.
    params = ls.scoped_params("step_search", {"plan": "p-uuid"})
    assert params == {"plan": "p-uuid", "pattern": "G-"}
    assert ls.scoped_params("step_search", {}) is None


def test_scoped_params_files_report_shape():
    assert ls.scoped_params("files_report", {"plan": "p-uuid"}) == {"plan": "p-uuid"}


def test_scoped_params_step_xref_shape():
    # Confirmed live: -32000 INVALID_FILTER "provide either text or (step
    # and field)" -- "text" alone is the simplest valid filter shape.
    params = ls.scoped_params("step_xref", {"plan": "p-uuid"})
    assert params == {"plan": "p-uuid", "text": "live-smoke"}


# --------------------------------------------------------------------------
# GATE_RED-expected probes (fourth live run): branch_weak/plan_score refuse
# with the documented GATE_RED domain error against the deliberately
# unpolished throwaway plan -- that refusal IS the expected/correct
# contract, so interpret_gate_red_probe inverts the usual ok->PASS logic.
# --------------------------------------------------------------------------


def test_gate_red_expected_membership():
    assert ls.GATE_RED_EXPECTED == frozenset({"branch_weak", "plan_score"})


def test_interpret_gate_red_probe_pass_on_gate_red_failure():
    status, detail = ls.interpret_gate_red_probe(False, "domain error GATE_RED: mechanical gate not green (11 findings)")
    assert status == ls.STATUS_PASS
    assert "GATE_RED" in detail


def test_interpret_gate_red_probe_fails_on_unexpected_success():
    status, detail = ls.interpret_gate_red_probe(True, {"weak_findings": []})
    assert status == ls.STATUS_FAIL
    assert "succeeded" in detail


def test_interpret_gate_red_probe_fails_on_non_gate_red_error():
    status, detail = ls.interpret_gate_red_probe(False, "PLAN_NOT_FOUND: no such plan")
    assert status == ls.STATUS_FAIL
    assert "NOT with the expected GATE_RED" in detail


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
# call() -- the async wrapper around the builtin-vs-domain routing policy
# (queued client._call by default, direct client._rpc.execute_command for
# KNOWN_BUILTIN_COMMANDS or as a one-shot fallback) + unwrap_envelope +
# exception .details surfacing. Exercised against a minimal fake client (no
# real network) via asyncio.run.
# --------------------------------------------------------------------------

_UNSET = object()


class _FakeRpc:
    """Stand-in for the composed JsonRpcClient reached via client._rpc."""

    def __init__(self, outer: "_FakeClient"):
        self._outer = outer

    async def execute_command(self, name, params=None, use_cmd_endpoint=False):
        self._outer.direct_calls.append((name, params or {}))
        # Per-name scripted direct responses (used by _ScriptedClient for
        # KNOWN_BUILTIN_COMMANDS names like "help") take priority over the
        # single shared _direct_outcome fallback below.
        direct_responses = getattr(self._outer, "_direct_responses", None)
        if direct_responses and name in direct_responses:
            outcome = direct_responses[name]
            if callable(outcome) and not isinstance(outcome, BaseException):
                outcome = outcome(params or {})
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome
        outcome = self._outer._direct_outcome
        if outcome is _UNSET:
            raise AssertionError(
                f"direct path invoked unexpectedly for {name!r} with no direct_outcome configured"
            )
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeClient:
    """Minimal stand-in for PlanManagerClient.

    ``outcome`` configures the queued path (``client._call``); the (default
    unset) ``direct_outcome`` configures the plain JSON-RPC path
    (``client._rpc.execute_command``) -- unset means "this test asserts the
    direct path is never reached", so an unexpected call fails loudly
    rather than silently returning something plausible.
    """

    def __init__(self, outcome=None, direct_outcome=_UNSET):
        self._outcome = outcome
        self._direct_outcome = direct_outcome
        self.queued_calls: list[tuple[str, dict]] = []
        self.direct_calls: list[tuple[str, dict]] = []
        self._rpc = _FakeRpc(self)

    async def _call(self, name, params=None):
        self.queued_calls.append((name, params or {}))
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
    client = _FakeClient(outcome=envelope)
    ok, data = asyncio.run(ls.call(client, "info", {}))
    assert ok is True
    assert data == {"identity": {"package_version": "0.1.52"}}
    assert client.queued_calls == [("info", {})]
    assert client.direct_calls == []


def test_call_non_completed_status_reports_failure():
    envelope = {"job_id": "j2", "command": "step_get", "status": "failed", "result": {}}
    client = _FakeClient(outcome=envelope)
    ok, message = asyncio.run(ls.call(client, "step_get", {"plan": "p", "step_id": "G-001"}))
    assert ok is False
    assert "non-success/incomplete envelope" in message
    assert "'status': 'failed'" in message
    # no "not found" text in this envelope -> never mistaken for an
    # unresolved-command routing problem, so the direct path is untouched.
    assert client.direct_calls == []


def test_call_exception_includes_details_verbatim():
    exc = _FakeErrorWithDetails(
        "Queued command 'plan_list' failed (job_id=deadbeef-0000)",
        details={"terminal_event": {"event": "command_failed"}, "result_status": {"error": "boom"}},
    )
    client = _FakeClient(outcome=exc)
    ok, message = asyncio.run(ls.call(client, "plan_list", {}))
    assert ok is False
    assert "Queued command 'plan_list' failed" in message
    assert "terminal_event" in message
    assert "command_failed" in message
    assert client.direct_calls == []


def test_call_exception_without_details_still_reports_str():
    client = _FakeClient(outcome=RuntimeError("plain transport error"))
    ok, message = asyncio.run(ls.call(client, "plan_list", {}))
    assert ok is False
    assert message == "plain transport error"


# --------------------------------------------------------------------------
# Builtin-vs-domain routing: KNOWN_BUILTIN_COMMANDS, the direct path, the
# one-shot fallback on an unresolved-command queue failure, DISPATCH_LOG.
# --------------------------------------------------------------------------


def test_known_builtin_commands_membership():
    # help IS the reproduced live defect; info/health/plan_list are
    # confirmed-working domain commands and must stay on the queued path.
    assert "help" in ls.KNOWN_BUILTIN_COMMANDS
    assert "echo" in ls.KNOWN_BUILTIN_COMMANDS
    assert "queue_get_job_status" in ls.KNOWN_BUILTIN_COMMANDS
    assert "info" not in ls.KNOWN_BUILTIN_COMMANDS
    assert "health" not in ls.KNOWN_BUILTIN_COMMANDS
    assert "plan_list" not in ls.KNOWN_BUILTIN_COMMANDS


def test_looks_like_unresolved_command_matches_live_evidence():
    diagnostic = (
        "Queued command 'help' failed (job_id=c0bab142-0000) | "
        "details={'terminal_event': {...}, 'result_status': "
        "{'description': 'Command execution failed: \"Command \\'help\\' not found\"'}}"
    )
    assert ls._looks_like_unresolved_command("help", diagnostic) is True


def test_looks_like_unresolved_command_rejects_domain_not_found_errors():
    # A legitimate domain NOT_FOUND error never quotes the *command* name
    # the way an adapter "Command 'x' not found" message does.
    diagnostic = "non-success/incomplete envelope: {'success': False, 'error': 'STEP_NOT_FOUND: step not found: G-001'}"
    assert ls._looks_like_unresolved_command("step_get", diagnostic) is False


def test_looks_like_unresolved_command_requires_not_found_text():
    diagnostic = "some other failure mentioning 'help' but no resolution phrase"
    assert ls._looks_like_unresolved_command("help", diagnostic) is False


def test_call_routes_known_builtin_directly_never_touching_queued_path():
    ls.reset_dispatch_log()
    direct_envelope = {"success": True, "data": {"commands": {"info": "..."}}}
    client = _FakeClient(outcome=AssertionError("queued path must not be reached"), direct_outcome=direct_envelope)
    ok, data = asyncio.run(ls.call(client, "help", {}))
    assert ok is True
    assert data == {"commands": {"info": "..."}}
    assert client.queued_calls == []
    assert client.direct_calls == [("help", {})]
    assert [e for e in ls.DISPATCH_LOG if e["command"] == "help"][-1]["path"] == "direct"


def test_call_falls_back_to_direct_path_on_unresolved_command_queue_failure():
    """Reproduces the exact second-live-run scenario for a command NOT yet
    in KNOWN_BUILTIN_COMMANDS: the queued path fails with an adapter
    "Command '<name>' not found" style error, and call() self-heals via
    one direct-path retry instead of reporting a hard failure."""
    ls.reset_dispatch_log()
    exc = _FakeErrorWithDetails(
        "Queued command 'mystery_builtin' failed (job_id=c0bab142-0000)",
        details={"result_status": {"description": "Command execution failed: \"Command 'mystery_builtin' not found\""}},
    )
    direct_envelope = {"success": True, "data": {"ok": True}}
    client = _FakeClient(outcome=exc, direct_outcome=direct_envelope)
    assert "mystery_builtin" not in ls.KNOWN_BUILTIN_COMMANDS
    ok, data = asyncio.run(ls.call(client, "mystery_builtin", {}))
    assert ok is True
    assert data == {"ok": True}
    assert client.queued_calls == [("mystery_builtin", {})]
    assert client.direct_calls == [("mystery_builtin", {})]
    log_entry = [e for e in ls.DISPATCH_LOG if e["command"] == "mystery_builtin"][-1]
    assert log_entry["path"] == "queued->direct-fallback"
    assert log_entry["fallback"] is True


def test_call_does_not_fallback_on_genuine_domain_not_found_error():
    """A real domain NOT_FOUND failure must be reported as-is, never
    misrouted into a direct-path retry (which would just repeat uselessly
    since the entity genuinely doesn't exist, not the command)."""
    ls.reset_dispatch_log()
    envelope = {"success": False, "error": "STEP_NOT_FOUND: step not found: G-001"}
    client = _FakeClient(outcome=envelope)  # direct_outcome left _UNSET on purpose
    ok, message = asyncio.run(ls.call(client, "step_get", {"plan": "p", "step_id": "G-001"}))
    assert ok is False
    assert "STEP_NOT_FOUND" in message
    assert client.direct_calls == []


def test_summarize_dispatch_fallbacks_none_when_nothing_fell_back():
    log = [{"command": "info", "path": "queued", "fallback": False}]
    assert ls.summarize_dispatch_fallbacks(log) is None


def test_summarize_dispatch_fallbacks_names_recovered_commands():
    log = [
        {"command": "info", "path": "queued", "fallback": False},
        {"command": "mystery_a", "path": "queued->direct-fallback", "fallback": True},
        {"command": "mystery_b", "path": "queued->direct-fallback", "fallback": True},
        {"command": "mystery_a", "path": "queued->direct-fallback", "fallback": True},
    ]
    note = ls.summarize_dispatch_fallbacks(log)
    assert note is not None
    assert "mystery_a" in note and "mystery_b" in note
    assert "KNOWN_BUILTIN_COMMANDS" in note


def test_reset_dispatch_log_clears_entries():
    ls.DISPATCH_LOG.append({"command": "x", "path": "direct", "fallback": False})
    assert ls.DISPATCH_LOG
    ls.reset_dispatch_log()
    assert ls.DISPATCH_LOG == []


# --------------------------------------------------------------------------
# Third-live-run fixes to the networked tier-3/regression coroutines:
# create/cleanup phase splitting (ordering) and the corrected bug-close and
# R2 recipes. Exercised against a scripted fake client (no real network).
# --------------------------------------------------------------------------


def _ok(data):
    return {"success": True, "data": data}


def _sequence(*outcomes):
    """A callable outcome usable in _ScriptedClient's response table: pops
    the next scripted outcome on each invocation, for a command name called
    more than once with different desired responses per call."""
    remaining = list(outcomes)

    def _next(_params):
        if not remaining:
            raise AssertionError("sequence exhausted: more calls than scripted outcomes")
        return remaining.pop(0)

    return _next


class _ScriptedClient:
    """Fake client whose queued path (_call) returns a scripted response per
    command name -- a value, an exception instance, or a callable(params)
    for dynamic/stateful behavior -- and records every (name, params) call
    in call order. Most coroutines tested below never invoke a
    KNOWN_BUILTIN_COMMANDS name, so the direct path is left unconfigured by
    default (reached only, and loudly, on a routing mistake); pass
    ``direct_responses`` (same value shapes as ``responses``) for tests
    that DO call a builtin like "help" (routed via client._rpc.execute_command,
    not client._call -- see live_smoke.py's KNOWN_BUILTIN_COMMANDS module note).
    """

    def __init__(self, responses: dict[str, Any], direct_responses: dict[str, Any] | None = None):
        self._responses = responses
        self._direct_responses = direct_responses or {}
        self.calls: list[tuple[str, dict]] = []
        self.direct_calls: list[tuple[str, dict]] = []
        self._direct_outcome = _UNSET
        self._rpc = _FakeRpc(self)

    async def _call(self, name, params=None):
        params = dict(params or {})
        self.calls.append((name, params))
        outcome = self._responses.get(name)
        if outcome is None:
            raise AssertionError(f"no scripted response for command {name!r} (params={params})")
        if callable(outcome) and not isinstance(outcome, BaseException):
            outcome = outcome(params)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def test_run_tier3_plan_step_create_does_not_delete_and_returns_entities():
    client = _ScriptedClient(
        {
            "plan_create": _ok({"uuid": "plan-1"}),
            "context_common": _ok({"common_block_id": "blk-1"}),
            "step_create": _sequence(
                _ok({"uuid": "step3-uuid", "step_id": "G-001"}),
                _ok({"uuid": "step4-uuid", "step_id": "T-001"}),
            ),
            "graph_order": _ok({"order": ["G-001/T-001"]}),
        }
    )
    results, entities, plan_uuid, plan_name = asyncio.run(ls.run_tier3_plan_step_create(client))
    assert plan_uuid == "plan-1"
    assert plan_name.startswith(ls.PREFIX)
    assert entities["plan"] == "plan-1"
    assert entities["step"] == "T-001"  # overwritten by the level-4 child
    assert entities["block"] == "blk-1"
    assert all(r.status != ls.STATUS_FAIL for r in results)
    assert not any(name == "plan_delete" for name, _ in client.calls), "create phase must never delete"


def test_run_tier3_plan_step_cleanup_deletes_and_verifies():
    client = _ScriptedClient(
        {
            "plan_delete": _ok({"deleted": True}),
            "plan_list": _ok({"plans": [{"name": "some-other-plan"}]}),
        }
    )
    results = asyncio.run(ls.run_tier3_plan_step_cleanup(client, "plan-1", "live-smoke-plan-xyz"))
    assert [c[0] for c in client.calls] == ["plan_delete", "plan_list"]
    assert client.calls[0][1] == {"plan": "plan-1", "hard": True}
    assert all(r.status == ls.STATUS_PASS for r in results)


def test_run_tier3_plan_step_cleanup_noop_when_plan_uuid_none():
    client = _ScriptedClient({})
    results = asyncio.run(ls.run_tier3_plan_step_cleanup(client, None, "irrelevant"))
    assert results == []
    assert client.calls == []


def test_run_tier3_todo_create_does_not_delete():
    client = _ScriptedClient(
        {
            "todo_create": _ok({"uuid": "todo-1"}),
            "todo_update": _ok({"uuid": "todo-1"}),
            "todo_resolve": _ok({"uuid": "todo-1"}),
            "todo_close": _ok({"uuid": "todo-1"}),
        }
    )
    results, todo_uuid = asyncio.run(ls.run_tier3_todo_create(client))
    assert todo_uuid == "todo-1"
    assert [c[0] for c in client.calls] == ["todo_create", "todo_update", "todo_resolve", "todo_close"]
    assert all(r.status == ls.STATUS_PASS for r in results)


def test_run_tier3_todo_cleanup_deletes_and_verifies_via_failing_get():
    client = _ScriptedClient(
        {
            "todo_delete": _ok({"deleted": True}),
            "todo_get": RuntimeError("todo not found"),
        }
    )
    results = asyncio.run(ls.run_tier3_todo_cleanup(client, "todo-1"))
    assert [c[0] for c in client.calls] == ["todo_delete", "todo_get"]
    assert all(r.status == ls.STATUS_PASS for r in results)


def test_run_tier3_todo_cleanup_noop_when_todo_uuid_none():
    client = _ScriptedClient({})
    assert asyncio.run(ls.run_tier3_todo_cleanup(client, None)) == []
    assert client.calls == []


def test_run_tier3_bug_create_runs_full_fix_verify_close_chain_in_order():
    """The exact fix for the third live run's bug_close failure (-32000
    "source fix not verified", INVALID_RUNTIME_STATUS_TRANSITION): the full
    documented closure path is bug_create -> bug_confirm -> bug_fix_create
    -> bug_fix_verify(passed=True) -> bug_close, in that order."""
    client = _ScriptedClient(
        {
            "bug_create": _ok({"uuid": "bug-1"}),
            "bug_confirm": _ok({"uuid": "bug-1", "status": "confirmed"}),
            "bug_fix_create": _ok({"bug_fix": {"uuid": "fix-1", "status": "proposed"}}),
            "bug_fix_verify": _ok({"uuid": "fix-1", "status": "verified"}),
            "bug_close": _ok({"uuid": "bug-1", "status": "closed"}),
        }
    )
    results, bug_uuid = asyncio.run(ls.run_tier3_bug_create(client, "plan-1"))
    assert bug_uuid == "bug-1"
    order = [name for name, _ in client.calls]
    assert order == ["bug_create", "bug_confirm", "bug_fix_create", "bug_fix_verify", "bug_close"]
    fix_verify_params = client.calls[3][1]
    assert fix_verify_params["bug_fix"] == "fix-1"
    assert fix_verify_params["passed"] is True
    assert all(r.status == ls.STATUS_PASS for r in results)


def test_run_tier3_bug_create_skips_verify_when_fix_create_fails():
    client = _ScriptedClient(
        {
            "bug_create": _ok({"uuid": "bug-1"}),
            "bug_confirm": _ok({"uuid": "bug-1"}),
            "bug_fix_create": RuntimeError("boom"),
            "bug_close": _ok({"uuid": "bug-1", "status": "closed"}),
        }
    )
    results, bug_uuid = asyncio.run(ls.run_tier3_bug_create(client, "plan-1"))
    assert bug_uuid == "bug-1"
    order = [name for name, _ in client.calls]
    assert "bug_fix_verify" not in order
    assert order == ["bug_create", "bug_confirm", "bug_fix_create", "bug_close"]
    fix_result = next(r for r in results if r.name == "bug_fix_create")
    assert fix_result.status == ls.STATUS_FAIL


def test_run_r2_uses_correct_level_chain_never_skipping_level_4():
    """Reproduces (as a unit test) the exact defect a prior R2 attempt had:
    creating level-5 steps directly under a level-3 parent, which live
    evidence showed fails downstream with GRAPH_CORRUPTED_CHAIN ("parent of
    step A-001 not found in nodes"). The corrected recipe must create
    levels 3 -> 4 -> 4 -> 5 -> 5, each level-5 step parented on a
    DIFFERENT level-4 tactical step, never directly on the level-3 step.

    Also covers the fourth-live-run fix: the curative dependency edge must
    reference the two T-level SIBLINGS (same parent G, same level 4), never
    the two A steps directly (they have different level-4 parents, so are
    not siblings -- confirmed live: -32000 INVALID_DEPENDENCY_SCOPE), and
    preview must be called WITH that curative batch (not an empty change
    list) so same_file_order carries all four simulation fields.
    """
    step_create_calls: list[dict] = []

    def _step_create(params):
        step_create_calls.append(dict(params))
        idx = len(step_create_calls)
        return _ok({"uuid": f"uuid-{idx}", "step_id": f"{params['slug']}-{idx}"})

    preview_calls: list[dict] = []

    def _preview(params):
        preview_calls.append(dict(params))
        return _ok(
            {"same_file_order": {"before_findings": [{"pair": 1}], "after_findings": [], "resolved_pairs": [{"pair": 1}], "introduced_pairs": []}}
        )

    client = _ScriptedClient(
        {
            "plan_create": _ok({"uuid": "r2-plan"}),
            "context_common": _ok({"common_block_id": "blk"}),
            "step_create": _step_create,
            "step_update": _ok({"uuid": "updated"}),
            "step_dependency_preview": _preview,
            "step_dependency_apply": _sequence(
                _ok({"dry_run": True, "applied": False}),
                _ok({"dry_run": False, "applied": True}),
            ),
            "graph_order": _ok({"order": ["g/t-001/a", "g/t-002/a"]}),
            "plan_delete": _ok({"deleted": True}),
        }
    )
    results = asyncio.run(ls.run_r2_same_file_order_ambiguity(client))
    failures = [r for r in results if r.status == ls.STATUS_FAIL]
    assert failures == [], f"unexpected failures: {[r.line() for r in failures]}"

    assert len(step_create_calls) == 5
    levels = [c["level"] for c in step_create_calls]
    assert levels == [3, 4, 4, 5, 5]

    g_call, t1_call, t2_call, a1_call, a2_call = step_create_calls
    assert "parent_step_id" not in g_call  # level 3: no parent

    g_step_id = f"{g_call['slug']}-1"
    assert t1_call["parent_step_id"] == g_step_id
    assert t2_call["parent_step_id"] == g_step_id
    t1_uuid, t2_uuid = "uuid-2", "uuid-3"

    t1_step_id = f"{t1_call['slug']}-2"
    t2_step_id = f"{t2_call['slug']}-3"
    # the two level-5 A steps are parented on DIFFERENT level-4 parents --
    # never both directly on G (the level-3 step), and never on the same
    # tactical parent either.
    assert a1_call["parent_step_id"] == t1_step_id
    assert a2_call["parent_step_id"] == t2_step_id
    assert a1_call["parent_step_id"] != a2_call["parent_step_id"]

    # context_common recompiled before EVERY step_create (5 creates -> 5
    # context_common calls; a block compiled before an earlier sibling's
    # create is stale for the next one, per has_current_common_block).
    context_common_calls = [c for name, c in client.calls if name == "context_common"]
    assert len(context_common_calls) == 5

    # both A steps got the SAME target_file via step_update -- the
    # pre-existing ambiguity the regression needs.
    step_update_calls = [c for name, c in client.calls if name == "step_update"]
    assert len(step_update_calls) == 2
    target_files = {c["fields"]["target_file"] for c in step_update_calls}
    assert len(target_files) == 1

    # preview is called WITH the curative batch (not changes=[]) -- its
    # PASS result depends on all four same_file_order simulation fields
    # (checked by the CheckResult status above, since a malformed preview
    # payload would have failed R2_preview_simulates_without_raising).
    assert len(preview_calls) == 1
    assert preview_calls[0]["changes"] != []

    # the curative step_dependency_apply batch references the two T-LEVEL
    # SIBLINGS' UUIDs (uuid-2, uuid-3 -- G=uuid-1, T-001=uuid-2, T-002=
    # uuid-3, A-under-T001=uuid-4, A-under-T002=uuid-5), never the two A
    # steps directly (they are not siblings of each other), and matches
    # what preview was given, applied both dry-run then real.
    apply_calls = [c for name, c in client.calls if name == "step_dependency_apply"]
    assert len(apply_calls) == 2
    assert apply_calls[0]["dry_run"] is True
    assert apply_calls[1]["dry_run"] is False
    assert apply_calls[0]["changes"] == apply_calls[1]["changes"] == preview_calls[0]["changes"]
    assert apply_calls[0]["changes"][0]["step_id"] == t2_uuid
    assert apply_calls[0]["changes"][0]["depends_on"] == [t1_uuid]

    assert client.calls[-1][0] == "plan_delete"  # cleanup always runs


def test_run_r2_preview_fails_when_same_file_order_missing_a_simulation_field():
    """A preview response missing any of the four documented simulation
    fields must FAIL the check, not pass on a partial/malformed payload."""
    step_create_calls: list[dict] = []

    def _step_create(params):
        step_create_calls.append(dict(params))
        idx = len(step_create_calls)
        return _ok({"uuid": f"uuid-{idx}", "step_id": f"{params['slug']}-{idx}"})

    client = _ScriptedClient(
        {
            "plan_create": _ok({"uuid": "r2-plan"}),
            "context_common": _ok({"common_block_id": "blk"}),
            "step_create": _step_create,
            "step_update": _ok({"uuid": "updated"}),
            # missing "resolved_pairs" and "introduced_pairs"
            "step_dependency_preview": _ok({"same_file_order": {"before_findings": [], "after_findings": []}}),
            "step_dependency_apply": _sequence(
                _ok({"dry_run": True, "applied": False}),
                _ok({"dry_run": False, "applied": True}),
            ),
            "graph_order": _ok({"order": []}),
            "plan_delete": _ok({"deleted": True}),
        }
    )
    results = asyncio.run(ls.run_r2_same_file_order_ambiguity(client))
    preview_result = next(r for r in results if r.name == "R2_preview_simulates_without_raising")
    assert preview_result.status == ls.STATUS_FAIL


def test_run_tier2_scoped_labels_gate_red_probe_and_passes_on_expected_refusal():
    client = _ScriptedClient(
        {
            "branch_weak": RuntimeError("GATE_RED: mechanical gate not green (11 findings)"),
        }
    )
    results = asyncio.run(
        ls.run_tier2_scoped(client, frozenset({"branch_weak"}), {"plan": "plan-1"})
    )
    assert len(results) == 1
    result = results[0]
    assert result.name == "branch_weak(gate_red_contract)"
    assert result.status == ls.STATUS_PASS
    assert "GATE_RED" in result.detail


def test_run_tier2_scoped_fails_gate_red_probe_on_unexpected_success():
    client = _ScriptedClient({"plan_score": _ok({"index": []})})
    results = asyncio.run(
        ls.run_tier2_scoped(client, frozenset({"plan_score"}), {"plan": "plan-1"})
    )
    result = results[0]
    assert result.name == "plan_score(gate_red_contract)"
    assert result.status == ls.STATUS_FAIL
    assert "succeeded" in result.detail


def test_run_tier2_scoped_ordinary_command_unaffected_by_gate_red_labeling():
    client = _ScriptedClient({"plan_status": _ok({"status": "draft"})})
    results = asyncio.run(
        ls.run_tier2_scoped(client, frozenset({"plan_status"}), {"plan": "plan-1"})
    )
    result = results[0]
    assert result.name == "plan_status"
    assert result.status == ls.STATUS_PASS


# --------------------------------------------------------------------------
# R4 (bug ad529347-925e-44c9-8b04-df9d82c07cb9 + its enforcement child
# 26fa21a5-5487-4cf7-9b41-64a350a7074c): nested TS inputs/outputs schema.
#
# Two orthogonal knobs on the scripted server:
#   - help_marker / field_schema_marker: whether ad529347's documentation
#     fix is present. Absent -> the two doc sub-checks SKIP (cosmetic,
#     never FAIL) -- a genuinely pre-ad529347 server is an expected,
#     reportable state.
#   - reject_malformed: whether 26fa21a5's write-time enforcement is
#     present. This is a HARD functional requirement, not marker-gated: a
#     server that still accepts a malformed level-4 item FAILs the
#     rejection/currency checks outright (modeled realistically below: the
#     wrongly-accepted write also stales the context block, matching the
#     bug's own reproduction).
#
# Neither scenario touches the live network -- both exercise
# run_r4_ts_inputs_outputs_schema purely against a _ScriptedClient.
# --------------------------------------------------------------------------


def _r4_step_create_sequence():
    calls: list[dict] = []

    def _step_create(params):
        calls.append(dict(params))
        idx = len(calls)
        return _ok({"uuid": f"uuid-{idx}", "step_id": f"{params['slug']}-{idx}"})

    return calls, _step_create


def _r4_client(*, help_marker: bool, field_schema_marker: bool, reject_malformed: bool) -> "_ScriptedClient":
    _calls, step_create = _r4_step_create_sequence()
    help_payload = {
        "metadata": {
            "detailed_description": (
                f"inputs item shape {{name, type, description}}; type must be {ls.R4_TYPE_ENUM_MARKER}"
                if help_marker
                else "inputs is a list."
            )
        }
    }
    field_schema_content = (
        [{"type": "field_schema", "level": 4, "schema": {"item_schemas": {"inputs": {"properties": {"type": f"must be {ls.R4_TYPE_ENUM_MARKER}"}}}}}]
        if field_schema_marker
        else [{"type": "field_schema", "level": 4, "schema": {"required_fields": ["inputs", "outputs"]}}]
    )
    malformed_item = {"name": "x", "type": "", "description": "y"}
    if reject_malformed:
        rejection_message = (
            f"inputs[0].type must be a non-empty string (expected item shape "
            f"{{name, type, description}}; type must be {ls.R4_TYPE_ENUM_MARKER})"
        )
        malformed_outcome = {
            "success": False,
            "error": {
                "code": -32000,
                "message": rejection_message,
                "data": {"domain_code": "INVALID_STEP_FIELD_SHAPE", "field": "fields"},
            },
        }
    else:
        # Pre-26fa21a5 behavior: the malformed item is accepted verbatim
        # and a revision is recorded.
        malformed_outcome = _ok({"uuid": "updated", "revision_uuid": "rev-1"})
    return _ScriptedClient(
        {
            "plan_create": _ok({"uuid": "r4-plan"}),
            "context_common": _sequence(
                _ok({}),  # plan, level 3
                _ok({"content": field_schema_content}),  # G, level 4
                _ok({"common_block_id": "blk-1"}),  # T, level 5 (baseline)
            ),
            "step_create": step_create,
            "block_list": _sequence(
                _ok({"blocks": [{"block_id": "blk-1", "is_live": True}]}),  # baseline: always current
                # After the malformed attempt: current iff it was actually
                # rejected -- a wrongly-accepted write stales the block,
                # matching the bug's own live reproduction.
                _ok({"blocks": [{"block_id": "blk-1", "is_live": reject_malformed}]}),
            ),
            "step_update": _sequence(
                malformed_outcome,
                _ok({"uuid": "updated2", "revision_uuid": "rev-2"}),  # valid write always succeeds
            ),
            "plan_delete": _ok({"deleted": True}),
        },
        # "help" is a KNOWN_BUILTIN_COMMANDS name (routed via the direct
        # execute_command path, never the queued client._call path).
        direct_responses={"help": _ok(help_payload)},
    )


def test_run_r4_pre_fix_server_skips_doc_checks_but_fails_enforcement_checks():
    """A server predating BOTH ad529347 (docs) and 26fa21a5 (enforcement):
    the cosmetic doc checks SKIP, but the malformed-item write wrongly
    succeeds and stales the context block -- both are HARD requirements
    and correctly FAIL, not SKIP. The subsequent valid write still
    succeeds regardless."""
    client = _r4_client(help_marker=False, field_schema_marker=False, reject_malformed=False)

    results = asyncio.run(ls.run_r4_ts_inputs_outputs_schema(client))

    by_name = {r.name: r for r in results}
    assert by_name["R4_help_documents_item_schema"].status == ls.STATUS_SKIP
    assert by_name["R4_field_schema_documents_item_schema"].status == ls.STATUS_SKIP
    assert ls.R4_PRE_FIX_SKIP_REASON in by_name["R4_help_documents_item_schema"].detail
    assert by_name["R4_step_update_malformed_item_rejected"].status == ls.STATUS_FAIL
    assert by_name["R4_context_currency_survives_rejected_write"].status == ls.STATUS_FAIL
    assert by_name["R4_step_update_valid_item_accepted"].status == ls.STATUS_PASS
    assert client.calls[-1][0] == "plan_delete"  # cleanup always runs


def test_run_r4_post_fix_server_passes_every_check():
    client = _r4_client(help_marker=True, field_schema_marker=True, reject_malformed=True)

    results = asyncio.run(ls.run_r4_ts_inputs_outputs_schema(client))

    by_name = {r.name: r for r in results}
    assert by_name["R4_help_documents_item_schema"].status == ls.STATUS_PASS
    assert by_name["R4_field_schema_documents_item_schema"].status == ls.STATUS_PASS
    assert by_name["R4_step_update_malformed_item_rejected"].status == ls.STATUS_PASS
    assert by_name["R4_context_currency_survives_rejected_write"].status == ls.STATUS_PASS
    assert by_name["R4_step_update_valid_item_accepted"].status == ls.STATUS_PASS
    assert not any(r.status == ls.STATUS_FAIL for r in results), [r.line() for r in results]
    assert not any(r.status == ls.STATUS_SKIP for r in results), [r.line() for r in results]


def test_run_r4_malformed_probe_is_object_shaped_and_valid_write_follows():
    """The first step_update probe is the malformed-but-object-shaped item
    (empty "type", carrying the shape/enum marker in its rejection
    message); the second is a fully valid item. A bare-string item is
    covered separately by
    tests/test_bug_26fa21a5_ts_inputs_outputs_write_rejection.py."""
    client = _r4_client(help_marker=True, field_schema_marker=True, reject_malformed=True)

    asyncio.run(ls.run_r4_ts_inputs_outputs_schema(client))

    step_update_calls = [params for name, params in client.calls if name == "step_update"]
    assert len(step_update_calls) == 2
    assert step_update_calls[0]["fields"]["inputs"] == [{"name": "x", "type": "", "description": "y"}]
    assert step_update_calls[1]["fields"]["inputs"][0]["type"] == "input"
    assert step_update_calls[1]["fields"]["outputs"][0]["type"] == "output"


def test_run_r4_transport_failure_on_plan_create_fails_not_skips():
    client = _ScriptedClient(
        {
            "help": _ok({"metadata": {"detailed_description": "no marker here"}}),
            "plan_create": RuntimeError("boom"),
        }
    )

    results = asyncio.run(ls.run_r4_ts_inputs_outputs_schema(client))

    plan_create_result = next(r for r in results if r.name == "R4_plan_create")
    assert plan_create_result.status == ls.STATUS_FAIL
    assert "boom" in plan_create_result.detail


# --------------------------------------------------------------------------
# run_r5_step_id_selector_docs (bug 761ee3dd, documentation): step-addressing
# commands accept UUID/canonical-path/unambiguous-local-id and reject an
# ambiguous bare id with AMBIGUOUS_STEP_ID (or AMBIGUOUS_PARENT_STEP_ID for a
# parent reference); several command schemas/metadata used to omit that from
# their step_id-family parameter description and error_cases. The doc-marker
# sub-checks are marker-gated SKIP on a pre-fix server (same convention as
# R4); the behavioral sub-checks assert the pre-existing (already shipped)
# ambiguity-rejection resolution logic directly and are never marker-gated.
# Exercised purely against a _ScriptedClient, no real network.
# --------------------------------------------------------------------------


def _r5_help_responder(*, doc_marker: bool):
    """Callable direct_responses["help"] value: keys its payload off the
    requested cmdname, using ls.R5_DOC_TARGETS as the single source of truth
    for which ambiguous code each command's help is expected to advertise."""
    codes_by_command = dict(ls.R5_DOC_TARGETS)

    def _respond(params):
        command_name = params.get("cmdname")
        ambiguous_code = codes_by_command.get(command_name, "AMBIGUOUS_STEP_ID")
        if doc_marker:
            text = (
                f"Step reference, as UUID, canonical path, or unambiguous local "
                f"step id; a bare local id matching more than one step is "
                f"rejected with {ambiguous_code}."
            )
            error_cases = {ambiguous_code: {"description": "ambiguous bare id"}}
        else:
            text = "Human-readable step identifier."
            error_cases = {}
        return _ok({"metadata": {"parameters": {"step_id": {"description": text}}, "error_cases": error_cases}})

    return _respond


def _r5_step_create_sequence():
    """Stateful step_create outcome: G-001 (level 3), T-001/T-002 (level 4,
    both children of G-001), and A-001 TWICE at level 5 -- one under T-001,
    one under T-002 -- reproducing the genuine cross-parent local-id
    ambiguity bug 761ee3dd's behavioral checks exercise."""
    calls: list[dict] = []

    def _step_create(params):
        calls.append(dict(params))
        level = params["level"]
        if level == 3:
            return _ok({"uuid": "g-uuid", "step_id": "G-001"})
        if level == 4:
            idx = sum(1 for c in calls if c["level"] == 4)
            return _ok({"uuid": f"t{idx}-uuid", "step_id": f"T-00{idx}"})
        idx = sum(1 for c in calls if c["level"] == 5)
        return _ok({"uuid": f"a{idx}-uuid", "step_id": "A-001"})

    return calls, _step_create


def _r5_step_get(params):
    """Stateful step_get outcome: the bare local id "A-001" is genuinely
    ambiguous (two live matches) and fails with AMBIGUOUS_STEP_ID; any other
    reference (a canonical path or a UUID) resolves to the first A step."""
    step_id = params.get("step_id")
    if step_id == "A-001":
        return {
            "success": False,
            "error": {
                "code": -32000,
                "message": "step_id A-001 resolves to multiple steps",
                "data": {
                    "domain_code": "AMBIGUOUS_STEP_ID",
                    "step_id": "A-001",
                    "matches": ["G-001/T-001/A-001", "G-001/T-002/A-001"],
                },
            },
        }
    return _ok({"uuid": "a1-uuid", "step_id": "A-001", "path": "G-001/T-001/A-001"})


def _r5_client(*, doc_marker: bool) -> "_ScriptedClient":
    _calls, step_create = _r5_step_create_sequence()
    return _ScriptedClient(
        {
            "plan_create": _ok({"uuid": "r5-plan"}),
            "context_common": _ok({"common_block_id": "blk"}),
            "step_create": step_create,
            "step_get": _r5_step_get,
            "plan_delete": _ok({"deleted": True}),
        },
        direct_responses={"help": _r5_help_responder(doc_marker=doc_marker)},
    )


def test_run_r5_pre_fix_server_skips_doc_checks_but_passes_behavioral_checks():
    """A server predating the 761ee3dd doc fix: every R5_help_documents_selector
    sub-check SKIPs (marker text absent), but the ambiguity-rejection
    behavior itself already shipped and must PASS unconditionally."""
    client = _r5_client(doc_marker=False)

    results = asyncio.run(ls.run_r5_step_id_selector_docs(client))

    by_name = {r.name: r for r in results}
    for command_name, _code in ls.R5_DOC_TARGETS:
        result = by_name[f"R5_help_documents_selector({command_name})"]
        assert result.status == ls.STATUS_SKIP, (command_name, result)
        assert ls.R5_PRE_FIX_SKIP_REASON in result.detail

    assert by_name["R5_scratch_ambiguous_A-001_created"].status == ls.STATUS_PASS
    assert by_name["R5_step_get_bare_ambiguous_id_rejected"].status == ls.STATUS_PASS
    assert by_name["R5_step_get_canonical_path_resolves"].status == ls.STATUS_PASS
    assert by_name["R5_step_get_uuid_resolves"].status == ls.STATUS_PASS
    assert client.calls[-1][0] == "plan_delete"  # cleanup always runs


def test_run_r5_post_fix_server_passes_every_check():
    client = _r5_client(doc_marker=True)

    results = asyncio.run(ls.run_r5_step_id_selector_docs(client))

    assert not any(r.status == ls.STATUS_FAIL for r in results), [r.line() for r in results]
    assert not any(r.status == ls.STATUS_SKIP for r in results), [r.line() for r in results]
    by_name = {r.name: r for r in results}
    for command_name, _code in ls.R5_DOC_TARGETS:
        assert by_name[f"R5_help_documents_selector({command_name})"].status == ls.STATUS_PASS


def test_run_r5_step_create_recipe_uses_two_different_tactical_parents():
    """The two level-5 creates must be parented on DIFFERENT level-4 tactical
    steps (T-001 and T-002) -- both under the same level-3 G-001 -- so the
    resulting "A-001" local id collision is a genuine cross-parent
    ambiguity, not an accidental same-parent duplicate the server would
    have refused as DUPLICATE_ID."""
    client = _r5_client(doc_marker=True)
    asyncio.run(ls.run_r5_step_id_selector_docs(client))

    step_create_calls = [params for name, params in client.calls if name == "step_create"]
    levels = [c["level"] for c in step_create_calls]
    assert levels == [3, 4, 4, 5, 5]
    g_call, t1_call, t2_call, a1_call, a2_call = step_create_calls
    assert "parent_step_id" not in g_call
    assert t1_call["parent_step_id"] == "G-001"
    assert t2_call["parent_step_id"] == "G-001"
    assert a1_call["parent_step_id"] == "T-001"
    assert a2_call["parent_step_id"] == "T-002"
    assert a1_call["parent_step_id"] != a2_call["parent_step_id"]

    context_common_calls = [c for name, c in client.calls if name == "context_common"]
    assert len(context_common_calls) == 4  # recompiled before each of the 4 non-level-3 creates


def test_run_r5_transport_failure_on_plan_create_fails_not_skips():
    client = _ScriptedClient(
        {"plan_create": RuntimeError("boom")},
        direct_responses={"help": _r5_help_responder(doc_marker=True)},
    )

    results = asyncio.run(ls.run_r5_step_id_selector_docs(client))

    plan_create_result = next(r for r in results if r.name == "R5_plan_create")
    assert plan_create_result.status == ls.STATUS_FAIL
    assert "boom" in plan_create_result.detail


# --------------------------------------------------------------------------
# run_r6_write_intent_negation (bug 5ebe3ce5, wrong_output, major): the
# parse.atomic_single_code_file check used to flag a negated ("do not
# modify X") second-file reference as an additional write target purely
# because its sentence also carried a write-intent verb. The negation
# sub-check is marker-gated SKIP on a pre-fix server -- judged by directly
# inspecting the live plan_validate JSON report rather than a help/doc
# marker, since this bug's fix is behavioral, not documentation. The
# true-positive sub-check (a genuinely commanded second write) is never
# marker-gated: it must hold on both a pre-fix and a post-fix server.
# Exercised purely against a _ScriptedClient, no real network.
# --------------------------------------------------------------------------


def _r6_step_create_sequence():
    """Stateful step_create outcome: G-001 (level 3), T-001 (level 4), then
    one level-5 AS per call, its step_id echoing the requested slug."""
    calls: list[dict] = []

    def _step_create(params):
        calls.append(dict(params))
        level = params["level"]
        if level == 3:
            return _ok({"uuid": "g-uuid", "step_id": "G-001"})
        if level == 4:
            return _ok({"uuid": "t-uuid", "step_id": "T-001"})
        idx = sum(1 for c in calls if c["level"] == 5)
        return _ok({"uuid": f"a{idx}-uuid", "step_id": params["slug"]})

    return calls, _step_create


def _r6_report(*, negated_flagged: bool, second_write_flagged: bool) -> str:
    """Build a plan_validate-shaped JSON report string carrying a
    parse.atomic_single_code_file finding for the negated reference and/or
    the true-positive second write, per the given flags -- mirroring the
    real gate's render_json shape closely enough for
    _r6_report_flags_path to parse."""
    findings = []
    if negated_flagged:
        findings.append(
            {
                "check_id": "parse.atomic_single_code_file",
                "severity": "error",
                "artifact_path": "G-001/T-001/negation-case",
                "message": (
                    "AS_MULTIPLE_CODE_FILES: target_file="
                    f"{ls.R6_NEGATED_TARGET!r}; additional_write_targets=[{ls.R6_NEGATED_REF!r}]; "
                    "source_fields=['prompt']"
                ),
            }
        )
    if second_write_flagged:
        findings.append(
            {
                "check_id": "parse.atomic_single_code_file",
                "severity": "error",
                "artifact_path": "G-001/T-001/true-positive-case",
                "message": (
                    "AS_MULTIPLE_CODE_FILES: target_file="
                    f"{ls.R6_TP_TARGET!r}; additional_write_targets=[{ls.R6_TP_SECOND!r}]; "
                    "source_fields=['prompt']"
                ),
            }
        )
    return json.dumps(
        {
            "checks": [{"check_id": "parse.atomic_single_code_file", "findings": findings, "passed": not findings}],
            "green": not findings,
        }
    )


def _r6_client(*, negated_flagged: bool, second_write_flagged: bool) -> "_ScriptedClient":
    _calls, step_create = _r6_step_create_sequence()
    report = _r6_report(negated_flagged=negated_flagged, second_write_flagged=second_write_flagged)
    return _ScriptedClient(
        {
            "plan_create": _ok({"uuid": "r6-plan"}),
            "context_common": _ok({}),
            "step_create": step_create,
            "step_update": _ok({"uuid": "updated", "revision_uuid": "rev-1"}),
            "plan_validate": _ok({"green": not (negated_flagged or second_write_flagged), "report": report}),
            "plan_delete": _ok({"deleted": True}),
        }
    )


def test_run_r6_pre_fix_server_skips_negation_check_but_flags_true_positive():
    """A server predating the 5ebe3ce5 fix: the negation check SKIPs
    (AS_MULTIPLE_CODE_FILES still fires on the negated reference), but the
    checker's pre-existing ability to flag a genuine second write still
    PASSes -- both are how a real pre-fix server behaves."""
    client = _r6_client(negated_flagged=True, second_write_flagged=True)

    results = asyncio.run(ls.run_r6_write_intent_negation(client))

    by_name = {r.name: r for r in results}
    assert by_name["R6_negated_reference_not_flagged"].status == ls.STATUS_SKIP
    assert ls.R6_PRE_FIX_SKIP_REASON in by_name["R6_negated_reference_not_flagged"].detail
    assert by_name["R6_true_positive_second_write_still_flagged"].status == ls.STATUS_PASS
    assert client.calls[-1][0] == "plan_delete"  # cleanup always runs


def test_run_r6_post_fix_server_passes_every_check():
    client = _r6_client(negated_flagged=False, second_write_flagged=True)

    results = asyncio.run(ls.run_r6_write_intent_negation(client))

    assert not any(r.status == ls.STATUS_FAIL for r in results), [r.line() for r in results]
    assert not any(r.status == ls.STATUS_SKIP for r in results), [r.line() for r in results]
    by_name = {r.name: r for r in results}
    assert by_name["R6_negated_reference_not_flagged"].status == ls.STATUS_PASS
    assert by_name["R6_true_positive_second_write_still_flagged"].status == ls.STATUS_PASS


def test_run_r6_true_positive_missing_is_a_fail_not_a_skip():
    """If the checker's power regressed too (the genuine second write is no
    longer flagged at all), that must FAIL loudly, never SKIP -- only the
    negation sub-check is marker-gated."""
    client = _r6_client(negated_flagged=False, second_write_flagged=False)

    results = asyncio.run(ls.run_r6_write_intent_negation(client))

    by_name = {r.name: r for r in results}
    assert by_name["R6_true_positive_second_write_still_flagged"].status == ls.STATUS_FAIL


def test_run_r6_transport_failure_on_plan_create_fails_not_skips():
    client = _ScriptedClient({"plan_create": RuntimeError("boom")})

    results = asyncio.run(ls.run_r6_write_intent_negation(client))

    plan_create_result = next(r for r in results if r.name == "R6_plan_create")
    assert plan_create_result.status == ls.STATUS_FAIL
    assert "boom" in plan_create_result.detail


def test_run_r6_step_create_recipe_covers_both_as_cases_under_one_ts():
    client = _r6_client(negated_flagged=True, second_write_flagged=True)

    asyncio.run(ls.run_r6_write_intent_negation(client))

    step_create_calls = [params for name, params in client.calls if name == "step_create"]
    levels = [c["level"] for c in step_create_calls]
    assert levels == [3, 4, 5, 5]
    slugs = [c["slug"] for c in step_create_calls if c["level"] == 5]
    assert slugs == ["negation-case", "true-positive-case"]

    context_common_calls = [c for name, c in client.calls if name == "context_common"]
    assert len(context_common_calls) == 4  # recompiled before each of the 4 non-level-3 creates


def test_r6_report_flags_path_matches_target_check_id_only():
    report = json.dumps(
        {
            "checks": [
                {
                    "check_id": "parse.atomic_single_code_file",
                    "findings": [
                        {"message": f"AS_MULTIPLE_CODE_FILES: additional_write_targets=[{ls.R6_NEGATED_REF!r}]"},
                    ],
                },
                {
                    "check_id": "parse.target_file",
                    "findings": [{"message": ls.R6_TP_SECOND}],
                },
            ],
        }
    )
    assert ls._r6_report_flags_path(report, ls.R6_NEGATED_REF) is True
    # A path mentioned only under a DIFFERENT check_id must not count.
    assert ls._r6_report_flags_path(report, ls.R6_TP_SECOND) is False


def test_r6_report_flags_path_handles_malformed_report_gracefully():
    assert ls._r6_report_flags_path("not json", ls.R6_NEGATED_REF) is False
    assert ls._r6_report_flags_path(None, ls.R6_NEGATED_REF) is False
    assert ls._r6_report_flags_path(42, ls.R6_NEGATED_REF) is False


# --------------------------------------------------------------------------
# R7 (CR-5a agent-config surface, delivery fixup): the 36 tool/toolset/role/
# provider/model/invocation_profile/resolve commands this change request
# adds. Marker-gated on catalog PRESENCE (R7_REQUIRED_COMMANDS <=
# catalog_names) rather than a response-shape marker, since on a pre-CR-5a
# server the entire command surface is absent, not merely differently
# behaved -- the same pre-fix SKIP convention as R4/R5/R6, one level up.
# Exercised purely against a _ScriptedClient, no real network.
# --------------------------------------------------------------------------


def _r7_success_responses() -> dict[str, Any]:
    """A fully-successful scripted response table for every command
    run_r7_agent_config_lifecycle invokes on a post-CR-5a server, in the
    exact call order the function itself uses."""
    return {
        "plan_create": _ok({"uuid": "r7-plan"}),
        "tool_create": _ok({"uuid": "tool-1"}),
        "tool_get": _ok({"uuid": "tool-1"}),
        "tool_list": _ok({"tools": [{"uuid": "tool-1"}], "total": 1, "limit": 5, "offset": 0}),
        "tool_update": _ok({"uuid": "tool-1", "description": "updated by live_smoke.py R7"}),
        "toolset_create": _ok({"uuid": "toolset-1"}),
        "toolset_get": _ok({"uuid": "toolset-1"}),
        "toolset_list": _ok({"toolsets": [{"uuid": "toolset-1"}], "total": 1, "limit": 5, "offset": 0}),
        "toolset_update": _ok({"uuid": "toolset-1", "description": "updated by live_smoke.py R7"}),
        "toolset_member_add": _ok({"uuid": "membership-1", "toolset_uuid": "toolset-1", "tool_uuid": "tool-1", "position": 0}),
        "tool_delete": _ok({"dry_run": False, "mode": "soft", "tool": {"uuid": "tool-1"}}),
        "toolset_member_remove": _ok({"uuid": "membership-1", "deleted_at": "2026-07-23T00:00:00Z"}),
        "toolset_delete": _ok({"dry_run": False, "mode": "hard", "deleted_uuid": "toolset-1"}),
        "role_create": _ok({"uuid": "role-1"}),
        "role_get": _ok({"uuid": "role-1"}),
        "role_list": _ok({"roles": [{"uuid": "role-1"}], "total": 1, "limit": 5, "offset": 0}),
        "role_update": _ok({"uuid": "role-1", "description": "updated by live_smoke.py R7"}),
        "role_delete": _ok({"dry_run": False, "mode": "hard", "deleted_uuid": "role-1"}),
        "provider_create": _ok({"uuid": "provider-1", "status": "active"}),
        "provider_set_status": _ok({"uuid": "provider-1", "status": "suspended"}),
        "provider_get": _ok({"uuid": "provider-1", "status": "suspended"}),
        "provider_list": _ok({"providers": [{"uuid": "provider-1"}], "total": 1, "limit": 5, "offset": 0}),
        "provider_update": _ok({"uuid": "provider-1", "status": "active"}),
        "model_create": _ok({"uuid": "model-1"}),
        "model_get": _ok({"uuid": "model-1"}),
        "model_list": _ok({"models": [{"uuid": "model-1"}], "total": 1, "limit": 5, "offset": 0}),
        "model_update": _ok({"uuid": "model-1", "cost_class": "live-smoke-cost-class"}),
        "role_model_resolve": _ok(
            {"source": "step_requirement", "chosen_provider": "provider-name", "chosen_model": "model-name", "chosen_level": "lvl", "provenance": {}}
        ),
        "model_delete": _ok({"dry_run": False, "mode": "hard", "deleted_uuid": "model-1"}),
        "provider_delete": _ok({"dry_run": False, "mode": "hard", "deleted_uuid": "provider-1"}),
        "invocation_profile_create": _ok({"uuid": "profile-1"}),
        "invocation_profile_get": _ok({"uuid": "profile-1"}),
        "invocation_profile_list": _ok({"profiles": [{"uuid": "profile-1"}], "total": 1, "limit": 5, "offset": 0}),
        "invocation_profile_update": _ok({"uuid": "profile-1", "temperature": 0.5}),
        "invocation_profile_resolve": _ok(
            {"profile": {"uuid": "profile-1"}, "source_scope": "system", "source_profile_uuid": "profile-1", "inheritance_path": []}
        ),
        "invocation_profile_delete": _ok({"dry_run": False, "mode": "hard", "deleted_uuid": "profile-1"}),
        "step_assignment_resolve": {
            "success": False,
            "error": {
                "code": -32000, "message": "no applicable step assignment for target",
                "data": {"domain_code": "NO_APPLICABLE_ASSIGNMENT"},
            },
        },
        "plan_delete": _ok({"deleted": True}),
    }


def test_run_r7_pre_deploy_server_skips_entire_group_not_per_command():
    """A server predating CR-5a entirely (none of the 36 commands in the
    live catalog): ONE aggregate SKIP, never 36 individual FAILs from a
    misleading 'command not found' routing failure."""
    client = _ScriptedClient({})

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, frozenset()))

    assert len(results) == 1
    result = results[0]
    assert result.name == "R7_agent_config_lifecycle"
    assert result.status == ls.STATUS_SKIP
    assert ls.R7_PRE_DEPLOY_SKIP_REASON in result.detail
    assert client.calls == []  # no call is even attempted


def test_run_r7_partial_deploy_still_skips_as_one_group():
    """Some but not all of the 36 commands present: still gated as a whole
    (the recipe below assumes the full CR-5a surface ships as one unit)."""
    partial = frozenset({"tool_create", "tool_get"})
    client = _ScriptedClient({})

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, partial))

    assert len(results) == 1
    assert results[0].status == ls.STATUS_SKIP
    assert "tool_create" not in results[0].detail  # only the MISSING names are listed
    assert "role_create" in results[0].detail


def test_run_r7_full_success_every_check_passes():
    client = _ScriptedClient(_r7_success_responses())

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    assert not any(r.status == ls.STATUS_FAIL for r in results), [r.line() for r in results]
    assert not any(r.status == ls.STATUS_SKIP for r in results), [r.line() for r in results]
    assert len(results) >= 30
    assert client.calls[-1][0] == "plan_delete"  # cleanup always runs last


def test_run_r7_tool_delete_is_soft_never_hard():
    """tool_delete is deliberately soft (the tool is still referenced by the
    live toolset membership at that point in the recipe) -- hard=true is
    never passed."""
    client = _ScriptedClient(_r7_success_responses())

    asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    tool_delete_calls = [params for name, params in client.calls if name == "tool_delete"]
    assert len(tool_delete_calls) == 1
    assert tool_delete_calls[0].get("hard") is not True


def test_run_r7_membership_lifecycle_ordering():
    """toolset_member_add happens while the tool is still live; tool_delete
    (soft) follows; the membership is detached before the toolset itself is
    hard-deleted."""
    client = _ScriptedClient(_r7_success_responses())

    asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    names = [name for name, _ in client.calls]
    assert names.index("toolset_member_add") < names.index("tool_delete")
    assert names.index("tool_delete") < names.index("toolset_member_remove")
    assert names.index("toolset_member_remove") < names.index("toolset_delete")


def test_run_r7_model_deleted_before_its_provider():
    """model_delete must precede provider_delete: deleting the provider
    first would be DELETE_BLOCKED by the still-live model.provider_uuid
    reference."""
    client = _ScriptedClient(_r7_success_responses())

    asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    names = [name for name, _ in client.calls]
    assert names.index("model_delete") < names.index("provider_delete")


def test_run_r7_provider_reactivated_before_role_model_resolve():
    """provider_set_status(suspended) is exercised, but provider_update
    flips status back to active BEFORE role_model_resolve -- its candidate
    list is built only from active providers."""
    client = _ScriptedClient(_r7_success_responses())

    asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    names = [name for name, _ in client.calls]
    assert names.index("provider_update") < names.index("role_model_resolve")
    provider_update_params = next(p for n, p in client.calls if n == "provider_update")
    assert provider_update_params["status"] == "active"


def test_run_r7_role_model_resolve_asserts_shape_not_specific_winner():
    """The resolve result is asserted for SHAPE only (source/chosen_provider/
    chosen_model present) -- a genuine live server may resolve via an
    explicit binding instead of the step-level-requirement path, and that
    must still PASS."""
    responses = _r7_success_responses()
    responses["role_model_resolve"] = _ok(
        {"source": "explicit_binding", "chosen_provider": "some-other-provider", "chosen_model": "some-other-model", "chosen_level": None, "provenance": {}}
    )
    client = _ScriptedClient(responses)

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    by_name = {r.name: r for r in results}
    assert by_name["R7_role_model_resolve"].status == ls.STATUS_PASS


def test_run_r7_role_model_resolve_missing_shape_fails():
    responses = _r7_success_responses()
    responses["role_model_resolve"] = _ok({"source": "step_requirement"})  # missing chosen_provider/chosen_model
    client = _ScriptedClient(responses)

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    by_name = {r.name: r for r in results}
    assert by_name["R7_role_model_resolve"].status == ls.STATUS_FAIL


def test_run_r7_invocation_profile_resolve_asserts_shape_not_specific_winner():
    responses = _r7_success_responses()
    responses["invocation_profile_resolve"] = _ok(
        {"profile": {"uuid": "some-other-profile"}, "source_scope": "role", "source_profile_uuid": "some-other-profile", "inheritance_path": []}
    )
    client = _ScriptedClient(responses)

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    by_name = {r.name: r for r in results}
    assert by_name["R7_invocation_profile_resolve"].status == ls.STATUS_PASS


def test_run_r7_step_assignment_resolve_no_applicable_assignment_is_pass():
    """No step_assignment_create command exists anywhere in this server's
    surface, so NO_APPLICABLE_ASSIGNMENT is the deterministic, expected
    outcome -- and it is this check's PASS condition, not a failure."""
    client = _ScriptedClient(_r7_success_responses())

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    by_name = {r.name: r for r in results}
    assert by_name["R7_step_assignment_resolve_no_applicable"].status == ls.STATUS_PASS


def test_run_r7_step_assignment_resolve_unexpected_success_fails():
    """If step_assignment_resolve ever DOES succeed (e.g. a future CR ships
    a write path and seed data), that is a surprise this pipeline must FAIL
    on, not silently accept as if it were the expected empty-table state."""
    responses = _r7_success_responses()
    responses["step_assignment_resolve"] = _ok(
        {"resolved_assigned_role": "as_author", "resolved_toolset_uuid": None, "source": "system", "source_assignment_uuid": "x", "inheritance_path": []}
    )
    client = _ScriptedClient(responses)

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    by_name = {r.name: r for r in results}
    assert by_name["R7_step_assignment_resolve_no_applicable"].status == ls.STATUS_FAIL


def test_run_r7_transport_failure_on_plan_create_fails_not_skips():
    client = _ScriptedClient({"plan_create": RuntimeError("boom")})

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    plan_create_result = next(r for r in results if r.name == "R7_plan_create")
    assert plan_create_result.status == ls.STATUS_FAIL
    assert "boom" in plan_create_result.detail
    assert [name for name, _ in client.calls] == ["plan_create"]  # nothing else attempted, no double-cleanup


def test_run_r7_mid_sequence_failure_still_cleans_up_created_entities():
    """toolset_create fails after tool_create succeeded: the tool must
    still be (soft-)deleted and the throwaway plan hard-deleted, via the
    top-level finally block."""
    responses = _r7_success_responses()
    responses["toolset_create"] = {"success": False, "error": {"message": "boom", "data": {"domain_code": "RUNTIME_VALIDATION_ERROR"}}}
    client = _ScriptedClient(responses)

    results = asyncio.run(ls.run_r7_agent_config_lifecycle(client, ls.R7_REQUIRED_COMMANDS))

    by_name = {r.name: r for r in results}
    assert by_name["R7_toolset_create"].status == ls.STATUS_FAIL
    names = [name for name, _ in client.calls]
    assert "tool_delete" in names  # cleanup fallback in finally
    assert names[-1] == "plan_delete"
    tool_delete_params = next(p for n, p in client.calls if n == "tool_delete")
    assert tool_delete_params.get("hard") is not True


def test_run_r7_required_commands_land_in_tier4_handled_not_skipped():
    result = ls.classify_catalog(ls.R7_REQUIRED_COMMANDS)
    skipped_names = {n for n, _ in result.skipped}
    assert skipped_names.isdisjoint(ls.R7_REQUIRED_COMMANDS)
    assert ls.R7_REQUIRED_COMMANDS <= set(result.tier4_handled)


# --------------------------------------------------------------------------
# R8 (bug 3de7a081, wrong_output, blocker): sequential in-cascade
# step_update calls on a GS and its TS child were reported to leave
# coverage.gs reporting persisted concepts missing, while step_get read
# them back correctly and coverage.relations passed -- a suspected
# divergent read path between step_get and the mechanical gate's coverage
# checks. Live reproduction (three scratch-plan trials, see
# tests/test_bug_3de7a081_gs_coverage_live_read.py) DISPROVED the theory:
# every observed server already evaluates coverage.gs against the live,
# in-cascade materialized state. R8's SKIP branch is therefore gated on
# directly inspecting cascade_preview's own gate_report_json (exactly like
# R6's negation sub-check), not on a catalog-presence or doc marker, since
# there is no known pre-fix deployment to gate a version split on.
# Exercised purely against a _ScriptedClient, no real network.
# --------------------------------------------------------------------------


def _r8_gate_report(*, concept_missing: bool) -> str:
    """Build a cascade_preview-shaped gate_report_json string carrying (or
    not) a coverage.gs finding on G-001 for concept C-001, mirroring the
    real gate's render_json shape closely enough for
    _r8_report_flags_gs_missing to parse."""
    findings = []
    if concept_missing:
        findings.append(
            {
                "check_id": "coverage.gs",
                "severity": "error",
                "artifact_path": "G-001",
                "message": "concept 'C-001' missing",
            }
        )
    return json.dumps(
        {
            "checks": [{"check_id": "coverage.gs", "findings": findings, "passed": not findings}],
            "green": not findings,
        }
    )


def _r8_success_responses(*, concept_missing: bool) -> dict[str, Any]:
    """The full scripted response table run_r8_gs_coverage_live_cascade_read
    invokes on the recipe's happy path, parameterized on whether the
    resulting gate_report_json still flags the concept missing."""
    report = _r8_gate_report(concept_missing=concept_missing)
    return {
        "plan_create": _ok({"uuid": "r8-plan"}),
        "context_common": _ok({}),
        "step_create": _sequence(
            _ok({"uuid": "g-uuid", "step_id": "G-001"}),
            _ok({"uuid": "t-uuid", "step_id": "T-001"}),
        ),
        "cascade_begin": _ok({"cascade_uuid": "cascade-1"}),
        "concept_add": _ok({"uuid": "concept-1", "concept_id": "C-001"}),
        "step_update": _sequence(
            _ok({"uuid": "g-uuid", "concepts": ["C-001"]}),
            _ok({"uuid": "t-uuid", "concepts": ["C-001"]}),
        ),
        "step_get": _ok({"uuid": "g-uuid", "concepts": ["C-001"]}),
        "cascade_preview": _ok({"gate_green": not concept_missing, "gate_report_json": report}),
        "cascade_abort": _ok({"aborted": True}),
        "plan_delete": _ok({"deleted": True}),
    }


def _r8_client(*, concept_missing: bool) -> "_ScriptedClient":
    return _ScriptedClient(_r8_success_responses(concept_missing=concept_missing))


def test_run_r8_correct_live_read_passes_every_check():
    """The behavior every investigated deployment actually exhibits:
    coverage.gs correctly reads the sequential in-cascade updates on both
    the GS and its TS child, reporting nothing missing."""
    client = _r8_client(concept_missing=False)

    results = asyncio.run(ls.run_r8_gs_coverage_live_cascade_read(client))

    assert not any(r.status == ls.STATUS_FAIL for r in results), [r.line() for r in results]
    assert not any(r.status == ls.STATUS_SKIP for r in results), [r.line() for r in results]
    by_name = {r.name: r for r in results}
    assert by_name["R8_coverage_gs_reads_live_cascade_state"].status == ls.STATUS_PASS
    assert by_name["R8_step_get_reads_back_persisted_concepts"].status == ls.STATUS_PASS
    assert client.calls[-1][0] == "plan_delete"  # cleanup always runs
    assert any(name == "cascade_abort" for name, _ in client.calls)


def test_run_r8_pre_fix_server_skips_not_fails():
    """If a server still (or again) exhibits the reported coverage.gs
    divergence, R8 reports SKIP naming the bug, never FAIL -- there is no
    known pre-fix deployment, so this is a defensive gate against an
    unanticipated server, not the expected steady state."""
    client = _r8_client(concept_missing=True)

    results = asyncio.run(ls.run_r8_gs_coverage_live_cascade_read(client))

    by_name = {r.name: r for r in results}
    assert by_name["R8_coverage_gs_reads_live_cascade_state"].status == ls.STATUS_SKIP
    assert ls.R8_PRE_FIX_SKIP_REASON in by_name["R8_coverage_gs_reads_live_cascade_state"].detail
    assert client.calls[-1][0] == "plan_delete"


def test_run_r8_transport_failure_on_plan_create_fails_not_skips():
    client = _ScriptedClient({"plan_create": RuntimeError("boom")})

    results = asyncio.run(ls.run_r8_gs_coverage_live_cascade_read(client))

    plan_create_result = next(r for r in results if r.name == "R8_plan_create")
    assert plan_create_result.status == ls.STATUS_FAIL
    assert "boom" in plan_create_result.detail
    assert [name for name, _ in client.calls] == ["plan_create"]  # nothing else attempted, no double-cleanup


def test_run_r8_step_update_sequence_matches_gs_then_ts_child():
    client = _r8_client(concept_missing=False)

    asyncio.run(ls.run_r8_gs_coverage_live_cascade_read(client))

    step_update_calls = [params for name, params in client.calls if name == "step_update"]
    assert [c["step_id"] for c in step_update_calls] == ["G-001", "T-001"]
    assert all(c["concepts"] == ["C-001"] for c in step_update_calls)
    assert all(c["cascade_uuid"] == "cascade-1" for c in step_update_calls)


def test_run_r8_mid_sequence_failure_still_aborts_cascade_and_cleans_up():
    """step_update on the TS child fails after the cascade was already
    opened: the open cascade must still be aborted and the throwaway plan
    hard-deleted, via the top-level finally block."""
    responses = _r8_success_responses(concept_missing=False)
    responses["step_update"] = _sequence(
        _ok({"uuid": "g-uuid", "concepts": ["C-001"]}),
        {"success": False, "error": {"message": "boom", "data": {"domain_code": "RUNTIME_VALIDATION_ERROR"}}},
    )
    client = _ScriptedClient(responses)

    results = asyncio.run(ls.run_r8_gs_coverage_live_cascade_read(client))

    by_name = {r.name: r for r in results}
    assert by_name["R8_step_update(T,concepts)"].status == ls.STATUS_FAIL
    names = [name for name, _ in client.calls]
    assert "cascade_abort" in names
    assert names[-1] == "plan_delete"


def test_r8_report_flags_gs_missing_matches_check_id_and_artifact_path_only():
    report = json.dumps(
        {
            "checks": [
                {
                    "check_id": "coverage.gs",
                    "findings": [
                        {"artifact_path": "G-001", "message": "concept 'C-001' missing"},
                        {"artifact_path": "G-002", "message": "concept 'C-001' missing"},
                    ],
                },
                {
                    "check_id": "coverage.relations",
                    "findings": [{"artifact_path": "G-001", "message": "concept 'C-001' missing"}],
                },
            ],
        }
    )
    assert ls._r8_report_flags_gs_missing(report, "G-001", "C-001") is True
    # A different artifact_path under the same check_id must not count.
    assert ls._r8_report_flags_gs_missing(report, "G-003", "C-001") is False
    # A match under a DIFFERENT check_id must not count.
    assert ls._r8_report_flags_gs_missing(report, "G-001", "C-002") is False


def test_r8_report_flags_gs_missing_handles_malformed_report_gracefully():
    assert ls._r8_report_flags_gs_missing("not json", "G-001", "C-001") is False
    assert ls._r8_report_flags_gs_missing(None, "G-001", "C-001") is False
    assert ls._r8_report_flags_gs_missing(42, "G-001", "C-001") is False
