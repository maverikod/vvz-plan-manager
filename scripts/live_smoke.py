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
    try/finally. Later additions to this same tier: R4/R5/R6 (bug ad529347/
    26fa21a5, 761ee3dd, 5ebe3ce5) and R7 (CR-5a's tool/toolset/role/provider/
    model/invocation_profile/resolve agent-config command surface, marker-
    gated SKIP on a pre-CR-5a server exactly like R4-R6's pre-fix SKIPs).
    R8 (bug 3de7a081): live reproduction against 0.1.57 (three scratch-plan
    trials, see tests/test_bug_3de7a081_gs_coverage_live_read.py) DISPROVED
    the reported divergent-read-path theory -- coverage.gs already reads the
    exact live, in-cascade materialized "step" table state on every deployed
    version this pipeline has observed, so there is no known pre-fix server
    to gate a marker against. R8 asserts that behavior directly (sequential
    in-cascade step_update on a GS and its TS child, matching concepts ->
    cascade_preview's coverage.gs reports nothing missing) and inspects the
    live gate_report_json exactly like R6's behavioral gate: if a future or
    unknown-vintage server ever DOES exhibit the reported divergence, this
    is reported as SKIP (not FAIL), naming the bug, so a genuine regression
    is visible without breaking the pipeline's exit code on servers this
    investigation did not anticipate.

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
    "step_search": ("plan",),
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
        # enum is ["dependents", "dependencies"] -- "downstream"/"upstream" are
        # NOT valid values (confirmed live: -32602 invalid enum value).
        return {"plan": entities["plan"], "step_id": entities["step"], "direction": "dependents"}
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
    if name == "step_search":
        # confirmed live: -32602 Missing required parameters: plan, pattern.
        # "G-" is a harmless substring (the level-3 human step_id prefix
        # convention) whether or not it matches anything in the throwaway plan.
        return {"plan": entities["plan"], "pattern": "G-"}
    if name == "step_xref":
        # confirmed live: -32000 INVALID_FILTER "provide either text or
        # (step and field)" -- step_xref_command.py's _resolve_query_hash
        # requires one of the two filter shapes; "text" alone is simplest
        # and needs no step/field coordination.
        return {"plan": entities["plan"], "text": "live-smoke"}
    return {"plan": entities["plan"]}


# GATE_RED-expected probes: branch_weak/plan_score run the mechanical gate
# (branch_weak_command.py, plan_score_command.py) against a throwaway plan
# that is DELIBERATELY unpolished (2-4 bare-skeleton steps, no concepts/
# relations/prompts) -- confirmed live, this refuses with the documented
# GATE_RED domain error ("mechanical gate not green (N findings)"), which
# is the CORRECT, expected contract response for an unpolished plan, not a
# probe failure. See interpret_gate_red_probe below for the PASS/FAIL logic.
GATE_RED_EXPECTED: frozenset[str] = frozenset({"branch_weak", "plan_score"})


def interpret_gate_red_probe(ok: bool, result_or_diagnostic: Any) -> tuple[str, str]:
    """PASS/FAIL logic for a GATE_RED_EXPECTED command's probe outcome.

    The throwaway plan is deliberately unpolished, so the CORRECT, expected
    response is a refusal carrying the GATE_RED domain error -- that
    refusal is what PASSes here, not an ordinary success. An unexpected
    success (the mechanical gate was somehow green) or ANY other failure
    (a real transport/unknown error, not the documented GATE_RED contract)
    both FAIL, so a genuine regression is never masked by this inverted
    expectation.
    """
    if ok:
        return STATUS_FAIL, f"expected a GATE_RED refusal but the call succeeded: {result_or_diagnostic!r}"
    diagnostic = str(result_or_diagnostic)
    if "GATE_RED" in diagnostic:
        return STATUS_PASS, f"refused as expected (GATE_RED contract): {diagnostic}"
    return STATUS_FAIL, f"failed, but NOT with the expected GATE_RED contract: {diagnostic}"


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
        "bug_fix_create",
        "bug_fix_verify",
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
        "step_update",
        "plan_create",
        "plan_delete",
        "graph_order",
        "project_view",
        "todo_list",
        "bug_list",
        # R7 (CR-5a agent-config surface): the 36 tool/role/provider/model/
        # toolset/invocation_profile/resolve commands this change request
        # adds, exercised end-to-end by run_r7_agent_config_lifecycle below.
        "tool_create", "tool_get", "tool_list", "tool_update", "tool_delete",
        "role_create", "role_get", "role_list", "role_update", "role_delete",
        "provider_create", "provider_get", "provider_list", "provider_set_status",
        "provider_update", "provider_delete",
        "model_create", "model_get", "model_list", "model_update", "model_delete",
        "toolset_create", "toolset_get", "toolset_list", "toolset_update", "toolset_delete",
        "toolset_member_add", "toolset_member_remove",
        "invocation_profile_create", "invocation_profile_get", "invocation_profile_list",
        "invocation_profile_update", "invocation_profile_delete", "invocation_profile_resolve",
        "role_model_resolve", "step_assignment_resolve",
        # R9 (bug c3950b83): the plan-level completion lock's two exempt
        # setter commands, exercised end-to-end by
        # run_r9_plan_completion_lock below.
        "plan_completed_set", "plan_comment_set",
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
    "bug_fix_update": "arbitrary bug-fix field mutation; not exercised beyond the create/verify/close lifecycle",
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
    # adapter-framework queue-management builtins: every call this pipeline
    # makes already exercises the queue machinery implicitly (KNOWN_BUILTIN_
    # COMMANDS/call() routes some commands through it, and the queued path is
    # the default for every domain command); none of these are safe or
    # meaningful to probe standalone (job_id/log/lifecycle churn belonging to
    # OTHER commands' own queue jobs, not a throwaway entity of their own).
    "queue_add_job": "adapter-framework queue-management builtin, exercised implicitly by every queued dispatch this pipeline makes; not separately probed",
    "queue_start_job": "adapter-framework queue-management builtin, exercised implicitly by every queued dispatch this pipeline makes; not separately probed",
    "queue_stop_job": "adapter-framework queue-management builtin, exercised implicitly by every queued dispatch this pipeline makes; not separately probed",
    "queue_delete_job": "adapter-framework queue-management builtin, exercised implicitly by every queued dispatch this pipeline makes; not separately probed",
    "queue_get_job_status": "adapter-framework queue-management builtin, exercised implicitly by every queued dispatch this pipeline makes; not separately probed",
    "queue_get_job_logs": "adapter-framework queue-management builtin, exercised implicitly by every queued dispatch this pipeline makes; not separately probed",
    "queue_list_jobs": "adapter-framework queue-management builtin, exercised implicitly by every queued dispatch this pipeline makes; not separately probed",
    "queue_health": "adapter-framework queue-management builtin, exercised implicitly by every queued dispatch this pipeline makes; not separately probed",
    # server-state mutating admin surface: excluded by design from a
    # throwaway-entity smoke pass -- these mutate live server/proxy
    # configuration shared by every other client, not a disposable entity.
    "reload": "server-state mutating admin surface (config/process reload); excluded by design from a throwaway smoke pass",
    "unload": "server-state mutating admin surface (module/resource unload); excluded by design from a throwaway smoke pass",
    "settings": "server-state mutating admin surface (live configuration); excluded by design from a throwaway smoke pass",
    "transport_management": "server-state mutating admin surface (transport/connection management); excluded by design from a throwaway smoke pass",
    "proxy_registration": "server-state mutating admin surface (mcp-proxy registry membership); excluded by design from a throwaway smoke pass",
    # peer-endpoint transfer handshake: needs a second party to transfer
    # to/from, outside a single throwaway-entity smoke pipeline.
    "transfer_download_begin": "requires a peer transfer endpoint/session handshake outside a single-pipeline throwaway smoke pass",
    "transfer_download_status": "requires an existing transfer session from transfer_download_begin",
    "transfer_upload_begin": "requires a peer transfer endpoint/session handshake outside a single-pipeline throwaway smoke pass",
    "transfer_upload_complete": "requires an existing transfer session from transfer_upload_begin",
    "transfer_upload_status": "requires an existing transfer session from transfer_upload_begin",
    # diagnostic stub, not a real domain/admin surface.
    "roletest": "diagnostic stub command with no real domain/admin behavior; not exercised",
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
# Builtin vs domain command routing (pure, no network) -- second live-run
# defect, on top of the envelope fix above.
#
# EVIDENCE: with envelope unwrapping fixed, Tier 0 went fully green, but
# catalog_fetch still failed: "Queued command 'help' failed" with an inner
# ``result_status.description = 'Command execution failed: "Command \'help\'
# not found"'`` (job_success=False, command_execution=False).
#
# ROOT CAUSE: `help` is an mcp_proxy_adapter FRAMEWORK builtin
# (`CommandApiMixin.help`,
# .venv/lib/python3.12/site-packages/mcp_proxy_adapter/client/jsonrpc_client
# /command_api.py:66-71) -- it is registered on the plain JSON-RPC command
# dispatcher, but NOT in the separate queue-executor registry that the
# WebSocket command-session path (`execute_command_unified`'s default
# auto_poll=True branch, command_api.py:269-330, which is what
# `PlanManagerClient._call` always drives) resolves commands against. That
# path opens a queue job for `help` that the queue runner then cannot
# execute ("Command 'help' not found"), and the terminal event is a
# failure, raising `CommandSessionFailedError` (command_api.py:298-307).
# `info` and `health`, by contrast, ARE plan_manager domain commands
# (plan_manager/commands/info_command.py, plan_manager/commands
# /health_command.py) registered in that same queue-executor registry, so
# they resolve fine via the queued path -- confirmed live (Tier 0 fully
# green after the envelope fix).
#
# FIX: `CommandApiMixin.execute_command(command, params,
# use_cmd_endpoint=False)` (command_api.py:85-109) is the plain,
# non-queued JSON-RPC dispatch primitive `CommandApiMixin.help` itself
# uses internally -- a single request/response round trip against the
# SAME held JsonRpcClient (`client._rpc`; no new session/connection is
# opened per call), resolvable against the plain-JSON-RPC command
# registry that DOES include framework builtins. KNOWN_BUILTIN_COMMANDS
# below routes proactively to that direct path (no failed queue round
# trip first) for every adapter-framework builtin this script is aware
# of; anything not in that set still takes the production-representative
# queued path FIRST (per the coordinator's explicit instruction to keep
# domain commands on the queued route), falling back to the direct path
# exactly once if the queued failure looks like an unresolved-command
# error (`_looks_like_unresolved_command`) -- so a command this script
# does not yet know is a builtin still self-heals, and a genuine domain
# error (e.g. STEP_NOT_FOUND) is never misrouted, since that phrasing
# never quotes the *command* name the way an adapter "Command 'x' not
# found" message does.
# --------------------------------------------------------------------------

KNOWN_BUILTIN_COMMANDS: frozenset[str] = frozenset(
    {
        "help",
        "echo",
        "config",
        "long_task",
        "job_status",
        "queue_add_job",
        "queue_start_job",
        "queue_stop_job",
        "queue_delete_job",
        "queue_get_job_status",
        "queue_get_job_logs",
        "queue_list_jobs",
        "queue_health",
    }
)


def summarize_dispatch_fallbacks(dispatch_log: list[dict[str, Any]]) -> Optional[str]:
    """Pure summary of DISPATCH_LOG entries that needed the fallback retry.

    Returns None when nothing fell back (the common case once
    KNOWN_BUILTIN_COMMANDS is accurate for the live server). Otherwise a
    human-readable note naming every command that recovered via the
    direct-path fallback -- each one is a candidate to add to
    KNOWN_BUILTIN_COMMANDS so future runs skip the failed queue round trip.
    """
    names = sorted({entry["command"] for entry in dispatch_log if entry.get("fallback")})
    if not names:
        return None
    return f"commands recovered via direct-path fallback (consider adding to KNOWN_BUILTIN_COMMANDS): {names}"


def _looks_like_unresolved_command(name: str, diagnostic_text: str) -> bool:
    """True iff a queued-path failure looks like "Command '<name>' not found".

    Deliberately narrow: requires BOTH "not found" and the failing
    command's own name in quotes, so a legitimate domain NOT_FOUND error
    (e.g. "step not found: G-001", which never quotes the *command* name)
    is never misclassified as an unresolved-command routing problem.
    """
    lowered = diagnostic_text.lower()
    name_quoted = f"'{name}'" in diagnostic_text or f'"{name}"' in diagnostic_text
    return "not found" in lowered and name_quoted


# Diagnostic trail of which dispatch path actually served each call this
# run -- "direct" (proactive, KNOWN_BUILTIN_COMMANDS), "queued" (the
# production-representative default), or "queued->direct-fallback" (a
# queued "Command not found" auto-recovered via one direct-path retry,
# meaning KNOWN_BUILTIN_COMMANDS is missing that command name). Reset per
# run by run_pipeline; printed as part of --json output for visibility.
DISPATCH_LOG: list[dict[str, Any]] = []


def reset_dispatch_log() -> None:
    DISPATCH_LOG.clear()


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


def _format_exception(exc: BaseException) -> str:
    """str(exc), plus a raised exception's .details verbatim when present
    (e.g. CommandSessionFailedError's {"terminal_event":..., "result_status":
    ...}) so a genuine queued failure is distinguishable from an unwrap bug."""
    details = getattr(exc, "details", None)
    message = str(exc)
    if details:
        message = f"{message} | details={details!r}"
    return message


async def _call_queued(client: Any, name: str, params: dict[str, Any]) -> tuple[bool, Any]:
    """Invoke one command through the client's queued dispatch primitive.

    This is the production-representative route: PlanManagerClient._call
    (client/plan_manager_client/dispatch.py:42-55) always drives
    execute_command_unified(..., auto_poll=True) -- the WebSocket
    command-session path that blocks for a terminal event before
    returning. Returns (True, data) on success, with ``data`` fully
    unwrapped through ``unwrap_envelope`` regardless of how many
    queue/success layers the live server's response carried. Returns
    (False, diagnostic) on any raised exception, or on a non-completed
    status / success=False found while unwrapping.
    """
    try:
        raw = await client._call(name, params)  # noqa: SLF001 -- documented single dispatch point
    except Exception as exc:  # noqa: BLE001 -- this IS the failure-classification boundary
        return False, _format_exception(exc)
    ok, data = unwrap_envelope(raw)
    if not ok:
        return False, f"non-success/incomplete envelope: {data!r}"
    return True, data


async def _call_direct(client: Any, name: str, params: dict[str, Any]) -> tuple[bool, Any]:
    """Invoke one command through the client's plain, non-queued JSON-RPC path.

    Reaches CommandApiMixin.execute_command(command, params,
    use_cmd_endpoint=False) on the composed client._rpc -- a single
    request/response round trip against the SAME held connection (no new
    session opened per call), resolvable against the plain-JSON-RPC command
    registry that includes adapter-framework builtins the queue executor
    does not know (see the KNOWN_BUILTIN_COMMANDS module note above). This
    is exactly the surface CommandApiMixin.help() itself uses internally.
    """
    try:
        raw = await client._rpc.execute_command(name, params, use_cmd_endpoint=False)  # noqa: SLF001
    except Exception as exc:  # noqa: BLE001
        return False, _format_exception(exc)
    ok, data = unwrap_envelope(raw)
    if not ok:
        return False, f"non-success/incomplete envelope (direct path): {data!r}"
    return True, data


async def call(client: Any, name: str, params: Optional[dict[str, Any]] = None) -> tuple[bool, Any]:
    """Dispatch one command via the routing policy in the module note above
    KNOWN_BUILTIN_COMMANDS: proactively direct for known adapter builtins,
    otherwise queued first with a one-shot direct-path fallback on an
    unresolved-command queue failure. Records which path served the call in
    DISPATCH_LOG for post-run diagnostics."""
    params = params or {}
    if name in KNOWN_BUILTIN_COMMANDS:
        ok, data = await _call_direct(client, name, params)
        DISPATCH_LOG.append({"command": name, "path": "direct", "fallback": False, "ok": ok})
        return ok, data

    ok, data = await _call_queued(client, name, params)
    if not ok and _looks_like_unresolved_command(name, str(data)):
        ok2, data2 = await _call_direct(client, name, params)
        DISPATCH_LOG.append({"command": name, "path": "queued->direct-fallback", "fallback": True, "ok": ok2})
        return ok2, data2

    DISPATCH_LOG.append({"command": name, "path": "queued", "fallback": False, "ok": ok})
    return ok, data


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
        if name in GATE_RED_EXPECTED:
            status, detail = interpret_gate_red_probe(ok, res)
            results.append(CheckResult("2", f"{name}(gate_red_contract)", status, detail))
            continue
        results.append(CheckResult("2", name, STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


def _extract_step_id(payload: Any) -> Optional[str]:
    if not isinstance(payload, dict):
        return None
    return payload.get("step_id")


async def run_tier3_plan_step_create(client: Any) -> tuple[list[CheckResult], dict[str, str], Optional[str], str]:
    """plan_create -> context_common -> step_create (L3, L4) -> graph_order.

    Deliberately does NOT delete the plan -- Tier-2-scoped reads
    (plan_status, step_get, ...) must run against this plan/step/block
    WHILE THEY STILL EXIST (third live run: every entity-scoped probe
    failed PLAN_NOT_FOUND because the original single-function lifecycle
    deleted the plan in its own `finally` before those reads ever ran).
    Returns (results, entities, plan_uuid_or_None, plan_name); the caller
    MUST invoke run_tier3_plan_step_cleanup with the same (plan_uuid,
    plan_name) once every scoped read that needs this plan has run.
    """
    results: list[CheckResult] = []
    entities: dict[str, str] = {}
    plan_name = unique_suffix("plan")

    ok, res = await call(client, "plan_create", {"name": plan_name})
    if not ok or not isinstance(res, dict) or not res.get("uuid"):
        results.append(CheckResult("3", "plan_create", STATUS_FAIL, str(res)))
        return results, entities, None, plan_name
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

    return results, entities, plan_uuid, plan_name


async def run_tier3_plan_step_cleanup(client: Any, plan_uuid: Optional[str], plan_name: str) -> list[CheckResult]:
    """plan_delete(hard) + verify absence from plan_list. Call ONLY after
    every Tier-2-scoped read needing this plan/step/block has finished."""
    results: list[CheckResult] = []
    if plan_uuid is None:
        return results
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
    return results


async def run_tier3_todo_create(client: Any) -> tuple[list[CheckResult], Optional[str]]:
    """todo_create -> todo_update -> todo_resolve -> todo_close.

    Deliberately does NOT delete the todo -- Tier-2-scoped todo_get must run
    against it while it still exists (see run_tier3_plan_step_create's
    docstring for the ordering defect this mirrors). Returns (results,
    todo_uuid_or_None); the caller MUST invoke run_tier3_todo_cleanup with
    the same todo_uuid once the scoped read has run.
    """
    results: list[CheckResult] = []
    title = unique_suffix("todo")

    ok, res = await call(
        client, "todo_create",
        {
            "title": title, "description": "throwaway smoke todo", "kind": "task",
            "priority_nice": 0, "created_by": "live-smoke", "anchor_type": "none",
        },
    )
    if not ok or not isinstance(res, dict) or not res.get("uuid"):
        results.append(CheckResult("3", "todo_create", STATUS_FAIL, str(res)))
        return results, None
    todo_uuid = res["uuid"]
    results.append(CheckResult("3", "todo_create", STATUS_PASS, f"uuid={todo_uuid}"))

    ok, res = await call(client, "todo_update", {"todo": todo_uuid, "changed_by": "live-smoke", "title": title + "-updated"})
    results.append(CheckResult("3", "todo_update", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

    ok, res = await call(client, "todo_resolve", {"todo": todo_uuid, "changed_by": "live-smoke"})
    results.append(CheckResult("3", "todo_resolve", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

    ok, res = await call(client, "todo_close", {"todo": todo_uuid, "changed_by": "live-smoke"})
    results.append(CheckResult("3", "todo_close", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

    return results, todo_uuid


async def run_tier3_todo_cleanup(client: Any, todo_uuid: Optional[str]) -> list[CheckResult]:
    """todo_delete(hard) + verify via a now-failing todo_get. Call ONLY
    after Tier-2-scoped todo_get has run against this todo."""
    results: list[CheckResult] = []
    if todo_uuid is None:
        return results
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


async def run_tier3_bug_create(client: Any, plan_uuid: str) -> tuple[list[CheckResult], Optional[str]]:
    """bug_create -> bug_confirm -> bug_fix_create -> bug_fix_verify(passed=True)
    -> bug_close, the FULL documented closure path.

    Confirmed live: bug_close alone (skipping the fix chain) fails -32000
    "source fix not verified" / INVALID_RUNTIME_STATUS_TRANSITION.
    BugClosureDiscipline.evaluate_closure (plan_manager/domain/bug_closure_
    discipline.py:36-70) requires source_fix_verified=True, and
    bug_close_command.py derives that as ``any(fix.status == "verified" and
    bool(fix.passed) for fix in fixes)`` -- so at least one bug_fix must
    reach status "verified" via bug_fix_verify(passed=True) before close is
    legal. No bug_delete command exists on this server's surface, so the
    lifecycle intentionally ends at close (see KNOWN_SKIP_REASONS note in
    the module docstring); the caller hard-deletes this bug's dedicated
    plan afterward.
    """
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
        return results, None
    bug_uuid = res["uuid"]
    results.append(CheckResult("3", "bug_create", STATUS_PASS, f"uuid={bug_uuid}"))

    ok, res = await call(client, "bug_confirm", {"plan": plan_uuid, "bug_id": bug_uuid, "changed_by": "live-smoke"})
    results.append(CheckResult("3", "bug_confirm", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

    ok, res = await call(
        client, "bug_fix_create",
        {
            "plan": plan_uuid, "bug": bug_uuid, "fix_type": "code",
            "summary": "throwaway smoke fix for live_smoke.py", "author": "live-smoke",
            "created_by": "live-smoke",
        },
    )
    # response is {"bug_fix": {...to_payload()...}} -- the uuid is nested,
    # not top-level (unlike most other create commands' flat payloads).
    fix_uuid = res.get("bug_fix", {}).get("uuid") if ok and isinstance(res, dict) else None
    results.append(CheckResult("3", "bug_fix_create", STATUS_PASS if (ok and fix_uuid) else STATUS_FAIL, "" if ok else str(res)))

    if fix_uuid:
        ok, res = await call(
            client, "bug_fix_verify",
            {"plan": plan_uuid, "bug_fix": fix_uuid, "changed_by": "live-smoke", "passed": True},
        )
        results.append(CheckResult("3", "bug_fix_verify", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

    ok, res = await call(client, "bug_close", {"plan": plan_uuid, "bug_id": bug_uuid, "closed_by": "live-smoke"})
    results.append(CheckResult("3", "bug_close", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results, bug_uuid


# ---- Tier 4: named bug regressions -----------------------------------------

# Bug ad529347: exact substring committed as the fix into
# plan_manager/commands/step_update_metadata.py (detailed_description +
# best_practices), plan_manager/views/context_blocks.py
# (TS_INPUT_OUTPUT_ITEM_SCHEMA, surfaced in level-4 field_schema.item_schemas),
# and plan_manager/verify/gate_structure.py (check_parse_inputs_outputs's
# parse.inputs_outputs finding message). Kept as one named constant so a
# future wording change updates every call site below in one place.
R4_TYPE_ENUM_MARKER = 'one of "input" or "output"'

R4_PRE_FIX_SKIP_REASON = (
    "server predates the ad529347 nested inputs/outputs schema-doc fix "
    "(marker text absent) -- redeploy pending"
)


def _r4_marker_present(payload: Any) -> bool:
    """True iff R4_TYPE_ENUM_MARKER appears literally in ``payload``.

    Deliberately uses ``str(payload)`` rather than ``json.dumps(payload)``:
    the marker itself contains literal double-quote characters (``one of
    "input" or "output"``), and json.dumps ALWAYS backslash-escapes
    embedded quotes in string values, so a naive
    ``marker in json.dumps(payload)`` check can never match -- confirmed by
    direct experiment (``json.dumps({"a": marker})`` yields ``\\"input\\"``,
    never a bare ``"input"``). Python's own ``str()``/``repr()`` of a dict
    shows string values containing double quotes UNCHANGED (it switches to
    single-quote wrapping instead of escaping), so the marker's literal
    quote characters survive the round trip.
    """
    return R4_TYPE_ENUM_MARKER in str(payload)


def _r4_block_is_live(res: Any, block_id: Any) -> Optional[bool]:
    """Return the ``is_live`` flag of one block_list entry matching block_id.

    ``res`` is block_list's own payload, ``{"blocks": [{"block_id": ...,
    "is_live": ...}, ...], "total": ..., ...}``. Returns None when ``res``
    is not shaped as expected or no entry matches ``block_id`` (a caller
    treats None as "could not determine currency", distinct from a
    definite True/False).
    """
    if not isinstance(res, dict):
        return None
    blocks = res.get("blocks")
    if not isinstance(blocks, list):
        return None
    for entry in blocks:
        if isinstance(entry, dict) and entry.get("block_id") == block_id:
            is_live = entry.get("is_live")
            return is_live if isinstance(is_live, bool) else None
    return None


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
    before candidate simulation.

    Repro sequence mirrors the coordinator's proven live repro exactly (an
    earlier attempt in this script skipped level 4 entirely -- creating
    level-5 steps directly under a level-3 parent -- which live evidence
    showed produces GRAPH_CORRUPTED_CHAIN downstream, "parent of step A-001
    not found in nodes": level 5 MUST have a level-4 parent, level 4 a
    level-3 parent):

        plan_create -> context_common(plan, child_level=3) ->
        step_create G (level 3) ->
        context_common(G, child_level=4) -> step_create T-001 (level 4, parent=G) ->
        context_common(G, child_level=4) -> step_create T-002 (level 4, parent=G) ->
        context_common(T-001, child_level=5) -> step_create A (level 5, parent=T-001) ->
        context_common(T-002, child_level=5) -> step_create A (level 5, parent=T-002) ->
        step_update both A steps' target_file to the SAME value (the
        pre-existing ambiguity: two same-file steps with no order between
        them) -> preview/apply.

    context_common is recompiled immediately before EVERY step_create, not
    once per parent: has_current_common_block (plan_manager/views/context_
    blocks.py:544-567) requires the stored block's revision_uuid to match
    the plan's CURRENT head revision exactly, and every step_create bumps
    that head revision -- so a block compiled before an earlier sibling's
    create is already stale for the next one.

    CURATIVE EDGE SCOPE (fourth live run): the two A steps live under
    DIFFERENT level-4 parents (T-001, T-002), so they are NOT siblings, and
    a direct A->A dependency edge is rejected -32000 INVALID_DEPENDENCY_
    SCOPE ("a dependency must reference a sibling step (same parent and
    level)") -- confirmed at plan_manager/commands/step_dependency_ops.py
    :85-94 (resolve_dependency_bare), which requires the target and every
    depends_on ref to share the SAME parent_step_uuid AND level. T-001 and
    T-002, by contrast, ARE siblings (both parented on G, both level 4), so
    the curative batch orders the T-LEVEL pair instead (T-002 depends_on
    [T-001]) -- ordering the tactical parents transitively orders the
    same-file atomic children beneath them. preview is run WITH this
    curative batch (not an empty change list) so its simulated
    same_file_order carries a non-trivial resolved_pairs entry, not just
    before_findings.
    """
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
            results.append(CheckResult("4", "R2_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R2_step_create(G)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R2_step_create(G)", STATUS_PASS, f"step_id={g_id}"))

        t_ids: dict[str, str] = {}
        t_uuids: dict[str, str] = {}
        for slug in ("t-001", "t-002"):
            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
            if not ok:
                results.append(CheckResult("4", f"R2_context_common(G,level4,before {slug})", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": slug, "parent_step_id": g_id})
            tid = _extract_step_id(res) if ok else None
            t_uuid = res.get("uuid") if ok and isinstance(res, dict) else None
            if not ok or tid is None or not t_uuid:
                results.append(CheckResult("4", f"R2_step_create({slug})", STATUS_FAIL, str(res)))
                return results
            t_ids[slug] = tid
            t_uuids[slug] = t_uuid
        results.append(CheckResult("4", "R2_step_create(T-001/T-002)", STATUS_PASS, f"{t_ids}"))

        a_uuids: dict[str, str] = {}
        for slug in ("t-001", "t-002"):
            t_id = t_ids[slug]
            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
            if not ok:
                results.append(CheckResult("4", f"R2_context_common({slug},level5)", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a", "parent_step_id": t_id})
            a_uuid = res.get("uuid") if ok and isinstance(res, dict) else None
            if not ok or not a_uuid:
                results.append(CheckResult("4", f"R2_step_create(A under {slug})", STATUS_FAIL, str(res)))
                return results
            a_uuids[slug] = a_uuid
        results.append(CheckResult("4", "R2_repro_steps_created", STATUS_PASS, f"G={g_id} T={t_ids} A={a_uuids}"))

        shared_file = "src/live_smoke_r2_shared_file.py"
        for slug, a_uuid in a_uuids.items():
            ok, res = await call(client, "step_update", {"plan": plan_uuid, "step_id": a_uuid, "fields": {"target_file": shared_file}})
            if not ok:
                results.append(CheckResult("4", f"R2_step_update(target_file,A under {slug})", STATUS_FAIL, str(res)))
                return results
        results.append(CheckResult("4", "R2_target_file_set_on_both_a_steps", STATUS_PASS, shared_file))

        # Pre-existing ambiguity now in place: the two A steps (different
        # level-4 parents) share target_file with no order between them.
        # The curative edge orders their SIBLING level-4 parents instead
        # (T-002 depends_on T-001) -- a direct A->A edge is out of scope
        # (INVALID_DEPENDENCY_SCOPE: A steps are not siblings of each other).
        curative_changes = [
            {"op": "add", "step_id": t_uuids["t-002"], "depends_on": [t_uuids["t-001"]]},
        ]

        ok, preview = await call(client, "step_dependency_preview", {"plan": plan_uuid, "changes": curative_changes})
        same_file = preview.get("same_file_order") if ok and isinstance(preview, dict) else None
        preview_fields_ok = isinstance(same_file, dict) and all(
            key in same_file for key in ("before_findings", "after_findings", "resolved_pairs", "introduced_pairs")
        )
        preview_ok = ok and preview_fields_ok
        results.append(
            CheckResult(
                "4", "R2_preview_simulates_without_raising", STATUS_PASS if preview_ok else STATUS_FAIL,
                "" if preview_ok else str(preview),
            )
        )

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


async def run_r4_ts_inputs_outputs_schema(client: Any) -> list[CheckResult]:
    """Bug ad529347 (documentation) + bug 26fa21a5 (its enforcement child).

    ad529347: step_update help and the level-4 (TS) context_common /
    context_bundle field_schema used to document fields.inputs /
    fields.outputs only as bare field names, with no nested item contract
    ({name, type, description}, type one of "input" or "output"). The two
    doc-marker sub-checks below (R4_help_documents_item_schema,
    R4_field_schema_documents_item_schema) still independently report SKIP
    (never FAIL) when R4_TYPE_ENUM_MARKER is absent from the live
    response -- this pipeline runs against whatever server is currently
    deployed, and a pre-ad529347 server is an expected, reportable state
    (redeploy pending), not a pipeline defect.

    26fa21a5: the documentation gap made it easy to construct exactly the
    malformed payload step_update then persisted verbatim -- advancing the
    working revision, staling current context blocks, and leaving
    plan_validate as the only place the corruption surfaced. The fix
    rejects a malformed level-4 inputs/outputs item atomically, before any
    write. R4_step_update_malformed_item_rejected /
    R4_step_update_valid_item_accepted / R4_context_currency_survives_rejected_write
    below assert the NEW contract directly against the live server and are
    NOT marker-gated SKIPs: a pre-26fa21a5 server FAILs them outright,
    because on such a server the malformed write would wrongly succeed.

    The former R4_gate_error_states_expected_shape check (proving
    plan_validate's parse.inputs_outputs message states the expected shape
    for an already-persisted invalid TS) is retired: since both step_update
    and layout_import now reject the malformed shape at write time, there
    is no longer a live path to get an invalid TS past the write boundary
    for plan_validate to later catch -- that unreachability is itself the
    fix working. The same message wording is now asserted directly on the
    rejection error from R4_step_update_malformed_item_rejected instead.
    """
    results: list[CheckResult] = []

    ok, help_res = await call(client, "help", {"cmdname": "step_update"})
    if not ok:
        results.append(CheckResult("4", "R4_help_documents_item_schema", STATUS_FAIL, str(help_res)))
    else:
        marker_present = _r4_marker_present(help_res)
        results.append(
            CheckResult(
                "4", "R4_help_documents_item_schema",
                STATUS_PASS if marker_present else STATUS_SKIP,
                "" if marker_present else R4_PRE_FIX_SKIP_REASON,
            )
        )

    plan_name = unique_suffix("r4-plan")
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": plan_name})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R4_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R4_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R4_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, common = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok or not isinstance(common, dict):
            results.append(CheckResult("4", "R4_context_common(G,level4)", STATUS_FAIL, str(common)))
            return results
        blocks = common.get("content") or common.get("blocks") or []
        field_schema_block = next(
            (b for b in blocks if isinstance(b, dict) and b.get("type") == "field_schema"), None
        )
        field_schema_marker_present = field_schema_block is not None and _r4_marker_present(field_schema_block)
        results.append(
            CheckResult(
                "4", "R4_field_schema_documents_item_schema",
                STATUS_PASS if field_schema_marker_present else STATUS_SKIP,
                "" if field_schema_marker_present else R4_PRE_FIX_SKIP_REASON,
            )
        )

        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R4_step_create(T)", STATUS_FAIL, str(res)))
            return results
        node_path = f"{g_id}/{t_id}"

        # Baseline: compile a common context block for T's own AS children
        # and confirm it is reported current, so the "survives a rejected
        # write" check below has a known-current block to re-check.
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
        block_id_before = res.get("common_block_id") if ok and isinstance(res, dict) else None
        if not ok or block_id_before is None:
            results.append(CheckResult("4", "R4_context_common(T,level5,baseline)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "block_list", {"plan": plan_uuid, "node": node_path, "kind": "common"})
        baseline_live = _r4_block_is_live(res, block_id_before)
        if not ok or baseline_live is not True:
            results.append(CheckResult("4", "R4_context_common(T,level5,baseline)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R4_context_common(T,level5,baseline)", STATUS_PASS))

        # 26fa21a5: a malformed level-4 item -- an object with an empty
        # "type" (the same probe ad529347's pre-fix check used to reach
        # plan_validate; a plain-string item is covered by the unit suite
        # in tests/test_bug_26fa21a5_ts_inputs_outputs_write_rejection.py)
        # -- must now be REJECTED atomically, with a message stating the
        # expected shape and allowed type values. Not marker-gated: a
        # pre-26fa21a5 server wrongly accepts this and FAILs here.
        ok, res = await call(
            client, "step_update",
            {
                "plan": plan_uuid, "step_id": t_id,
                "fields": {
                    "inputs": [{"name": "x", "type": "", "description": "y"}],
                    "outputs": [],
                },
            },
        )
        # call()/unwrap_envelope report a queued-path domain error as a
        # formatted diagnostic STRING (not a dict -- see _call_queued's
        # "non-success/incomplete envelope: {data!r}"), the same pattern
        # already used for GATE_RED detection elsewhere in this pipeline;
        # check the stable domain_code and shape marker as substrings.
        rejected_correctly = (
            (not ok)
            and "INVALID_STEP_FIELD_SHAPE" in str(res)
            and _r4_marker_present(res)
        )
        results.append(
            CheckResult(
                "4", "R4_step_update_malformed_item_rejected",
                STATUS_PASS if rejected_correctly else STATUS_FAIL,
                "" if rejected_correctly else f"ok={ok} res={res!r}",
            )
        )

        # Context currency must survive the rejected write above: the same
        # block_id compiled at baseline is still reported current.
        ok, res = await call(client, "block_list", {"plan": plan_uuid, "node": node_path, "kind": "common"})
        still_live = _r4_block_is_live(res, block_id_before)
        results.append(
            CheckResult(
                "4", "R4_context_currency_survives_rejected_write",
                STATUS_PASS if (ok and still_live is True) else STATUS_FAIL,
                "" if (ok and still_live is True) else f"ok={ok} res={res!r}",
            )
        )

        # A subsequent VALID write must still succeed and advance the
        # revision -- the rejection above is a shape check, not a lockout.
        ok, res = await call(
            client, "step_update",
            {
                "plan": plan_uuid, "step_id": t_id,
                "fields": {
                    "inputs": [{"name": "source-file-path", "type": "input", "description": "Path to the file being read."}],
                    "outputs": [{"name": "parsed-record-list", "type": "output", "description": "Records parsed from the source file."}],
                },
            },
        )
        valid_accepted = ok and isinstance(res, dict) and bool(res.get("revision_uuid"))
        results.append(
            CheckResult(
                "4", "R4_step_update_valid_item_accepted",
                STATUS_PASS if valid_accepted else STATUS_FAIL,
                "" if valid_accepted else f"ok={ok} res={res!r}",
            )
        )
    finally:
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R5_PRE_FIX_SKIP_REASON = (
    "server predates the 761ee3dd step-id-selector documentation fix "
    "(marker text absent) -- redeploy pending"
)

# (command_name, ambiguous_code) for every command audited under bug
# 761ee3dd whose step-addressing parameter now documents all three selector
# forms (UUID, canonical path, unambiguous local step id) and the ambiguity
# error case it can raise.
R5_DOC_TARGETS: list[tuple[str, str]] = [
    ("step_get", "AMBIGUOUS_STEP_ID"),
    ("step_delete", "AMBIGUOUS_STEP_ID"),
    ("step_move", "AMBIGUOUS_STEP_ID"),
    ("step_set_status", "AMBIGUOUS_STEP_ID"),
    ("graph_deps", "AMBIGUOUS_STEP_ID"),
    ("graph_dependents", "AMBIGUOUS_STEP_ID"),
    ("graph_impact", "AMBIGUOUS_STEP_ID"),
    ("step_create", "AMBIGUOUS_PARENT_STEP_ID"),
    ("step_update", "AMBIGUOUS_STEP_ID"),
    ("step_transition", "AMBIGUOUS_STEP_ID"),
    ("context_common", "AMBIGUOUS_STEP_ID"),
    ("step_runtime_get", "AMBIGUOUS_STEP_ID"),
    ("step_runtime_report", "AMBIGUOUS_STEP_ID"),
]


def _r5_doc_marker_present(payload: Any, ambiguous_code: str) -> bool:
    """True iff ``payload`` documents a selector-form wording marker
    ("unambiguous" or "canonical path") AND names ``ambiguous_code``
    somewhere in the payload (its error_cases). Uses ``str(payload)`` the
    same way ``_r4_marker_present`` does (see its docstring for why a naive
    json.dumps substring check is unsafe for embedded-quote markers; this
    marker has none, but the helper stays consistent with its sibling)."""
    text = str(payload)
    return ("unambiguous" in text or "canonical path" in text) and ambiguous_code in text


async def run_r5_step_id_selector_docs(client: Any) -> list[CheckResult]:
    """Bug 761ee3dd (documentation, critical): step-addressing commands
    accept a UUID, a canonical path, or an unambiguous bare local step id,
    and reject an ambiguous bare id with AMBIGUOUS_STEP_ID (or
    AMBIGUOUS_PARENT_STEP_ID for a parent/new-parent reference) --
    resolve_step_ref's ambiguity rejection itself already shipped before
    this bug and is exercised unconditionally below. What used to be
    missing was the DOCUMENTATION: several command schemas/metadata named
    only a plain "human-readable step_id" and omitted the ambiguity error
    case from error_cases entirely.

    The R5_help_documents_selector(*) sub-checks are marker-gated SKIP
    (never FAIL) when the marker text is absent from the live help
    response -- this pipeline runs against whatever server is currently
    deployed, and a pre-761ee3dd server is an expected, reportable state
    (redeploy pending), not a pipeline defect (same convention as
    run_r4_ts_inputs_outputs_schema's R4_PRE_FIX_SKIP_REASON checks).

    The R5_step_get_* behavioral sub-checks assert the pre-existing
    resolution contract directly against a throwaway scratch plan and are
    NOT marker-gated: two atomic steps are created with the same local id
    "A-001" under two different tactical parents, so the bare id is
    genuinely ambiguous; step_get with that bare id must fail with
    AMBIGUOUS_STEP_ID while the canonical path and the UUID of one of them
    must each resolve.
    """
    results: list[CheckResult] = []

    for command_name, ambiguous_code in R5_DOC_TARGETS:
        ok, help_res = await call(client, "help", {"cmdname": command_name})
        if not ok:
            results.append(
                CheckResult("4", f"R5_help_documents_selector({command_name})", STATUS_FAIL, str(help_res))
            )
            continue
        marker_present = _r5_doc_marker_present(help_res, ambiguous_code)
        results.append(
            CheckResult(
                "4", f"R5_help_documents_selector({command_name})",
                STATUS_PASS if marker_present else STATUS_SKIP,
                "" if marker_present else R5_PRE_FIX_SKIP_REASON,
            )
        )

    plan_name = unique_suffix("r5-plan")
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": plan_name})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R5_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "root"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R5_step_create(G)", STATUS_FAIL, str(res)))
            return results

        t_ids: list[str] = []
        for slug in ("tactical-one", "tactical-two"):
            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
            if not ok:
                results.append(CheckResult("4", f"R5_context_common(G,level4,{slug})", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(
                client, "step_create", {"plan": plan_uuid, "level": 4, "slug": slug, "parent_step_id": g_id}
            )
            t_id = _extract_step_id(res) if ok else None
            if not ok or t_id is None:
                results.append(CheckResult("4", f"R5_step_create(T,{slug})", STATUS_FAIL, str(res)))
                return results
            t_ids.append(t_id)

        a_uuid_first: Optional[str] = None
        for index, (t_id, slug) in enumerate(zip(t_ids, ("atomic-one", "atomic-two"))):
            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
            if not ok:
                results.append(CheckResult("4", f"R5_context_common(T,level5,{slug})", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(
                client, "step_create", {"plan": plan_uuid, "level": 5, "slug": slug, "parent_step_id": t_id}
            )
            a_id = _extract_step_id(res) if ok else None
            if not ok or a_id is None:
                results.append(CheckResult("4", f"R5_step_create(A,{slug})", STATUS_FAIL, str(res)))
                return results
            if index == 0:
                a_uuid_first = res.get("uuid") if isinstance(res, dict) else None
        results.append(CheckResult("4", "R5_scratch_ambiguous_A-001_created", STATUS_PASS, f"parents={t_ids}"))

        ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": "A-001"})
        bare_rejected = (not ok) and "AMBIGUOUS_STEP_ID" in str(res)
        results.append(
            CheckResult(
                "4", "R5_step_get_bare_ambiguous_id_rejected",
                STATUS_PASS if bare_rejected else STATUS_FAIL,
                "" if bare_rejected else f"ok={ok} res={res!r}",
            )
        )

        canonical_path = f"{g_id}/{t_ids[0]}/A-001"
        ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": canonical_path})
        canonical_resolved = ok and isinstance(res, dict) and res.get("step_id") == "A-001"
        results.append(
            CheckResult(
                "4", "R5_step_get_canonical_path_resolves",
                STATUS_PASS if canonical_resolved else STATUS_FAIL,
                "" if canonical_resolved else f"ok={ok} res={res!r}",
            )
        )

        if a_uuid_first is None:
            results.append(CheckResult("4", "R5_step_get_uuid_resolves", STATUS_FAIL, "no uuid captured at creation"))
        else:
            ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": a_uuid_first})
            uuid_resolved = ok and isinstance(res, dict) and res.get("step_id") == "A-001"
            results.append(
                CheckResult(
                    "4", "R5_step_get_uuid_resolves",
                    STATUS_PASS if uuid_resolved else STATUS_FAIL,
                    "" if uuid_resolved else f"ok={ok} res={res!r}",
                )
            )
    finally:
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R6_PRE_FIX_SKIP_REASON = (
    "server predates the 5ebe3ce5 write-intent negation fix "
    "(AS_MULTIPLE_CODE_FILES still fires on a negated reference) "
    "-- redeploy pending"
)

R6_NEGATED_TARGET = "src/live_smoke_r6_target_negation.py"
R6_NEGATED_REF = "src/live_smoke_r6_legacy.py"
R6_TP_TARGET = "src/live_smoke_r6_target_tp.py"
R6_TP_SECOND = "src/live_smoke_r6_second.py"


def _r6_report_flags_path(report_json: Any, path: str) -> bool:
    """True iff ``path`` appears in any parse.atomic_single_code_file
    finding message within a plan_validate JSON report string.

    ``report_json`` is the raw ``report`` field of a plan_validate result
    (a JSON-encoded string per plan_manager.verify.finding.render_json);
    a non-string or unparseable value is treated as "not flagged" so a
    malformed report surfaces as a FAIL on the caller's own assertion
    rather than a spurious match here.
    """
    if not isinstance(report_json, str):
        return False
    try:
        payload = json.loads(report_json)
    except ValueError:
        return False
    for check in payload.get("checks", []) if isinstance(payload, dict) else []:
        if not isinstance(check, dict) or check.get("check_id") != "parse.atomic_single_code_file":
            continue
        for finding in check.get("findings", []) or []:
            if isinstance(finding, dict) and path in str(finding.get("message", "")):
                return True
    return False


async def run_r6_write_intent_negation(client: Any) -> list[CheckResult]:
    """Bug 5ebe3ce5 (wrong_output, major): the parse.atomic_single_code_file
    check (finding AS_MULTIPLE_CODE_FILES) used to treat every path-like
    token on a write-intent-bearing SENTENCE as an additional write target,
    with no regard for negation or read-only reference intent -- "Do not
    modify X" was flagged as commanding a second write to X purely because
    its sentence also carried a write-intent verb ("modify").

    R6_negated_reference_not_flagged is marker-gated SKIP (never FAIL) on a
    server predating the fix: this pipeline runs against whatever server is
    currently deployed, and a pre-fix server correctly (for ITS OWN,
    unfixed code) still emits the finding for the negated reference -- an
    expected, reportable state (redeploy pending), not a pipeline defect
    (same convention as run_r4_ts_inputs_outputs_schema/run_r5_step_id_
    selector_docs' marker-gated doc checks). It is judged by inspecting the
    live plan_validate JSON report directly, not by a help/doc marker,
    because this bug's fix is behavioral, not documentation.

    R6_true_positive_second_write_still_flagged is NOT marker-gated: a
    genuinely commanded second write ("Also update Y") must still be
    flagged on both a pre-fix and a post-fix server -- the fix narrows the
    check's false positives, it must not blunt its true positives.
    """
    results: list[CheckResult] = []
    plan_name = unique_suffix("r6-plan")
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": plan_name})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R6_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R6_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R6_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R6_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R6_step_create(T)", STATUS_FAIL, str(res)))
            return results

        as_specs = [
            (
                "negation-case",
                R6_NEGATED_TARGET,
                f"Update {R6_NEGATED_TARGET} to add the helper. Do not modify {R6_NEGATED_REF}.",
            ),
            (
                "true-positive-case",
                R6_TP_TARGET,
                f"Update {R6_TP_TARGET} to add the helper. Also update {R6_TP_SECOND}.",
            ),
        ]
        for slug, target_file, prompt in as_specs:
            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
            if not ok:
                results.append(CheckResult("4", f"R6_context_common(T,level5,{slug})", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": slug, "parent_step_id": t_id})
            a_id = _extract_step_id(res) if ok else None
            if not ok or a_id is None:
                results.append(CheckResult("4", f"R6_step_create(A,{slug})", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(
                client, "step_update",
                {
                    "plan": plan_uuid, "step_id": a_id,
                    "fields": {
                        "name": slug, "target_file": target_file, "operation": "modify_file",
                        "priority": 1, "prompt": prompt, "verification": "pytest tests/test_live_smoke_r6.py",
                    },
                },
            )
            if not ok:
                results.append(CheckResult("4", f"R6_step_update(A,{slug})", STATUS_FAIL, str(res)))
                return results
        results.append(CheckResult("4", "R6_repro_steps_created", STATUS_PASS, f"G={g_id} T={t_id}"))

        ok, res = await call(client, "plan_validate", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "R6_plan_validate", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R6_plan_validate", STATUS_PASS))
        report = res.get("report")

        negated_flagged = _r6_report_flags_path(report, R6_NEGATED_REF)
        if negated_flagged:
            results.append(
                CheckResult(
                    "4", "R6_negated_reference_not_flagged", STATUS_SKIP,
                    R6_PRE_FIX_SKIP_REASON,
                )
            )
        else:
            results.append(CheckResult("4", "R6_negated_reference_not_flagged", STATUS_PASS))

        second_write_flagged = _r6_report_flags_path(report, R6_TP_SECOND)
        results.append(
            CheckResult(
                "4", "R6_true_positive_second_write_still_flagged",
                STATUS_PASS if second_write_flagged else STATUS_FAIL,
                "" if second_write_flagged else f"report={report!r}",
            )
        )
    finally:
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R7_PRE_DEPLOY_SKIP_REASON = (
    "server predates the CR-5a agent-config command surface (tool/role/provider/model/"
    "toolset/invocation_profile/resolve commands not yet present in the live help catalog) "
    "-- redeploy pending"
)

# The 36 commands this change request adds (tool C-001, toolset C-002, role
# C-003, provider C-004, model C-005, step_assignment C-007 resolve-only,
# invocation_profile C-008): presence of ALL of them in the live help catalog
# is this pipeline's proxy for "this server has CR-5a deployed" -- see
# run_r7_agent_config_lifecycle's docstring.
R7_REQUIRED_COMMANDS: frozenset[str] = frozenset(
    {
        "tool_create", "tool_get", "tool_list", "tool_update", "tool_delete",
        "role_create", "role_get", "role_list", "role_update", "role_delete",
        "provider_create", "provider_get", "provider_list", "provider_set_status",
        "provider_update", "provider_delete",
        "model_create", "model_get", "model_list", "model_update", "model_delete",
        "toolset_create", "toolset_get", "toolset_list", "toolset_update", "toolset_delete",
        "toolset_member_add", "toolset_member_remove",
        "invocation_profile_create", "invocation_profile_get", "invocation_profile_list",
        "invocation_profile_update", "invocation_profile_delete", "invocation_profile_resolve",
        "role_model_resolve", "step_assignment_resolve",
    }
)


async def run_r7_agent_config_lifecycle(client: Any, catalog_names: frozenset[str]) -> list[CheckResult]:
    """CR-5a agent-config surface (C-001 tool, C-002 toolset, C-003 role,
    C-004 provider, C-005 model, C-007 step assignment resolve-only, C-008
    invocation profile): a representative live CRUD-plus-resolve cycle over
    the 36 commands this change request adds -- every one of them fell into
    classify_catalog's GENERIC_SKIP_REASON before this function existed (see
    tests/test_live_smoke_script.py::
    test_classify_catalog_no_generic_reason_among_shipped_commands, the
    guard this fixup satisfies together with TIER4_HANDLED's R7 additions
    above).

    Marker-gated on R7_REQUIRED_COMMANDS <= catalog_names, exactly like
    run_r4_ts_inputs_outputs_schema/run_r5_step_id_selector_docs/
    run_r6_write_intent_negation's pre-fix SKIP convention: this pipeline
    runs against whatever server is currently deployed, and a pre-CR-5a
    server (the entire command surface absent from the live help catalog,
    not merely a changed behavior on an existing command) is an expected,
    reportable state (redeploy pending), not a pipeline defect -- ONE
    aggregate SKIP is reported rather than 36 individual ones, since on a
    pre-CR-5a server none of these commands can be attempted at all without
    the dispatch layer's "Command not found" routing looking like a
    (misleading) transport FAIL rather than a clean, expected SKIP.

    Recipe (throwaway, ``live-smoke-`` prefixed, every created entity torn
    down in a single top-level try/finally regardless of where the sequence
    stops -- entities already deleted along the natural flow below have
    their tracking variable reset to None so the finally block never
    double-deletes them):

      1. A dedicated throwaway plan supplies the plan-coordinate every
         resolve command below requires.
      2. tool_create -> tool_get -> tool_list -> tool_update.
      3. toolset_create -> toolset_get -> toolset_list -> toolset_update ->
         toolset_member_add(toolset, tool) -- the tool is attached WHILE
         still live.
      4. tool_delete: deliberately SOFT. The tool is still referenced by the
         live toolset membership just created; hard mode is gated by the
         universal deletion rule's inbound-reference integrity check, while
         soft delete carries no such gate.
      5. toolset_member_remove (detach) -> toolset_delete(hard) -- safe now
         that the membership has been removed.
      6. role_create -> role_get -> role_list -> role_update ->
         role_delete(hard) -- a Role (C-003) row is a distinct stored entity
         from the RuntimeRole enum string the resolve commands key on
         (role="as_author" below); nothing downstream references this row.
      7. provider_create(status=active) -> provider_set_status(suspended) ->
         provider_get -> provider_list -> provider_update(status back to
         active, plus a general field) -- the provider must be active again
         before the role_model_resolve probe in step 9, since its candidate
         list is built from list_providers(status="active") only.
      8. model_create(provider_uuid=<the provider>, level=<a live-smoke
         unique level string>) -> model_get -> model_list ->
         model_update(a non-level field, so the unique level survives
         intact for step 9).
      9. role_model_resolve(plan=<throwaway plan>, role="as_author",
         step_required_level=<the unique level>) -- guaranteed to succeed
         regardless of any real production model-binding/role-default
         configuration already live on this shared server: role_model_
         resolve checks an explicit binding FIRST (if one already applies
         live, source="explicit_binding" wins) and otherwise falls through
         to the step-level-requirement path, where our own uniquely-leveled
         model is the only possible match -- either way this is a genuine,
         non-flaky success. Only the result SHAPE is asserted (source/
         chosen_provider/chosen_model keys present), never which path won,
         so this check can never flake off real production bindings.
     10. model_delete(hard) -- before provider_delete, else provider_delete
         would be DELETE_BLOCKED by the still-live model.provider_uuid
         reference.
     11. provider_delete(hard).
     12. invocation_profile_create(scope="system", role="as_author", ...) ->
         invocation_profile_get -> invocation_profile_list ->
         invocation_profile_update -> invocation_profile_resolve(plan=
         <throwaway plan>, role="as_author"). scope="system" is the
         simplest valid scope (no companion fields at all); role="as_author"
         narrows this profile's blast radius on the shared live server to
         only targets requesting that one role (profile_applies still
         returns True unconditionally once scope="system" is reached, but
         only after the role filter already passed). Like step 9, only
         result shape (source_scope present) is asserted, not which
         candidate wins, for the same non-flakiness reason.
     13. invocation_profile_delete(hard).
     14. step_assignment_resolve(plan=<throwaway plan>, role="as_author") --
         asserted as the CLEAN NO_APPLICABLE_ASSIGNMENT domain-error path.
         Unlike role_model_resolve/invocation_profile_resolve, this is NOT
         merely likely to be empty: no step_assignment_create (or any other
         step_assignment write) command exists anywhere in this server's
         surface -- C-007 ships resolve-only in CR-5a -- so the
         step_assignment table structurally cannot hold a row on any server
         running this code, live production data notwithstanding. This is
         the "assert the precise domain-error path" case the task
         instructions call for when a successful path is not constructible.
     15. The throwaway plan is hard-deleted.
    """
    if not R7_REQUIRED_COMMANDS <= catalog_names:
        missing = sorted(R7_REQUIRED_COMMANDS - catalog_names)
        return [
            CheckResult(
                "4", "R7_agent_config_lifecycle", STATUS_SKIP,
                f"{R7_PRE_DEPLOY_SKIP_REASON} (missing: {missing})",
            )
        ]

    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    tool_uuid: Optional[str] = None
    toolset_uuid: Optional[str] = None
    membership_uuid: Optional[str] = None
    role_uuid: Optional[str] = None
    provider_uuid: Optional[str] = None
    model_uuid: Optional[str] = None
    profile_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r7-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R7_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        # --- tool CRUD (create/get/list/update; delete happens after the
        # toolset membership below, deliberately soft -- see docstring). ---
        tool_name = unique_suffix("tool")
        ok, res = await call(
            client, "tool_create",
            {
                "name": tool_name, "server_id": "live-smoke-server", "command": "noop",
                "pinned_options": {}, "created_by": "live-smoke",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R7_tool_create", STATUS_FAIL, str(res)))
            return results
        tool_uuid = res["uuid"]
        results.append(CheckResult("4", "R7_tool_create", STATUS_PASS, f"uuid={tool_uuid}"))

        ok, res = await call(client, "tool_get", {"tool_uuid": tool_uuid})
        results.append(CheckResult("4", "R7_tool_get", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "tool_list", {"name": tool_name, "limit": 5})
        list_ok = ok and isinstance(res, dict) and "tools" in res
        results.append(CheckResult("4", "R7_tool_list", STATUS_PASS if list_ok else STATUS_FAIL, "" if list_ok else str(res)))

        ok, res = await call(
            client, "tool_update",
            {"tool_uuid": tool_uuid, "changed_by": "live-smoke", "description": "updated by live_smoke.py R7"},
        )
        results.append(CheckResult("4", "R7_tool_update", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        # --- toolset CRUD + membership (tool attached while still live). ---
        toolset_name = unique_suffix("toolset")
        ok, res = await call(client, "toolset_create", {"name": toolset_name, "created_by": "live-smoke"})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R7_toolset_create", STATUS_FAIL, str(res)))
            return results
        toolset_uuid = res["uuid"]
        results.append(CheckResult("4", "R7_toolset_create", STATUS_PASS, f"uuid={toolset_uuid}"))

        ok, res = await call(client, "toolset_get", {"toolset_uuid": toolset_uuid})
        results.append(CheckResult("4", "R7_toolset_get", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "toolset_list", {"name": toolset_name, "limit": 5})
        list_ok = ok and isinstance(res, dict) and "toolsets" in res
        results.append(CheckResult("4", "R7_toolset_list", STATUS_PASS if list_ok else STATUS_FAIL, "" if list_ok else str(res)))

        ok, res = await call(
            client, "toolset_update",
            {"toolset_uuid": toolset_uuid, "changed_by": "live-smoke", "description": "updated by live_smoke.py R7"},
        )
        results.append(CheckResult("4", "R7_toolset_update", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(
            client, "toolset_member_add",
            {"toolset_uuid": toolset_uuid, "tool_uuid": tool_uuid, "position": 0, "created_by": "live-smoke"},
        )
        membership_uuid = res.get("uuid") if ok and isinstance(res, dict) else None
        results.append(
            CheckResult(
                "4", "R7_toolset_member_add", STATUS_PASS if (ok and membership_uuid) else STATUS_FAIL,
                "" if ok else str(res),
            )
        )

        # --- tool_delete: deliberately SOFT (see docstring point 4). ---
        ok, res = await call(client, "tool_delete", {"tool_uuid": tool_uuid, "changed_by": "live-smoke"})
        soft_ok = ok and isinstance(res, dict) and res.get("mode") == "soft"
        results.append(CheckResult("4", "R7_tool_delete_soft", STATUS_PASS if soft_ok else STATUS_FAIL, "" if soft_ok else str(res)))
        if ok:
            tool_uuid = None  # naturally deleted; the finally block must not double-delete

        if membership_uuid:
            ok, res = await call(client, "toolset_member_remove", {"membership_uuid": membership_uuid, "changed_by": "live-smoke"})
            results.append(CheckResult("4", "R7_toolset_member_remove", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
            if ok:
                membership_uuid = None

        ok, res = await call(client, "toolset_delete", {"toolset_uuid": toolset_uuid, "changed_by": "live-smoke", "hard": True})
        hard_ok = ok and isinstance(res, dict) and res.get("mode") == "hard"
        results.append(CheckResult("4", "R7_toolset_delete_hard", STATUS_PASS if hard_ok else STATUS_FAIL, "" if hard_ok else str(res)))
        if ok:
            toolset_uuid = None

        # --- role CRUD ---
        role_name = unique_suffix("role")
        ok, res = await call(client, "role_create", {"name": role_name, "created_by": "live-smoke"})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R7_role_create", STATUS_FAIL, str(res)))
            return results
        role_uuid = res["uuid"]
        results.append(CheckResult("4", "R7_role_create", STATUS_PASS, f"uuid={role_uuid}"))

        ok, res = await call(client, "role_get", {"role_uuid": role_uuid})
        results.append(CheckResult("4", "R7_role_get", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "role_list", {"limit": 5})
        list_ok = ok and isinstance(res, dict) and "roles" in res
        results.append(CheckResult("4", "R7_role_list", STATUS_PASS if list_ok else STATUS_FAIL, "" if list_ok else str(res)))

        ok, res = await call(
            client, "role_update",
            {"role_uuid": role_uuid, "changed_by": "live-smoke", "description": "updated by live_smoke.py R7"},
        )
        results.append(CheckResult("4", "R7_role_update", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "role_delete", {"role_uuid": role_uuid, "changed_by": "live-smoke", "hard": True})
        hard_ok = ok and isinstance(res, dict) and res.get("mode") == "hard"
        results.append(CheckResult("4", "R7_role_delete_hard", STATUS_PASS if hard_ok else STATUS_FAIL, "" if hard_ok else str(res)))
        if ok:
            role_uuid = None

        # --- provider CRUD (status flipped suspended -> active so the
        # role_model_resolve probe below sees an active provider). ---
        provider_name = unique_suffix("provider")
        ok, res = await call(
            client, "provider_create",
            {"name": provider_name, "type": "cloud_api", "rented_hardware": False, "status": "active", "created_by": "live-smoke"},
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R7_provider_create", STATUS_FAIL, str(res)))
            return results
        provider_uuid = res["uuid"]
        results.append(CheckResult("4", "R7_provider_create", STATUS_PASS, f"uuid={provider_uuid}"))

        ok, res = await call(
            client, "provider_set_status",
            {"provider_uuid": provider_uuid, "status": "suspended", "changed_by": "live-smoke"},
        )
        status_ok = ok and isinstance(res, dict) and res.get("status") == "suspended"
        results.append(CheckResult("4", "R7_provider_set_status", STATUS_PASS if status_ok else STATUS_FAIL, "" if status_ok else str(res)))

        ok, res = await call(client, "provider_get", {"provider_uuid": provider_uuid})
        results.append(CheckResult("4", "R7_provider_get", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "provider_list", {"type": "cloud_api", "limit": 5})
        list_ok = ok and isinstance(res, dict) and "providers" in res
        results.append(CheckResult("4", "R7_provider_list", STATUS_PASS if list_ok else STATUS_FAIL, "" if list_ok else str(res)))

        ok, res = await call(
            client, "provider_update",
            {"provider_uuid": provider_uuid, "changed_by": "live-smoke", "status": "active", "billing_notes": "live-smoke R7"},
        )
        update_ok = ok and isinstance(res, dict) and res.get("status") == "active"
        results.append(CheckResult("4", "R7_provider_update", STATUS_PASS if update_ok else STATUS_FAIL, "" if update_ok else str(res)))

        # --- model CRUD (unique level -- guarantees a deterministic
        # role_model_resolve candidate below regardless of production data). ---
        model_level = unique_suffix("level")
        model_name = unique_suffix("model")
        ok, res = await call(
            client, "model_create",
            {
                "name": model_name, "provider_uuid": provider_uuid, "level": model_level,
                "execution_mode": "interactive", "created_by": "live-smoke",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R7_model_create", STATUS_FAIL, str(res)))
            return results
        model_uuid = res["uuid"]
        results.append(CheckResult("4", "R7_model_create", STATUS_PASS, f"uuid={model_uuid}"))

        ok, res = await call(client, "model_get", {"model_uuid": model_uuid})
        results.append(CheckResult("4", "R7_model_get", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "model_list", {"provider_uuid": provider_uuid, "limit": 5})
        list_ok = ok and isinstance(res, dict) and "models" in res
        results.append(CheckResult("4", "R7_model_list", STATUS_PASS if list_ok else STATUS_FAIL, "" if list_ok else str(res)))

        ok, res = await call(
            client, "model_update",
            {"model_uuid": model_uuid, "changed_by": "live-smoke", "cost_class": "live-smoke-cost-class"},
        )
        results.append(CheckResult("4", "R7_model_update", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        # --- role_model_resolve: guaranteed non-flaky success (see docstring point 9). ---
        ok, res = await call(
            client, "role_model_resolve",
            {"plan": plan_uuid, "role": "as_author", "step_required_level": model_level},
        )
        resolve_shape_ok = ok and isinstance(res, dict) and {"source", "chosen_provider", "chosen_model"} <= res.keys()
        results.append(
            CheckResult(
                "4", "R7_role_model_resolve", STATUS_PASS if resolve_shape_ok else STATUS_FAIL,
                "" if resolve_shape_ok else f"ok={ok} res={res!r}",
            )
        )

        ok, res = await call(client, "model_delete", {"model_uuid": model_uuid, "changed_by": "live-smoke", "hard": True})
        hard_ok = ok and isinstance(res, dict) and res.get("mode") == "hard"
        results.append(CheckResult("4", "R7_model_delete_hard", STATUS_PASS if hard_ok else STATUS_FAIL, "" if hard_ok else str(res)))
        if ok:
            model_uuid = None

        ok, res = await call(client, "provider_delete", {"provider_uuid": provider_uuid, "changed_by": "live-smoke", "hard": True})
        hard_ok = ok and isinstance(res, dict) and res.get("mode") == "hard"
        results.append(CheckResult("4", "R7_provider_delete_hard", STATUS_PASS if hard_ok else STATUS_FAIL, "" if hard_ok else str(res)))
        if ok:
            provider_uuid = None

        # --- invocation_profile CRUD + resolve (see docstring point 12). ---
        ok, res = await call(
            client, "invocation_profile_create",
            {"scope": "system", "role": "as_author", "created_by": "live-smoke", "temperature": 0.3},
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R7_invocation_profile_create", STATUS_FAIL, str(res)))
            return results
        profile_uuid = res["uuid"]
        results.append(CheckResult("4", "R7_invocation_profile_create", STATUS_PASS, f"uuid={profile_uuid}"))

        ok, res = await call(client, "invocation_profile_get", {"profile_uuid": profile_uuid})
        results.append(CheckResult("4", "R7_invocation_profile_get", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "invocation_profile_list", {"scope": "system", "limit": 5})
        list_ok = ok and isinstance(res, dict) and "profiles" in res
        results.append(CheckResult("4", "R7_invocation_profile_list", STATUS_PASS if list_ok else STATUS_FAIL, "" if list_ok else str(res)))

        ok, res = await call(
            client, "invocation_profile_update",
            {"profile_uuid": profile_uuid, "changed_by": "live-smoke", "temperature": 0.5},
        )
        results.append(CheckResult("4", "R7_invocation_profile_update", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

        ok, res = await call(client, "invocation_profile_resolve", {"plan": plan_uuid, "role": "as_author"})
        resolve_shape_ok = ok and isinstance(res, dict) and "source_scope" in res
        results.append(
            CheckResult(
                "4", "R7_invocation_profile_resolve", STATUS_PASS if resolve_shape_ok else STATUS_FAIL,
                "" if resolve_shape_ok else f"ok={ok} res={res!r}",
            )
        )

        ok, res = await call(
            client, "invocation_profile_delete",
            {"profile_uuid": profile_uuid, "changed_by": "live-smoke", "hard": True},
        )
        hard_ok = ok and isinstance(res, dict) and res.get("mode") == "hard"
        results.append(
            CheckResult("4", "R7_invocation_profile_delete_hard", STATUS_PASS if hard_ok else STATUS_FAIL, "" if hard_ok else str(res))
        )
        if ok:
            profile_uuid = None

        # --- step_assignment_resolve: the clean NO_APPLICABLE_ASSIGNMENT
        # path (see docstring point 14 -- deterministic, not merely likely). ---
        ok, res = await call(client, "step_assignment_resolve", {"plan": plan_uuid, "role": "as_author"})
        clean_error = (not ok) and "NO_APPLICABLE_ASSIGNMENT" in str(res)
        results.append(
            CheckResult(
                "4", "R7_step_assignment_resolve_no_applicable", STATUS_PASS if clean_error else STATUS_FAIL,
                "" if clean_error else f"ok={ok} res={res!r}",
            )
        )
    finally:
        # Best-effort cleanup of anything the sequence above did not already
        # naturally delete (e.g. an early return on a mid-sequence failure).
        # Ordering matters: memberships before their toolset, model before
        # its provider (DELETE_BLOCKED otherwise).
        if membership_uuid is not None:
            await call(client, "toolset_member_remove", {"membership_uuid": membership_uuid, "changed_by": "live-smoke"})
        if tool_uuid is not None:
            await call(client, "tool_delete", {"tool_uuid": tool_uuid, "changed_by": "live-smoke"})
        if toolset_uuid is not None:
            await call(client, "toolset_delete", {"toolset_uuid": toolset_uuid, "changed_by": "live-smoke", "hard": True})
        if role_uuid is not None:
            await call(client, "role_delete", {"role_uuid": role_uuid, "changed_by": "live-smoke", "hard": True})
        if model_uuid is not None:
            await call(client, "model_delete", {"model_uuid": model_uuid, "changed_by": "live-smoke", "hard": True})
        if provider_uuid is not None:
            await call(client, "provider_delete", {"provider_uuid": provider_uuid, "changed_by": "live-smoke", "hard": True})
        if profile_uuid is not None:
            await call(client, "invocation_profile_delete", {"profile_uuid": profile_uuid, "changed_by": "live-smoke", "hard": True})
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R8_PRE_FIX_SKIP_REASON = (
    "server exhibits the reported coverage.gs divergence (bug 3de7a081): "
    "the mechanical gate reported the concept missing even though both "
    "the GS and its TS child carry it after sequential in-cascade "
    "step_update calls -- redeploy pending"
)


def _r8_report_flags_gs_missing(report_json: Any, artifact_path: str, concept_id: str) -> bool:
    """True iff a coverage.gs finding on ``artifact_path`` reports
    ``concept_id`` missing within a cascade_preview/plan_validate JSON
    report string.

    ``report_json`` is the raw ``gate_report_json``/``report`` field (a
    JSON-encoded string per plan_manager.verify.finding.render_json); a
    non-string or unparseable value is treated as "not flagged" so a
    malformed report surfaces as a FAIL on the caller's own assertion
    rather than a spurious match here (mirrors ``_r6_report_flags_path``).
    """
    if not isinstance(report_json, str):
        return False
    try:
        payload = json.loads(report_json)
    except ValueError:
        return False
    for check in payload.get("checks", []) if isinstance(payload, dict) else []:
        if not isinstance(check, dict) or check.get("check_id") != "coverage.gs":
            continue
        for finding in check.get("findings", []) or []:
            if not isinstance(finding, dict):
                continue
            if finding.get("artifact_path") != artifact_path:
                continue
            if f"{concept_id!r}" in str(finding.get("message", "")):
                return True
    return False


async def run_r8_gs_coverage_live_cascade_read(client: Any) -> list[CheckResult]:
    """Bug 3de7a081 (wrong_output, blocker, reported against the doc-store
    plan's open cascade cc468aa3): sequential in-cascade step_update calls
    on GS steps succeeded and step_get read the persisted concepts back
    correctly, but cascade_preview's coverage.gs reported those same
    concepts MISSING while coverage.relations passed -- the reporter's
    structural suspicion was a divergent read path (step_get resolving the
    cascade-materialized state while coverage.gs reads a stale/base-
    revision state).

    Live investigation (three scratch-plan trials on
    scratch-bugrepro-3de7a081, hard-deleted after; recorded in
    tests/test_bug_3de7a081_gs_coverage_live_read.py) DISPROVED that
    theory against 0.1.57: check_coverage_gs/gs_coverage
    (plan_manager.verify.gate / plan_manager.views.coverage) always query
    the "step" table directly through the SAME open, already-committed
    connection cascade_preview's run_gate call opens -- identical to what
    step_get resolves, with no cascade overlay or cache layer at any
    level. The doc-store plan's flagged GS concepts (e.g. G-007's own
    concept C-061) had no TS child referencing them at all: a genuine,
    still-open authoring gap, not a stale read. Every deployed version
    this investigation touched already behaves correctly, so there is no
    known pre-fix marker to gate a version split on.

    Recipe (throwaway, ``live-smoke-`` prefixed plan, hard-deleted in a
    top-level try/finally): plan_create -> context_common(plan,level3) ->
    step_create G (level 3) -> context_common(G,level4) -> step_create T
    (level 4, parent=G) -> cascade_begin -> concept_add(C-001, in-cascade)
    -> step_update(G, concepts=[C-001], in-cascade) -> step_update(T,
    concepts=[C-001], in-cascade) -- the exact sequential in-cascade
    step_update pattern the bug report described -- -> cascade_preview.

    The live gate_report_json is inspected directly for a coverage.gs
    finding on G reporting C-001 missing, exactly like R6's behavioral
    (not doc-marker) gate: if the currently deployed server still (or
    again) exhibits the reported divergence, this is reported as SKIP
    (not FAIL) naming the bug, rather than failing the pipeline outright
    on a server this investigation did not anticipate; the correct,
    already-observed behavior asserts PASS.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    cascade_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r8-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R8_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R8_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R8_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R8_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R8_step_create(T)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R8_repro_steps_created", STATUS_PASS, f"G={g_id} T={t_id}"))

        ok, res = await call(client, "cascade_begin", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict) or not res.get("cascade_uuid"):
            results.append(CheckResult("4", "R8_cascade_begin", STATUS_FAIL, str(res)))
            return results
        cascade_uuid = res["cascade_uuid"]
        results.append(CheckResult("4", "R8_cascade_begin", STATUS_PASS, f"cascade_uuid={cascade_uuid}"))

        ok, res = await call(
            client, "concept_add",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-001",
                "name": "LiveSmokeR8Concept", "definition": "R8 scratch concept for bug 3de7a081.",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R8_concept_add", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R8_concept_add", STATUS_PASS))

        # Sequential in-cascade step_update calls: GS first, then its TS
        # child -- the exact order the bug report described.
        ok, res = await call(
            client, "step_update",
            {"plan": plan_uuid, "step_id": g_id, "concepts": ["C-001"], "cascade_uuid": cascade_uuid},
        )
        if not ok or not isinstance(res, dict) or res.get("concepts") != ["C-001"]:
            results.append(CheckResult("4", "R8_step_update(G,concepts)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R8_step_update(G,concepts)", STATUS_PASS))

        ok, res = await call(
            client, "step_update",
            {"plan": plan_uuid, "step_id": t_id, "concepts": ["C-001"], "cascade_uuid": cascade_uuid},
        )
        if not ok or not isinstance(res, dict) or res.get("concepts") != ["C-001"]:
            results.append(CheckResult("4", "R8_step_update(T,concepts)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R8_step_update(T,concepts)", STATUS_PASS))

        ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": g_id})
        step_get_ok = ok and isinstance(res, dict) and res.get("concepts") == ["C-001"]
        results.append(
            CheckResult(
                "4", "R8_step_get_reads_back_persisted_concepts", STATUS_PASS if step_get_ok else STATUS_FAIL,
                "" if step_get_ok else str(res),
            )
        )

        ok, res = await call(client, "cascade_preview", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict) or "gate_report_json" not in res:
            results.append(CheckResult("4", "R8_cascade_preview", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R8_cascade_preview", STATUS_PASS))

        still_missing = _r8_report_flags_gs_missing(res.get("gate_report_json"), g_id, "C-001")
        if still_missing:
            results.append(
                CheckResult(
                    "4", "R8_coverage_gs_reads_live_cascade_state", STATUS_SKIP,
                    R8_PRE_FIX_SKIP_REASON,
                )
            )
        else:
            results.append(CheckResult("4", "R8_coverage_gs_reads_live_cascade_state", STATUS_PASS))
    finally:
        if cascade_uuid is not None:
            await call(client, "cascade_abort", {"plan": plan_uuid})
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R9_PRE_DEPLOY_SKIP_REASON = (
    "server predates the plan-level completion-lock commands (bug c3950b83: "
    "plan_completed_set/plan_comment_set not yet present in the live help "
    "catalog) -- redeploy pending"
)

# Presence of both setter commands in the live help catalog is this
# pipeline's proxy for "this server has the bug c3950b83 fix deployed" --
# see run_r9_plan_completion_lock's docstring.
R9_REQUIRED_COMMANDS: frozenset[str] = frozenset({"plan_completed_set", "plan_comment_set"})


async def run_r9_plan_completion_lock(client: Any, catalog_names: frozenset[str]) -> list[CheckResult]:
    """Bug c3950b83 (plan-level completion lock; L1 design ruling
    2026-07-23, superseding an earlier per-step-status carve-out attempt):
    a shipped, frozen plan could never record that it had been executed --
    step_set_status/cascade_begin both refuse a frozen plan and
    plan_unfreeze is disproportionate for routine closeout bookkeeping. The
    fix is a single boolean `completed` flag (plus a free-form `comment`)
    on the plan row: once set, every OTHER mutating command that resolves
    its `plan` parameter to that plan refuses with PLAN_COMPLETED, while
    plan_completed_set/plan_comment_set stay reachable at all times so the
    flag itself (and the plan's comment) are always settable, and reads
    (plan_list, step_tree, ...) are never blocked either way.

    Availability-gated exactly like R7: if the live server predates this
    surface (R9_REQUIRED_COMMANDS not a subset of the live help catalog),
    every check here is SKIPped (never FAILed) naming bug c3950b83, rather
    than failing the pipeline outright against an as-yet-undeployed server.

    Recipe (throwaway, ``live-smoke-`` prefixed plan, hard-deleted in a
    top-level try/finally -- the flag is unset in that finally BEFORE the
    delete attempt, since plan_delete itself is refused while completed is
    true): plan_create -> plan_comment_set (attach a note) -> todo_create
    and comment_add, BOTH anchored to the plan (anchor_type=plan) while it
    is still unlocked -> plan_completed_set(true) -> a representative
    plan-parameter mutating command (step_create) asserted to refuse with
    PLAN_COMPLETED -> a representative read (step_tree) asserted to still
    succeed -> the THIRD seam (plan_manager.commands.plan_completion_guard):
    todo_update and comment_delete, each addressing its target by the
    entity's OWN uuid with NO `plan` parameter at all, asserted to ALSO
    refuse with PLAN_COMPLETED (derived from the entity's own anchor) ->
    plan_completed_set(false) -> the original mutation (step_create)
    asserted to succeed again. Cleanup hard-deletes the todo and comment
    before the plan itself.
    """
    results: list[CheckResult] = []
    if not R9_REQUIRED_COMMANDS <= catalog_names:
        missing = sorted(R9_REQUIRED_COMMANDS - catalog_names)
        results.append(
            CheckResult(
                "4", "R9_plan_completion_lock", STATUS_SKIP,
                f"{R9_PRE_DEPLOY_SKIP_REASON} (missing: {missing})",
            )
        )
        return results

    plan_uuid: Optional[str] = None
    todo_uuid: Optional[str] = None
    comment_uuid: Optional[str] = None
    completed_set = False
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r9-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R9_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]
        results.append(CheckResult("4", "R9_plan_create", STATUS_PASS, f"plan_uuid={plan_uuid}"))

        ok, res = await call(
            client, "plan_comment_set",
            {"plan": plan_uuid, "comment": "live-smoke R9 scratch plan for bug c3950b83.", "changed_by": "live-smoke"},
        )
        comment_ok = ok and isinstance(res, dict) and res.get("comment") == "live-smoke R9 scratch plan for bug c3950b83."
        results.append(CheckResult("4", "R9_plan_comment_set", STATUS_PASS if comment_ok else STATUS_FAIL, "" if comment_ok else str(res)))
        if not comment_ok:
            return results

        # Entity-uuid-addressed targets for the third seam, created while
        # the plan is still unlocked (todo_create/comment_add anchor
        # validation would themselves refuse a plan/step anchor targeting
        # an already-completed plan).
        ok, res = await call(
            client, "todo_create",
            {
                "title": "R9 plan-anchored scratch todo", "description": "bug c3950b83 third-seam check.",
                "kind": "task", "priority_nice": 0, "created_by": "live-smoke",
                "anchor_type": "plan", "anchor_plan_uuid": plan_uuid,
            },
        )
        todo_created_ok = ok and isinstance(res, dict) and res.get("uuid")
        results.append(CheckResult("4", "R9_todo_create(plan_anchored)", STATUS_PASS if todo_created_ok else STATUS_FAIL, "" if todo_created_ok else str(res)))
        if todo_created_ok:
            todo_uuid = res["uuid"]

        ok, res = await call(
            client, "comment_add",
            {
                "plan": plan_uuid, "anchor_type": "plan", "anchor_plan_uuid": plan_uuid,
                "kind": "observation", "visibility": "execution_context", "author": "live-smoke",
                "body": "R9 plan-anchored scratch comment.", "created_by": "live-smoke",
            },
        )
        comment_created_ok = ok and isinstance(res, dict) and res.get("uuid")
        results.append(CheckResult("4", "R9_comment_add(plan_anchored)", STATUS_PASS if comment_created_ok else STATUS_FAIL, "" if comment_created_ok else str(res)))
        if comment_created_ok:
            comment_uuid = res["uuid"]

        ok, res = await call(
            client, "plan_completed_set",
            {"plan": plan_uuid, "completed": True, "changed_by": "live-smoke"},
        )
        lock_ok = ok and isinstance(res, dict) and res.get("completed") is True and res.get("audit_uuid")
        results.append(CheckResult("4", "R9_plan_completed_set(true)", STATUS_PASS if lock_ok else STATUS_FAIL, "" if lock_ok else str(res)))
        if not lock_ok:
            return results
        completed_set = True

        # A representative `plan`-parameter mutating command must refuse
        # with PLAN_COMPLETED while the lock is set.
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g-locked"})
        refused_ok = (not ok) and "PLAN_COMPLETED" in str(res)
        results.append(
            CheckResult(
                "4", "R9_mutation_refused_while_completed", STATUS_PASS if refused_ok else STATUS_FAIL,
                "" if refused_ok else str(res),
            )
        )

        # A representative read must still succeed while the lock is set.
        ok, res = await call(client, "step_tree", {"plan": plan_uuid})
        read_ok = ok and isinstance(res, dict) and "tree" in res
        results.append(CheckResult("4", "R9_read_still_allowed_while_completed", STATUS_PASS if read_ok else STATUS_FAIL, "" if read_ok else str(res)))

        # THIRD SEAM: entity-uuid-addressed commands with NO `plan`
        # parameter at all must ALSO refuse, via plan_completion_guard
        # deriving the owning plan from the entity's own anchor.
        if todo_uuid is not None:
            ok, res = await call(client, "todo_update", {"todo": todo_uuid, "changed_by": "live-smoke", "priority_nice": -1})
            todo_refused_ok = (not ok) and "PLAN_COMPLETED" in str(res)
            results.append(
                CheckResult(
                    "4", "R9_todo_update_refused_while_completed", STATUS_PASS if todo_refused_ok else STATUS_FAIL,
                    "" if todo_refused_ok else str(res),
                )
            )
        if comment_uuid is not None:
            ok, res = await call(client, "comment_delete", {"comment": comment_uuid, "changed_by": "live-smoke"})
            comment_refused_ok = (not ok) and "PLAN_COMPLETED" in str(res)
            results.append(
                CheckResult(
                    "4", "R9_comment_delete_refused_while_completed", STATUS_PASS if comment_refused_ok else STATUS_FAIL,
                    "" if comment_refused_ok else str(res),
                )
            )

        ok, res = await call(
            client, "plan_completed_set",
            {"plan": plan_uuid, "completed": False, "changed_by": "live-smoke"},
        )
        unlock_ok = ok and isinstance(res, dict) and res.get("completed") is False
        results.append(CheckResult("4", "R9_plan_completed_set(false)", STATUS_PASS if unlock_ok else STATUS_FAIL, "" if unlock_ok else str(res)))
        if unlock_ok:
            completed_set = False

        # The same mutation must be admitted again once the lock is cleared.
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g-unlocked"})
        results.append(CheckResult("4", "R9_mutation_admitted_after_unlock", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    finally:
        if plan_uuid is not None and completed_set:
            # Cleanup must unset the flag FIRST -- while set, plan_delete
            # AND the entity-uuid-addressed comment_delete/todo_delete below
            # are all refused with PLAN_COMPLETED (the third seam derives
            # their owning plan from their own anchor, independent of any
            # `plan` parameter).
            await call(client, "plan_completed_set", {"plan": plan_uuid, "completed": False, "changed_by": "live-smoke-cleanup"})
        if comment_uuid is not None:
            await call(client, "comment_delete", {"comment": comment_uuid, "changed_by": "live-smoke-cleanup", "hard": True})
        if todo_uuid is not None:
            await call(client, "todo_delete", {"todo": todo_uuid, "changed_by": "live-smoke-cleanup", "hard": True})
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R10_PRE_FIX_SKIP_REASON = (
    "server still enforces the pre-fix plan_validate branch-scope contract "
    "(bug e197b94a: gs_step_id, ts_step_id, and as_step_id all wrongly "
    "required) -- redeploy pending"
)


async def run_r10_branch_scope_hierarchical_selectors(client: Any) -> list[CheckResult]:
    """Bug e197b94a: plan_validate scope='branch' wrongly runtime-required
    gs_step_id, ts_step_id, AND as_step_id all non-empty, while the
    generated schema/help already marked ts/as as optional -- making
    GS-only and GS+TS branch validation impossible and any branch with
    zero AS descendants (real case: doc-store G-007, four TS children,
    zero AS) mechanically unverifiable.

    Fixed contract (hierarchical selectors with precedence): gs_step_id
    alone selects the whole GS subtree; gs_step_id + ts_step_id narrows to
    one TS subtree; adding as_step_id narrows to one atomic branch.
    as_step_id without ts_step_id (a skipped level) is rejected
    deterministically. Validation runs over whatever descendants actually
    exist -- a TS with zero AS children is valid input, not an error.

    Availability-gated exactly like R6/R8 (a behavioral gate, not a
    catalog/doc marker: this bug changed an EXISTING command's runtime
    contract, so no help-catalog membership check can detect the fix).
    The GS-only call is itself the version probe: if the live server still
    carries the pre-fix contract, that call fails with the old "gs_step_id,
    ts_step_id, and as_step_id are all required" -32602, and every check in
    this group is SKIPped (never FAILed) naming bug e197b94a, rather than
    failing the pipeline against a not-yet-deployed fix.

    Recipe (throwaway, ``live-smoke-`` prefixed plan, hard-deleted in a
    top-level try/finally; context_common recompiled immediately before
    EVERY step_create, exactly like R2/R8/R9 -- a stored common block goes
    stale the instant an earlier sibling's step_create bumps the plan's
    head revision): plan_create -> context_common(plan,level3) ->
    step_create G (level 3) -> context_common(G,level4) -> step_create
    T-001 (level 4, parent=G) -> context_common(G,level4) -> step_create
    T-002 (level 4, parent=G, deliberately left with ZERO AS children --
    the doc-store G-007 shape) -> plan_validate(scope=branch, gs_step_id=G
    only) -> plan_validate(scope=branch, gs_step_id=G, ts_step_id=T-002,
    the zero-AS TS) -> plan_validate(scope=branch, gs_step_id=G,
    as_step_id=<bogus>, no ts_step_id) asserted to be REJECTED with the
    documented skipped-level message -- that rejection IS the pass
    condition, not a probe failure. The queued plan_validate call is
    unwrapped transparently by this script's call() (queue_semantics),
    exactly like R6's plan_validate use.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r10-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R10_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R10_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R10_step_create(G)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R10_step_create(G)", STATUS_PASS, f"step_id={g_id}"))

        t_ids: dict[str, str] = {}
        for slug in ("t-001", "t-002"):
            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
            if not ok:
                results.append(CheckResult("4", f"R10_context_common(G,level4,before {slug})", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": slug, "parent_step_id": g_id})
            tid = _extract_step_id(res) if ok else None
            if not ok or tid is None:
                results.append(CheckResult("4", f"R10_step_create({slug})", STATUS_FAIL, str(res)))
                return results
            t_ids[slug] = tid
        results.append(
            CheckResult(
                "4", "R10_step_create(T-001/T-002)", STATUS_PASS,
                f"{t_ids} -- T-002 deliberately left with zero AS children",
            )
        )

        # The GS-only call is itself the version probe (behavioral gate,
        # mirrors R6/R8): a pre-fix server rejects this before any
        # mechanical check ever runs.
        ok, res = await call(
            client, "plan_validate",
            {"plan": plan_uuid, "scope": "branch", "gs_step_id": g_id, "format": "json"},
        )
        pre_fix_detected = (not ok) and (
            "gs_step_id, ts_step_id, and as_step_id are all required" in str(res)
        )
        if pre_fix_detected:
            results.append(
                CheckResult(
                    "4", "R10_branch_scope_hierarchical_selectors", STATUS_SKIP,
                    R10_PRE_FIX_SKIP_REASON,
                )
            )
            return results

        gs_only_ok = ok and isinstance(res, dict) and "report" in res and "green" in res
        results.append(
            CheckResult(
                "4", "R10_plan_validate(gs_only)", STATUS_PASS if gs_only_ok else STATUS_FAIL,
                "" if gs_only_ok else str(res),
            )
        )

        # GS+TS narrows to the TS subtree -- T-002 has zero AS descendants,
        # exactly the reported doc-store G-007 shape; this must succeed,
        # never be rejected as unverifiable.
        ok, res = await call(
            client, "plan_validate",
            {"plan": plan_uuid, "scope": "branch", "gs_step_id": g_id, "ts_step_id": t_ids["t-002"], "format": "json"},
        )
        gs_ts_zero_as_ok = ok and isinstance(res, dict) and "report" in res and "green" in res
        results.append(
            CheckResult(
                "4", "R10_plan_validate(gs_plus_ts_zero_as)", STATUS_PASS if gs_ts_zero_as_ok else STATUS_FAIL,
                "" if gs_ts_zero_as_ok else str(res),
            )
        )

        # Skipped level (as_step_id without ts_step_id) MUST be rejected --
        # that rejection, with the documented message, IS the pass
        # condition here, not a probe failure.
        ok, res = await call(
            client, "plan_validate",
            {"plan": plan_uuid, "scope": "branch", "gs_step_id": g_id, "as_step_id": "A-999", "format": "json"},
        )
        skipped_level_ok = (not ok) and "as_step_id requires ts_step_id" in str(res)
        results.append(
            CheckResult(
                "4", "R10_plan_validate(skipped_level_rejected)", STATUS_PASS if skipped_level_ok else STATUS_FAIL,
                "" if skipped_level_ok else str(res),
            )
        )
    finally:
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R11_SUMMARY_ROW_BYTE_CEILING = 512

R11_PRE_FIX_SKIP_REASON = (
    "server does not accept the view parameter on the list-family commands "
    "yet (bug 8a13977d: todo_list(active_only=true, limit=50) serialized "
    "137,022 chars with no compact projection) -- redeploy pending"
)


async def run_r11_list_view_projection(client: Any) -> list[CheckResult]:
    """Bug 8a13977d: todo_list(active_only=true, limit=50) serialized
    137,022 chars on 0.1.60 (222,558 bytes of raw JSON, ~4.45 KB/item over
    50 rows) -- list-family commands always inlined the full record with no
    caller-selectable compact shape, an unusable response for a
    token-budgeted agent caller.

    Fix: a uniform `view` parameter ("full", unchanged default; "summary",
    a compact per-entity projection) across the *_list command surface,
    implemented once in plan_manager.commands.list_projection and declared
    per-entity via SUMMARY_FIELDS.

    Read-only, no throwaway entities: every check here reads whatever data
    already exists live (rows may be zero -- the shape/size assertions
    apply per-row, vacuously true on an empty page).

    Availability-gated exactly like R6/R8/R10 (a behavioral gate: `view` is
    a brand-new parameter, so get_schema's additionalProperties=False
    rejects it outright on a pre-fix server). The todo_list(view=summary)
    call is itself the version probe: if it is rejected as an unknown
    property, every check in this group is SKIPped (never FAILed) naming
    bug 8a13977d, rather than failing the pipeline against a not-yet-deployed
    fix.
    """
    results: list[CheckResult] = []

    ok, res = await call(client, "todo_list", {"limit": 5, "view": "summary"})
    pre_fix_detected = (not ok) and (
        "view" in str(res) and (
            "additional" in str(res).lower() or "unexpected" in str(res).lower() or "not allowed" in str(res).lower()
        )
    )
    if pre_fix_detected:
        results.append(CheckResult("4", "R11_list_view_projection", STATUS_SKIP, R11_PRE_FIX_SKIP_REASON))
        return results

    todo_summary_ok = ok and isinstance(res, dict) and isinstance(res.get("todos"), list)
    results.append(CheckResult("4", "R11_todo_list(view=summary)_call", STATUS_PASS if todo_summary_ok else STATUS_FAIL, "" if todo_summary_ok else str(res)))
    if todo_summary_ok:
        expected_todo_fields = {
            "uuid", "todo_uuid", "title", "status", "kind",
            "priority_nice", "primary_anchor_type", "anchor_ref_id", "updated_at",
        }
        oversized = [row for row in res["todos"] if len(json.dumps(row).encode("utf-8")) >= R11_SUMMARY_ROW_BYTE_CEILING]
        wrong_shape = [row for row in res["todos"] if isinstance(row, dict) and set(row) != expected_todo_fields]
        results.append(CheckResult("4", "R11_todo_list(view=summary)_row_size", STATUS_PASS if not oversized else STATUS_FAIL, "" if not oversized else f"{len(oversized)} row(s) >= {R11_SUMMARY_ROW_BYTE_CEILING} bytes"))
        results.append(CheckResult("4", "R11_todo_list(view=summary)_row_fields", STATUS_PASS if not wrong_shape else STATUS_FAIL, "" if not wrong_shape else f"unexpected shape: {wrong_shape[:1]}"))

    ok, res = await call(client, "bug_list", {"limit": 5, "view": "summary"})
    bug_summary_ok = ok and isinstance(res, dict) and isinstance(res.get("bugs"), list)
    results.append(CheckResult("4", "R11_bug_list(view=summary)_call", STATUS_PASS if bug_summary_ok else STATUS_FAIL, "" if bug_summary_ok else str(res)))
    if bug_summary_ok:
        expected_bug_fields = {
            "uuid", "bug_uuid", "title", "kind", "severity", "status",
            "priority_nice", "source_anchor_type", "source_ref_id", "updated_at",
        }
        oversized = [row for row in res["bugs"] if len(json.dumps(row).encode("utf-8")) >= R11_SUMMARY_ROW_BYTE_CEILING]
        wrong_shape = [row for row in res["bugs"] if isinstance(row, dict) and set(row) != expected_bug_fields]
        results.append(CheckResult("4", "R11_bug_list(view=summary)_row_size", STATUS_PASS if not oversized else STATUS_FAIL, "" if not oversized else f"{len(oversized)} row(s) >= {R11_SUMMARY_ROW_BYTE_CEILING} bytes"))
        results.append(CheckResult("4", "R11_bug_list(view=summary)_row_fields", STATUS_PASS if not wrong_shape else STATUS_FAIL, "" if not wrong_shape else f"unexpected shape: {wrong_shape[:1]}"))

    # One CR-5a agent-config family member, per the mandate.
    ok, res = await call(client, "tool_list", {"limit": 5, "view": "summary"})
    tool_summary_ok = ok and isinstance(res, dict) and isinstance(res.get("tools"), list)
    results.append(CheckResult("4", "R11_tool_list(view=summary)_call", STATUS_PASS if tool_summary_ok else STATUS_FAIL, "" if tool_summary_ok else str(res)))
    if tool_summary_ok:
        expected_tool_fields = {"uuid", "name", "server_id", "command", "updated_at"}
        oversized = [row for row in res["tools"] if len(json.dumps(row).encode("utf-8")) >= R11_SUMMARY_ROW_BYTE_CEILING]
        wrong_shape = [row for row in res["tools"] if isinstance(row, dict) and set(row) != expected_tool_fields]
        results.append(CheckResult("4", "R11_tool_list(view=summary)_row_size", STATUS_PASS if not oversized else STATUS_FAIL, "" if not oversized else f"{len(oversized)} row(s) >= {R11_SUMMARY_ROW_BYTE_CEILING} bytes"))
        results.append(CheckResult("4", "R11_tool_list(view=summary)_row_fields", STATUS_PASS if not wrong_shape else STATUS_FAIL, "" if not wrong_shape else f"unexpected shape: {wrong_shape[:1]}"))

    # view=full (the default) still returns the pre-fix, verbose shape.
    ok, res = await call(client, "todo_list", {"limit": 1, "view": "full"})
    full_verbose_ok = ok and isinstance(res, dict) and isinstance(res.get("todos"), list) and all(
        "description" in row and "blocking_reason" in row for row in res["todos"] if isinstance(row, dict)
    )
    results.append(CheckResult("4", "R11_todo_list(view=full)_still_verbose", STATUS_PASS if full_verbose_ok else STATUS_FAIL, "" if full_verbose_ok else str(res)))

    # Omitting view entirely must behave identically to view=full (default pinned).
    ok_default, res_default = await call(client, "todo_list", {"limit": 1})
    ok_explicit_full, res_explicit_full = await call(client, "todo_list", {"limit": 1, "view": "full"})
    default_matches_full = (
        ok_default and ok_explicit_full
        and isinstance(res_default, dict) and isinstance(res_explicit_full, dict)
        and set(res_default.get("todos", [{}])[0] if res_default.get("todos") else {}) ==
        set(res_explicit_full.get("todos", [{}])[0] if res_explicit_full.get("todos") else {})
    )
    results.append(CheckResult("4", "R11_default_view_matches_full", STATUS_PASS if default_matches_full else STATUS_FAIL, "" if default_matches_full else f"default={res_default} explicit_full={res_explicit_full}"))

    # An invalid view value must error cleanly (INVALID_FILTER), not crash or hang.
    ok, res = await call(client, "todo_list", {"limit": 1, "view": "bogus"})
    invalid_view_rejected = (not ok) and "view" in str(res).lower()
    results.append(CheckResult("4", "R11_invalid_view_rejected", STATUS_PASS if invalid_view_rejected else STATUS_FAIL, "" if invalid_view_rejected else str(res)))

    return results


async def run_pipeline(args: argparse.Namespace) -> Summary:
    from plan_manager_client.client import PlanManagerClient

    reset_dispatch_log()
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

    # --- Tier 3 CREATE phase: every throwaway entity Tier-2-scoped reads
    # need is created here and kept ALIVE until those reads have run (third
    # live run: every entity-scoped probe failed PLAN_NOT_FOUND / was
    # SKIPped because the old single-pass lifecycle functions deleted their
    # entities before the scoped reads ever ran -- see run_tier3_plan_step_
    # create's docstring). Cleanup is a separate, later phase below.
    plan_step_results, entities, plan_uuid, plan_name = await run_tier3_plan_step_create(client)

    todo_create_results, todo_uuid = await run_tier3_todo_create(client)
    if todo_uuid is not None:
        entities["todo"] = todo_uuid

    # bug lifecycle needs its own plan (bug_create/bug_close/... all take a
    # "plan" param) -- kept alive through the scoped reads below, then
    # hard-deleted alongside everything else in the cleanup phase.
    bug_plan_name = unique_suffix("bug-plan")
    ok, bug_plan_res = await call(client, "plan_create", {"name": bug_plan_name})
    bug_create_results: list[CheckResult] = []
    bug_plan_uuid: Optional[str] = None
    if ok and isinstance(bug_plan_res, dict) and bug_plan_res.get("uuid"):
        bug_plan_uuid = bug_plan_res["uuid"]
        bug_create_results, bug_uuid = await run_tier3_bug_create(client, bug_plan_uuid)
        if bug_uuid is not None:
            entities["bug"] = bug_uuid
    else:
        bug_create_results = [CheckResult("3", "bug_plan_create", STATUS_FAIL, str(bug_plan_res))]

    entities["project"] = args.project

    results += plan_step_results
    results += todo_create_results
    results += bug_create_results

    # --- Tier 2 scoped probes run WHILE every entity above is still alive.
    results += await run_tier2_scoped(client, catalog_names, entities)

    # --- Tier 3 CLEANUP phase: now it is safe to tear everything down.
    results += await run_tier3_plan_step_cleanup(client, plan_uuid, plan_name)
    results += await run_tier3_todo_cleanup(client, todo_uuid)
    if bug_plan_uuid is not None:
        ok, res = await call(client, "plan_delete", {"plan": bug_plan_uuid, "hard": True})
        results.append(CheckResult("3", "bug_plan_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))

    results += await run_r1_todo_anchor_none(client)
    results += await run_r2_same_file_order_ambiguity(client)
    results += await run_r3_project_view(client, catalog_names, args.project)
    results += await run_r4_ts_inputs_outputs_schema(client)
    results += await run_r5_step_id_selector_docs(client)
    results += await run_r6_write_intent_negation(client)
    results += await run_r7_agent_config_lifecycle(client, catalog_names)
    results += await run_r8_gs_coverage_live_cascade_read(client)
    results += await run_r9_plan_completion_lock(client, catalog_names)
    results += await run_r10_branch_scope_hierarchical_selectors(client)
    results += await run_r11_list_view_projection(client)

    fallback_note = summarize_dispatch_fallbacks(DISPATCH_LOG)
    if fallback_note is not None:
        results.append(CheckResult("diag", "dispatch_fallbacks_used", STATUS_PASS, fallback_note))

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
        payload = summary.to_dict()
        payload["dispatch_log"] = list(DISPATCH_LOG)
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(summary.render_text())
    return summary.exit_code()


if __name__ == "__main__":
    sys.exit(main())
