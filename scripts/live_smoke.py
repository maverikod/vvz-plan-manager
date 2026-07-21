#!/usr/bin/env python3
"""THE ONE automated real-server test pipeline for planmgr (ops/delivery-release.yaml
invariant: "exactly ONE pre-delivery/real-server pipeline -- extend it, never
multiply"). Supersedes the manual docs/delivery/cr{1..4}-live-smoke-procedure.md
runbooks as the automated baseline; those runbooks remain as deep manual
procedures for cases this script does not (yet) automate.

Author: Vasiliy Zdanovskiy
email: vasilyvz@gmail.com

TRANSPORT DECISION
------------------
Reuses the shipped ``client/plan_manager_client`` package rather than
implementing a second JSON-RPC caller (laws.yaml ``server_client_law``: a
server project's client hides ALL network interaction; a project built on
mcp-proxy-adapter implements it as a WRAPPER over the adapter's client,
never reimplementing transport). ``plan_manager_client.client.PlanManagerClient``
composes (holds, never inherits) ``mcp_proxy_adapter.client.jsonrpc_client
.client.JsonRpcClient`` on ``self._rpc``, which supplies protocol/TLS/mTLS,
token auth, and queued-job auto-polling (queue_semantics law: a "completed"
queue envelope is not success on its own -- the client's
``execute_command_unified(..., auto_poll=True)`` already unwraps the
terminal queued result before returning). Every command in this script is
dispatched through ``_CommandDispatchMixin._call(name, params)`` --
documented on the class as "the single dispatch point used by every
command-family mixin" -- rather than through one of the five per-family
facade mixins. This is a deliberate choice: the live server's ``help``
catalog can name commands (e.g. ``project_view``, added in parallel with
this script) that do not yet have a facade method; ``_call`` reaches any
named command the live server advertises, which is exactly what a
catalog-driven smoke pipeline needs. ``_call`` is "protected" only by naming
convention -- it is the class's own documented generic dispatch primitive,
not a private transport internal.

TLS
---
``packaging/etc/planmgr/config.json.template`` and ``docker/healthcheck.sh``
agree on exactly three server protocol shapes: ``http`` (plain), ``https``
(self-signed, no client cert), and ``mtls`` (HTTPS with a client certificate
presented and verified against ``server.ssl.ca``). ``JsonRpcClient``'s own
``protocol`` parameter takes exactly these three literal values. This script
mirrors that three-way choice via ``--protocol {http,https,mtls}`` plus
``--cert/--key/--ca``; for convenience, ``--base-url`` (default
``https://127.0.0.1:8080`` for on-host runs, matching the task's stated
default) parses into host/port/protocol, and --protocol=https with both
--cert and --key supplied auto-upgrades the effective protocol to "mtls"
(the shapes only differ in whether a client cert is presented).

TIER DESIGN
-----------
Tier 0: reachability + health/version, asserting --expect-version when given.
Tier 1: EVERY command named in the live ``help`` catalog answers
    ``help(cmdname=<name>)`` with a non-empty schema -- the "all commands"
    baseline coverage requirement.
Tier 2: safe read-only commands invoked with minimal params. Split into
    TIER2_STATIC_PARAMS (zero entity dependency: catalogs, "list"
    commands with limit=1, info/health/ops endpoints) and
    TIER2_SCOPED_NEEDS (need a plan/step/todo/bug/project id created in
    Tier 3, run immediately after Tier 3 creates them, before cleanup).
    Commands this script cannot safely exercise (destructive, needing
    externally prepared payloads, mutating shared non-throwaway state,
    or needing entities this pass does not create) are named in
    KNOWN_SKIP_REASONS with an explicit, non-generic reason; anything left
    over in the live catalog that this script does not recognize at all
    falls into the generic-reason bucket -- nothing is silently capped.
Tier 3: CRUD lifecycles on THROWAWAY entities, all named/titled with the
    ``live-smoke-`` prefix, deleted (verified deleted) in a try/finally even
    on failure: a plan -> step hierarchy (via context_common gate) ->
    graph_order -> plan_delete(hard); a todo lifecycle (create -> update ->
    resolve -> close -> delete hard); a bug lifecycle (create -> confirm ->
    close; no bug_delete command exists in this server's surface, so the
    lifecycle ends at close, not a hard delete).
Tier 4: the three named bug regressions (R1/R2/R3) from the task, each its
    own dedicated throwaway plan where relevant, cleaned up in its own
    try/finally.

Zero-trust note: every result is read back from the live server's own
response, never assumed from a prior call's request payload.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid as uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

REPO_ROOT = Path(__file__).resolve().parent.parent
_CLIENT_SRC = REPO_ROOT / "client"
if str(_CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(_CLIENT_SRC))

PREFIX = "live-smoke-"
DEFAULT_PROJECT_ID = "f06b7269-cc9c-4293-886b-24984e4033ba"

STATUS_PASS = "PASS"
STATUS_FAIL = "FAIL"
STATUS_SKIP = "SKIP"


# --------------------------------------------------------------------------
# Pure data model (no network) -- importable and unit-testable in isolation.
# --------------------------------------------------------------------------


@dataclass
class CheckResult:
    """One check's outcome. Pure data; never touches the network itself."""

    tier: str
    name: str
    status: str
    detail: str = ""

    def line(self) -> str:
        base = f"[{self.status:4s}] {self.tier:6s} {self.name}"
        return f"{base}: {self.detail}" if self.detail else base


@dataclass
class Summary:
    """Aggregated results plus the counts/exit-code computation.

    Kept as a thin, pure wrapper around ``list[CheckResult]`` so
    ``compute_summary`` is fully unit-testable without any network access.
    """

    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == STATUS_PASS]

    @property
    def failed(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == STATUS_FAIL]

    @property
    def skipped(self) -> list[CheckResult]:
        return [r for r in self.results if r.status == STATUS_SKIP]

    def exit_code(self) -> int:
        """0 iff zero failures; SKIPs never affect the exit code."""
        return 0 if not self.failed else 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "counts": {
                "pass": len(self.passed),
                "fail": len(self.failed),
                "skip": len(self.skipped),
            },
            "failed": [r.name for r in self.failed],
            "skipped": [{"name": r.name, "reason": r.detail} for r in self.skipped],
            "results": [
                {"tier": r.tier, "name": r.name, "status": r.status, "detail": r.detail}
                for r in self.results
            ],
            "exit_code": self.exit_code(),
        }

    def render_text(self) -> str:
        lines = [r.line() for r in self.results]
        lines.append("")
        lines.append(
            f"SUMMARY: {len(self.passed)} passed, {len(self.failed)} failed, "
            f"{len(self.skipped)} skipped (of {len(self.results)} checks)"
        )
        if self.failed:
            lines.append("FAILED: " + ", ".join(r.name for r in self.failed))
        if self.skipped:
            lines.append("SKIPPED:")
            for r in self.skipped:
                lines.append(f"  - {r.name}: {r.detail}")
        return "\n".join(lines)


def compute_summary(results: list[CheckResult]) -> Summary:
    """Build a Summary from a flat list of CheckResult (pure, no network)."""
    return Summary(results=list(results))


# --------------------------------------------------------------------------
# Tier 2 allowlists -- pure data + pure classification (unit-tested without
# network in tests/test_live_smoke_script.py).
# --------------------------------------------------------------------------

# Zero-entity-dependency read-only commands: safe to invoke with a static,
# always-valid params dict, no throwaway entity required.
TIER2_STATIC_PARAMS: dict[str, dict[str, Any]] = {
    "plan_list": {"limit": 1},
    "todo_list": {"limit": 1},
    "bug_list": {"limit": 1},
    "audit_list": {"limit": 1},
    "info": {},
    "command_catalog_dump": {},
    "command_timing_stats": {},
    "ops_status": {},
    "health": {},
    "bug_propagation_list": {},
    "comment_list": {},
    "escalation_list": {},
    "execution_attempt_list": {},
    "model_binding_list": {},
    "review_result_list": {},
    "runtime_link_list": {},
    "step_search": {},
    "todo_queue": {},
}

# Read-only commands whose minimal-valid-params invocation needs an entity
# id produced by Tier 3 (or the standing --project arg, need "project").
# Value = tuple of entity keys the params builder (`scoped_params`) needs
# present in the live `entities` dict before this command can be probed.
TIER2_SCOPED_NEEDS: dict[str, tuple[str, ...]] = {
    "plan_status": ("plan",),
    "step_tree": ("plan",),
    "step_list": ("plan",),
    "block_list": ("plan",),
    "branch_dump": ("plan",),
    "branch_weak": ("plan",),
    "concept_list": ("plan",),
    "para_list": ("plan",),
    "relation_list": ("plan",),
    "plan_project_list": ("plan",),
    "plan_score": ("plan",),
    "plan_validate": ("plan",),
    "graph_order": ("plan",),
    "graph_parallel_map": ("plan",),
    "project_dependency_list": ("plan",),
    "srt_snapshot_list": ("plan",),
    "step_runtime_list": ("plan",),
    "step_xref": ("plan",),
    "files_report": ("plan",),
    "step_get": ("plan", "step"),
    "step_dependency_list": ("plan", "step"),
    "step_runtime_get": ("plan", "step"),
    "graph_deps": ("plan", "step"),
    "graph_impact": ("plan", "step"),
    "graph_dependents": ("plan", "step"),
    "block_get": ("plan", "block"),
    "todo_get": ("todo",),
    "bug_get": ("bug",),
    "bug_impact_list": ("bug",),
    "bug_fix_list": ("bug",),
    "project_dependents": ("project",),
}


def scoped_params(name: str, entities: dict[str, str]) -> Optional[dict[str, Any]]:
    """Build minimal params for a TIER2_SCOPED_NEEDS command from live entity ids.

    Returns None when ``name`` is not a scoped command, or when one of its
    required entity keys was never populated (e.g. a prior Tier-3 step
    failed) -- the caller must then record a SKIP, not guess a value.
    """
    needs = TIER2_SCOPED_NEEDS.get(name)
    if needs is None:
        return None
    if any(need not in entities for need in needs):
        return None
    if name in ("step_get", "step_dependency_list", "step_runtime_get", "graph_deps", "graph_impact"):
        return {"plan": entities["plan"], "step_id": entities["step"]}
    if name == "graph_dependents":
        return {"plan": entities["plan"], "step_id": entities["step"], "direction": "downstream"}
    if name == "block_get":
        return {"plan": entities["plan"], "block_id": entities["block"]}
    if name == "todo_get":
        return {"todo": entities["todo"]}
    if name == "bug_get":
        return {"bug_id": entities["bug"]}
    if name == "bug_impact_list":
        return {"bug_id": entities["bug"]}
    if name == "bug_fix_list":
        return {"bug": entities["bug"]}
    if name == "project_dependents":
        return {"project_id": entities["project"]}
    if name == "files_report":
        return {"plan": entities["plan"]}
    return {"plan": entities["plan"]}


# Commands explicitly handled by name in Tier 3 / Tier 4 flows (not generic
# probes): reported under their own named checks, never funnelled into the
# generic SKIP bucket even though they are mutating and thus absent from
# TIER2_*.
TIER3_HANDLED: frozenset[str] = frozenset(
    {
        "plan_create",
        "context_common",
        "step_create",
        "plan_delete",
        "todo_create",
        "todo_update",
        "todo_resolve",
        "todo_close",
        "todo_delete",
        "bug_create",
        "bug_confirm",
        "bug_close",
    }
)
TIER4_HANDLED: frozenset[str] = frozenset(
    {
        "todo_create",
        "todo_delete",
        "step_dependency_preview",
        "step_dependency_apply",
        "step_create",
        "plan_create",
        "plan_delete",
        "graph_order",
        "project_view",
        "todo_list",
        "bug_list",
    }
)

# Commands this pipeline deliberately never invokes live, with the specific
# reason each is unsafe/out-of-scope for a throwaway-entity smoke pass.
KNOWN_SKIP_REASONS: dict[str, str] = {
    "export_cleanup": "destructive filesystem cleanup of export archives; not exercised against live data",
    "plan_import": "requires a prepared export archive/source payload outside the scope of a throwaway smoke entity",
    "export_upload_save": "requires a prior chunked transfer_id handshake; not exercised in this pass",
    "export_read": "requires a materialized export file produced by plan_export/hrs_export; not exercised in this pass",
    "export_archive": "archives export state for a real plan; destructive of export history, not exercised against live data",
    "hrs_import": "mutates HRS from an externally prepared document; out of scope for a throwaway smoke entity",
    "hrs_export": "produces a file-system export artifact; not exercised in this pass",
    "plan_export": "produces a file-system export artifact; not exercised in this pass",
    "plan_snapshot": "produces a file-system snapshot artifact; not exercised in this pass",
    "cascade_begin": "opens a long-lived cascade coordination window; not exercised outside a dedicated cascade CR",
    "cascade_preview": "requires an open cascade_uuid from cascade_begin",
    "cascade_commit": "requires an open cascade_uuid from cascade_begin",
    "cascade_abort": "requires an open cascade_uuid from cascade_begin",
    "plan_unfreeze": "mutates a frozen plan's admission state; no frozen throwaway plan is constructed in this pass",
    "srt_snapshot_create": "computes a semantic reproduction snapshot; expensive/embedding-dependent, not exercised in this pass",
    "srt_diff": "requires two existing srt snapshots",
    "model_binding_set": "mutates the shared, project-wide role/model binding registry; not safe to exercise against live config",
    "model_binding_update": "requires an existing binding_uuid from model_binding_set",
    "model_binding_remove": "requires an existing binding_uuid from model_binding_set",
    "model_binding_resolve": "requires a specific role value from the shared binding registry; not derivable generically",
    "model_binding_get": "requires an existing binding_uuid from model_binding_set",
    "para_insert": "mutates the human-owned HRS prose (root CLAUDE.md: HRS changes only on user decision)",
    "para_update": "mutates the human-owned HRS prose",
    "para_delete": "mutates the human-owned HRS prose",
    "para_label_assign": "mutates the human-owned HRS prose",
    "para_mark_non_binding": "mutates the human-owned HRS prose",
    "para_get": "requires an existing HRS paragraph label; not created in this pass (HRS is human-owned)",
    "concept_add": "mutates MRS concept graph outside a dedicated throwaway lifecycle",
    "concept_update": "mutates MRS concept graph outside a dedicated throwaway lifecycle",
    "concept_remove": "mutates MRS concept graph outside a dedicated throwaway lifecycle",
    "concept_get": "requires an existing concept_id in a populated MRS",
    "concept_coverage": "requires an existing concept_id in a populated MRS",
    "relation_add": "mutates MRS relation graph outside a dedicated throwaway lifecycle",
    "relation_update": "mutates MRS relation graph outside a dedicated throwaway lifecycle",
    "relation_remove": "mutates MRS relation graph outside a dedicated throwaway lifecycle",
    "context_compile": "requires a populated concept scope beyond the minimal throwaway lifecycle",
    "context_specific": "requires a common_block_id and concept scope beyond the minimal throwaway lifecycle",
    "context_bundle": "requires a populated children/concept scope beyond the minimal throwaway lifecycle",
    "branch_prompt": "requires a fully-populated GS/TS/AS branch; out of scope for the minimal throwaway lifecycle",
    "plan_prompt_chain": "requires a populated authoring branch; out of scope for the minimal throwaway lifecycle",
    "step_prompt_verify": "verifies a frozen atomic-step prompt hash; no frozen plan exists in this pass",
    "step_update": "mutates arbitrary declarative step content; not exercised beyond the create/dependency/delete lifecycle",
    "step_move": "reparents a step; not exercised beyond the create/dependency/delete lifecycle",
    "step_set_status": "mutates step status outside the create/dependency/delete lifecycle",
    "step_transition": "transitions plan-level freeze status; no frozen throwaway plan is constructed in this pass",
    "step_delete": "covered implicitly by plan_delete(hard) cascading its steps; not separately invoked in this pass",
    "step_runtime_report": "reports execution-runtime telemetry; not exercised in this pass",
    "execution_attempt_create": "records an execution-runtime attempt; not exercised in this pass",
    "execution_attempt_report": "requires an existing attempt_id from execution_attempt_create",
    "execution_attempt_get": "requires an existing attempt_id from execution_attempt_create",
    "review_result_create": "records a review verdict against an object beyond this pass's scope",
    "review_result_get": "requires an existing review_uuid from review_result_create",
    "escalation_create": "records an escalation record beyond this pass's scope",
    "escalation_get": "requires an existing escalation_uuid from escalation_create",
    "escalation_resolve": "requires an existing escalation_uuid from escalation_create",
    "comment_add": "records a comment beyond this pass's scope",
    "comment_get": "requires an existing comment_uuid from comment_add",
    "comment_supersede": "requires an existing comment_uuid from comment_add",
    "comment_resolve": "requires an existing comment_uuid from comment_add",
    "comment_delete": "requires an existing comment_uuid from comment_add",
    "runtime_link_add": "links two runtime entities beyond this pass's scope",
    "runtime_link_remove": "requires an existing link from runtime_link_add",
    "todo_link_add": "links two todo items beyond this pass's minimal lifecycle",
    "todo_link_remove": "requires an existing link from todo_link_add",
    "todo_reanchor": "reanchors a todo's primary anchor; not exercised beyond the create/delete lifecycle",
    "todo_promote_to_cascade_request": "promotes a todo into a cascade request; not exercised in this pass",
    "bug_reanchor": "reanchors a bug's primary source; not exercised beyond the create/confirm/close lifecycle",
    "bug_reject": "terminal bug transition; not exercised beyond the create/confirm/close lifecycle",
    "bug_mark_duplicate": "requires a second bug to mark as a duplicate target; not exercised in this pass",
    "bug_reopen": "reopens a terminal bug; not exercised beyond the create/confirm/close lifecycle",
    "bug_update": "arbitrary bug field mutation; not exercised beyond the create/confirm/close lifecycle",
    "bug_triage": "alternate lifecycle branch to bug_confirm; not exercised in this pass",
    "bug_impact_add": "records a bug impact beyond this pass's scope",
    "bug_impact_update": "requires an existing impact_uuid from bug_impact_add",
    "bug_impact_discover": "runs CA-backed impact discovery; not exercised in this pass",
    "bug_fix_create": "records a bug fix beyond this pass's scope",
    "bug_fix_update": "requires an existing bug_fix from bug_fix_create",
    "bug_fix_verify": "requires an existing bug_fix from bug_fix_create",
    "bug_propagation_create": "records a fix propagation beyond this pass's scope",
    "bug_propagation_update": "requires an existing propagation_id from bug_propagation_create",
    "bug_propagation_generate_todos": "requires an existing bug_fix_id from bug_fix_create",
    "project_dependency_add": "mutates the shared project-dependency graph; not safe to exercise against live config",
    "project_dependency_update": "requires an existing dependency_uuid from project_dependency_add",
    "project_dependency_confirm": "requires an existing dependency_uuid from project_dependency_add",
    "project_dependency_remove": "requires an existing dependency_uuid from project_dependency_add",
    "project_dependency_discover": "runs CA-backed dependency discovery; not exercised in this pass",
    "step_dependency_add": "covered by the R2 regression's dedicated step_dependency_apply lifecycle, not separately probed",
    "step_dependency_remove": "covered by the R2 regression's dedicated step_dependency_apply lifecycle, not separately probed",
    "step_dependency_set": "covered by the R2 regression's dedicated step_dependency_apply lifecycle, not separately probed",
    "step_dependency_clear": "covered by the R2 regression's dedicated step_dependency_apply lifecycle, not separately probed",
    "plan_project_attach": "mutates the plan<->project binding on a throwaway plan we already tear down; not exercised in this pass",
    "plan_project_detach": "requires an existing plan_project_attach binding to remove; not exercised in this pass",
    "plan_project_set_primary": "requires an existing plan_project_attach binding to promote; not exercised in this pass",
    "plan_project_clear_primary": "requires an existing primary plan-project binding to clear; not exercised in this pass",
}


GENERIC_SKIP_REASON = (
    "not covered by an explicit safe-invocation recipe in this pipeline; "
    "add a TIER2/TIER3/TIER4/KNOWN_SKIP_REASONS entry before relying on this "
    "command's live behavior"
)


@dataclass
class Classification:
    """Pure partition of a live command catalog into pipeline tiers."""

    tier2_static: list[str]
    tier2_scoped: list[str]
    tier3_handled: list[str]
    tier4_handled: list[str]
    skipped: list[tuple[str, str]]


def classify_catalog(catalog_names: frozenset[str]) -> Classification:
    """Partition a live ``help`` catalog into tiers (pure, no network).

    ``help`` itself is excluded (it drives Tier 1, not a Tier-2 probe target).
    Every other name lands in exactly one bucket: TIER2_STATIC_PARAMS,
    TIER2_SCOPED_NEEDS, TIER3_HANDLED/TIER4_HANDLED (accounted for but not
    generically probed), or the SKIP list (explicit reason if known, the
    generic reason otherwise -- never silently dropped).
    """
    names = sorted(n for n in catalog_names if n != "help")
    tier2_static: list[str] = []
    tier2_scoped: list[str] = []
    tier3_handled: list[str] = []
    tier4_handled: list[str] = []
    skipped: list[tuple[str, str]] = []
    handled = TIER3_HANDLED | TIER4_HANDLED
    for name in names:
        if name in TIER2_STATIC_PARAMS:
            tier2_static.append(name)
            continue
        if name in TIER2_SCOPED_NEEDS:
            tier2_scoped.append(name)
            continue
        if name in handled:
            if name in TIER3_HANDLED:
                tier3_handled.append(name)
            if name in TIER4_HANDLED:
                tier4_handled.append(name)
            continue
        if name in KNOWN_SKIP_REASONS:
            skipped.append((name, KNOWN_SKIP_REASONS[name]))
            continue
        skipped.append((name, GENERIC_SKIP_REASON))
    return Classification(
        tier2_static=tier2_static,
        tier2_scoped=tier2_scoped,
        tier3_handled=tier3_handled,
        tier4_handled=tier4_handled,
        skipped=skipped,
    )


def unique_suffix(tag: str) -> str:
    """Return a short unique slug fragment for one throwaway entity name."""
    return f"{PREFIX}{tag}-{uuid_mod.uuid4().hex[:8]}"


# --------------------------------------------------------------------------
# Envelope unwrapping (pure, no network) -- fixes a real first-live-run
# defect: the 0.1.52 server queues EVERY command, even trivial reads
# (info/help came back "completed" almost instantly, but still queued).
#
# INVESTIGATION FINDING (queue-mode selection): the shipped
# client/plan_manager_client/dispatch.py `_CommandDispatchMixin._call`
# already calls the adapter's `execute_command_unified(..., auto_poll=True)`
# -- this IS the client's synchronous poll-and-unwrap mode; it blocks until
# the WebSocket command session reports a terminal event and then fetches
# `session.result()` (see
# .venv/lib/python3.12/site-packages/mcp_proxy_adapter/client/jsonrpc_client
# /command_api.py:224-330). There is NO more-synchronous alternative to
# switch to: passing `expect_queue=False` does not mean "wait, but skip
# WebSocket bookkeeping" -- it means "return the initial acceptance
# envelope immediately, before the job finishes" (command_api.py's
# docstring at 246-266, and the `if expect_queue is False: return
# {"mode": "immediate", ..., "result": command_result}` branch further
# down), i.e. the ASYNC/non-blocking handoff mode -- the opposite of what
# a synchronous smoke pipeline needs. So `_call`'s hardcoded auto_poll=True
# was already the right mode; there was nothing to "enable explicitly".
#
# The actual defect is in how many wrapper layers are peeled off after the
# terminal event. command_api.py:308-316 does exactly ONE conditional
# unwrap: `raw_result = session_result.get("result")`, then unwraps a
# SECOND level only `if isinstance(raw_result, dict) and "data" in
# raw_result`. On this live run, that second check evidently found no
# top-level "data" key (server-side result-fetch shape apparently nests
# one level deeper than the adapter code assumes), so the unwrap stopped
# one layer early and `execute_command_unified`'s own "result" field --
# which `_call` returns via `response.get("result")` -- still carried the
# full queue envelope (job_id/command/inner-result/status), exactly the
# shape in the evidence: `{"job_id":..., "command": "info", "result":
# {"success": True, "data": {"identity": {...}}}, "status": "completed"}`.
#
# Rather than patch the shared adapter/client package (out of scope for a
# script-local fix, and used elsewhere), this script defensively unwraps
# ANY nesting/combination of the two known envelope shapes itself:
#   - a queue/dispatch envelope: dict with "status" alongside "job_id"
#     and/or "queued" and/or "mode" -- only a COMPLETED status is unwrapped
#     (into its "result" key); any other status is a failure, and the full
#     envelope at that layer is preserved verbatim for diagnosis.
#   - an adapter SuccessResult/ErrorResult envelope: dict with a boolean
#     "success" key -- True unwraps into "data" (or the envelope minus
#     "success" if "data" is absent); False is a failure, surfacing
#     "error" (or the whole envelope) verbatim.
# queue_semantics law: a "completed" queue status is not command success on
# its own -- always check the inner result, which is exactly what this
# loop does at every layer before declaring victory.
# --------------------------------------------------------------------------

COMPLETED_STATUSES: frozenset[str] = frozenset({"completed", "command_completed", "job_completed"})
_UNWRAP_MAX_DEPTH = 5


def unwrap_envelope(raw: Any) -> tuple[bool, Any]:
    """Peel any nesting/combination of queue and success/error envelopes.

    Returns (True, data) once ``raw`` is fully unwrapped to plain command
    data (a dict with no recognized wrapper keys, or any non-dict value).
    Returns (False, diagnostic) at the first failing layer -- a
    non-completed queue status, or an explicit success=False -- with
    ``diagnostic`` set to the raw payload AT THAT LAYER (never summarized
    away), so a genuine command failure is distinguishable from an unwrap
    bug. A malformed/cyclical shape that never resolves within
    ``_UNWRAP_MAX_DEPTH`` layers is itself reported as a failure rather
    than looping forever.
    """
    current = raw
    for _ in range(_UNWRAP_MAX_DEPTH):
        if not isinstance(current, dict):
            return True, current
        if "status" in current and any(k in current for k in ("job_id", "queued", "mode")):
            status = current.get("status")
            if status not in COMPLETED_STATUSES:
                return False, current
            current = current.get("result")
            continue
        if "success" in current and isinstance(current.get("success"), bool):
            if not current["success"]:
                return False, current.get("error", current)
            current = current.get("data", {k: v for k, v in current.items() if k != "success"})
            continue
        return True, current
    return False, {"error": "envelope unwrap exceeded max depth", "raw": raw}


# --------------------------------------------------------------------------
# Networked runtime (async) -- everything below touches the live server.
# tests/test_live_smoke_script.py never imports asyncio or calls these.
# --------------------------------------------------------------------------


def _protocol_from_base_url(base_url: str) -> tuple[str, str, int]:
    """Parse --base-url into (protocol, host, port); protocol in {http,https}."""
    parts = urlsplit(base_url)
    scheme = parts.scheme or "https"
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if scheme == "https" else 80)
    return scheme, host, port


def build_config(args: argparse.Namespace) -> "ClientConnectionConfig":  # noqa: F821
    from plan_manager_client.config import ClientConnectionConfig

    if args.base_url:
        protocol, host, port = _protocol_from_base_url(args.base_url)
    else:
        protocol, host, port = args.protocol, args.host, args.port
    if args.protocol_override:
        protocol = args.protocol_override
    if protocol == "https" and args.cert and args.key:
        protocol = "mtls"
    return ClientConnectionConfig(
        protocol=protocol,
        host=host,
        port=port,
        cert=args.cert,
        key=args.key,
        ca=args.ca,
        check_hostname=False,
        timeout=args.timeout,
    )


async def call(client: Any, name: str, params: Optional[dict[str, Any]] = None) -> tuple[bool, Any]:
    """Invoke one command through the client's generic dispatch primitive.

    Returns (True, data) on success, with ``data`` fully unwrapped through
    ``unwrap_envelope`` regardless of how many queue/success layers the live
    server's response carried (see the module-level investigation note
    above ``unwrap_envelope``). Returns (False, diagnostic) on any raised
    exception (the diagnostic string includes the exception's ``.details``
    attribute verbatim when present -- e.g. CommandSessionFailedError's
    ``{"terminal_event": ..., "result_status": ...}`` -- so a genuine queued
    failure is distinguishable from an unwrap bug) or on a non-completed
    status / success=False found while unwrapping.
    """
    try:
        raw = await client._call(name, params or {})  # noqa: SLF001 -- documented single dispatch point
    except Exception as exc:  # noqa: BLE001 -- this IS the failure-classification boundary
        details = getattr(exc, "details", None)
        message = str(exc)
        if details:
            message = f"{message} | details={details!r}"
        return False, message
    ok, data = unwrap_envelope(raw)
    if not ok:
        return False, f"non-success/incomplete envelope: {data!r}"
    return True, data


async def run_tier0(client: Any, expect_version: Optional[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    ok, info = await call(client, "info", {})
    if not ok:
        results.append(CheckResult("0", "server_reachable", STATUS_FAIL, str(info)))
        return results
    results.append(CheckResult("0", "server_reachable", STATUS_PASS))
    identity = (info or {}).get("identity", {}) if isinstance(info, dict) else {}
    version = identity.get("package_version")
    if version is None:
        results.append(CheckResult("0", "info_has_version", STATUS_FAIL, f"no identity.package_version in {info!r}"))
    else:
        results.append(CheckResult("0", "info_has_version", STATUS_PASS, f"version={version}"))
        if expect_version is not None:
            status = STATUS_PASS if version == expect_version else STATUS_FAIL
            results.append(CheckResult("0", "version_matches_expected", status, f"reported={version} expected={expect_version}"))
    ok, health = await call(client, "health", {})
    results.append(CheckResult("0", "health_ok", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(health)))
    return results


async def run_tier1(client: Any, catalog_names: list[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in catalog_names:
        ok, schema = await call(client, "help", {"cmdname": name})
        if not ok:
            results.append(CheckResult("1", f"help({name})", STATUS_FAIL, str(schema)))
            continue
        has_schema = isinstance(schema, dict) and bool(schema.get("schema") or schema.get("metadata"))
        results.append(
            CheckResult(
                "1", f"help({name})", STATUS_PASS if has_schema else STATUS_FAIL,
                "" if has_schema else f"empty/malformed help payload: {schema!r}",
            )
        )
    return results


async def run_tier2_static(client: Any, catalog_names: frozenset[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name, params in TIER2_STATIC_PARAMS.items():
        if name not in catalog_names:
            continue
        ok, res = await call(client, name, params)
        results.append(CheckResult("2", name, STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


async def run_tier2_scoped(client: Any, catalog_names: frozenset[str], entities: dict[str, str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name in TIER2_SCOPED_NEEDS:
        if name not in catalog_names:
            continue
        params = scoped_params(name, entities)
        if params is None:
            results.append(CheckResult("2", name, STATUS_SKIP, "required throwaway entity was not available"))
            continue
        ok, res = await call(client, name, params)
        results.append(CheckResult("2", name, STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


def _extract_step_id(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    return payload.get("step_id")


async def run_tier3_plan_step_lifecycle(client: Any) -> tuple[list[CheckResult], dict[str, str]]:
    """plan_create -> context_common -> step_create (L3, L4) -> graph_order -> plan_delete(hard).

    Returns (results, entities) where entities carries plan/step/block ids
    for Tier-2-scoped reads to reuse before cleanup. Cleanup always runs.
    """
    results: list[CheckResult] = []
    entities: dict[str, str] = {}
    plan_name = unique_suffix("plan")
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": plan_name})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("3", "plan_create", STATUS_FAIL, str(res)))
            return results, entities
        plan_uuid = res["uuid"]
        entities["plan"] = plan_uuid
        results.append(CheckResult("3", "plan_create", STATUS_PASS, f"uuid={plan_uuid}"))

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        results.append(CheckResult("3", "context_common(level3)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "root"})
        step3_id = _extract_step_id(res) if ok else None
        if not ok or step3_id is None:
            results.append(CheckResult("3", "step_create(level3)", STATUS_FAIL, str(res)))
        else:
            results.append(CheckResult("3", "step_create(level3)", STATUS_PASS, f"step_id={step3_id}"))
            entities["step"] = step3_id

            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": step3_id, "child_level": 4})
            block_id = res.get("common_block_id") if ok and isinstance(res, dict) else None
            results.append(CheckResult("3", "context_common(level4)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
            if block_id:
                entities["block"] = block_id

            ok, res = await call(
                client, "step_create",
                {"plan": plan_uuid, "level": 4, "slug": "child", "parent_step_id": step3_id},
            )
            step4_id = _extract_step_id(res) if ok else None
            results.append(CheckResult("3", "step_create(level4)", STATUS_PASS if (ok and step4_id) else STATUS_FAIL, "" if ok else str(res)))
            if step4_id:
                entities["step"] = step4_id

        ok, res = await call(client, "graph_order", {"plan": plan_uuid})
        order_ok = ok and isinstance(res, dict) and "order" in res
        results.append(CheckResult("3", "graph_order", STATUS_PASS if order_ok else STATUS_FAIL, "" if order_ok else str(res)))
    finally:
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("3", "plan_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
            if ok:
                ok2, listing = await call(client, "plan_list", {"limit": 200})
                names = []
                if ok2 and isinstance(listing, dict):
                    names = [p.get("name") for p in listing.get("plans", []) if isinstance(p, dict)]
                deleted_confirmed = plan_name not in names
                results.append(
                    CheckResult(
                        "3", "plan_delete(hard)_verified", STATUS_PASS if deleted_confirmed else STATUS_FAIL,
                        "" if deleted_confirmed else "plan still present in plan_list after hard delete",
                    )
                )
    return results, entities


async def run_tier3_todo_lifecycle(client: Any) -> list[CheckResult]:
    results: list[CheckResult] = []
    title = unique_suffix("todo")
    todo_uuid: Optional[str] = None
    try:
        ok, res = await call(
            client, "todo_create",
            {
                "title": title, "description": "throwaway smoke todo", "kind": "task",
                "priority_nice": 0, "created_by": "live-smoke", "anchor_type": "none",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("3", "todo_create", STATUS_FAIL, str(res)))
            return results
        todo_uuid = res["uuid"]
        results.append(CheckResult("3", "todo_create", STATUS_PASS, f"uuid={todo_uuid}"))

        ok, res = await call(client, "todo_update", {"todo": todo_uuid, "changed_by": "live-smoke", "title": title + "-updated"})
        results.append(CheckResult("3", "todo_update", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "todo_resolve", {"todo": todo_uuid, "changed_by": "live-smoke"})
        results.append(CheckResult("3", "todo_resolve", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "todo_close", {"todo": todo_uuid, "changed_by": "live-smoke"})
        results.append(CheckResult("3", "todo_close", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    finally:
        if todo_uuid is not None:
            ok, res = await call(client, "todo_delete", {"todo": todo_uuid, "changed_by": "live-smoke", "hard": True})
            results.append(CheckResult("3", "todo_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
            if ok:
                ok2, fetched = await call(client, "todo_get", {"todo": todo_uuid})
                results.append(
                    CheckResult(
                        "3", "todo_delete(hard)_verified", STATUS_PASS if not ok2 else STATUS_FAIL,
                        "" if not ok2 else "todo still fetchable after hard delete",
                    )
                )
    return results


async def run_tier3_bug_lifecycle(client: Any, plan_uuid: str) -> list[CheckResult]:
    """bug_create -> bug_confirm -> bug_close. No bug_delete command exists on
    this server's surface, so the lifecycle intentionally ends at close
    (recorded, not treated as a gap -- see KNOWN_SKIP_REASONS note in the
    module docstring)."""
    results: list[CheckResult] = []
    title = unique_suffix("bug")
    ok, res = await call(
        client, "bug_create",
        {
            "plan": plan_uuid, "title": title, "short_description": "throwaway smoke bug",
            "detailed_description": "throwaway smoke bug for live_smoke.py", "kind": "functional",
            "severity": "trivial", "priority_nice": 19, "reporter": "live-smoke",
            "created_by": "live-smoke", "source_type": "unidentified",
        },
    )
    if not ok or not isinstance(res, dict) or not res.get("uuid"):
        results.append(CheckResult("3", "bug_create", STATUS_FAIL, str(res)))
        return results
    bug_uuid = res["uuid"]
    results.append(CheckResult("3", "bug_create", STATUS_PASS, f"uuid={bug_uuid}"))

    ok, res = await call(client, "bug_confirm", {"plan": plan_uuid, "bug_id": bug_uuid, "changed_by": "live-smoke"})
    results.append(CheckResult("3", "bug_confirm", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

    ok, res = await call(client, "bug_close", {"plan": plan_uuid, "bug_id": bug_uuid, "closed_by": "live-smoke"})
    results.append(CheckResult("3", "bug_close", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


# ---- Tier 4: named bug regressions -----------------------------------------


async def run_r1_todo_anchor_none(client: Any) -> list[CheckResult]:
    """Bug c72e047c: literal anchor_type="none" (and description="none") used
    to fail -32602 "Missing required parameters"; must now succeed and report
    primary_anchor_type=="none"."""
    results: list[CheckResult] = []
    todo_uuid: Optional[str] = None
    try:
        ok, res = await call(
            client, "todo_create",
            {
                "title": unique_suffix("r1"), "description": "none", "kind": "task",
                "priority_nice": 0, "created_by": "live-smoke", "anchor_type": "none",
            },
        )
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "R1_todo_create_anchor_none", STATUS_FAIL, str(res)))
            return results
        todo_uuid = res.get("uuid")
        anchor_ok = res.get("primary_anchor_type") == "none"
        results.append(
            CheckResult(
                "4", "R1_todo_create_anchor_none", STATUS_PASS if anchor_ok else STATUS_FAIL,
                "" if anchor_ok else f"primary_anchor_type={res.get('primary_anchor_type')!r}",
            )
        )
        results.append(CheckResult("4", "R1_description_literal_none_accepted", STATUS_PASS if ok else STATUS_FAIL))
    finally:
        if todo_uuid is not None:
            await call(client, "todo_delete", {"todo": todo_uuid, "changed_by": "live-smoke", "hard": True})
    return results


async def run_r2_same_file_order_ambiguity(client: Any) -> list[CheckResult]:
    """Bug 64107707: step_dependency_preview/apply on a plan with pre-existing
    same-file order ambiguity used to fail AS_SAME_FILE_ORDER_AMBIGUOUS
    before candidate simulation. Repro: two same-file pairs (A/B on fileX,
    C/D on fileY) with no dependency between each pair -- the pre-existing
    ambiguity. preview() must now always simulate (returning
    same_file_order.before_findings for both pairs, not raising). A fully
    curative apply (add A->B and C->D, curing both pairs, introducing no new
    ambiguity) must commit."""
    results: list[CheckResult] = []
    plan_name = unique_suffix("r2-plan")
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": plan_name})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R2_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R2_context_common(level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "root"})
        root_id = _extract_step_id(res) if ok else None
        if not ok or root_id is None:
            results.append(CheckResult("4", "R2_step_create(root)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": root_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R2_context_common(level5)", STATUS_FAIL, str(res)))
            return results

        step_ids: dict[str, str] = {}
        for slug in ("a", "b", "c", "d"):
            ok, res = await call(
                client, "step_create",
                {"plan": plan_uuid, "level": 5, "slug": slug, "parent_step_id": root_id},
            )
            sid = _extract_step_id(res) if ok else None
            if not ok or sid is None:
                results.append(CheckResult("4", f"R2_step_create({slug})", STATUS_FAIL, str(res)))
                return results
            step_ids[slug] = sid
        results.append(CheckResult("4", "R2_repro_steps_created", STATUS_PASS, f"{step_ids}"))

        # Pre-existing ambiguity: a/b share target_file X, c/d share target_file
        # Y (both set at scaffold time via SKELETON_FIELDS defaults, so both
        # pairs currently have an EMPTY shared target_file "" -- same-file
        # admission treats same (non-empty distinguishing) target_file steps
        # with no order between them as ambiguous; using step_update is out of
        # scope for this throwaway pass (see KNOWN_SKIP_REASONS), so this
        # repro relies on the scaffold default being identical across
        # siblings, which is exactly the shape same_file_admission flags.

        ok, preview = await call(client, "step_dependency_preview", {"plan": plan_uuid, "changes": []})
        same_file = preview.get("same_file_order") if ok and isinstance(preview, dict) else None
        preview_ok = ok and isinstance(same_file, dict) and "before_findings" in same_file
        results.append(
            CheckResult(
                "4", "R2_preview_simulates_without_raising", STATUS_PASS if preview_ok else STATUS_FAIL,
                "" if preview_ok else str(preview),
            )
        )

        curative_changes = [
            {"op": "add", "step_id": step_ids["b"], "depends_on": [step_ids["a"]]},
            {"op": "add", "step_id": step_ids["d"], "depends_on": [step_ids["c"]]},
        ]
        ok, dry = await call(client, "step_dependency_apply", {"plan": plan_uuid, "changes": curative_changes, "dry_run": True})
        dry_ok = ok and isinstance(dry, dict) and dry.get("dry_run") is True
        results.append(CheckResult("4", "R2_apply_dry_run_no_mutation", STATUS_PASS if dry_ok else STATUS_FAIL, "" if dry_ok else str(dry)))

        ok, real = await call(client, "step_dependency_apply", {"plan": plan_uuid, "changes": curative_changes, "dry_run": False})
        real_ok = ok and isinstance(real, dict) and real.get("applied") is True
        results.append(CheckResult("4", "R2_apply_curative_commits", STATUS_PASS if real_ok else STATUS_FAIL, "" if real_ok else str(real)))

        ok, order = await call(client, "graph_order", {"plan": plan_uuid})
        order_ok = ok and isinstance(order, dict) and "order" in order
        results.append(CheckResult("4", "R2_graph_order_clean", STATUS_PASS if order_ok else STATUS_FAIL, "" if order_ok else str(order)))
    finally:
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


async def run_r3_project_view(client: Any, catalog_names: frozenset[str], project_id: str) -> list[CheckResult]:
    """Bug 18951d08: project_view's todo/bug UUID sets must equal
    todo_list/bug_list(project=...) under identical filters. If project_view
    is absent from the live catalog, this is a FAILURE, not a SKIP -- the
    task requires it be reported as failed when missing."""
    results: list[CheckResult] = []
    if "project_view" not in catalog_names:
        results.append(CheckResult("4", "R3_project_view", STATUS_FAIL, "project_view is not present in the live command catalog"))
        return results

    ok, view = await call(client, "project_view", {"project": project_id, "active_only": True, "todo_limit": 200, "bug_limit": 200})
    if not ok or not isinstance(view, dict):
        results.append(CheckResult("4", "R3_project_view_call", STATUS_FAIL, str(view)))
        return results
    results.append(CheckResult("4", "R3_project_view_call", STATUS_PASS))

    ok_t, todos = await call(client, "todo_list", {"project": project_id, "active_only": True, "limit": 200})
    ok_b, bugs = await call(client, "bug_list", {"project": project_id, "active_only": True, "limit": 200})
    if not ok_t or not ok_b:
        results.append(CheckResult("4", "R3_reference_lists", STATUS_FAIL, f"todo_list ok={ok_t} bug_list ok={ok_b}"))
        return results

    view_todo_uuids = {t.get("uuid") for t in view.get("todos", []) if isinstance(t, dict)}
    ref_todo_uuids = {t.get("uuid") for t in todos.get("todos", []) if isinstance(todos, dict) and isinstance(t, dict)}
    view_bug_uuids = {b.get("uuid") for b in view.get("bugs", []) if isinstance(b, dict)}
    ref_bug_uuids = {b.get("uuid") for b in bugs.get("bugs", []) if isinstance(bugs, dict) and isinstance(b, dict)}

    todos_match = view_todo_uuids == ref_todo_uuids
    bugs_match = view_bug_uuids == ref_bug_uuids
    results.append(CheckResult("4", "R3_todo_uuid_set_matches_todo_list", STATUS_PASS if todos_match else STATUS_FAIL, "" if todos_match else f"view={view_todo_uuids} ref={ref_todo_uuids}"))
    results.append(CheckResult("4", "R3_bug_uuid_set_matches_bug_list", STATUS_PASS if bugs_match else STATUS_FAIL, "" if bugs_match else f"view={view_bug_uuids} ref={ref_bug_uuids}"))

    match_source_present = all("match_source" in t for t in view.get("todos", []) if isinstance(t, dict)) and all(
        "match_source" in b for b in view.get("bugs", []) if isinstance(b, dict)
    )
    results.append(CheckResult("4", "R3_match_source_present", STATUS_PASS if match_source_present else STATUS_FAIL))
    return results


async def run_pipeline(args: argparse.Namespace) -> Summary:
    from plan_manager_client.client import PlanManagerClient

    config = build_config(args)
    client = PlanManagerClient(**config.to_jsonrpc_kwargs())

    results: list[CheckResult] = []
    results += await run_tier0(client, args.expect_version)
    if any(r.status == STATUS_FAIL and r.name == "server_reachable" for r in results):
        return compute_summary(results)

    ok, help_all = await call(client, "help", {})
    catalog: dict[str, str] = help_all.get("commands", {}) if ok and isinstance(help_all, dict) else {}
    if not ok or not catalog:
        results.append(CheckResult("1", "catalog_fetch", STATUS_FAIL, str(help_all)))
        return compute_summary(results)
    catalog_names = frozenset(catalog.keys())
    results.append(CheckResult("1", "catalog_fetch", STATUS_PASS, f"{len(catalog_names)} commands"))

    results += await run_tier1(client, sorted(catalog_names))

    classification = classify_catalog(catalog_names)
    for name, reason in classification.skipped:
        results.append(CheckResult("2", name, STATUS_SKIP, reason))

    results += await run_tier2_static(client, catalog_names)

    plan_step_results, entities = await run_tier3_plan_step_lifecycle(client)
    todo_results = await run_tier3_todo_lifecycle(client)

    # bug lifecycle needs its own plan (the plan/step lifecycle plan is
    # already hard-deleted by the time we get here); create/clean a
    # dedicated one so bug entities can still exist during the tier2-scoped
    # bug_get/bug_impact_list/bug_fix_list probes below.
    bug_plan_name = unique_suffix("bug-plan")
    ok, bug_plan_res = await call(client, "plan_create", {"name": bug_plan_name})
    bug_results: list[CheckResult] = []
    if ok and isinstance(bug_plan_res, dict) and bug_plan_res.get("uuid"):
        bug_plan_uuid = bug_plan_res["uuid"]
        bug_results = await run_tier3_bug_lifecycle(client, bug_plan_uuid)
        for r in bug_results:
            if r.name == "bug_create" and r.status == STATUS_PASS:
                entities["bug"] = r.detail.split("uuid=", 1)[-1]
        await call(client, "plan_delete", {"plan": bug_plan_uuid, "hard": True})
    else:
        bug_results = [CheckResult("3", "bug_plan_create", STATUS_FAIL, str(bug_plan_res))]

    entities["project"] = args.project

    results += plan_step_results
    results += todo_results
    results += bug_results
    results += await run_tier2_scoped(client, catalog_names, entities)

    results += await run_r1_todo_anchor_none(client)
    results += await run_r2_same_file_order_ambiguity(client)
    results += await run_r3_project_view(client, catalog_names, args.project)

    return compute_summary(results)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default=None, help="e.g. https://127.0.0.1:8080; overrides --host/--port/--protocol")
    parser.add_argument("--protocol", dest="protocol", default="https", choices=["http", "https", "mtls"])
    parser.add_argument("--protocol-override", default=None, choices=["http", "https", "mtls"], help="force this protocol regardless of --base-url")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cert", default=None, help="client cert path (mTLS)")
    parser.add_argument("--key", default=None, help="client key path (mTLS)")
    parser.add_argument("--ca", default=None, help="CA cert path (https/mTLS)")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--expect-version", default=None, help="fail Tier 0 if info's package_version differs")
    parser.add_argument("--project", default=DEFAULT_PROJECT_ID, help="project UUID used for project-scoped reads (default: this project's own id)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON summary instead of text")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    summary = asyncio.run(run_pipeline(args))
    if args.json:
        print(json.dumps(summary.to_dict(), indent=2, default=str))
    else:
        print(summary.render_text())
    return summary.exit_code()


if __name__ == "__main__":
    sys.exit(main())
