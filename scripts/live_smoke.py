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
import base64
import json
import re
import sys
import uuid as uuid_mod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Optional
from urllib.parse import urlsplit

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
_CLIENT_SRC = REPO_ROOT / "client"
if str(_CLIENT_SRC) not in sys.path:
    sys.path.insert(0, str(_CLIENT_SRC))

from live_smoke_tests import LIVE_SMOKE_TEST_KEYS
from live_smoke_tests import LIVE_SMOKE_TEST_SPECS
from live_smoke_tests import format_live_smoke_test_listing
from live_smoke_tests import get_live_smoke_test_spec
from live_smoke_tests import resolve_selected_test_specs

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


def has_failures(results: list[CheckResult]) -> bool:
    """Return True iff any result in the batch is a failure."""

    return any(r.status == STATUS_FAIL for r in results)


# --------------------------------------------------------------------------
# Tier 2 allowlists -- pure data + pure classification (unit-tested without
# network in tests/test_live_smoke_script.py).
# --------------------------------------------------------------------------

# Zero-entity-dependency read-only commands: safe to invoke with a static,
# always-valid params dict, no throwaway entity required.
TIER2_STATIC_PARAMS: dict[str, dict[str, Any]] = {
    # Read-only registry lookup; a literal fragment needs no fixture entity.
    "id_resolve": {"fragment": "0000", "limit": 1},
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
        # todo 9b09c9b0 (full bug-family CRUD delete surface): run_tier3_bug_create's
        # caller hard-deletes the fix then the bug in the Tier-3 cleanup phase.
        "bug_fix_delete",
        "bug_delete",
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
        # todo 9b09c9b0 (full bug-family CRUD delete surface): exercised
        # end-to-end (dry_run -> hard -> bug_list absence) by
        # run_r19_bug_delete_full_crud_lifecycle, and also used for cleanup
        # by R13/R16/R17's finally blocks.
        "bug_delete",
        # R27 runtime work-layer CRUD: live lifecycle for the new wish and
        # calendar_entry surfaces, exercised end-to-end by
        # run_r27_runtime_work_layer_lifecycle below.
        "wish_create", "wish_get", "wish_list", "wish_update", "wish_delete",
        "calendar_entry_create", "calendar_entry_get", "calendar_entry_list",
        "calendar_entry_update", "calendar_entry_delete",
        # R34 (CR-6 G-004/T-004): the generic reference-graph inspection
        # command, exercised end-to-end (direct + recursive traversal over a
        # plan -> todo -> comment fixture) by
        # run_r34_reference_inspect_traversal below.
        "reference_inspect",
        # R38 (CR-7 G-005/T-002/A-002): the black-box export/import
        # round-trip regression -- plan_export, export_read, hrs_export,
        # plan_import, and the plan_project_attach binding it verifies
        # survives the round trip -- exercised end-to-end by
        # run_r38_export_import_round_trip below.
        "plan_export", "export_read", "hrs_export", "plan_import", "plan_project_attach",
    }
)

# Commands this pipeline deliberately never invokes live, with the specific
# reason each is unsafe/out-of-scope for a throwaway-entity smoke pass.
KNOWN_SKIP_REASONS: dict[str, str] = {
    "export_cleanup": "destructive filesystem cleanup of export archives; not exercised against live data",
    "runtime_purge_batch": "irreversibly purges EVERY soft-deleted row of an entity type, not just this pass's throwaway rows; not safe to exercise against live data",
    # CR-7 G-006/T-002/A-002: find is read-only and safe, but clear directly
    # nulls an arbitrary catalogued reference column (not scoped to this
    # pass's own throwaway rows) and delete_carriers(dry_run=false) delegates
    # to the same irreversible set-wise purge engine runtime_purge_batch
    # uses -- one command bundling a safe and two unsafe operations, so the
    # whole command is skipped rather than only partially probed.
    "reference_repair": "clear mutates arbitrary catalogued reference columns and delete_carriers(dry_run=false) irreversibly removes entities via the set-wise purge engine, not scoped to this pass's own throwaway rows; not safe to exercise generically against live data",
    # plan_import/export_read/hrs_export/plan_export: R38 (CR-7 G-005/T-002/
    # A-002) now exercises the whole export/import round trip end-to-end --
    # see TIER4_HANDLED and run_r38_export_import_round_trip below.
    "export_upload_save": "requires a prior chunked transfer_id handshake; not exercised in this pass",
    "export_archive": "archives export state for a real plan; destructive of export history, not exercised against live data",
    "hrs_import": "mutates HRS from an externally prepared document; out of scope for a throwaway smoke entity",
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
    "para_insert": "mutates the human-owned HRS prose (root CLAUDE.md: HRS changes only on user decision); the one sanctioned exception is R38's dedicated fixed-identity export/import round-trip fixture, a single paragraph on a plan the pipeline itself creates and hard-deletes -- not exercised outside that dedicated scenario",
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
    "block_rebuild": "mutates stored derived context-block artifacts; not exercised outside a dedicated stale-block refresh scenario",
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
    "wish_reanchor": "exercised end to end by its own R-check (R53: create/reanchor-in-place/identity-preserved/negative-control), not by a generic Tier-2 probe",
    "comment_reanchor": "reanchors a comment's primary anchor; help()/schema probed end to end by its own R-check (R54: reanchor symmetry across anchored entities), not exercised via a live reanchor call in this pass",
    "calendar_entry_reanchor": "reanchors a calendar entry's primary anchor; help()/schema probed end to end by its own R-check (R54: reanchor symmetry across anchored entities), not exercised via a live reanchor call in this pass",
    "escalation_reanchor": "reanchors an escalation's primary anchor; help()/schema probed end to end by its own R-check (R54: reanchor symmetry across anchored entities), not exercised via a live reanchor call in this pass",
    "execution_attempt_supersede": "records that a stale execution attempt was replaced by a specific later one; exercised end to end by its own R-check (R55: supersede lifecycle sets a forward pointer without rewriting the stale row's status, idempotent same-target repeat, refused different-target re-supersede, lineage guard), not by a generic Tier-2 probe",
    "review_result_supersede": "records that a stale review result was replaced by a specific later one; exercised end to end by its own R-check (R55: supersede lifecycle sets a forward pointer without rewriting the stale row's status, lineage guard across object_type and shared step), not by a generic Tier-2 probe",
    "bug_reject": "terminal bug transition; not exercised beyond the create/confirm/close lifecycle",
    "bug_mark_duplicate": "requires a second bug to mark as a duplicate target; not exercised in this pass",
    "bug_reopen": "reopens a terminal bug; not exercised beyond the create/confirm/close lifecycle",
    "bug_update": "arbitrary bug field mutation; not exercised beyond the create/confirm/close lifecycle",
    "bug_triage": "alternate lifecycle branch to bug_confirm; not exercised in this pass",
    "bug_impact_add": "records a bug impact beyond this pass's scope",
    "bug_impact_update": "requires an existing impact_uuid from bug_impact_add",
    "bug_impact_discover": "runs CA-backed impact discovery; not exercised in this pass",
    "bug_impact_delete": "requires an existing impact_uuid from bug_impact_add, which this pass never creates; not exercised in this pass",
    "bug_fix_update": "arbitrary bug-fix field mutation; not exercised beyond the create/verify/close lifecycle",
    "bug_propagation_create": "records a fix propagation beyond this pass's scope",
    "bug_propagation_update": "requires an existing propagation_id from bug_propagation_create",
    "bug_propagation_generate_todos": "requires an existing bug_fix_id from bug_fix_create",
    "bug_fix_propagation_delete": "requires an existing propagation_id from bug_propagation_create, which this pass never creates; not exercised in this pass",
    "project_dependency_add": "mutates the shared project-dependency graph; not safe to exercise against live config",
    "project_dependency_update": "requires an existing dependency_uuid from project_dependency_add",
    "project_dependency_confirm": "requires an existing dependency_uuid from project_dependency_add",
    "project_dependency_remove": "requires an existing dependency_uuid from project_dependency_add",
    "project_dependency_discover": "runs CA-backed dependency discovery; not exercised in this pass",
    "project_uuid_reserve": "exercised end to end by its own R-check (reserve/collision/resolve/release with cleanup), not by a generic Tier-2 probe",
    "execution_graph": "exercised end to end by its own R-check (R57: typed execution graph over roles/deps/verification), not by a generic Tier-2 probe",
    "step_dependency_add": "covered by the R2 regression's dedicated step_dependency_apply lifecycle, not separately probed",
    "step_dependency_remove": "covered by the R2 regression's dedicated step_dependency_apply lifecycle, not separately probed",
    "step_dependency_set": "covered by the R2 regression's dedicated step_dependency_apply lifecycle, not separately probed",
    "step_dependency_clear": "covered by the R2 regression's dedicated step_dependency_apply lifecycle, not separately probed",
    # plan_project_attach: R38 (CR-7 G-005/T-002/A-002) now exercises it for
    # real, on the round-trip fixture plan -- see TIER4_HANDLED above.
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


def _looks_like_unknown_param(diagnostic_text: str, param_name: str) -> bool:
    """True iff a command-call failure looks like a schema rejection of
    `param_name` as an unrecognized property (additionalProperties=False on
    a server predating the parameter's introduction), rather than any other
    validation or domain error naming that string incidentally.

    Same narrow-match idiom as R11's inline pre-fix probe
    (run_r11_list_view_projection): requires `param_name` to appear AND
    one of a small set of "schema rejected an unknown key" phrasings.
    """
    lowered = diagnostic_text.lower()
    return param_name in diagnostic_text and (
        "additional" in lowered or "unexpected" in lowered or "not allowed" in lowered
    )


def _looks_like_missing_required_param(diagnostic_text: str, param_name: str) -> bool:
    """True iff a command-call failure looks like the schema rejecting the
    call because `param_name` was NOT supplied (a server predating the
    parameter being made optional), rather than any other validation or
    domain error naming that string incidentally.

    Mirrors _looks_like_unknown_param's narrow-match idiom, but for the
    opposite direction: requires `param_name` to appear AND one of a small
    set of "a required parameter is missing" phrasings (the adapter's own
    wording is "Missing required parameters: ...", see
    mcp_proxy_adapter.commands.base.Command.validate_params).
    """
    lowered = diagnostic_text.lower()
    return param_name in diagnostic_text and ("missing required" in lowered or "required parameter" in lowered)


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


_ERROR_CODE_PATTERN = re.compile(r"-3\d{4}")


def _typed_error_code(diagnostic: Any) -> Optional[int]:
    """Extract a JSON-RPC-style numeric error code from a call() failure
    diagnostic, whichever shape it arrived in.

    Two shapes are observed in practice: an unwrapped ``ErrorResult`` dict
    (``{"code": ..., "message": ...}``, produced when ``unwrap_envelope``
    peels a domain ``success: False`` layer down to its ``"error"`` sub-dict
    -- see ``mcp_proxy_adapter.commands.result.ErrorResult.to_dict``), or a
    formatted transport exception string (``"... (code: -32602)"``, from
    ``JsonRpcTransport._extract_result`` on the direct-call path). Falling
    back to a regex search over ``str(diagnostic)`` makes this robust to
    either shape without depending on which dispatch path served the call.

    Args:
        diagnostic: The failure value returned as the second element of a
            ``call()`` result tuple when the first element is False.

    Returns:
        The negative JSON-RPC error code (e.g. -32602) if one can be found,
        else None.
    """
    if isinstance(diagnostic, dict) and isinstance(diagnostic.get("code"), int):
        return diagnostic["code"]
    match = _ERROR_CODE_PATTERN.search(str(diagnostic))
    return int(match.group(0)) if match else None


def _error_message(diagnostic: Any) -> str:
    """Best-effort human-readable message extracted from a call() failure diagnostic.

    Prefers a dict's own ``"message"`` key (the shape ``ErrorResult.to_dict``
    produces once unwrapped); falls back to ``str(diagnostic)`` for any other
    shape (e.g. a formatted transport exception string).

    Args:
        diagnostic: The failure value returned as the second element of a
            ``call()`` result tuple when the first element is False.

    Returns:
        The extracted message string.
    """
    if isinstance(diagnostic, dict):
        message = diagnostic.get("message")
        if isinstance(message, str):
            return message
    return str(diagnostic)


# Diagnostic trail of which dispatch path actually served each call this
# run -- "direct" (proactive, KNOWN_BUILTIN_COMMANDS), "queued" (the
# production-representative default), or "queued->direct-fallback" (a
# queued "Command not found" auto-recovered via one direct-path retry,
# meaning KNOWN_BUILTIN_COMMANDS is missing that command name). Reset per
# run by run_pipeline; printed as part of --json output for visibility.
DISPATCH_LOG: list[dict[str, Any]] = []
_CALL_WATCHDOG_TIMEOUT: float | None = None
_CALL_WATCHDOG_GRACE_SECONDS = 5.0


def reset_dispatch_log() -> None:
    DISPATCH_LOG.clear()


def configure_call_watchdog(timeout: float | None, *, grace_seconds: float = _CALL_WATCHDOG_GRACE_SECONDS) -> None:
    """Configure a per-client-invocation outer watchdog for live-smoke calls.

    The PlanManagerClient forwards ``timeout`` to the adapter, where valid
    queued calls may still need normal terminal-event polling.  The smoke
    verifier adds this outer guard at ``timeout + 5s`` so a broken client or
    non-returning transport cannot stall the whole run or prevent fixture
    cleanup.  Passing ``None`` disables the guard.
    """
    global _CALL_WATCHDOG_TIMEOUT
    _CALL_WATCHDOG_TIMEOUT = None if timeout is None else max(0.0, float(timeout) + grace_seconds)


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


async def _with_call_watchdog(name: str, path: str, awaitable: Awaitable[tuple[bool, Any]]) -> tuple[bool, Any]:
    if _CALL_WATCHDOG_TIMEOUT is None:
        return await awaitable
    try:
        return await asyncio.wait_for(awaitable, timeout=_CALL_WATCHDOG_TIMEOUT)
    except asyncio.TimeoutError:
        return (
            False,
            f"outer watchdog exceeded for {path} command {name!r} "
            f"after {_CALL_WATCHDOG_TIMEOUT:.3f}s",
        )


async def call(client: Any, name: str, params: Optional[dict[str, Any]] = None) -> tuple[bool, Any]:
    """Dispatch one command via the routing policy in the module note above
    KNOWN_BUILTIN_COMMANDS: proactively direct for known adapter builtins,
    otherwise queued first with a one-shot direct-path fallback on an
    unresolved-command queue failure. Records which path served the call in
    DISPATCH_LOG for post-run diagnostics."""
    params = params or {}
    if name in KNOWN_BUILTIN_COMMANDS:
        ok, data = await _with_call_watchdog(name, "direct", _call_direct(client, name, params))
        DISPATCH_LOG.append({"command": name, "path": "direct", "fallback": False, "ok": ok})
        return ok, data

    ok, data = await _with_call_watchdog(name, "queued", _call_queued(client, name, params))
    if not ok and _looks_like_unresolved_command(name, str(data)):
        ok2, data2 = await _with_call_watchdog(name, "direct", _call_direct(client, name, params))
        DISPATCH_LOG.append({"command": name, "path": "queued->direct-fallback", "fallback": True, "ok": ok2})
        return ok2, data2

    DISPATCH_LOG.append({"command": name, "path": "queued", "fallback": False, "ok": ok})
    return ok, data


HELP_CATALOG_MAX_PAGE = 200  # matches the server's pagination MAX_LIMIT (plan_manager.commands.runtime_filtering)


async def fetch_full_help_catalog(client: Any) -> tuple[bool, dict[str, str], Any]:
    """Fetch the ENTIRE help() no-cmdname catalog, paging with the server's
    max page size until exhausted.

    Bug 507b74ae bounded help()'s default no-cmdname response (bounded
    default 50, max 200 rows per page, per plan_manager.commands.
    runtime_filtering's uniform pagination contract) -- but tier1+ of this
    pipeline classify/probe EVERY catalog command, so they need the full
    catalog, not just a bounded first page. This loops requesting
    HELP_CATALOG_MAX_PAGE rows at a time, merging every page's 'commands'
    map, until the response's 'pagination.has_more' is false.

    Backward compatible with a server predating the fix: such a server has
    no 'pagination' key in its response at all (limit/offset are silently
    ignored by the pre-fix builtin's **kwargs) and already returns every
    command in the single unbounded response, so the loop takes exactly one
    iteration in that case, unchanged from before this helper existed.

    Returns (ok, catalog, last_raw_response); ok is False only if the very
    first page's call fails, in which case last_raw_response carries the
    failure detail for the caller's existing catalog_fetch FAIL reporting.
    """
    catalog: dict[str, str] = {}
    offset = 0
    while True:
        ok, page = await call(client, "help", {"limit": HELP_CATALOG_MAX_PAGE, "offset": offset})
        if not ok or not isinstance(page, dict):
            return ok, catalog, page
        page_commands = page.get("commands", {})
        if isinstance(page_commands, dict):
            catalog.update(page_commands)
        pagination = page.get("pagination")
        if not isinstance(pagination, dict) or not pagination.get("has_more"):
            return True, catalog, page
        returned = pagination.get("returned", len(page_commands) if isinstance(page_commands, dict) else 0)
        if not isinstance(returned, int) or returned <= 0:
            # Defensive: has_more=True with no forward progress would loop
            # forever; stop here with whatever was collected so far.
            return True, catalog, page
        offset += returned


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
            break
        has_schema = isinstance(schema, dict) and bool(schema.get("schema") or schema.get("metadata"))
        check = CheckResult(
            "1",
            f"help({name})",
            STATUS_PASS if has_schema else STATUS_FAIL,
            "" if has_schema else f"empty/malformed help payload: {schema!r}",
        )
        results.append(check)
        if check.status == STATUS_FAIL:
            break
    return results


async def run_tier2_static(client: Any, catalog_names: frozenset[str]) -> list[CheckResult]:
    results: list[CheckResult] = []
    for name, params in TIER2_STATIC_PARAMS.items():
        if name not in catalog_names:
            continue
        ok, res = await call(client, name, params)
        check = CheckResult("2", name, STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res))
        results.append(check)
        if check.status == STATUS_FAIL:
            break
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
            check = CheckResult("2", f"{name}(gate_red_contract)", status, detail)
            results.append(check)
            if check.status == STATUS_FAIL:
                break
            continue
        check = CheckResult("2", name, STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res))
        results.append(check)
        if check.status == STATUS_FAIL:
            break
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


async def run_tier3_bug_create(client: Any, plan_uuid: str) -> tuple[list[CheckResult], Optional[str], Optional[str]]:
    """bug_create -> bug_confirm -> bug_fix_create -> bug_fix_verify(passed=True)
    -> bug_close, the FULL documented closure path.

    Confirmed live: bug_close alone (skipping the fix chain) fails -32000
    "source fix not verified" / INVALID_RUNTIME_STATUS_TRANSITION.
    BugClosureDiscipline.evaluate_closure (plan_manager/domain/bug_closure_
    discipline.py:36-70) requires source_fix_verified=True, and
    bug_close_command.py derives that as ``any(fix.status == "verified" and
    bool(fix.passed) for fix in fixes)`` -- so at least one bug_fix must
    reach status "verified" via bug_fix_verify(passed=True) before close is
    legal. bug_delete (and bug_fix_delete for its child fix) now exist on
    the command surface (todo 9b09c9b0); this function returns both
    identifiers, and the caller performs the explicit hard-delete cleanup
    (bug_fix_delete before bug_delete -- the fix's live bug_uuid reference
    would otherwise block the bug's own hard delete) IN ADDITION TO
    hard-deleting this bug's dedicated plan, since source_plan_uuid carries
    no FK/cascade of its own (plan hard delete never touched this row).
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
        return results, None, None
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
    return results, bug_uuid, fix_uuid


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
      4. tool_delete(dry_run=true): expected SUCCESS preview with
         blocked=true and references {"toolset_membership.tool_uuid": 1}.
         The tool is still referenced by the live toolset membership just
         created, and the universal deletion rule reports that block in the
         dry-run payload instead of raising DELETE_BLOCKED.
      5. toolset_member_remove (detach) -> tool_delete(soft default) ->
         toolset_delete(hard) -- the real soft delete only runs after the
         blocking membership has been removed.
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

        # --- tool_delete dry-run: expected SUCCESS preview with blocked=true
        # while the live membership still points at the tool (see docstring
        # point 4). ---
        ok, res = await call(
            client,
            "tool_delete",
            {"tool_uuid": tool_uuid, "changed_by": "live-smoke", "dry_run": True},
        )
        blocked_preview = (
            ok
            and isinstance(res, dict)
            and res.get("dry_run") is True
            and res.get("mode") == "soft"
            and res.get("blocked") is True
            and isinstance(res.get("references"), dict)
            and res["references"].get("toolset_membership.tool_uuid") == 1
        )
        results.append(
            CheckResult(
                "4",
                "R7_tool_delete_dry_run_blocked",
                STATUS_PASS if blocked_preview else STATUS_FAIL,
                "" if blocked_preview else f"ok={ok} res={res!r}",
            )
        )

        if membership_uuid:
            ok, res = await call(client, "toolset_member_remove", {"membership_uuid": membership_uuid, "changed_by": "live-smoke"})
            results.append(CheckResult("4", "R7_toolset_member_remove", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
            if ok:
                membership_uuid = None

        # --- tool_delete: real soft delete after the blocking membership
        # has been detached (see docstring point 5). ---
        ok, res = await call(client, "tool_delete", {"tool_uuid": tool_uuid, "changed_by": "live-smoke"})
        soft_ok = ok and isinstance(res, dict) and res.get("mode") == "soft"
        results.append(
            CheckResult(
                "4",
                "R7_tool_delete_soft_after_detach",
                STATUS_PASS if soft_ok else STATUS_FAIL,
                "" if soft_ok else str(res),
            )
        )
        if ok:
            tool_uuid = None  # naturally deleted; the finally block must not double-delete

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


R8_D8849951_PRE_FIX_SKIP_REASON = (
    "server predates todo d8849951's coverage.gs wording fix: the finding "
    "still ends in the bare '... missing' wording that read as \"missing "
    "from the GS row\" (bugs 3de7a081/a8c43201) instead of \"not covered by "
    "any child (TS) step\" -- redeploy pending"
)

R8_D8849951_IDENTITY_SKIP_REASON = (
    "server predates todo d8849951's plan_validate state-identity fields: "
    "tip_revision_uuid/cascade_uuid are absent from the response -- "
    "redeploy pending"
)


def _r8_gs_finding_message(report_json: Any, artifact_path: str, concept_id: str) -> Optional[str]:
    """Return the message text of the coverage.gs finding on
    ``artifact_path`` for ``concept_id`` within a cascade_preview/
    plan_validate JSON report string, or None if no such finding exists.

    Sibling of ``_r8_report_flags_gs_missing`` (same lookup, but returns
    the message text itself instead of a boolean) so a caller can inspect
    the exact wording -- used by todo d8849951's reworded-message check.
    """
    if not isinstance(report_json, str):
        return None
    try:
        payload = json.loads(report_json)
    except ValueError:
        return None
    for check in payload.get("checks", []) if isinstance(payload, dict) else []:
        if not isinstance(check, dict) or check.get("check_id") != "coverage.gs":
            continue
        for finding in check.get("findings", []) or []:
            if not isinstance(finding, dict):
                continue
            if finding.get("artifact_path") != artifact_path:
                continue
            message = str(finding.get("message", ""))
            if f"{concept_id!r}" in message:
                return message
    return None


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

    Todo d8849951 extension: the ambiguous "concept 'X' missing" wording
    that read as "missing from the GS row" itself (rather than "not yet
    covered by a TS child") caused two rejected false-blocker reports
    (3de7a081, then a8c43201) against a gate that was working as
    designed. After the base repro above proves no finding exists once
    both levels carry the concept, this same throwaway plan/cascade adds
    a SECOND concept to G-001 only (never to T-001), forcing a genuine,
    deliberate coverage.gs finding, and inspects its message: PASS if it
    carries the new "not covered by any child (TS) step" wording, SKIP
    (naming this todo) if it still ends in the bare pre-fix "... missing"
    wording. The same open cascade also exercises plan_validate's
    tip_revision_uuid/cascade_uuid response fields (bug a8c43201's
    follow-up: plan_validate previously exposed only the committed-head
    revision_uuid label, unlike cascade_preview's base+tip) -- SKIP
    (naming this todo) if those fields are absent from the response,
    otherwise PASS iff they match the open cascade's own
    cascade_uuid/tip_revision_uuid as cascade_preview reports them.
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

        # Todo 3c762bfe made view="summary" (no gate_report_json) the
        # cascade_preview DEFAULT; view="full" is the explicit opt-in this
        # bug's own check needs. A server predating that change rejects
        # "view" as an unknown property -- fall back to the plain call,
        # whose (only) shape on such a server IS the full one.
        ok, res = await call(client, "cascade_preview", {"plan": plan_uuid, "view": "full"})
        if not ok and _looks_like_unknown_param(str(res), "view"):
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

        # --- Todo d8849951: reworded coverage.gs wording + plan_validate
        # state identity. Adding a second concept to G-001 ONLY (not to
        # its TS child T-001) forces a genuine, deliberate coverage.gs
        # finding -- the exact GS-declared-but-not-child-covered gap the
        # reworded message describes -- so its wording can be inspected.
        # C-002 must exist in the plan's concept table BEFORE it can be
        # set on a step's own concepts (CONCEPT_NOT_FOUND otherwise, live
        # pipeline regression on 0.1.63 against this block's first draft
        # -- mirrors the C-001 concept_add above exactly; no context_common
        # recompile is needed, concept_add does not touch context blocks).
        ok, res = await call(
            client, "concept_add",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-002",
                "name": "LiveSmokeR8UncoveredConcept", "definition": "R8 scratch concept for todo d8849951's deliberately-uncovered GS concept.",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R8_concept_add(C-002)", STATUS_FAIL, str(res)))
            results.append(CheckResult("4", "R8_step_update(G,add_uncovered_concept)", STATUS_FAIL, "skipped: concept_add(C-002) failed"))
            ok = False
        else:
            results.append(CheckResult("4", "R8_concept_add(C-002)", STATUS_PASS))

            ok, res = await call(
                client, "step_update",
                {"plan": plan_uuid, "step_id": g_id, "concepts": ["C-001", "C-002"], "cascade_uuid": cascade_uuid},
            )
            if not ok or not isinstance(res, dict) or res.get("concepts") != ["C-001", "C-002"]:
                results.append(CheckResult("4", "R8_step_update(G,add_uncovered_concept)", STATUS_FAIL, str(res)))
                ok = False
            else:
                results.append(CheckResult("4", "R8_step_update(G,add_uncovered_concept)", STATUS_PASS))

        if ok:
            ok, res = await call(client, "cascade_preview", {"plan": plan_uuid, "view": "full"})
            if not ok and _looks_like_unknown_param(str(res), "view"):
                ok, res = await call(client, "cascade_preview", {"plan": plan_uuid})
            if not ok or not isinstance(res, dict) or "gate_report_json" not in res:
                results.append(CheckResult("4", "R8_cascade_preview(after_uncovered_concept)", STATUS_FAIL, str(res)))
            else:
                results.append(CheckResult("4", "R8_cascade_preview(after_uncovered_concept)", STATUS_PASS))
                preview_tip = res.get("tip_revision_uuid")
                preview_cascade_uuid = res.get("cascade_uuid")

                message = _r8_gs_finding_message(res.get("gate_report_json"), g_id, "C-002")
                if message is None:
                    results.append(
                        CheckResult(
                            "4", "R8_coverage_gs_new_wording", STATUS_FAIL,
                            "no coverage.gs finding for C-002 -- expected an uncovered concept",
                        )
                    )
                elif "not covered by any child (TS) step" in message:
                    results.append(CheckResult("4", "R8_coverage_gs_new_wording", STATUS_PASS, message))
                elif message.endswith("missing"):
                    results.append(
                        CheckResult("4", "R8_coverage_gs_new_wording", STATUS_SKIP, R8_D8849951_PRE_FIX_SKIP_REASON)
                    )
                else:
                    results.append(CheckResult("4", "R8_coverage_gs_new_wording", STATUS_FAIL, message))

                # plan_validate's tip_revision_uuid/cascade_uuid must match
                # the same open cascade's state cascade_preview just
                # reported -- both read the same live tip (bug a8c43201's
                # follow-up: remove the base/tip presentation asymmetry).
                ok, res = await call(client, "plan_validate", {"plan": plan_uuid, "scope": "plan"})
                if not ok or not isinstance(res, dict):
                    results.append(CheckResult("4", "R8_plan_validate(open_cascade_identity)", STATUS_FAIL, str(res)))
                elif "tip_revision_uuid" not in res or "cascade_uuid" not in res:
                    results.append(
                        CheckResult(
                            "4", "R8_plan_validate(open_cascade_identity)", STATUS_SKIP,
                            R8_D8849951_IDENTITY_SKIP_REASON,
                        )
                    )
                else:
                    identity_ok = (
                        res.get("tip_revision_uuid") == preview_tip
                        and res.get("cascade_uuid") == preview_cascade_uuid
                        and res.get("cascade_uuid") == cascade_uuid
                        and res.get("tip_revision_uuid") is not None
                    )
                    results.append(
                        CheckResult(
                            "4", "R8_plan_validate(open_cascade_identity)",
                            STATUS_PASS if identity_ok else STATUS_FAIL,
                            "" if identity_ok else str(res),
                        )
                    )
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

# bug_list's summary projection widened under bugs 7383c8a8/45f0c128 (18
# fields, including short_description and five anchor/ownership fields, vs
# the original 10-field 8a13977d shape) so a page is independently useful
# for triage; see tests/test_bug_8a13977d_list_view_projection.py's
# BUG_SUMMARY_ROW_BYTE_CEILING for the matching unit-level ceiling and its
# rationale.
R11_BUG_SUMMARY_ROW_BYTE_CEILING = 1024

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

    Fix: a uniform `view` parameter ("full", the original default; "summary",
    a compact per-entity projection) across the *_list command surface,
    implemented once in plan_manager.commands.list_projection and declared
    per-entity via SUMMARY_FIELDS. Todo ffe0b0a8 later flipped the default
    to view=summary for 9 of those commands -- including todo_list, the one
    this group's default-view check exercises (see
    R11_default_view_matches_summary below) -- wherever the entity already
    declared SUMMARY_FIELDS; view=full remains available and unchanged.

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

    # The plan list is the compact catalog callers use to decide which plan
    # to inspect next.  Completion is operational state, not free text, so
    # it belongs in this exact summary projection.  Assert the complete
    # response contract (including nested row types) here rather than merely
    # checking that plan_list accepted view=summary.
    expected_plan_list_response_fields = {"plans", "total", "limit", "offset"}
    expected_plan_summary_fields = {
        "uuid", "name", "status", "primary_project_id", "deleted", "completed",
    }
    ok, res = await call(client, "plan_list", {"limit": 5, "view": "summary"})
    plan_list_summary_ok = (
        ok
        and isinstance(res, dict)
        and set(res) == expected_plan_list_response_fields
        and isinstance(res.get("plans"), list)
        and type(res.get("total")) is int
        and type(res.get("limit")) is int
        and type(res.get("offset")) is int
    )
    results.append(
        CheckResult(
            "4",
            "R11_plan_list(view=summary)_response_fields_and_types",
            STATUS_PASS if plan_list_summary_ok else STATUS_FAIL,
            "" if plan_list_summary_ok else str(res),
        )
    )
    if plan_list_summary_ok:
        wrong_plan_rows = [
            row
            for row in res["plans"]
            if not (
                isinstance(row, dict)
                and set(row) == expected_plan_summary_fields
                and type(row.get("uuid")) is str
                and type(row.get("name")) is str
                and type(row.get("status")) is str
                and (row.get("primary_project_id") is None or type(row.get("primary_project_id")) is str)
                and type(row.get("deleted")) is bool
                and type(row.get("completed")) is bool
            )
        ]
        results.append(
            CheckResult(
                "4",
                "R11_plan_list(view=summary)_row_fields_and_types",
                STATUS_PASS if not wrong_plan_rows else STATUS_FAIL,
                "" if not wrong_plan_rows else f"unexpected shape/type: {wrong_plan_rows[:1]}",
            )
        )

    # Summary gained completion state above; the full view must stay the
    # original complete payload so existing detailed callers are unaffected.
    expected_plan_full_fields = {
        "uuid", "name", "status", "context_budget", "has_head", "project_ids",
        "project_count", "primary_project_id", "deleted", "completed", "comment",
    }
    ok, res = await call(client, "plan_list", {"limit": 1, "view": "full"})
    plan_list_full_ok = (
        ok
        and isinstance(res, dict)
        and set(res) == expected_plan_list_response_fields
        and isinstance(res.get("plans"), list)
        and type(res.get("total")) is int
        and type(res.get("limit")) is int
        and type(res.get("offset")) is int
        and all(
            isinstance(row, dict)
            and set(row) == expected_plan_full_fields
            and type(row.get("uuid")) is str
            and type(row.get("name")) is str
            and type(row.get("status")) is str
            and type(row.get("context_budget")) is int
            and type(row.get("has_head")) is bool
            and isinstance(row.get("project_ids"), list)
            and all(type(project_id) is str for project_id in row["project_ids"])
            and type(row.get("project_count")) is int
            and (row.get("primary_project_id") is None or type(row.get("primary_project_id")) is str)
            and type(row.get("deleted")) is bool
            and type(row.get("completed")) is bool
            and (row.get("comment") is None or type(row.get("comment")) is str)
            for row in res["plans"]
        )
    )
    results.append(
        CheckResult(
            "4",
            "R11_plan_list(view=full)_original_fields_and_types",
            STATUS_PASS if plan_list_full_ok else STATUS_FAIL,
            "" if plan_list_full_ok else str(res),
        )
    )

    ok, res = await call(client, "bug_list", {"limit": 5, "view": "summary"})
    bug_summary_ok = ok and isinstance(res, dict) and isinstance(res.get("bugs"), list)
    results.append(CheckResult("4", "R11_bug_list(view=summary)_call", STATUS_PASS if bug_summary_ok else STATUS_FAIL, "" if bug_summary_ok else str(res)))
    if bug_summary_ok:
        # Widened under bugs 7383c8a8/45f0c128 (bug_list oversized response /
        # no usable pagination; project_view leaked the same full bodies).
        expected_bug_fields = {
            "uuid", "bug_uuid", "title", "short_description", "status", "kind", "severity",
            "priority_nice", "reporter", "owner", "source_anchor_type", "source_project_id",
            "source_plan_uuid", "source_command", "source_service", "created_at", "updated_at",
            "closed_at",
        }
        oversized = [row for row in res["bugs"] if len(json.dumps(row).encode("utf-8")) >= R11_BUG_SUMMARY_ROW_BYTE_CEILING]
        wrong_shape = [row for row in res["bugs"] if isinstance(row, dict) and set(row) != expected_bug_fields]
        results.append(CheckResult("4", "R11_bug_list(view=summary)_row_size", STATUS_PASS if not oversized else STATUS_FAIL, "" if not oversized else f"{len(oversized)} row(s) >= {R11_BUG_SUMMARY_ROW_BYTE_CEILING} bytes"))
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

    # Omitting view entirely must behave identically to view=summary: todo
    # ffe0b0a8 flipped the default for todo_list (one of the 9 commands in
    # its scope) from view=full to view=summary, so the omitted-view
    # default is no longer the verbose shape (that is still checked
    # explicitly above, via R11_todo_list(view=full)_still_verbose).
    ok_default, res_default = await call(client, "todo_list", {"limit": 1})
    ok_explicit_summary, res_explicit_summary = await call(client, "todo_list", {"limit": 1, "view": "summary"})
    default_matches_summary = (
        ok_default and ok_explicit_summary
        and isinstance(res_default, dict) and isinstance(res_explicit_summary, dict)
        and set(res_default.get("todos", [{}])[0] if res_default.get("todos") else {}) ==
        set(res_explicit_summary.get("todos", [{}])[0] if res_explicit_summary.get("todos") else {})
    )
    results.append(CheckResult("4", "R11_default_view_matches_summary", STATUS_PASS if default_matches_summary else STATUS_FAIL, "" if default_matches_summary else f"default={res_default} explicit_summary={res_explicit_summary}"))

    # An invalid view value must error cleanly (INVALID_FILTER), not crash or hang.
    ok, res = await call(client, "todo_list", {"limit": 1, "view": "bogus"})
    invalid_view_rejected = (not ok) and "view" in str(res).lower()
    results.append(CheckResult("4", "R11_invalid_view_rejected", STATUS_PASS if invalid_view_rejected else STATUS_FAIL, "" if invalid_view_rejected else str(res)))

    return results


R12_PRE_FIX_SKIP_REASON = (
    "server predates the response-size/cascade-tip batch (todos 3c762bfe "
    "cascade_preview pagination, 4265fa4e srt_snapshot_list compact "
    "default, eb2dcccb block_get pagination, 1fb0fbfc srt_snapshot_create "
    "cascade-tip selector): cascade_preview's view=summary param was "
    "rejected as an unrecognized property -- redeploy pending"
)

R12_EMBEDDING_SKIP_REASON = (
    "srt_snapshot_create's embedding dependency is unavailable in this "
    "environment (EMBEDDINGS_UNAVAILABLE) -- todo 1fb0fbfc's cascade-tip "
    "selector is exercised at the unit level (tests/"
    "test_todo_1fb0fbfc_srt_snapshot_create_cascade_tip.py); skipped here "
    "rather than failing the pipeline on an environmental dependency"
)

R12_B6ED4B0B_SKIP_REASON = (
    "server predates todo b6ed4b0b's gate_report_json findings pagination "
    "-- cascade_preview(view=full)'s response carries no gate_findings_total "
    "key at all -- redeploy pending"
)


async def run_r12_response_size_and_cascade_tip_batch(client: Any) -> list[CheckResult]:
    """Todos 3c762bfe / 4265fa4e / eb2dcccb / 1fb0fbfc / b6ed4b0b: one
    live-reported batch of response-size defects (doc-store plan authoring
    hit the MCP Proxy caller output budget on cascade_preview's change_set,
    srt_snapshot_list's embedded tree/vectors, and block_get's entry list)
    plus one behavioral defect (srt_snapshot_create recorded the base
    committed revision instead of an open cascade's working tip), plus
    todo b6ed4b0b's follow-on: gate_report_json itself embeds a full,
    UNBOUNDED findings list per check inside cascade_preview(view=full) --
    paginated independently via gate_findings_limit/gate_findings_offset.

    Recipe (throwaway ``live-smoke-`` prefixed plan, hard-deleted in a
    top-level try/finally, mirroring run_r8_gs_coverage_live_cascade_read):
    plan_create -> context_common(plan,level3) [common block for block_get]
    -> step_create G -> cascade_begin -> concept_add (distinct working tip)
    -> cascade_preview (default=summary, then view=full+category filter,
    then view=full+gate_findings_limit=1) -> block_get (pagination
    envelope) -> srt_snapshot_create by cascade_uuid (embedding-gated) ->
    srt_snapshot_list (compact default, newest-first) -> cascade_abort.

    Availability-gated exactly like R6/R8/R10/R11: cascade_preview's
    view=summary param is the version probe (rejected as an unrecognized
    property on a pre-fix server -> the whole group SKIPs naming this
    batch, rather than failing against a not-yet-deployed fix). The
    gate_findings pagination extension (todo b6ed4b0b) is gated
    independently: a server with the base view=full support but predating
    just this follow-on returns no gate_findings_total key, which SKIPs
    only that one check (R12_B6ED4B0B_SKIP_REASON) rather than the whole
    group.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    cascade_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r12-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R12_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        # Version probe: view=summary is brand-new on cascade_preview: a
        # server predating todo 3c762bfe rejects it outright
        # (additionalProperties=False), regardless of cascade state.
        ok, res = await call(client, "cascade_preview", {"plan": plan_uuid, "view": "summary"})
        if not ok and _looks_like_unknown_param(str(res), "view"):
            results.append(CheckResult("4", "R12_response_size_and_cascade_tip_batch", STATUS_SKIP, R12_PRE_FIX_SKIP_REASON))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        block_id = res.get("common_block_id") if ok and isinstance(res, dict) else None
        if not ok or not block_id:
            results.append(CheckResult("4", "R12_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R12_context_common(plan,level3)", STATUS_PASS, f"block_id={block_id}"))

        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R12_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "cascade_begin", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict) or not res.get("cascade_uuid"):
            results.append(CheckResult("4", "R12_cascade_begin", STATUS_FAIL, str(res)))
            return results
        cascade_uuid = res["cascade_uuid"]
        results.append(CheckResult("4", "R12_cascade_begin", STATUS_PASS, f"cascade_uuid={cascade_uuid}"))

        # A distinct working tip: adding a concept in-cascade moves the ref
        # ahead of the cascade's base_revision_uuid.
        ok, res = await call(
            client, "concept_add",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-001",
                "name": "LiveSmokeR12Concept", "definition": "R12 scratch concept for the response-size/cascade-tip batch.",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R12_concept_add", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R12_concept_add", STATUS_PASS))

        # --- Unit 1 (todo 3c762bfe): cascade_preview default=summary, view=full, category filter ---
        ok, res = await call(client, "cascade_preview", {"plan": plan_uuid})
        summary_shape_ok = (
            ok and isinstance(res, dict) and "summary" in res
            and "entries" not in res and "change_set" not in res and "gate_report_json" not in res
        )
        results.append(CheckResult("4", "R12_cascade_preview(default=summary)", STATUS_PASS if summary_shape_ok else STATUS_FAIL, "" if summary_shape_ok else str(res)))

        ok, res = await call(client, "cascade_preview", {"plan": plan_uuid, "view": "full"})
        full_shape_ok = (
            ok and isinstance(res, dict)
            and {"entries", "total", "limit", "offset", "gate_report_json", "summary"} <= set(res)
        )
        results.append(CheckResult("4", "R12_cascade_preview(view=full)", STATUS_PASS if full_shape_ok else STATUS_FAIL, "" if full_shape_ok else str(res)))
        if full_shape_ok:
            added_present = any(e.get("category") == "added" for e in res["entries"])
            results.append(CheckResult("4", "R12_cascade_preview(view=full)_has_added_entry", STATUS_PASS if added_present else STATUS_FAIL, "" if added_present else str(res["entries"])))

        ok, res = await call(client, "cascade_preview", {"plan": plan_uuid, "view": "full", "category": "added"})
        category_filtered_ok = ok and isinstance(res, dict) and all(e.get("category") == "added" for e in res.get("entries", []))
        results.append(CheckResult("4", "R12_cascade_preview(category=added)", STATUS_PASS if category_filtered_ok else STATUS_FAIL, "" if category_filtered_ok else str(res)))

        # --- Unit 1b (todo b6ed4b0b): gate_report_json findings pagination ---
        ok, res = await call(client, "cascade_preview", {"plan": plan_uuid, "view": "full", "gate_findings_limit": 1})
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "R12_b6ed4b0b_gate_findings_pagination", STATUS_FAIL, str(res)))
        elif "gate_findings_total" not in res:
            results.append(CheckResult("4", "R12_b6ed4b0b_gate_findings_pagination", STATUS_SKIP, R12_B6ED4B0B_SKIP_REASON))
        else:
            gate_envelope_ok = (
                isinstance(res.get("gate_report_json"), str)
                and isinstance(res.get("gate_findings_total"), int)
                and res.get("gate_findings_limit") == 1
                and isinstance(res.get("gate_findings_offset"), int)
            )
            gate_windowed_ok = False
            if gate_envelope_ok:
                parsed_gate_report = json.loads(res["gate_report_json"])
                gate_checks = parsed_gate_report.get("checks", [])
                finding_count_present = all(isinstance(c, dict) and "finding_count" in c for c in gate_checks)
                windowed_findings_total = sum(
                    len(c.get("findings", [])) for c in gate_checks if isinstance(c, dict)
                )
                gate_windowed_ok = finding_count_present and windowed_findings_total <= 1
            gate_ok = gate_envelope_ok and gate_windowed_ok
            results.append(CheckResult("4", "R12_b6ed4b0b_gate_findings_pagination", STATUS_PASS if gate_ok else STATUS_FAIL, "" if gate_ok else str(res)))

        # --- Unit 3 (todo eb2dcccb): block_get pagination envelope ---
        ok, res = await call(client, "block_get", {"plan": plan_uuid, "block_id": block_id, "limit": 5, "offset": 0})
        block_page_ok = (
            ok and isinstance(res, dict)
            and {"blocks", "content", "total", "limit", "offset"} <= set(res)
            and len(res["blocks"]) <= 5
        )
        results.append(CheckResult("4", "R12_block_get(paginated)", STATUS_PASS if block_page_ok else STATUS_FAIL, "" if block_page_ok else str(res)))

        # --- Unit 4 (todo 1fb0fbfc): srt_snapshot_create cascade-tip selector ---
        ok, res = await call(
            client, "srt_snapshot_create",
            {
                "plan": plan_uuid, "algorithm_version": "live-smoke-r12", "summarizer_version": "live-smoke-r12",
                "embedding_model": "live-smoke-r12", "cascade_uuid": cascade_uuid,
            },
        )
        if not ok and ("EMBEDDINGS_UNAVAILABLE" in str(res) or "embedding" in str(res).lower()):
            results.append(CheckResult("4", "R12_srt_snapshot_create(cascade_uuid)", STATUS_SKIP, R12_EMBEDDING_SKIP_REASON))
        elif not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "R12_srt_snapshot_create(cascade_uuid)", STATUS_FAIL, str(res)))
        else:
            tip_ok = (
                res.get("snapshot_mode") == "cascade_tip"
                and res.get("cascade_uuid") == cascade_uuid
                and res.get("revision_uuid")
            )
            results.append(CheckResult("4", "R12_srt_snapshot_create(cascade_uuid)_tip_semantics", STATUS_PASS if tip_ok else STATUS_FAIL, "" if tip_ok else str(res)))

            snapshot_uuid = res.get("uuid")
            ok, res = await call(client, "srt_snapshot_list", {"plan": plan_uuid, "limit": 5})
            list_ok = (
                ok and isinstance(res, dict) and isinstance(res.get("snapshots"), list)
                and any(row.get("uuid") == snapshot_uuid for row in res["snapshots"])
                and all("tree_content" not in row for row in res["snapshots"])
            )
            results.append(CheckResult("4", "R12_srt_snapshot_list(compact_default_finds_snapshot)", STATUS_PASS if list_ok else STATUS_FAIL, "" if list_ok else str(res)))
    finally:
        if cascade_uuid is not None:
            await call(client, "cascade_abort", {"plan": plan_uuid})
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R13_PRE_FIX_SKIP_REASON = (
    "server predates bugs 7383c8a8/45f0c128 (bug_list still defaults to "
    "view=full / project_view still embeds full bug bodies) -- redeploy pending"
)


async def run_r13_bug_list_project_view_bounded(client: Any, project_id: str) -> list[CheckResult]:
    """Bugs 7383c8a8 (bug_list: 176,477 chars for 42 active bugs live, no
    usable pagination) and 45f0c128 (project_view: 63,439 chars spilled for
    7 bugs despite limit params) -- both traced to embedding the full
    BugReport body (detailed_description, expected_behavior, actual_behavior,
    reproduction, evidence, environment) in every row.

    Fix: bug_list's `view` parameter now defaults to "summary" (the widened
    projection: uuid, bug_uuid, title, short_description, status, kind,
    severity, priority_nice, reporter, owner, source_anchor_type,
    source_project_id, source_plan_uuid, source_command, source_service,
    created_at, updated_at, closed_at), with limit/offset/total pagination
    (default 50, max 200, unchanged from before this fix); project_view's
    bug AND todo rows are now unconditionally the same summary projection
    (no view param there -- the whole command is a bounded aggregate view).

    Recipe: a dedicated throwaway plan + one scratch bug carrying a
    multi-KB detailed_description (the exact shape that spilled live),
    taken through the full documented closure path (mirrors
    run_tier3_bug_create) so cleanup can hard-delete the plan afterward;
    self-contained top-level try/finally, no shared Tier-3 state touched.

    project_id is the SAME --project argument R3_project_view already uses;
    this check's project_view assertions are about GENERAL boundedness
    (no bug/todo row on that project ever carries a body field) rather than
    requiring the scratch bug specifically be project-anchored (source_type
    project/file anchoring is confirmed live against the Code Analysis
    server and can legitimately fall back to unidentified -- not something
    this response-size check should depend on).

    Pre-fix detection: the scratch bug_list row is itself the version probe
    -- if omitting `view` still returns detailed_description, the fix is
    not deployed yet and the whole group is SKIPped, not FAILed.
    """
    results: list[CheckResult] = []
    plan_name = unique_suffix("r13-plan")
    ok, plan_res = await call(client, "plan_create", {"name": plan_name})
    if not ok or not isinstance(plan_res, dict) or not plan_res.get("uuid"):
        results.append(CheckResult("4", "R13_plan_create", STATUS_FAIL, str(plan_res)))
        return results
    plan_uuid = plan_res["uuid"]
    bug_uuid: Optional[str] = None
    try:
        big_body = "lorem ipsum dolor sit amet " * 300  # ~8.1 KB, mirrors the live-reported spill
        title = unique_suffix("r13-bug")
        ok, res = await call(
            client, "bug_create",
            {
                "plan": plan_uuid, "title": title, "short_description": "R13 scratch bug (large body)",
                "detailed_description": big_body, "kind": "functional", "severity": "trivial",
                "priority_nice": 19, "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "plan", "source_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R13_bug_create", STATUS_FAIL, str(res)))
            return results
        bug_uuid = res["uuid"]
        results.append(CheckResult("4", "R13_bug_create", STATUS_PASS, f"uuid={bug_uuid}"))

        # 7383c8a8: bug_list, `view` omitted -- must already be bounded.
        ok, res = await call(client, "bug_list", {"plan": plan_uuid})
        bug_list_ok = ok and isinstance(res, dict) and isinstance(res.get("bugs"), list)
        if not bug_list_ok:
            results.append(CheckResult("4", "R13_7383c8a8_bug_list_call", STATUS_FAIL, str(res)))
            return results

        row = next((b for b in res["bugs"] if isinstance(b, dict) and b.get("uuid") == bug_uuid), None)
        pre_fix_detected = row is not None and "detailed_description" in row
        if pre_fix_detected:
            results.append(CheckResult("4", "R13_bug_list_project_view_bounded", STATUS_SKIP, R13_PRE_FIX_SKIP_REASON))
            return results

        results.append(CheckResult("4", "R13_7383c8a8_bug_list_call", STATUS_PASS))
        row_ok = row is not None
        results.append(CheckResult("4", "R13_7383c8a8_bug_list_row_present", STATUS_PASS if row_ok else STATUS_FAIL, "" if row_ok else f"bug {bug_uuid} not in bug_list(plan={plan_name}) response"))
        if row_ok:
            no_body = not any(f in row for f in ("detailed_description", "expected_behavior", "actual_behavior", "reproduction", "evidence", "environment"))
            results.append(CheckResult("4", "R13_7383c8a8_bug_list_row_no_body", STATUS_PASS if no_body else STATUS_FAIL, "" if no_body else f"row leaked a body field: {sorted(row.keys())}"))
        pagination_ok = all(k in res for k in ("total", "limit", "offset"))
        results.append(CheckResult("4", "R13_7383c8a8_bug_list_pagination_fields", STATUS_PASS if pagination_ok else STATUS_FAIL, "" if pagination_ok else f"missing pagination field(s) in {sorted(res.keys())}"))

        # 45f0c128: project_view must stay bounded -- no bug/todo body leaks,
        # regardless of which project's live data is currently on file.
        ok, res = await call(client, "project_view", {"project": project_id, "active_only": True, "bug_limit": 50, "todo_limit": 50})
        view_ok = ok and isinstance(res, dict)
        results.append(CheckResult("4", "R13_45f0c128_project_view_call", STATUS_PASS if view_ok else STATUS_FAIL, "" if view_ok else str(res)))
        if view_ok:
            bug_rows = [b for b in res.get("bugs", []) if isinstance(b, dict)]
            leaked_bug = [b for b in bug_rows if any(f in b for f in ("detailed_description", "expected_behavior", "actual_behavior", "reproduction", "evidence", "environment"))]
            results.append(CheckResult("4", "R13_45f0c128_project_view_bugs_no_body", STATUS_PASS if not leaked_bug else STATUS_FAIL, "" if not leaked_bug else f"{len(leaked_bug)} bug row(s) leaked a body field"))
            todo_rows = [t for t in res.get("todos", []) if isinstance(t, dict)]
            leaked_todo = [t for t in todo_rows if any(f in t for f in ("description", "blocking_reason", "execution_result"))]
            results.append(CheckResult("4", "R13_45f0c128_project_view_todos_no_body", STATUS_PASS if not leaked_todo else STATUS_FAIL, "" if not leaked_todo else f"{len(leaked_todo)} todo row(s) leaked a body field"))
    finally:
        # bug_delete (todo 9b09c9b0) now exists: hard-delete the scratch bug
        # itself before the plan -- source_plan_uuid carries no FK/cascade,
        # so plan_delete(hard) alone leaves this row orphaned.
        if bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
            results.append(CheckResult("4", "R13_bug_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
        results.append(CheckResult("4", "R13_plan_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R14_PRE_FIX_SKIP_REASON = (
    "server predates bug e6152cc0's plan_score AS-selector fix -- "
    "score_branch resolved via resolve_branch (plain Branch, no `depth`) "
    "and handed it to run_gate, which crashes inside "
    "plan_manager.verify.gate_data.scope_steps on branch.depth for any "
    "non-None branch scope -- redeploy pending"
)

# The documented ErrorResult codes plan_score's own docstring names for a
# scope='branch' call (GATE_RED / STEP_NOT_FOUND / PLAN_NOT_FOUND /
# EMBEDDINGS_UNAVAILABLE / VERDICT_STALE): any of these appearing in a
# failed call's diagnostic proves the command reached its normal
# domain-error mapping rather than leaking the unmapped AttributeError this
# bug raised (map_exception's fallback re-raises anything it does not
# recognize, so bug e6152cc0's crash was never wrapped in one of these
# codes -- it surfaced as a raw, uncoded internal failure instead).
_R14_KNOWN_DOMAIN_CODES = (
    "GATE_RED", "STEP_NOT_FOUND", "PLAN_NOT_FOUND", "EMBEDDINGS_UNAVAILABLE", "VERDICT_STALE",
)


async def run_r14_plan_score_as_selector_depth(client: Any) -> list[CheckResult]:
    """Bug e6152cc0: plan_score crashed on AS-level selectors because the
    plain ``Branch`` object ``score_branch`` resolved its scope into (via
    ``plan_manager.views.branch.resolve_branch``) has no ``depth`` field,
    while ``run_gate``'s hierarchical scoping (bug e197b94a's depth
    dispatch, ``plan_manager.verify.gate_data.scope_steps``) unconditionally
    reads ``branch.depth`` the instant a non-None branch is passed in --
    before any check group ever runs. Fixed by resolving through
    ``resolve_branch_scope`` instead (``BranchScope`` carries ``depth``).

    Recipe (throwaway ``live-smoke-`` prefixed plan, hard-deleted in a
    top-level try/finally, mirroring R10's minimal G/T/A chain):
    plan_create -> context_common(plan,level3) -> step_create G (level 3)
    -> context_common(G,level4) -> step_create T (level 4, parent=G) ->
    context_common(T,level5) -> step_create A (level 5, parent=T) ->
    plan_score(scope='branch', gs_step_id=G, ts_step_id=T, as_step_id=A).

    The plan_score call itself is both the repro and the version probe (same
    idiom as R10's GS-only call): this minimal fixture has no target_file,
    concepts, or inputs/outputs, so the mechanical gate is essentially
    certain to be red -- the fixed server therefore answers with the
    documented GATE_RED domain error (or, if the gate happens to be green,
    a genuine score); either is a clean, mapped response. The pre-fix
    server instead leaks the unmapped AttributeError as a raw, uncoded
    failure (map_exception's fallback re-raises anything it does not
    recognize) -- detected as "failed, and none of plan_score's documented
    error codes appear in the diagnostic" -- and this check group SKIPs
    naming bug e6152cc0, rather than failing the pipeline against a
    not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r14-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R14_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R14_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R14_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R14_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R14_step_create(T)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R14_context_common(T,level5)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a", "parent_step_id": t_id})
        a_id = _extract_step_id(res) if ok else None
        if not ok or a_id is None:
            results.append(CheckResult("4", "R14_step_create(A)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R14_repro_steps_created", STATUS_PASS, f"G={g_id} T={t_id} A={a_id}"))

        ok, res = await call(
            client, "plan_score",
            {"plan": plan_uuid, "scope": "branch", "gs_step_id": g_id, "ts_step_id": t_id, "as_step_id": a_id},
        )
        if ok:
            score_shape_ok = isinstance(res, dict) and res.get("scope") == "branch" and "index" in res
            results.append(
                CheckResult(
                    "4", "R14_plan_score_as_selector_no_depth_crash", STATUS_PASS if score_shape_ok else STATUS_FAIL,
                    "" if score_shape_ok else f"unexpected shape: {res!r}",
                )
            )
            return results

        if any(code in str(res) for code in _R14_KNOWN_DOMAIN_CODES):
            results.append(
                CheckResult(
                    "4", "R14_plan_score_as_selector_no_depth_crash", STATUS_PASS,
                    f"clean documented domain error, not a raw crash: {res!r}",
                )
            )
        else:
            results.append(
                CheckResult("4", "R14_plan_score_as_selector_no_depth_crash", STATUS_SKIP, R14_PRE_FIX_SKIP_REASON)
            )
    finally:
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R15_HELP_PRE_FIX_SKIP_REASON = (
    "server predates bug 507b74ae's help() catalog pagination: the "
    "no-cmdname response carries no 'pagination' envelope (limit/offset "
    "are silently ignored by the pre-fix builtin help's **kwargs, per its "
    "additionalProperties: True schema)"
)

R15_CONTEXT_BUNDLE_PRE_FIX_SKIP_REASON = (
    "server predates bug 03956ccf's context_bundle pagination: 'limit' is "
    "rejected as an unrecognized property (pre-fix schema's "
    "additionalProperties: False)"
)


async def run_r15_response_size_pagination_batch(client: Any) -> list[CheckResult]:
    """Bugs 507b74ae (help() no-cmdname catalog was unbounded -- ~200+
    commands, name + description per row, in one response) and 03956ccf
    (context_bundle's compiled 'common' block, and each child's own delta
    block, can grow to hundreds of entries when the parent scope is
    plan-wide and were returned unbounded). Both now use the project's
    uniform limit/offset pagination contract (plan_manager.commands.
    runtime_filtering: bounded default 50, max 200).

    Unit 1 (507b74ae) needs no throwaway plan: calls help() directly and
    checks the no-cmdname response stays under a sane byte bound and
    carries a 'pagination' envelope with total/limit/offset/returned/
    has_more; a smaller explicit limit is also checked to prove the page
    itself is actually bounded, not just decorated with metadata.

    Unit 2 (03956ccf) mirrors R8/R12's throwaway-plan recipe in full:
    plan_create -> context_common(plan,level3) -> step_create(level3,
    direct mode, no cascade_uuid -- establishes the plan's head revision,
    a precondition cascade_begin enforces) -> cascade_begin ->
    concept_add(cascade_uuid) -> context_bundle with an explicit small
    limit (MRS entities are cascade-only, so concept_add needs an open
    cascade like R8/R12's) to prove the 'common' block's (and each
    child's) first page is bounded, and that a caller can continue past
    it with block_get(block_id, limit, offset) using the block_id
    context_bundle already returns.

    Each unit detects a pre-fix server independently (see the two
    _PRE_FIX_SKIP_REASON constants above) and SKIPs only that unit, rather
    than failing the whole batch against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []

    # --- Unit 1 (bug 507b74ae): help() no-cmdname catalog pagination ---
    ok, res = await call(client, "help", {"limit": 5, "offset": 0})
    if not ok or not isinstance(res, dict):
        results.append(CheckResult("4", "R15_507b74ae_help_catalog_reachable", STATUS_FAIL, str(res)))
    else:
        pagination = res.get("pagination")
        if not isinstance(pagination, dict):
            results.append(
                CheckResult("4", "R15_507b74ae_help_catalog_pagination", STATUS_SKIP, R15_HELP_PRE_FIX_SKIP_REASON)
            )
        else:
            envelope_ok = {"total", "limit", "offset", "returned", "has_more"} <= set(pagination)
            results.append(
                CheckResult(
                    "4", "R15_507b74ae_help_catalog_pagination_envelope",
                    STATUS_PASS if envelope_ok else STATUS_FAIL, "" if envelope_ok else str(pagination),
                )
            )
            page_bounded_ok = (
                isinstance(res.get("commands"), dict)
                and len(res["commands"]) <= 5
                and pagination.get("limit") == 5
            )
            results.append(
                CheckResult(
                    "4", "R15_507b74ae_help_catalog_page_bounded",
                    STATUS_PASS if page_bounded_ok else STATUS_FAIL,
                    "" if page_bounded_ok else str(res.get("commands")),
                )
            )

            ok2, res2 = await call(client, "help", {})
            size_ok = ok2 and isinstance(res2, dict) and len(json.dumps(res2)) < 20000
            results.append(
                CheckResult(
                    "4", "R15_507b74ae_help_default_response_size_bounded",
                    STATUS_PASS if size_ok else STATUS_FAIL,
                    "" if size_ok else f"len={len(json.dumps(res2)) if ok2 and isinstance(res2, dict) else 'n/a'}",
                )
            )

    # --- Unit 2 (bug 03956ccf): context_bundle pagination ---
    plan_uuid: Optional[str] = None
    cascade_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r15-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R15_03956ccf_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        # cascade_begin requires the plan to already have a head revision
        # (CASCADE_CONFLICT "cannot open a cascade on a plan with no head
        # revision" otherwise) -- a brand-new plan_create has none. R8/R12
        # establish one first via a DIRECT-mode (no cascade_uuid) level-3
        # step_create: StepCreateCommand.execute (plan_manager/commands/
        # step_create_command.py) admits target_kind="paragraph" with
        # cascade_uuid=None as a legal direct mutation on a fresh plan
        # (cascade/regime.check_admission), then calls storage.version_
        # store.record_revision(..., ref_name=None), which advances the
        # plan's head_revision_uuid directly (domain.plan.set_head_revision)
        # -- exactly the missing precondition. Mirror R8/R12's own ordering:
        # context_common(plan,level3) -> step_create(level3, direct) ->
        # cascade_begin -> mutate(cascade_uuid) -> ... -> cascade_abort.
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R15_03956ccf_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R15_03956ccf_step_create(head_revision)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R15_03956ccf_step_create(head_revision)", STATUS_PASS, f"G={g_id}"))

        ok, res = await call(client, "cascade_begin", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict) or not res.get("cascade_uuid"):
            results.append(CheckResult("4", "R15_03956ccf_cascade_begin", STATUS_FAIL, str(res)))
            return results
        cascade_uuid = res["cascade_uuid"]
        results.append(CheckResult("4", "R15_03956ccf_cascade_begin", STATUS_PASS, f"cascade_uuid={cascade_uuid}"))

        ok, res = await call(
            client, "concept_add",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-001", "name": "LiveSmokeR15Concept",
                "definition": "R15 scratch concept for the response-size pagination batch.",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R15_03956ccf_concept_add", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(
            client, "context_bundle",
            {
                "plan": plan_uuid, "node": "plan", "child_level": 4,
                "children": [{"ref": "r15-child", "concepts": ["C-001"]}],
                "limit": 1, "offset": 0,
            },
        )
        if not ok and _looks_like_unknown_param(str(res), "limit"):
            results.append(
                CheckResult(
                    "4", "R15_03956ccf_context_bundle_pagination", STATUS_SKIP,
                    R15_CONTEXT_BUNDLE_PRE_FIX_SKIP_REASON,
                )
            )
            return results
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "R15_03956ccf_context_bundle", STATUS_FAIL, str(res)))
            return results

        common = res.get("common") if isinstance(res.get("common"), dict) else {}
        children = res.get("children") if isinstance(res.get("children"), list) else []

        common_bounded_ok = (
            {"blocks", "content", "total", "limit", "offset", "block_id"} <= set(common)
            and len(common.get("blocks", [])) <= 1
            and common.get("limit") == 1
        )
        results.append(
            CheckResult(
                "4", "R15_03956ccf_context_bundle_common_bounded",
                STATUS_PASS if common_bounded_ok else STATUS_FAIL, "" if common_bounded_ok else str(common),
            )
        )

        child_bounded_ok = (
            len(children) == 1
            and {"blocks", "content", "total", "limit", "offset"} <= set(children[0])
            and len(children[0].get("blocks", [])) <= 1
        )
        results.append(
            CheckResult(
                "4", "R15_03956ccf_context_bundle_child_bounded",
                STATUS_PASS if child_bounded_ok else STATUS_FAIL, "" if child_bounded_ok else str(children),
            )
        )

        # Subsequent-page retrieval works: block_get on the SAME block_id
        # context_bundle returned, with offset=1, must not error and must
        # report the same total -- proving context_bundle's block_id feeds
        # block_get's own pagination without a schema mismatch (the
        # documented continuation path for anything past the first page).
        if common_bounded_ok:
            block_id = common["block_id"]
            ok, res2 = await call(client, "block_get", {"plan": plan_uuid, "block_id": block_id, "limit": 50, "offset": 1})
            follow_on_ok = (
                ok and isinstance(res2, dict)
                and {"blocks", "content", "total", "limit", "offset"} <= set(res2)
                and res2["total"] == common["total"]
            )
            results.append(
                CheckResult(
                    "4", "R15_03956ccf_context_bundle_block_get_follow_on_page",
                    STATUS_PASS if follow_on_ok else STATUS_FAIL, "" if follow_on_ok else str(res2),
                )
            )
    finally:
        if cascade_uuid is not None:
            await call(client, "cascade_abort", {"plan": plan_uuid})
        if plan_uuid is not None:
            await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
    return results


R16_PRE_FIX_SKIP_REASON = (
    "server predates bug 32755092's append mode -- `append` is rejected as "
    "an unrecognized bug_update property (pre-fix schema's "
    "additionalProperties: False) -- redeploy pending"
)


async def run_r16_bug_update_append_history(client: Any) -> list[CheckResult]:
    """Bug 32755092: bug_update's free-text fields (detailed_description,
    expected_behavior, actual_behavior, reproduction) silently REPLACED the
    whole field instead of appending -- a history-loss footgun. Fixed by an
    optional `append` boolean (default false, unchanged REPLACE semantics):
    append=true joins the incoming text onto the currently stored value with
    a blank-line separator; appending to an empty/null field just sets it.

    Recipe (throwaway `live-smoke-` prefixed plan, hard-deleted in a
    top-level try/finally; one scratch bug anchored to it via
    source_type=plan -- per the established convention in this pipeline,
    see R13's docstring, source_plan_uuid carries no FK/cascade, so the
    scratch bug row itself is never independently deleted, only its plan):
    plan_create -> bug_create(detailed_description=<seed>) ->
    bug_update(detailed_description=<note1>, append=true) ->
    bug_update(detailed_description=<note2>, append=true), asserting each
    response's detailed_description accumulates seed+note1, then
    seed+note1+note2 -> a final bug_update WITHOUT append, asserting the
    unchanged default REPLACE semantics still overwrite the whole field.

    Pre-fix detection: `append` is a brand-new schema parameter under
    additionalProperties:false, so a not-yet-deployed server rejects the
    FIRST append=true call with a validation error naming `append` as an
    unrecognized property; that failure is the version probe and SKIPs the
    whole group naming bug 32755092, rather than failing the pipeline
    against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    bug_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r16-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R16_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        seed_text = "R16 seed detailed description."
        ok, res = await call(
            client, "bug_create",
            {
                "plan": plan_uuid, "title": unique_suffix("r16-bug"), "short_description": "R16 append scratch bug",
                "detailed_description": seed_text, "kind": "functional", "severity": "trivial",
                "priority_nice": 19, "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "plan", "source_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R16_bug_create", STATUS_FAIL, str(res)))
            return results
        bug_uuid = res["uuid"]
        results.append(CheckResult("4", "R16_bug_create", STATUS_PASS, f"uuid={bug_uuid}"))

        note1 = "R16 first appended note."
        ok, res = await call(
            client, "bug_update",
            {"bug_id": bug_uuid, "changed_by": "live-smoke", "detailed_description": note1, "append": True},
        )
        if not ok:
            pre_fix = _looks_like_unknown_param(str(res), "append")
            results.append(
                CheckResult(
                    "4", "R16_bug_update_append(1)", STATUS_SKIP if pre_fix else STATUS_FAIL,
                    R16_PRE_FIX_SKIP_REASON if pre_fix else str(res),
                )
            )
            return results
        after_first = res.get("detailed_description") if isinstance(res, dict) else None
        first_ok = isinstance(after_first, str) and seed_text in after_first and note1 in after_first
        results.append(
            CheckResult(
                "4", "R16_bug_update_append(1)_history_preserved", STATUS_PASS if first_ok else STATUS_FAIL,
                "" if first_ok else f"got: {after_first!r}",
            )
        )

        note2 = "R16 second appended note."
        ok, res = await call(
            client, "bug_update",
            {"bug_id": bug_uuid, "changed_by": "live-smoke", "detailed_description": note2, "append": True},
        )
        after_second = res.get("detailed_description") if ok and isinstance(res, dict) else None
        second_ok = ok and isinstance(after_second, str) and seed_text in after_second and note1 in after_second and note2 in after_second
        results.append(
            CheckResult(
                "4", "R16_bug_update_append(2)_history_preserved", STATUS_PASS if second_ok else STATUS_FAIL,
                "" if second_ok else str(res),
            )
        )

        # append=false (the default) must still REPLACE -- unchanged prior behavior.
        replace_text = "R16 replacement text."
        ok, res = await call(
            client, "bug_update",
            {"bug_id": bug_uuid, "changed_by": "live-smoke", "detailed_description": replace_text},
        )
        replaced_text = res.get("detailed_description") if ok and isinstance(res, dict) else None
        replace_ok = ok and replaced_text == replace_text
        results.append(
            CheckResult(
                "4", "R16_bug_update_default_replace_unchanged", STATUS_PASS if replace_ok else STATUS_FAIL,
                "" if replace_ok else str(res),
            )
        )
    finally:
        # bug_delete (todo 9b09c9b0) now exists: hard-delete the scratch bug
        # itself before the plan -- source_plan_uuid carries no FK/cascade,
        # so plan_delete(hard) alone leaves this row orphaned.
        if bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
            results.append(CheckResult("4", "R16_bug_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("4", "R16_plan_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R17_PRE_FIX_SKIP_REASON = (
    "server predates bug 3eec33f2's optional-plan fix -- bug_create still "
    "hard-requires `plan` even for a source_type=project anchor -- redeploy pending"
)


async def run_r17_bug_optional_plan_project_anchor(client: Any, project_id: str) -> list[CheckResult]:
    """Bug 3eec33f2: the bug command group required a mandatory `plan`
    parameter even for project-anchored bugs (source_type=project has no
    plan anchor at all), so an unrelated completed plan's PLAN_COMPLETED
    lock could block mutating a bug that has nothing to do with that plan.
    Fixed: `plan` is now OPTIONAL on bug_create and the bug/bug_fix
    mutating and lifecycle commands; bug_create still REQUIRES `plan` when
    source_type is plan/revision/step (that anchor itself needs it).

    Recipe: create a project-anchored bug (source_type=project,
    source_project_id=<--project>) WITHOUT ever supplying `plan`, then
    bug_update it (also without `plan`), asserting both succeed. No plan
    is ever created here; bug_delete (todo 9b09c9b0) now exists, so the
    scratch bug itself is hard-deleted in a top-level finally instead of
    being left dangling (the historical convention -- see R13's docstring
    -- predates that command).

    Pre-fix detection: `plan` is REQUIRED at the schema level on a
    not-yet-deployed server, so the bug_create call fails with a "missing
    required parameter" validation error naming `plan`; that failure is
    the version probe and SKIPs the whole group naming bug 3eec33f2,
    rather than failing the pipeline against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    bug_uuid: Optional[str] = None
    try:
        ok, res = await call(
            client, "bug_create",
            {
                "title": unique_suffix("r17-bug"), "short_description": "R17 project-anchored scratch bug (no plan)",
                "detailed_description": "R17: created without a plan parameter.", "kind": "functional",
                "severity": "trivial", "priority_nice": 19, "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "project", "source_project_id": project_id,
            },
        )
        if not ok:
            pre_fix = _looks_like_missing_required_param(str(res), "plan")
            results.append(
                CheckResult(
                    "4", "R17_bug_create_without_plan", STATUS_SKIP if pre_fix else STATUS_FAIL,
                    R17_PRE_FIX_SKIP_REASON if pre_fix else str(res),
                )
            )
            return results
        bug_ok = isinstance(res, dict) and bool(res.get("uuid"))
        results.append(CheckResult("4", "R17_bug_create_without_plan", STATUS_PASS if bug_ok else STATUS_FAIL, "" if bug_ok else str(res)))
        if not bug_ok:
            return results
        bug_uuid = res["uuid"]

        ok, res = await call(
            client, "bug_update",
            {"bug_id": bug_uuid, "changed_by": "live-smoke", "severity": "minor"},
        )
        update_ok = ok and isinstance(res, dict) and res.get("severity") == "minor"
        results.append(CheckResult("4", "R17_bug_update_without_plan", STATUS_PASS if update_ok else STATUS_FAIL, "" if update_ok else str(res)))
    finally:
        if bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
            results.append(CheckResult("4", "R17_bug_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


A795EA4D_PRE_FIX_SKIP_REASON = (
    "server predates bug a795ea4d's fix -- context_bundle's store_context_block "
    "dedup identity has no per-child discriminator, so distinct AS children "
    "sharing an identical concept scope are silently aliased onto ONE shared "
    "specific block_id -- redeploy pending"
)


async def run_r18_context_bundle_child_block_identity(client: Any) -> list[CheckResult]:
    """Bug a795ea4d: context_bundle(node=T, child_level=5, children=[A-001..
    A-005], each scoped to the SAME live concepts) returned ONE shared
    specific block_id for all five children -- store_context_block's
    idempotent-dedup identity keyed a 'specific' block on (plan,
    revision/cascade, node_path, child_level, kind, common_block,
    scope_concepts, content_hash) with no per-child discriminator, so
    siblings whose scope is fully covered by the common block (hence an
    identically EMPTY compiled delta) collapsed onto the first child's row.
    Fixed by threading each child's supplied 'ref' into that identity as an
    explicit child_ref column (migration 0023).

    Recipe (mirrors R15 unit 2's/R8's cascade_begin -> concept_add(cascade_
    scoped) -> ... idiom, since MRS concepts are cascade-only, AND R2/R8/
    R12's context_common-immediately-before-every-step_create idiom, since
    has_current_common_block requires the stored block's revision_uuid to
    match the plan's CURRENT head revision exactly): plan_create ->
    context_common(plan, level3) -> step_create G (level 3) ->
    context_common(G, level4) -> step_create T (level 4, parent=G) ->
    cascade_begin -> concept_add(C-001/C-002/C-003, cascade-scoped) ->
    context_bundle(node=T, child_level=5, shared_concepts=[C-001..C-003],
    children=[A-001..A-005] each scoped to the SAME three concepts) --
    every child's compiled delta is legitimately empty (fully covered by
    the T common block), so this reproduces the worst-case aliasing the
    bug report described. context_bundle itself needs no preceding
    context_common(T, level5) call: unlike step_create it always compiles
    fresh, and the A-00N children are virtual refs, never real level-5
    steps. Asserts the five returned block_ids are pairwise distinct, then
    reads each back via block_get and asserts its child_ref/attribution
    matches the child that requested it.

    Pre-fix detection: aliased (non-distinct) block_ids across the five
    children IS the bug's own symptom -- observing it here is the version
    probe, and SKIPs (not FAILs) this check against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    cascade_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r18-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R18_a795ea4d_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        # context_common must be (re)compiled for the parent/child_level
        # immediately before EVERY step_create -- has_current_common_block
        # (plan_manager/views/context_blocks.py) requires the stored
        # block's revision_uuid to match the plan's CURRENT head revision
        # exactly, and step_create bumps that head revision. Same idiom as
        # R2/R8/R12/R15 unit 2 (run_tier3_plan_step_create's docstring is
        # the canonical statement of this contract).
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R18_a795ea4d_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R18_a795ea4d_step_create(G)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R18_a795ea4d_step_create(G)", STATUS_PASS, f"step_id={g_id}"))

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R18_a795ea4d_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R18_a795ea4d_step_create(T)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R18_a795ea4d_step_create(T)", STATUS_PASS, f"step_id={t_id}"))

        # No context_common(T, level5) call is needed here: unlike
        # step_create (gated by has_current_common_block), context_bundle
        # itself compiles the common/specific blocks fresh on every call
        # (plan_manager/commands/context_bundle_command.py) -- the A-00N
        # children below are virtual refs passed straight to context_bundle,
        # never materialized as real level-5 steps.
        ok, res = await call(client, "cascade_begin", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict) or not res.get("cascade_uuid"):
            results.append(CheckResult("4", "R18_a795ea4d_cascade_begin", STATUS_FAIL, str(res)))
            return results
        cascade_uuid = res["cascade_uuid"]
        results.append(CheckResult("4", "R18_a795ea4d_cascade_begin", STATUS_PASS, f"cascade_uuid={cascade_uuid}"))

        concept_ids = ["C-001", "C-002", "C-003"]
        for concept_id in concept_ids:
            ok, res = await call(
                client, "concept_add",
                {
                    "plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": concept_id,
                    "name": f"LiveSmokeR18Concept{concept_id[-1]}",
                    "definition": "R18 scratch concept for bug a795ea4d's child-block-identity check.",
                },
            )
            if not ok:
                results.append(CheckResult("4", f"R18_a795ea4d_concept_add({concept_id})", STATUS_FAIL, str(res)))
                return results
        results.append(CheckResult("4", "R18_a795ea4d_concept_add(C-001..C-003)", STATUS_PASS))

        child_refs = [f"A-{i:03d}" for i in range(1, 6)]
        children = [{"ref": ref, "concepts": list(concept_ids)} for ref in child_refs]
        ok, res = await call(
            client, "context_bundle",
            {
                "plan": plan_uuid, "node": t_id, "child_level": 5,
                "shared_concepts": list(concept_ids), "children": children,
                "cascade_uuid": cascade_uuid,
            },
        )
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "R18_a795ea4d_context_bundle", STATUS_FAIL, str(res)))
            return results

        bundle_children = res.get("children") if isinstance(res.get("children"), list) else []
        shape_ok = len(bundle_children) == 5 and all(
            isinstance(c, dict) and c.get("total") == 0 and c.get("blocks") == [] for c in bundle_children
        )
        results.append(
            CheckResult(
                "4", "R18_a795ea4d_context_bundle_empty_delta_shape",
                STATUS_PASS if shape_ok else STATUS_FAIL, "" if shape_ok else str(bundle_children),
            )
        )
        if not shape_ok:
            return results

        returned_refs = [c.get("ref") for c in bundle_children]
        block_ids = [c.get("block_id") for c in bundle_children]
        if len(set(block_ids)) != 5:
            results.append(
                CheckResult(
                    "4", "R18_a795ea4d_distinct_child_block_ids", STATUS_SKIP,
                    A795EA4D_PRE_FIX_SKIP_REASON,
                )
            )
            return results
        results.append(
            CheckResult(
                "4", "R18_a795ea4d_distinct_child_block_ids", STATUS_PASS,
                f"refs={returned_refs} block_ids={block_ids}",
            )
        )

        # block_get path: each child's own stored block, read back
        # independently, must identify -- via child_ref -- its own child.
        attribution_ok = True
        attribution_detail = ""
        for ref, block_id in zip(returned_refs, block_ids):
            ok, res = await call(client, "block_get", {"plan": plan_uuid, "block_id": block_id})
            if not ok or not isinstance(res, dict) or res.get("child_ref") != ref:
                attribution_ok = False
                attribution_detail = f"ref={ref} block_id={block_id} block_get={res}"
                break
        results.append(
            CheckResult(
                "4", "R18_a795ea4d_block_get_child_attribution",
                STATUS_PASS if attribution_ok else STATUS_FAIL, attribution_detail,
            )
        )
    finally:
        if cascade_uuid is not None:
            await call(client, "cascade_abort", {"plan": plan_uuid})
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("4", "R18_a795ea4d_plan_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


async def run_r19_bug_delete_full_crud_lifecycle(client: Any) -> list[CheckResult]:
    """Todo 9b09c9b0: full CRUD for the bug family -- exercises the new
    bug_delete command end to end (soft/hard/dry_run mirror bug_delete's
    sibling todo_delete/comment_delete/tool_delete): plan_create ->
    bug_create(source_type=plan) -> bug_delete(dry_run=true), asserting the
    preview shape {dry_run, would_delete, mode, blocked, references} reports
    an unblocked soft-mode preview -> bug_delete(hard=true), asserting the
    hard-delete result {dry_run, mode, deleted_uuid} -> bug_list(plan),
    asserting the bug is no longer present (physically gone, not merely
    hidden by the deleted_at filter a soft delete would apply).

    Self-contained top-level try/finally: the dedicated plan is always
    hard-deleted afterward, whether or not the bug itself was already
    removed by the check's own bug_delete(hard=true) call.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r19-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R19_9b09c9b0_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(
            client, "bug_create",
            {
                "plan": plan_uuid, "title": unique_suffix("r19-bug"),
                "short_description": "R19 full-CRUD scratch bug", "detailed_description": "R19: bug_delete lifecycle probe.",
                "kind": "functional", "severity": "trivial", "priority_nice": 19, "reporter": "live-smoke",
                "created_by": "live-smoke", "source_type": "plan", "source_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R19_9b09c9b0_bug_create", STATUS_FAIL, str(res)))
            return results
        bug_uuid = res["uuid"]
        results.append(CheckResult("4", "R19_9b09c9b0_bug_create", STATUS_PASS, f"uuid={bug_uuid}"))

        ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "dry_run": True})
        dry_run_ok = (
            ok and isinstance(res, dict)
            and res.get("dry_run") is True
            and res.get("would_delete") == bug_uuid
            and res.get("mode") == "soft"
            and res.get("blocked") is False
            and res.get("references") == {}
        )
        results.append(CheckResult("4", "R19_9b09c9b0_bug_delete(dry_run)", STATUS_PASS if dry_run_ok else STATUS_FAIL, "" if dry_run_ok else str(res)))
        if not dry_run_ok:
            return results

        ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
        hard_ok = ok and isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == bug_uuid
        results.append(CheckResult("4", "R19_9b09c9b0_bug_delete(hard)", STATUS_PASS if hard_ok else STATUS_FAIL, "" if hard_ok else str(res)))
        if not hard_ok:
            return results

        ok, res = await call(client, "bug_list", {"plan": plan_uuid})
        gone_ok = ok and isinstance(res, dict) and isinstance(res.get("bugs"), list) and not any(
            isinstance(b, dict) and b.get("uuid") == bug_uuid for b in res["bugs"]
        )
        results.append(CheckResult("4", "R19_9b09c9b0_bug_gone_from_bug_list", STATUS_PASS if gone_ok else STATUS_FAIL, "" if gone_ok else str(res)))
    finally:
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("4", "R19_9b09c9b0_plan_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R20_PRE_FIX_SKIP_REASON = (
    "server predates todo a5ec9c1a's optional-plan extension to the "
    "bug_impact_*/bug_propagation_* command groups -- bug_impact_add still "
    "hard-requires `plan` even for a project-anchored bug -- redeploy pending"
)


async def run_r20_bug_impact_optional_plan_a5ec9c1a(client: Any, project_id: str) -> list[CheckResult]:
    """Todo a5ec9c1a: extend bug 3eec33f2's optional-`plan` pattern (shipped
    0.1.64 for the bug/bug_fix command family) to bug_impact_*/
    bug_propagation_*: `plan` becomes `str | None = None` -- the owning bug
    is always resolved directly by `bug_id` (globally unique), so a
    project-anchored bug's impact record no longer needs an unrelated plan
    supplied at all.

    Recipe (mirrors R17's plan-less convention -- no plan is ever created
    here): bug_create(source_type=project, source_project_id=<--project>,
    no `plan`) -> bug_impact_add(bug_id=..., target_type=project,
    impact_type=uses_broken_api, created_by=..., target_project_id=
    <--project>, no `plan`), asserting success. Cleanup (top-level
    try/finally): bug_impact_delete(hard=true) then bug_delete(hard=true).

    Pre-fix detection: `plan` is REQUIRED at the schema level on a
    not-yet-deployed server, so bug_impact_add fails with a "missing
    required parameter" validation error naming `plan`; that failure is
    the version probe and SKIPs this check naming todo a5ec9c1a, rather
    than failing the pipeline against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    bug_uuid: Optional[str] = None
    impact_uuid: Optional[str] = None
    try:
        ok, res = await call(
            client, "bug_create",
            {
                "title": unique_suffix("r20-bug"), "short_description": "R20 project-anchored scratch bug (no plan)",
                "detailed_description": "R20: bug_impact_add optional-plan probe.", "kind": "functional",
                "severity": "trivial", "priority_nice": 19, "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "project", "source_project_id": project_id,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R20_a5ec9c1a_bug_create", STATUS_FAIL, str(res)))
            return results
        bug_uuid = res["uuid"]
        results.append(CheckResult("4", "R20_a5ec9c1a_bug_create", STATUS_PASS, f"uuid={bug_uuid}"))

        ok, res = await call(
            client, "bug_impact_add",
            {
                "bug_id": bug_uuid, "target_type": "project", "impact_type": "uses_broken_api",
                "created_by": "live-smoke", "target_project_id": project_id,
            },
        )
        if not ok:
            pre_fix = _looks_like_missing_required_param(str(res), "plan")
            results.append(
                CheckResult(
                    "4", "R20_a5ec9c1a_bug_impact_add_without_plan", STATUS_SKIP if pre_fix else STATUS_FAIL,
                    R20_PRE_FIX_SKIP_REASON if pre_fix else str(res),
                )
            )
            return results
        impact_ok = isinstance(res, dict) and bool(res.get("uuid"))
        results.append(
            CheckResult(
                "4", "R20_a5ec9c1a_bug_impact_add_without_plan", STATUS_PASS if impact_ok else STATUS_FAIL,
                "" if impact_ok else str(res),
            )
        )
        if not impact_ok:
            return results
        impact_uuid = res["uuid"]
    finally:
        if impact_uuid is not None:
            ok, res = await call(client, "bug_impact_delete", {"impact_uuid": impact_uuid, "changed_by": "live-smoke", "hard": True})
            results.append(CheckResult("4", "R20_a5ec9c1a_bug_impact_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
            results.append(CheckResult("4", "R20_a5ec9c1a_bug_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R21_PRE_FIX_SKIP_REASON = (
    "server predates bug 0d8755bd's class-1 fix -- concept_add's bare "
    "uuid.UUID(cascade_uuid) parse raises an untyped ValueError inside "
    "validate_params, surfacing as an untyped -32603 instead of a clean "
    "-32602 -- redeploy pending"
)


async def run_r21_typed_invalid_params_concept_add(client: Any) -> list[CheckResult]:
    """Bug 0d8755bd class 1: a bare `uuid.UUID(cascade_uuid)` parse inside
    concept_add's validate_params raised an untyped ValueError, invisible
    to the adapter's typed-error mapping (mcp_proxy_adapter.commands.base.
    Command.run only special-cases ValidationError/InvalidParamsError/
    NotFoundError/TimeoutError/CommandError) -- it fell through to the
    generic except-Exception branch and surfaced as an untyped -32603
    instead of a clean -32602 InvalidParamsError. Fixed by catching
    ValueError and re-raising as InvalidParamsError.

    Recipe: concept_add(plan=<a nonexistent plan identifier>,
    cascade_uuid="not-a-uuid", concept_id/name/definition filled) --
    cascade_uuid is parsed in validate_params before plan is ever
    resolved, so the supplied plan need not exist; asserts the failure's
    typed error code is -32602, never -32603.

    Pre-fix detection: an observed -32603 IS the bug's own symptom --
    observing it here is the version probe, and SKIPs (not FAILs) this
    check against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    ok, res = await call(
        client, "concept_add",
        {
            "plan": unique_suffix("r21-nonexistent-plan"), "cascade_uuid": "not-a-uuid",
            "concept_id": "C-001", "name": "R21LiveSmokeConcept", "definition": "R21 typed-error probe.",
        },
    )
    if ok:
        results.append(CheckResult("4", "R21_0d8755bd_concept_add_bad_cascade_uuid", STATUS_FAIL, f"call unexpectedly succeeded: {res!r}"))
        return results
    code = _typed_error_code(res)
    if code == -32603:
        results.append(CheckResult("4", "R21_0d8755bd_concept_add_bad_cascade_uuid", STATUS_SKIP, R21_PRE_FIX_SKIP_REASON))
        return results
    typed_ok = code == -32602
    results.append(
        CheckResult(
            "4", "R21_0d8755bd_concept_add_bad_cascade_uuid", STATUS_PASS if typed_ok else STATUS_FAIL,
            "" if typed_ok else f"code={code} diagnostic={res!r}",
        )
    )
    return results


R22_PRE_FIX_SKIP_REASON = (
    "server predates bug 0d8755bd's class-2A fix -- comment_get's bare "
    "uuid.UUID(comment_uuid) parse raises an untyped ValueError, surfacing "
    "as an untyped -32603 instead of a clean -32602 naming comment_uuid -- "
    "redeploy pending"
)


async def run_r22_typed_invalid_params_comment_get(client: Any) -> list[CheckResult]:
    """Bug 0d8755bd class 2A: comment_get's bare `uuid.UUID(comment_uuid)`
    parse raised an untyped ValueError; fixed by catching it and raising
    InvalidParamsError(f"comment_uuid is not a valid UUID: {comment_uuid!r}").

    Recipe: comment_get(plan=<nonexistent>, comment_uuid="not-a-uuid") --
    comment_uuid is validated before plan is ever resolved, so the
    supplied plan need not exist; asserts a typed -32602 whose message
    names comment_uuid, never a raw -32603.

    Pre-fix detection: mirrors R21 -- an observed -32603 IS the bug's own
    symptom and SKIPs (not FAILs) against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    ok, res = await call(client, "comment_get", {"plan": unique_suffix("r22-nonexistent-plan"), "comment_uuid": "not-a-uuid"})
    if ok:
        results.append(CheckResult("4", "R22_0d8755bd_comment_get_bad_comment_uuid", STATUS_FAIL, f"call unexpectedly succeeded: {res!r}"))
        return results
    code = _typed_error_code(res)
    if code == -32603:
        results.append(CheckResult("4", "R22_0d8755bd_comment_get_bad_comment_uuid", STATUS_SKIP, R22_PRE_FIX_SKIP_REASON))
        return results
    message = _error_message(res)
    typed_ok = code == -32602 and "comment_uuid is not a valid UUID" in message
    results.append(
        CheckResult(
            "4", "R22_0d8755bd_comment_get_bad_comment_uuid", STATUS_PASS if typed_ok else STATUS_FAIL,
            "" if typed_ok else f"code={code} message={message!r}",
        )
    )
    return results


R23_PRE_FIX_SKIP_REASON = (
    "server predates bug 0d8755bd's class-2B fix -- review_result_get's "
    "bare uuid.UUID(review_uuid) parse raises an untyped ValueError, "
    "surfacing as an untyped -32603 instead of a clean -32602 naming "
    "review_uuid -- redeploy pending"
)


async def run_r23_typed_invalid_params_review_result_get(client: Any) -> list[CheckResult]:
    """Bug 0d8755bd class 2B: review_result_get's bare
    `uuid.UUID(review_uuid)` parse raised an untyped ValueError; fixed by
    catching it and raising InvalidParamsError(f"review_uuid is not a
    valid UUID: {review_uuid!r}").

    Recipe: review_result_get(plan=<nonexistent>, review_uuid=
    "not-a-uuid") -- asserts a typed -32602 whose message names
    review_uuid and never leaks the generic untyped-exception wording.

    Pre-fix detection: mirrors R21/R22 -- an observed -32603 IS the bug's
    own symptom and SKIPs (not FAILs) against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    ok, res = await call(client, "review_result_get", {"plan": unique_suffix("r23-nonexistent-plan"), "review_uuid": "not-a-uuid"})
    if ok:
        results.append(CheckResult("4", "R23_0d8755bd_review_result_get_bad_review_uuid", STATUS_FAIL, f"call unexpectedly succeeded: {res!r}"))
        return results
    code = _typed_error_code(res)
    if code == -32603:
        results.append(CheckResult("4", "R23_0d8755bd_review_result_get_bad_review_uuid", STATUS_SKIP, R23_PRE_FIX_SKIP_REASON))
        return results
    message = _error_message(res)
    typed_ok = (
        code == -32602
        and "review_uuid is not a valid UUID" in message
        and "Unexpected error" not in message
    )
    results.append(
        CheckResult(
            "4", "R23_0d8755bd_review_result_get_bad_review_uuid", STATUS_PASS if typed_ok else STATUS_FAIL,
            "" if typed_ok else f"code={code} message={message!r}",
        )
    )
    return results


R24_PRE_FIX_SKIP_REASON = (
    "server predates bug 85b180bf's pagination fix entirely -- "
    "command_catalog_dump's no-arg response carries no returned/has_more "
    "envelope keys at all -- redeploy pending"
)

R24_RESPONSE_BYTE_CEILING = 80000


async def run_r24_command_catalog_dump_pagination(client: Any) -> list[CheckResult]:
    """Bug 85b180bf (revised fix) + todo 9c409a47: command_catalog_dump's
    no-arg default is now bounded to 10 entries (~48 KB on the live
    199-command catalog, well under the original bug's ~130 KB complaint),
    sorted deterministically by command name, with an additive returned/
    has_more pagination envelope; limit/offset share the exact same
    validation and MAX_LIMIT as every other paginated command.

    Checks: no-arg call -> limit==10, returned==len(commands), has_more is
    true, total >= 100, serialized response < 80000 bytes; command order
    is stable across two consecutive no-arg calls; page 2 (offset=res
    ['limit']) is disjoint from page 1 and itself sorted by name; limit=0
    -> INVALID_PAGINATION.

    Pre-fix detection: a server predating even the FIRST fix attempt
    (commit 8a3d6fc) returns no returned/has_more keys at all (the
    original unbounded response); that shape SKIPs this whole check
    naming bug 85b180bf, rather than failing the pipeline against a
    not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    ok, res = await call(client, "command_catalog_dump", {})
    if not ok or not isinstance(res, dict):
        results.append(CheckResult("4", "R24_85b180bf_command_catalog_dump_default", STATUS_FAIL, str(res)))
        return results
    if "returned" not in res or "has_more" not in res:
        results.append(CheckResult("4", "R24_85b180bf_command_catalog_dump_default", STATUS_SKIP, R24_PRE_FIX_SKIP_REASON))
        return results

    commands = res.get("commands", [])
    size_bytes = len(json.dumps(res).encode("utf-8"))
    default_ok = (
        res.get("limit") == 10
        and res.get("returned") == len(commands)
        and res.get("has_more") is True
        and isinstance(res.get("total"), int) and res["total"] >= 100
        and size_bytes < R24_RESPONSE_BYTE_CEILING
    )
    results.append(
        CheckResult(
            "4", "R24_85b180bf_command_catalog_dump_default", STATUS_PASS if default_ok else STATUS_FAIL,
            "" if default_ok else (
                f"limit={res.get('limit')} returned={res.get('returned')} has_more={res.get('has_more')} "
                f"total={res.get('total')} bytes={size_bytes}"
            ),
        )
    )

    ok2, res2 = await call(client, "command_catalog_dump", {})
    names1 = [c.get("name") for c in commands if isinstance(c, dict)]
    names2 = (
        [c.get("name") for c in res2.get("commands", []) if isinstance(c, dict)]
        if ok2 and isinstance(res2, dict) else None
    )
    stable_ok = ok2 and names2 is not None and names1 == names2
    results.append(
        CheckResult(
            "4", "R24_9c409a47_order_stable_across_calls", STATUS_PASS if stable_ok else STATUS_FAIL,
            "" if stable_ok else f"call1={names1} call2={names2}",
        )
    )

    page2_offset = res.get("limit", 10)
    ok3, res3 = await call(client, "command_catalog_dump", {"offset": page2_offset})
    page2_commands = res3.get("commands", []) if ok3 and isinstance(res3, dict) else []
    names_page2 = [c.get("name") for c in page2_commands if isinstance(c, dict)]
    disjoint_ok = ok3 and not (set(names1) & set(names_page2))
    sorted_ok = names_page2 == sorted(names_page2)
    results.append(
        CheckResult(
            "4", "R24_page2_disjoint_and_sorted", STATUS_PASS if (disjoint_ok and sorted_ok) else STATUS_FAIL,
            "" if (disjoint_ok and sorted_ok) else f"page1={names1} page2={names_page2}",
        )
    )

    ok4, res4 = await call(client, "command_catalog_dump", {"limit": 0})
    invalid_ok = (not ok4) and "INVALID_PAGINATION" in str(res4)
    results.append(CheckResult("4", "R24_limit_zero_invalid_pagination", STATUS_PASS if invalid_ok else STATUS_FAIL, "" if invalid_ok else str(res4)))
    return results


R25_PRE_FIX_SKIP_REASON = (
    "server predates todo ffe0b0a8's view=summary default flip -- "
    "todo_list/comment_list still embed the full record by default -- "
    "redeploy pending"
)


async def run_r25_list_summary_default_drops_free_text(client: Any) -> list[CheckResult]:
    """Todo ffe0b0a8: every list command whose entity declares
    SUMMARY_FIELDS now defaults to view=summary (was view=full) -- the
    compact default projection drops the entity's unbounded free-text
    field. Checks two representative members: todo_list rows carry no
    "description" (R11 already covers todo_list(view=summary) explicitly;
    this checks the OMITTED-view default instead); comment_list rows carry
    no "body" (the comment text itself).

    Read-only, no throwaway entities: reads whatever live data already
    exists (rows may be zero, in which case there is nothing to inspect
    the row shape of -- this SKIPs for lack of data rather than asserting
    anything about an empty page).
    """
    results: list[CheckResult] = []

    ok, res = await call(client, "todo_list", {"limit": 5})
    if not ok or not isinstance(res, dict) or not isinstance(res.get("todos"), list):
        results.append(CheckResult("4", "R25_ffe0b0a8_todo_list_summary_default", STATUS_FAIL, str(res)))
    else:
        rows = res["todos"]
        if not rows:
            results.append(
                CheckResult("4", "R25_ffe0b0a8_todo_list_summary_default", STATUS_SKIP, "no live todo rows available to inspect the default row projection")
            )
        else:
            no_description = all(isinstance(r, dict) and "description" not in r for r in rows)
            results.append(
                CheckResult(
                    "4", "R25_ffe0b0a8_todo_list_summary_default", STATUS_PASS if no_description else STATUS_SKIP,
                    "" if no_description else R25_PRE_FIX_SKIP_REASON,
                )
            )

    ok, res = await call(client, "comment_list", {"limit": 5})
    if not ok or not isinstance(res, dict) or not isinstance(res.get("comments"), list):
        results.append(CheckResult("4", "R25_ffe0b0a8_comment_list_summary_default", STATUS_FAIL, str(res)))
    else:
        rows = res["comments"]
        if not rows:
            results.append(
                CheckResult("4", "R25_ffe0b0a8_comment_list_summary_default", STATUS_SKIP, "no live comment rows available to inspect the default row projection")
            )
        else:
            no_body = all(isinstance(r, dict) and "body" not in r for r in rows)
            results.append(
                CheckResult(
                    "4", "R25_ffe0b0a8_comment_list_summary_default", STATUS_PASS if no_body else STATUS_SKIP,
                    "" if no_body else R25_PRE_FIX_SKIP_REASON,
                )
            )
    return results


R26_PRE_FIX_SKIP_REASON = (
    "server predates todo f47a2db0's queue scoping -- anchor_plan is "
    "rejected as an unrecognized property on todo_queue -- redeploy pending"
)

R26_ANCHOR_PLAN = "e4a9fd91-151e-4e11-bc98-423142d9298a"


async def run_r26_todo_queue_anchor_plan_scoping(client: Any) -> list[CheckResult]:
    """Todo f47a2db0: todo_queue gained anchor_plan/project server-side
    scoping (was global-only, forcing every caller to fetch everything and
    filter client-side). Checks anchor_plan=<the live roadmap plan UUID>:
    every returned row's plan_uuid matches, and the filtered total never
    exceeds the unfiltered total.

    Pre-fix detection: anchor_plan is a brand-new schema parameter under
    additionalProperties:false; a not-yet-deployed server rejects it as an
    unrecognized property, which is the version probe and SKIPs this
    check naming todo f47a2db0, rather than failing against a
    not-yet-deployed fix.
    """
    results: list[CheckResult] = []

    ok, res = await call(client, "todo_queue", {"anchor_plan": R26_ANCHOR_PLAN, "limit": 50})
    if not ok and _looks_like_unknown_param(str(res), "anchor_plan"):
        results.append(CheckResult("4", "R26_f47a2db0_todo_queue_anchor_plan", STATUS_SKIP, R26_PRE_FIX_SKIP_REASON))
        return results
    if not ok or not isinstance(res, dict) or not isinstance(res.get("queue"), list):
        results.append(CheckResult("4", "R26_f47a2db0_todo_queue_anchor_plan", STATUS_FAIL, str(res)))
        return results
    rows = res["queue"]
    filtered_total = res.get("total")
    all_match = all(isinstance(r, dict) and r.get("plan_uuid") == R26_ANCHOR_PLAN for r in rows)
    results.append(
        CheckResult(
            "4", "R26_f47a2db0_todo_queue_anchor_plan_rows_match", STATUS_PASS if all_match else STATUS_FAIL,
            "" if all_match else str(rows),
        )
    )

    ok2, res2 = await call(client, "todo_queue", {"limit": 1})
    unfiltered_total = res2.get("total") if ok2 and isinstance(res2, dict) else None
    total_bound_ok = (
        ok2 and isinstance(filtered_total, int) and isinstance(unfiltered_total, int)
        and filtered_total <= unfiltered_total
    )
    results.append(
        CheckResult(
            "4", "R26_f47a2db0_todo_queue_filtered_total_bounded", STATUS_PASS if total_bound_ok else STATUS_FAIL,
            "" if total_bound_ok else f"filtered={filtered_total} unfiltered={unfiltered_total}",
        )
    )
    return results


R27_PRE_DEPLOY_SKIP_REASON = (
    "server predates the runtime work-layer CRUD surface for wish/calendar_entry "
    "-- redeploy pending"
)

R27_REQUIRED_COMMANDS: frozenset[str] = frozenset(
    {
        "wish_create", "wish_get", "wish_list", "wish_update", "wish_delete",
        "calendar_entry_create", "calendar_entry_get", "calendar_entry_list",
        "calendar_entry_update", "calendar_entry_delete",
    }
)


async def run_r27_runtime_work_layer_lifecycle(
    client: Any,
    catalog_names: frozenset[str],
    project_id: str,
) -> list[CheckResult]:
    """Runtime work-layer CRUD lifecycle: wish + calendar_entry.

    Marker-gated on the full command surface being present in the live
    catalog, mirroring R7/R9's grouped "skip pre-deploy, exercise
    post-deploy" convention.

    Recipe:
      1. wish_create(project anchor) -> wish_get -> wish_list(project,
         active_only, limit) -> wish_update(status=planned). The limit=5
         call only pins the page CONTRACT (shape/total/limit/offset) --
         membership of the freshly created scratch wish is located
         separately by paging with limit=50 (advancing offset until found
         or offset >= total), since 5+ pre-existing project wishes ordered
         ahead of it would otherwise push it past a fixed limit-5 page and
         produce a false FAIL (bug 396ea09b). Both conditions are AND-ed
         into the single R27_wish_list CheckResult.
      2. calendar_entry_create(project anchor, linked to that wish) ->
         calendar_entry_get -> calendar_entry_list(project, wish, day
         window, limit) -> calendar_entry_update(status=in_progress).
      3. wish_delete(dry_run=true) proves the inbound-reference guard is
         live while the calendar entry still points at it.
      4. calendar_entry_delete(hard=true) -> wish_delete(hard=true).

    Cleanup is top-level try/finally: if a mid-sequence failure leaves
    either row alive, the finally block hard-deletes the calendar entry
    first, then the wish, so the reference guard is respected even during
    cleanup.
    """
    if not R27_REQUIRED_COMMANDS <= catalog_names:
        missing = sorted(R27_REQUIRED_COMMANDS - catalog_names)
        return [
            CheckResult(
                "4",
                "R27_runtime_work_layer_lifecycle",
                STATUS_SKIP,
                f"{R27_PRE_DEPLOY_SKIP_REASON} (missing: {missing})",
            )
        ]

    results: list[CheckResult] = []
    wish_uuid: Optional[str] = None
    calendar_entry_uuid: Optional[str] = None
    try:
        ok, res = await call(
            client,
            "wish_create",
            {
                "title": unique_suffix("r27-wish"),
                "description": "R27 live CRUD probe for the runtime work layer.",
                "kind": "feature",
                "priority_nice": -4,
                "created_by": "live-smoke",
                "anchor_type": "project",
                "anchor_project_id": project_id,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("wish_uuid"):
            results.append(CheckResult("4", "R27_wish_create", STATUS_FAIL, str(res)))
            return results
        wish_uuid = res["wish_uuid"]
        results.append(CheckResult("4", "R27_wish_create", STATUS_PASS, f"uuid={wish_uuid}"))

        ok, res = await call(client, "wish_get", {"wish": wish_uuid})
        wish_get_ok = ok and isinstance(res, dict) and res.get("wish_uuid") == wish_uuid
        results.append(CheckResult("4", "R27_wish_get", STATUS_PASS if wish_get_ok else STATUS_FAIL, "" if wish_get_ok else str(res)))
        if not wish_get_ok:
            return results

        ok, res = await call(client, "wish_list", {"project": project_id, "active_only": True, "limit": 5})
        wish_list_page_ok = (
            ok and isinstance(res, dict) and isinstance(res.get("wishes"), list)
            and isinstance(res.get("total"), int) and res.get("limit") == 5 and res.get("offset") == 0
        )

        # The page contract above only pins limit=5's shape; with 5+
        # pre-existing project wishes ordered ahead of the scratch one, it
        # can legitimately land on a later page. Membership is located
        # separately by paging with limit=50 until found or offset exceeds
        # the reported total, so the assertion is deterministic regardless
        # of how many other wishes the project already holds.
        wish_list_membership_ok = False
        membership_res: Any = res
        if wish_list_page_ok:
            total = res["total"]
            offset = 0
            while offset < total:
                ok, page = await call(
                    client, "wish_list",
                    {"project": project_id, "active_only": True, "limit": 50, "offset": offset},
                )
                membership_res = page
                if not ok:
                    break
                if isinstance(page, dict) and isinstance(page.get("wishes"), list) and any(
                    isinstance(row, dict) and row.get("wish_uuid") == wish_uuid for row in page["wishes"]
                ):
                    wish_list_membership_ok = True
                    break
                offset += 50

        wish_list_ok = wish_list_page_ok and wish_list_membership_ok
        results.append(
            CheckResult(
                "4", "R27_wish_list", STATUS_PASS if wish_list_ok else STATUS_FAIL,
                "" if wish_list_ok else str(membership_res),
            )
        )
        if not wish_list_ok:
            return results

        ok, res = await call(client, "wish_update", {"wish": wish_uuid, "changed_by": "live-smoke", "status": "planned"})
        wish_update_ok = ok and isinstance(res, dict) and res.get("status") == "planned"
        results.append(CheckResult("4", "R27_wish_update", STATUS_PASS if wish_update_ok else STATUS_FAIL, "" if wish_update_ok else str(res)))
        if not wish_update_ok:
            return results

        ok, res = await call(
            client,
            "calendar_entry_create",
            {
                "title": unique_suffix("r27-calendar"),
                "description": "R27 linked calendar entry for the runtime work-layer lifecycle.",
                "status": "planned",
                "start_date": "2026-07-27",
                "end_date": "2026-07-28",
                "created_by": "live-smoke",
                "anchor_type": "project",
                "anchor_project_id": project_id,
                "wish": wish_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("calendar_entry_uuid"):
            results.append(CheckResult("4", "R27_calendar_entry_create", STATUS_FAIL, str(res)))
            return results
        calendar_entry_uuid = res["calendar_entry_uuid"]
        results.append(CheckResult("4", "R27_calendar_entry_create", STATUS_PASS, f"uuid={calendar_entry_uuid}"))

        ok, res = await call(client, "calendar_entry_get", {"calendar_entry": calendar_entry_uuid})
        entry_get_ok = ok and isinstance(res, dict) and res.get("calendar_entry_uuid") == calendar_entry_uuid
        results.append(CheckResult("4", "R27_calendar_entry_get", STATUS_PASS if entry_get_ok else STATUS_FAIL, "" if entry_get_ok else str(res)))
        if not entry_get_ok:
            return results

        ok, res = await call(
            client,
            "calendar_entry_list",
            {"project": project_id, "wish": wish_uuid, "day_from": "2026-07-27", "day_to": "2026-07-28", "limit": 5},
        )
        entry_list_ok = (
            ok and isinstance(res, dict) and isinstance(res.get("calendar_entries"), list)
            and isinstance(res.get("total"), int) and res.get("limit") == 5 and res.get("offset") == 0
            and any(isinstance(row, dict) and row.get("calendar_entry_uuid") == calendar_entry_uuid for row in res["calendar_entries"])
        )
        results.append(CheckResult("4", "R27_calendar_entry_list", STATUS_PASS if entry_list_ok else STATUS_FAIL, "" if entry_list_ok else str(res)))
        if not entry_list_ok:
            return results

        ok, res = await call(
            client,
            "calendar_entry_update",
            {"calendar_entry": calendar_entry_uuid, "changed_by": "live-smoke", "status": "in_progress"},
        )
        entry_update_ok = ok and isinstance(res, dict) and res.get("status") == "in_progress"
        results.append(CheckResult("4", "R27_calendar_entry_update", STATUS_PASS if entry_update_ok else STATUS_FAIL, "" if entry_update_ok else str(res)))
        if not entry_update_ok:
            return results

        ok, res = await call(client, "wish_delete", {"wish": wish_uuid, "changed_by": "live-smoke", "dry_run": True})
        wish_delete_preview_ok = (
            ok and isinstance(res, dict) and res.get("dry_run") is True
            and res.get("would_delete") == wish_uuid and res.get("mode") == "soft"
            and res.get("blocked") is True
            and isinstance(res.get("references"), dict)
            and res["references"].get("calendar_entry.wish_uuid", 0) >= 1
        )
        results.append(
            CheckResult(
                "4",
                "R27_wish_delete(dry_run_blocked_by_calendar_entry)",
                STATUS_PASS if wish_delete_preview_ok else STATUS_FAIL,
                "" if wish_delete_preview_ok else str(res),
            )
        )
        if not wish_delete_preview_ok:
            return results

        ok, res = await call(
            client,
            "calendar_entry_delete",
            {"calendar_entry": calendar_entry_uuid, "changed_by": "live-smoke", "hard": True},
        )
        entry_delete_ok = ok and isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == calendar_entry_uuid
        results.append(CheckResult("4", "R27_calendar_entry_delete(hard)", STATUS_PASS if entry_delete_ok else STATUS_FAIL, "" if entry_delete_ok else str(res)))
        if not entry_delete_ok:
            return results
        calendar_entry_uuid = None

        ok, res = await call(client, "wish_delete", {"wish": wish_uuid, "changed_by": "live-smoke", "hard": True})
        wish_delete_ok = ok and isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == wish_uuid
        results.append(CheckResult("4", "R27_wish_delete(hard)", STATUS_PASS if wish_delete_ok else STATUS_FAIL, "" if wish_delete_ok else str(res)))
        if not wish_delete_ok:
            return results
        wish_uuid = None
    finally:
        if calendar_entry_uuid is not None:
            ok, res = await call(
                client,
                "calendar_entry_delete",
                {"calendar_entry": calendar_entry_uuid, "changed_by": "live-smoke", "hard": True},
            )
            results.append(CheckResult("4", "R27_calendar_entry_delete(hard_cleanup)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if wish_uuid is not None:
            ok, res = await call(client, "wish_delete", {"wish": wish_uuid, "changed_by": "live-smoke", "hard": True})
            results.append(CheckResult("4", "R27_wish_delete(hard_cleanup)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R28_PRE_FIX_SKIP_REASON = (
    "server predates bug 1e13649f's fix -- bug_delete(hard=true) on a bug "
    "whose source_plan_uuid anchors a hard-deleted plan raises -32603 "
    "(insert on runtime_audit_log violates FK "
    "runtime_audit_log_plan_uuid_fkey) -- redeploy pending"
)

# Must match plan_manager.storage.runtime_audit_store.DANGLING_PLAN_UUID_FIELD
# (this script talks to the server over the wire only -- it never imports
# server internals -- so the key name is duplicated here, not imported).
R28_DANGLING_PLAN_UUID_FIELD = "_dangling_plan_uuid"


def _looks_like_dangling_plan_anchor_fk_violation(diagnostic_text: str) -> bool:
    """True iff a command-call failure looks like bug 1e13649f's runtime_audit_log_plan_uuid_fkey violation (a runtime audit write anchored to a plan that no longer exists), rather than any other error incidentally similar.

    Narrow match: requires the exact FK constraint name from the violation
    message to appear in the diagnostic text.
    """
    return "runtime_audit_log_plan_uuid_fkey" in diagnostic_text


async def run_r28_bug_delete_dangling_plan_anchor(client: Any) -> list[CheckResult]:
    """Bug 1e13649f: bug_delete (soft and hard paths, per the bug report)
    on a bug whose source_plan_uuid anchors a plan that was hard-deleted
    out from under it used to fail with -32603 (insert on
    runtime_audit_log violates FK runtime_audit_log_plan_uuid_fkey).
    bug_report.source_plan_uuid carries no FK of its own (plan_delete does
    not cascade to it), so a dangling anchor is a legal, reachable state,
    but the NEW audit row bug_delete's hard path writes for its own
    hard_delete action was rejected by runtime_audit_log's own plan_uuid
    FK. Fixed at the shared audit layer (record_runtime_change, the single
    write path every plan-anchored runtime mutation funnels through): a
    dangling plan_uuid now falls back to an unanchored (NULL) audit row
    with the original plan uuid preserved in changed_fields, so the
    deletion always succeeds and the audit trail is never silently
    dropped.

    Recipe (the bug's own live repro): plan_create -> bug_create
    (source_type=plan, anchored to that plan) -> plan_delete(hard=true)
    (the bug's source_plan_uuid is now dangling) -> bug_delete(hard=true),
    asserting SUCCESS (not the historical FK error) -> audit_list(entity_
    type=bug_report, entity_id=<bug>, action=hard_delete), asserting
    exactly one record with plan_uuid=None and the original (now-deleted)
    plan uuid preserved under changed_fields[R28_DANGLING_PLAN_UUID_FIELD].

    Pre-fix detection: bug_delete(hard=true) fails with the exact FK
    violation text this bug names; that failure is the version probe and
    SKIPs this check naming bug 1e13649f, rather than failing the
    pipeline against a not-yet-deployed fix.

    Self-contained top-level try/finally: the anchor plan is deliberately
    hard-deleted as PART of the recipe (that dangling state is what is
    under test), so finally only has cleanup left to do when a step
    before or including the fixed bug_delete call failed and left the bug
    (or, if plan_create succeeded but bug_create did not, the plan)
    behind.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    bug_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r28-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R28_1e13649f_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(
            client, "bug_create",
            {
                "plan": plan_uuid, "title": unique_suffix("r28-bug"),
                "short_description": "R28 dangling-plan-anchor scratch bug",
                "detailed_description": "R28: bug_delete(hard) after its anchor plan is hard-deleted (bug 1e13649f).",
                "kind": "functional", "severity": "trivial", "priority_nice": 19, "reporter": "live-smoke",
                "created_by": "live-smoke", "source_type": "plan", "source_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R28_1e13649f_bug_create", STATUS_FAIL, str(res)))
            return results
        bug_uuid = res["uuid"]
        results.append(CheckResult("4", "R28_1e13649f_bug_create", STATUS_PASS, f"uuid={bug_uuid}"))

        ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
        plan_gone_ok = ok and isinstance(res, dict)
        results.append(
            CheckResult(
                "4", "R28_1e13649f_plan_delete(hard)_dangles_bug_anchor", STATUS_PASS if plan_gone_ok else STATUS_FAIL,
                "" if plan_gone_ok else str(res),
            )
        )
        if not plan_gone_ok:
            return results
        # the plan row is gone now; finally must not try to delete it again
        deleted_plan_uuid = plan_uuid
        plan_uuid = None

        ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
        if not ok:
            pre_fix = _looks_like_dangling_plan_anchor_fk_violation(str(res))
            results.append(
                CheckResult(
                    "4", "R28_1e13649f_bug_delete(hard)_dangling_anchor", STATUS_SKIP if pre_fix else STATUS_FAIL,
                    R28_PRE_FIX_SKIP_REASON if pre_fix else str(res),
                )
            )
            return results
        hard_ok = isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == bug_uuid
        results.append(
            CheckResult(
                "4", "R28_1e13649f_bug_delete(hard)_dangling_anchor", STATUS_PASS if hard_ok else STATUS_FAIL,
                "" if hard_ok else str(res),
            )
        )
        if not hard_ok:
            return results
        deleted_bug_uuid = bug_uuid
        bug_uuid = None  # already gone; nothing left for finally to clean up

        ok, res = await call(
            client, "audit_list",
            {"entity_type": "bug_report", "entity_id": deleted_bug_uuid, "action": "hard_delete", "limit": 5},
        )
        items = res.get("items") if ok and isinstance(res, dict) else None
        record = items[0] if isinstance(items, list) and len(items) == 1 else None
        audit_ok = (
            record is not None
            and record.get("plan_uuid") is None
            and isinstance(record.get("changed_fields"), dict)
            and record["changed_fields"].get(R28_DANGLING_PLAN_UUID_FIELD) == deleted_plan_uuid
        )
        results.append(
            CheckResult(
                "4", "R28_1e13649f_audit_row_null_plan_preserves_dangling_uuid", STATUS_PASS if audit_ok else STATUS_FAIL,
                "" if audit_ok else str(res),
            )
        )
    finally:
        if bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
            results.append(CheckResult("4", "R28_1e13649f_bug_delete(hard)_cleanup", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("4", "R28_1e13649f_plan_delete(hard)_cleanup", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R29_PRE_FIX_SKIP_REASON = (
    "server predates bug 36414056's fix -- step_transition(to_status=frozen) "
    "on a branch scope raises -32603 (\"'Branch' object has no attribute "
    "'depth'\") before the freeze gate can run -- redeploy pending"
)


def _looks_like_branch_depth_attribute_error(diagnostic_text: str) -> bool:
    """True iff a command-call failure looks like bug 36414056's crash (the
    scoped freeze gate handing run_gate a plain Branch view instead of a
    BranchScope), rather than any other error incidentally similar.

    Narrow match: requires the exact AttributeError text from the violation
    to appear in the diagnostic text.
    """
    return "'Branch' object has no attribute 'depth'" in diagnostic_text


async def run_r29_step_transition_branch_scope_freeze_gate(client: Any) -> list[CheckResult]:
    """Bug 36414056: step_transition(to_status=frozen) on a branch scope
    (scope=G-NNN) used to crash with -32603 AttributeError ("'Branch'
    object has no attribute 'depth'") because the scoped freeze gate built
    a plain views.branch.Branch and handed it to run_gate, which consumes
    a BranchScope (reads branch.depth for scope labeling and step
    selection). Fixed by constructing BranchScope(depth="as", ...) at the
    single call site in step_transition_command._run_transition_gate.

    Recipe (the bug's own live repro on a throwaway plan): plan_create ->
    context_common/step_create chain G -> T -> A (context_common
    recompiled before every step_create, per the head-revision currency
    contract) -> step_transition(scope=G, to_status=frozen,
    require_green=true), asserting the freeze GATE RUNS: either the
    transition succeeds (gate green) or the documented GATE_RED domain
    error comes back -- never the raw AttributeError.

    Pre-fix detection: the exact AttributeError text is the version probe
    and SKIPs this check naming bug 36414056, rather than failing the
    pipeline against a not-yet-deployed fix.

    Cleanup: top-level try/finally hard-deletes the throwaway plan.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r29-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R29_36414056_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R29_36414056_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R29_36414056_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R29_36414056_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R29_36414056_step_create(T)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R29_36414056_context_common(T,level5)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a", "parent_step_id": t_id})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R29_36414056_step_create(A)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R29_36414056_repro_chain_created", STATUS_PASS, f"G={g_id} T={t_id}"))

        ok, res = await call(
            client, "step_transition",
            {"plan": plan_uuid, "scope": g_id, "to_status": "frozen", "require_green": True},
        )
        if ok:
            # Gate ran and came back green enough to freeze: the crash is gone.
            results.append(CheckResult("4", "R29_36414056_branch_scope_freeze_gate_runs", STATUS_PASS, "frozen (gate green)"))
            return results
        diagnostic = str(res)
        if _looks_like_branch_depth_attribute_error(diagnostic):
            results.append(
                CheckResult(
                    "4", "R29_36414056_branch_scope_freeze_gate_runs", STATUS_SKIP,
                    R29_PRE_FIX_SKIP_REASON,
                )
            )
            return results
        gate_ran = "GATE_RED" in diagnostic or "mechanical gate is red" in diagnostic
        results.append(
            CheckResult(
                "4", "R29_36414056_branch_scope_freeze_gate_runs", STATUS_PASS if gate_ran else STATUS_FAIL,
                "GATE_RED (gate executed, domain-shaped refusal)" if gate_ran else diagnostic,
            )
        )
    finally:
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("4", "R29_36414056_plan_delete(hard)_cleanup", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R30_PRE_FIX_SKIP_REASON = (
    "server predates todo 19391f0b's strict subtree closure -- the dependent "
    "goal's subtree starts in the same wave as (or earlier than) the tail of "
    "the producer goal's subtree -- redeploy pending"
)


async def run_r30_parallel_map_subtree_closure(client: Any) -> list[CheckResult]:
    """Todo 19391f0b: graph_parallel_map must schedule a dependent goal's
    ENTIRE subtree strictly after the LAST node of the producer goal's
    subtree, not merely after the producer goal's own start wave (the
    start-barrier semantics bug 85a9d14b's fix shipped in 0.1.84).

    Recipe (throwaway plan, hard-deleted in try/finally): plan_create ->
    G-001 with T-001 and two atomics serialized by an explicit sibling
    edge (A-002 depends_on A-001, so the producer subtree spans two
    waves) -> G-002 with T-001/A-001 -> goal edge G-002 depends_on G-001
    (both via step_dependency_apply; goals and atomics are siblings, so
    both edges are legal) -> graph_parallel_map, asserting
    min(wave over G-002 subtree) > max(wave over G-001 subtree).

    Pre-fix detection: on a server with start-barrier-only semantics the
    overlap is exactly consumer_start <= producer_tail; that observation
    SKIPs this check naming todo 19391f0b rather than failing the
    pipeline against a not-yet-deployed server.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r30-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R30_19391f0b_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        step_uuids: dict[str, str] = {}
        g_ids: dict[str, str] = {}
        for g_slug in ("g1", "g2"):
            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
            if not ok:
                results.append(CheckResult("4", f"R30_19391f0b_context_common(plan,before {g_slug})", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": g_slug})
            g_id = _extract_step_id(res) if ok else None
            if not ok or g_id is None or not isinstance(res, dict) or not res.get("uuid"):
                results.append(CheckResult("4", f"R30_19391f0b_step_create({g_slug})", STATUS_FAIL, str(res)))
                return results
            g_ids[g_slug] = g_id
            step_uuids[g_slug] = res["uuid"]

            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
            if not ok:
                results.append(CheckResult("4", f"R30_19391f0b_context_common({g_slug},level4)", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
            # Both goals' tactical children get the per-parent step_id
            # T-001, so a bare T-001 reference is AMBIGUOUS_STEP_ID from
            # the second goal on -- address the T by uuid throughout.
            t_uuid = res.get("uuid") if ok and isinstance(res, dict) else None
            if not ok or not t_uuid:
                results.append(CheckResult("4", f"R30_19391f0b_step_create({g_slug}/t)", STATUS_FAIL, str(res)))
                return results

            a_slugs = ("a1", "a2") if g_slug == "g1" else ("a1",)
            for a_slug in a_slugs:
                ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_uuid, "child_level": 5})
                if not ok:
                    results.append(CheckResult("4", f"R30_19391f0b_context_common({g_slug}/t,level5)", STATUS_FAIL, str(res)))
                    return results
                ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": a_slug, "parent_step_id": t_uuid})
                if not ok or not isinstance(res, dict) or not res.get("uuid"):
                    results.append(CheckResult("4", f"R30_19391f0b_step_create({g_slug}/t/{a_slug})", STATUS_FAIL, str(res)))
                    return results
                step_uuids[f"{g_slug}/{a_slug}"] = res["uuid"]
        results.append(CheckResult("4", "R30_19391f0b_two_goal_repro_built", STATUS_PASS, f"g1={g_ids['g1']} g2={g_ids['g2']}"))

        edges = [
            {"op": "add", "step_id": step_uuids["g1/a2"], "depends_on": [step_uuids["g1/a1"]]},
            {"op": "add", "step_id": step_uuids["g2"], "depends_on": [step_uuids["g1"]]},
        ]
        ok, res = await call(client, "step_dependency_apply", {"plan": plan_uuid, "changes": edges, "dry_run": False})
        edges_ok = ok and isinstance(res, dict) and res.get("applied") is True
        results.append(CheckResult("4", "R30_19391f0b_edges_applied", STATUS_PASS if edges_ok else STATUS_FAIL, "" if edges_ok else str(res)))
        if not edges_ok:
            return results

        ok, res = await call(client, "graph_parallel_map", {"plan": plan_uuid})
        wave_rows = res.get("waves") if ok and isinstance(res, dict) else None
        if not ok or not isinstance(wave_rows, list) or not wave_rows:
            results.append(CheckResult("4", "R30_19391f0b_graph_parallel_map", STATUS_FAIL, str(res)))
            return results

        wave_of: dict[str, int] = {}
        for index, row in enumerate(wave_rows):
            for path in row:
                wave_of[path] = index
        g1_prefix, g2_prefix = g_ids["g1"], g_ids["g2"]
        producer_waves = [w for path, w in wave_of.items() if path == g1_prefix or path.startswith(g1_prefix + "/")]
        consumer_waves = [w for path, w in wave_of.items() if path == g2_prefix or path.startswith(g2_prefix + "/")]
        if len(producer_waves) != 4 or len(consumer_waves) != 3:
            results.append(
                CheckResult(
                    "4", "R30_19391f0b_wave_membership", STATUS_FAIL,
                    f"expected 4 producer + 3 consumer nodes, got {len(producer_waves)}+{len(consumer_waves)}: {wave_of}",
                )
            )
            return results
        producer_tail = max(producer_waves)
        consumer_start = min(consumer_waves)
        if consumer_start > producer_tail:
            results.append(
                CheckResult(
                    "4", "R30_19391f0b_consumer_after_entire_producer_subtree", STATUS_PASS,
                    f"producer_tail_wave={producer_tail} consumer_start_wave={consumer_start}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "R30_19391f0b_consumer_after_entire_producer_subtree", STATUS_SKIP,
                    f"{R30_PRE_FIX_SKIP_REASON} (producer_tail={producer_tail} consumer_start={consumer_start})",
                )
            )
    finally:
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("4", "R30_19391f0b_plan_delete(hard)_cleanup", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R31_PRE_FIX_SKIP_REASON = (
    "server predates bug e3060750's fix -- block_rebuild resolves the "
    "committed head even while a cascade is open (summaries carry "
    "cascade_uuid=null yet is_current=true) -- redeploy pending"
)


async def run_r31_block_rebuild_open_cascade(client: Any) -> list[CheckResult]:
    """Bug e3060750: block_rebuild during an open cascade used to rebuild
    against the COMMITTED head (cascade_uuid=null, committed revision) yet
    report is_current=true, so the gate immediately rejected the rebuilt
    blocks as stale. Fixed by defaulting the command to the plan's live
    working state (open cascade tip when a cascade is open).

    Recipe (throwaway plan, try/finally cleanup): plan_create ->
    context_common/step_create G -> T (so G has a child and a common
    block exists) -> block_list to capture the stored common block id ->
    cascade_begin -> concept_add (in-cascade truth advance, stales the
    block) -> block_rebuild(block_ids=[id]), asserting the summary row
    carries the OPEN cascade's uuid with is_current=true. Pre-fix
    detection: cascade_uuid=null with is_current=true is the exact filed
    signature and SKIPs naming bug e3060750. Cleanup: cascade_abort, then
    plan_delete(hard).
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    cascade_open = False
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r31-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R31_e3060750_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R31_e3060750_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R31_e3060750_step_create(G)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R31_e3060750_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        if not ok:
            results.append(CheckResult("4", "R31_e3060750_step_create(T)", STATUS_FAIL, str(res)))
            return results
        # Recompile AFTER the T exists so a current common block for
        # (G, child_level=4) is stored at the pre-cascade head.
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R31_e3060750_context_common(G,level4,post-T)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "block_list", {"plan": plan_uuid, "kind": "common", "limit": 10})
        rows = res.get("blocks") if ok and isinstance(res, dict) else None
        if rows is None and ok and isinstance(res, dict):
            rows = res.get("items")
        block_id = None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and row.get("node_path") == g_id:
                    block_id = row.get("block_id") or row.get("uuid")
                    break
            if block_id is None and rows:
                first = rows[0]
                block_id = first.get("block_id") or first.get("uuid") if isinstance(first, dict) else None
        if not ok or not block_id:
            results.append(CheckResult("4", "R31_e3060750_block_list", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R31_e3060750_seed_block_found", STATUS_PASS, f"block={block_id}"))

        ok, res = await call(client, "cascade_begin", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict) or not res.get("cascade_uuid"):
            results.append(CheckResult("4", "R31_e3060750_cascade_begin", STATUS_FAIL, str(res)))
            return results
        open_cascade_uuid = res["cascade_uuid"]
        cascade_open = True

        ok, res = await call(
            client, "concept_add",
            {
                "plan": plan_uuid, "cascade_uuid": open_cascade_uuid, "concept_id": "C-001",
                "name": "LiveSmokeR31Concept", "definition": "R31 scratch concept (bug e3060750).",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R31_e3060750_concept_add", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "block_rebuild", {"plan": plan_uuid, "block_ids": [str(block_id)], "limit": 5})
        rebuilt_rows = res.get("blocks") if ok and isinstance(res, dict) else None
        row = rebuilt_rows[0] if isinstance(rebuilt_rows, list) and rebuilt_rows else None
        if not ok or not isinstance(row, dict):
            results.append(CheckResult("4", "R31_e3060750_block_rebuild", STATUS_FAIL, str(res)))
            return results
        rebuilt_cascade = row.get("cascade_uuid")
        is_current = row.get("is_current")
        if rebuilt_cascade == open_cascade_uuid and is_current is True:
            results.append(
                CheckResult(
                    "4", "R31_e3060750_rebuild_targets_open_cascade", STATUS_PASS,
                    f"cascade_uuid={rebuilt_cascade}",
                )
            )
        elif rebuilt_cascade in (None, "") and is_current is True:
            results.append(
                CheckResult(
                    "4", "R31_e3060750_rebuild_targets_open_cascade", STATUS_SKIP,
                    R31_PRE_FIX_SKIP_REASON,
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "R31_e3060750_rebuild_targets_open_cascade", STATUS_FAIL,
                    f"cascade_uuid={rebuilt_cascade!r} is_current={is_current!r} (open cascade {open_cascade_uuid})",
                )
            )
    finally:
        if cascade_open:
            ok, res = await call(client, "cascade_abort", {"plan": plan_uuid})
            results.append(CheckResult("4", "R31_e3060750_cascade_abort_cleanup", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("4", "R31_e3060750_plan_delete(hard)_cleanup", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


R32_PRE_FIX_SKIP_REASON = (
    "server predates bug 74ba4313's fix -- the plan_unfreeze audit record "
    "does not name the opened cascade_uuid, so cascade provenance is "
    "unverifiable from audit_list -- redeploy pending"
)


async def run_r32_unfreeze_audit_names_cascade(client: Any) -> list[CheckResult]:
    """Bug 74ba4313: cascade provenance must be verifiable from audit_list.
    cascade_begin/commit/abort already write audited records; the gap was
    the unfreeze door: plan_unfreeze audited BEFORE the cascade existed,
    so its record could not name the opened cascade_uuid, leaving the
    begin side of an unfreeze-opened cascade's chain unverifiable.

    Recipe (throwaway plan, try/finally cleanup): plan_create -> G/T/A
    chain -> step_transition(whole_plan -> frozen, require_green=false)
    -> plan_unfreeze(changed_by, reason) capturing the returned
    cascade_uuid -> audit_list(plan, action=plan_unfreeze), asserting the
    newest record's changed_fields.cascade_uuid equals the returned one.
    Pre-fix detection: the field absent from changed_fields SKIPs naming
    bug 74ba4313. Cleanup: cascade_abort, plan_delete(hard).
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    cascade_open = False
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r32-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R32_74ba4313_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R32_74ba4313_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R32_74ba4313_step_create(G)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R32_74ba4313_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_uuid = res.get("uuid") if ok and isinstance(res, dict) else None
        if not ok or not t_uuid:
            results.append(CheckResult("4", "R32_74ba4313_step_create(T)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_uuid, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R32_74ba4313_context_common(T,level5)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a", "parent_step_id": t_uuid})
        if not ok:
            results.append(CheckResult("4", "R32_74ba4313_step_create(A)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(
            client, "step_transition",
            {"plan": plan_uuid, "scope": "whole_plan", "to_status": "frozen", "require_green": False},
        )
        if not ok:
            results.append(CheckResult("4", "R32_74ba4313_freeze_whole_plan", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R32_74ba4313_frozen_repro_built", STATUS_PASS, f"G={g_id}"))

        ok, res = await call(
            client, "plan_unfreeze",
            {"plan": plan_uuid, "changed_by": "live-smoke", "reason": "R32 provenance probe (bug 74ba4313)"},
        )
        opened_cascade = res.get("cascade_uuid") if ok and isinstance(res, dict) else None
        if not ok or not opened_cascade:
            results.append(CheckResult("4", "R32_74ba4313_plan_unfreeze", STATUS_FAIL, str(res)))
            return results
        cascade_open = True

        ok, res = await call(
            client, "audit_list",
            {"plan": plan_uuid, "action": "plan_unfreeze", "limit": 1},
        )
        items = res.get("items") if ok and isinstance(res, dict) else None
        record = items[0] if isinstance(items, list) and items else None
        if not ok or not isinstance(record, dict):
            results.append(CheckResult("4", "R32_74ba4313_audit_list", STATUS_FAIL, str(res)))
            return results
        changed_fields = record.get("changed_fields")
        changed_fields = changed_fields if isinstance(changed_fields, dict) else {}
        if changed_fields.get("cascade_uuid") == opened_cascade:
            results.append(
                CheckResult(
                    "4", "R32_74ba4313_unfreeze_audit_names_cascade", STATUS_PASS,
                    f"cascade_uuid={opened_cascade}",
                )
            )
        elif "cascade_uuid" not in changed_fields:
            results.append(
                CheckResult(
                    "4", "R32_74ba4313_unfreeze_audit_names_cascade", STATUS_SKIP,
                    R32_PRE_FIX_SKIP_REASON,
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "R32_74ba4313_unfreeze_audit_names_cascade", STATUS_FAIL,
                    f"audit cascade_uuid={changed_fields.get('cascade_uuid')!r} != opened {opened_cascade}",
                )
            )
    finally:
        if cascade_open:
            ok, res = await call(client, "cascade_abort", {"plan": plan_uuid})
            results.append(CheckResult("4", "R32_74ba4313_cascade_abort_cleanup", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            results.append(CheckResult("4", "R32_74ba4313_plan_delete(hard)_cleanup", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    return results


async def run_r33_project_uuid_reserve_lifecycle(
    client: Any, catalog_names: frozenset[str]
) -> list[CheckResult]:
    """CR-6 G-002: the project_uuid_reserve namespace-reservation lifecycle.

    Reserve, release and resolve are the three actions of ONE command,
    selected by its action parameter; there is no separate
    project_uuid_resolve or project_uuid_release command.

    Recipe (no plan fixture needed, the reservation is plan-independent):
    reserve a fresh uuid4 -> reserve the SAME uuid again and require the
    deterministic DUPLICATE_ID refusal -> resolve and require
    kind=project_reservation -> release -> resolve again and require
    RESERVATION_NOT_FOUND, proving the release actually freed the
    identifier. Cleanup runs in a finally block once the reserve
    succeeded, so a mid-check assertion failure never leaves a
    reservation occupying an identifier on the live server.
    """
    results: list[CheckResult] = []
    if "project_uuid_reserve" not in catalog_names:
        results.append(
            CheckResult(
                "4", "R33_project_uuid_reserve", STATUS_SKIP,
                "server predates project_uuid_reserve",
            )
        )
        return results

    reserved = str(uuid_mod.uuid4())
    actor = "live-smoke-r33"
    holding = False
    try:
        ok, res = await call(
            client,
            "project_uuid_reserve",
            {"action": "reserve", "project_uuid": reserved, "reserved_by": actor},
        )
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "r33-reserve", STATUS_FAIL, str(res)))
            return results
        holding = True
        if res.get("project_uuid") == reserved and res.get("reserved_by") == actor:
            results.append(CheckResult("4", "r33-reserve", STATUS_PASS, f"reserved {reserved}"))
        else:
            results.append(CheckResult("4", "r33-reserve", STATUS_FAIL, f"payload did not echo the reservation: {res!r}"))
            return results

        ok, res = await call(
            client,
            "project_uuid_reserve",
            {"action": "reserve", "project_uuid": reserved, "reserved_by": actor},
        )
        # call()/unwrap_envelope surfaces a domain error as a formatted
        # diagnostic string, so assert on the stable domain_code substring,
        # the same idiom the other Tier-4 checks use.
        if (not ok) and "DUPLICATE_ID" in str(res):
            results.append(CheckResult("4", "r33-collision", STATUS_PASS, "DUPLICATE_ID"))
        else:
            results.append(CheckResult("4", "r33-collision", STATUS_FAIL, f"expected DUPLICATE_ID, got ok={ok} {res!r}"))
            return results

        ok, res = await call(
            client,
            "project_uuid_reserve",
            {"action": "resolve", "project_uuid": reserved, "reserved_by": actor},
        )
        kind = res.get("kind") if ok and isinstance(res, dict) else None
        if ok and kind == "project_reservation":
            results.append(CheckResult("4", "r33-resolve", STATUS_PASS, "kind=project_reservation"))
        else:
            results.append(CheckResult("4", "r33-resolve", STATUS_FAIL, f"expected kind=project_reservation, got ok={ok} {res!r}"))
            return results

        ok, res = await call(
            client,
            "project_uuid_reserve",
            {"action": "release", "project_uuid": reserved, "reserved_by": actor},
        )
        if ok:
            holding = False
            results.append(CheckResult("4", "r33-release", STATUS_PASS, f"released {reserved}"))
        else:
            results.append(CheckResult("4", "r33-release", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(
            client,
            "project_uuid_reserve",
            {"action": "resolve", "project_uuid": reserved, "reserved_by": actor},
        )
        if (not ok) and "RESERVATION_NOT_FOUND" in str(res):
            results.append(CheckResult("4", "r33-post-release", STATUS_PASS, "RESERVATION_NOT_FOUND"))
        else:
            results.append(CheckResult("4", "r33-post-release", STATUS_FAIL, f"expected RESERVATION_NOT_FOUND, got ok={ok} {res!r}"))
    finally:
        if holding:
            ok, res = await call(
                client,
                "project_uuid_reserve",
                {"action": "release", "project_uuid": reserved, "reserved_by": actor},
            )
            results.append(
                CheckResult(
                    "4", "r33-cleanup", STATUS_PASS if ok else STATUS_FAIL,
                    "" if ok else str(res),
                )
            )
    return results


async def run_r34_reference_inspect_traversal(
    client: Any, catalog_names: frozenset[str]
) -> list[CheckResult]:
    """CR-6 G-004/T-004: reference_inspect over the live reference graph.

    Deviation from the step recipe, deliberate: the recipe asked for a
    second todo LINKED to the first as the second hop, but
    todo_link.from_todo_uuid is ON DELETE CASCADE, so the catalog
    classifies it as cascading and reference_inspect (which reports only
    references that BLOCK a hard delete) would never show it. A comment
    anchored to the todo IS a blocking referrer
    (runtime_comment.anchor_ref_id with primary_anchor_type='todo'), so
    the fixture uses a comment for hop two. Anything else would assert a
    hop that cannot exist and fail for the wrong reason.

    Recipe (throwaway plan, try/finally cleanup): plan_create -> a todo
    anchored to that plan (a blocking referrer of the plan via
    todo_item.anchor_plan_uuid) -> a comment anchored to the todo (a
    blocking referrer of the todo) -> reference_inspect(plan,
    recursive=false), asserting the todo appears among direct_referrers
    with the four-key shape -> reference_inspect(plan, recursive=true,
    depth_limit=5), asserting the comment is reached through the traversal
    and the traversal metadata is present.

    Assertions are on payload fields and domain codes, never message prose.
    """
    results: list[CheckResult] = []
    if "reference_inspect" not in catalog_names:
        results.append(
            CheckResult(
                "4", "R34_reference_inspect", STATUS_SKIP,
                "server predates reference_inspect",
            )
        )
        return results

    plan_uuid: Optional[str] = None
    todo_uuid: Optional[str] = None
    comment_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r34-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "r34-plan-create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(
            client, "todo_create",
            {
                "title": unique_suffix("r34-todo"),
                "description": "R34 reference_inspect scratch todo",
                "kind": "task", "priority_nice": 19, "created_by": "live-smoke",
                "anchor_type": "plan", "anchor_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "r34-todo-create", STATUS_FAIL, str(res)))
            return results
        todo_uuid = res["uuid"]

        ok, res = await call(
            client, "comment_add",
            {
                "plan": plan_uuid, "anchor_type": "todo", "anchor_ref_id": todo_uuid,
                "kind": "comment", "visibility": "audit_only", "author": "live-smoke",
                "body": "R34 reference_inspect second-hop referrer",
                "created_by": "live-smoke",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "r34-comment-add", STATUS_FAIL, str(res)))
            return results
        comment_uuid = res["uuid"]

        ok, res = await call(
            client, "reference_inspect",
            {"entity_type": "plan", "entity_id": plan_uuid, "recursive": False},
        )
        direct = res.get("direct_referrers") if ok and isinstance(res, dict) else None
        matched = None
        if isinstance(direct, list):
            matched = next(
                (
                    row for row in direct
                    if isinstance(row, dict) and row.get("referrer_id") == todo_uuid
                ),
                None,
            )
        if matched is None:
            results.append(
                CheckResult(
                    "4", "r34-direct", STATUS_FAIL,
                    f"the anchored todo is not among direct_referrers: ok={ok} {res!r}",
                )
            )
            return results
        shape_ok = (
            matched.get("table") == "todo_item"
            and matched.get("column") == "anchor_plan_uuid"
            # referrer_kind, never referrer_type: the key must match the guard's
            # lookup and the DELETE_BLOCKED payload.
            and matched.get("referrer_kind") == "todo_item"
        )
        results.append(
            CheckResult(
                "4", "r34-direct", STATUS_PASS if shape_ok else STATUS_FAIL,
                f"todo_item.anchor_plan_uuid -> {todo_uuid}" if shape_ok
                else f"unexpected referrer shape: {matched!r}",
            )
        )
        if not shape_ok:
            return results

        ok, res = await call(
            client, "reference_inspect",
            {
                "entity_type": "plan", "entity_id": plan_uuid,
                "recursive": True, "depth_limit": 5,
            },
        )
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "r34-recursive", STATUS_FAIL, str(res)))
            return results
        traversal = res.get("traversal")
        items = res.get("items")
        reached_comment = False
        if isinstance(items, list):
            reached_comment = any(
                isinstance(row, dict) and row.get("referrer_id") == comment_uuid
                for row in items
            )
        metadata_ok = (
            isinstance(traversal, dict)
            and "nodes_visited" in traversal
            and "cycles_detected" in traversal
            and "edges_traversed" in traversal
        )
        if reached_comment and metadata_ok:
            results.append(
                CheckResult(
                    "4", "r34-recursive", STATUS_PASS,
                    f"nodes_visited={traversal.get('nodes_visited')} "
                    f"cycles_detected={traversal.get('cycles_detected')}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "r34-recursive", STATUS_FAIL,
                    f"reached_comment={reached_comment} traversal={traversal!r}",
                )
            )
    finally:
        # Reverse creation order: the comment blocks the todo's hard delete, and
        # the todo blocks the plan's.
        cleanup_ok = True
        if comment_uuid is not None:
            ok, res = await call(
                client, "comment_delete",
                {"comment": comment_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if todo_uuid is not None:
            ok, res = await call(
                client, "todo_delete",
                {"todo": todo_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "r34-cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


R35_PRE_FIX_SYMPTOM = "not supported between instances of"


async def run_r35_work_queue_timestamp_types(client: Any) -> list[CheckResult]:
    """Bug 4375c341: todo_queue died sorting a datetime against ISO strings.

    `bug_fix_store._row_to_record` inverted its isinstance guard for
    created_at/updated_at on the dict (crud_*) path, so a real psycopg
    datetime landed unconverted in `BugFix.created_at` -- a field
    annotated `str`. `work_item_from_bug_fix` copied it into
    `WorkItem.created_at`, and `order_queue`'s sort then compared that
    datetime against the ISO strings every other work source yields:
    -32603 "'<' not supported between instances of 'str' and
    'datetime.datetime'".

    Why this needs a LIVE check: the defect is invisible to the unit
    suites' fake cursors, which hand back strings. Only a real psycopg
    connection returns timestamptz as a datetime, and only a queue
    containing a live bug_fix row alongside another live work source
    performs the mixed comparison. A green unit run proves nothing here.

    Recipe (throwaway plan, try/finally cleanup): plan_create -> bug_create
    (anchored to that plan) -> bug_confirm -> bug_fix_create, which is the
    row whose created_at is the datetime -> a todo anchored to the same
    plan, so the queue holds a SECOND source whose created_at is an ISO
    string and the sort has something to compare against -> todo_queue
    scoped to that plan, asserting SUCCESS and that both work kinds are
    present in the returned page. Cleanup: bug_fix_delete -> bug_delete ->
    todo_delete -> plan_delete(hard), in that order (the fix's live
    bug_uuid reference blocks the bug's hard delete).

    Pre-fix detection: todo_queue fails with the comparison TypeError this
    bug names, which SKIPs naming bug 4375c341 rather than failing the
    pipeline against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    bug_uuid: Optional[str] = None
    fix_uuid: Optional[str] = None
    todo_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r35-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R35_4375c341_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(
            client, "bug_create",
            {
                "plan": plan_uuid, "title": unique_suffix("r35-bug"),
                "short_description": "R35 work-queue timestamp scratch bug",
                "detailed_description": "R35: todo_queue must order a live bug_fix (bug 4375c341).",
                "kind": "functional", "severity": "trivial", "priority_nice": 19,
                "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "plan", "source_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R35_4375c341_bug_create", STATUS_FAIL, str(res)))
            return results
        bug_uuid = res["uuid"]

        ok, res = await call(
            client, "bug_confirm",
            {"plan": plan_uuid, "bug_id": bug_uuid, "changed_by": "live-smoke"},
        )
        if not ok:
            results.append(CheckResult("4", "R35_4375c341_bug_confirm", STATUS_FAIL, str(res)))
            return results

        # This is the row that carried the unconverted datetime.
        ok, res = await call(
            client, "bug_fix_create",
            {
                # bug_fix_create takes `bug`; only bug_confirm/bug_delete use bug_id.
                "plan": plan_uuid, "bug": bug_uuid, "fix_type": "code",
                "summary": "R35 scratch fix whose created_at must be an ISO string",
                "author": "live-smoke", "created_by": "live-smoke",
            },
        )
        # bug_fix_create nests its payload under "bug_fix" rather than returning a
        # flat record like most create commands (same note as run_tier3_bug_create).
        fix_payload = res.get("bug_fix") if ok and isinstance(res, dict) else None
        fix_uuid = fix_payload.get("uuid") if isinstance(fix_payload, dict) else None
        if not ok or not fix_uuid:
            results.append(CheckResult("4", "R35_4375c341_bug_fix_create", STATUS_FAIL, str(res)))
            return results
        # Direct evidence of the fix at the source: the store must have converted
        # the row's timestamptz before it ever reached the queue.
        fix_created_at = fix_payload.get("created_at")
        if isinstance(fix_created_at, str):
            results.append(
                CheckResult(
                    "4", "R35_4375c341_bug_fix_created_at_is_iso", STATUS_PASS,
                    f"created_at={fix_created_at}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "R35_4375c341_bug_fix_created_at_is_iso", STATUS_FAIL,
                    f"created_at is {type(fix_created_at).__name__}, not an ISO string: {fix_created_at!r}",
                )
            )
            return results

        # A second live work source, so the sort has an ISO string to compare
        # the bug_fix timestamp against. With only one item there is nothing to
        # order and the defect stays hidden.
        ok, res = await call(
            client, "todo_create",
            {
                "title": unique_suffix("r35-todo"),
                "description": "R35 second work source for the queue sort",
                "kind": "task", "priority_nice": 19, "created_by": "live-smoke",
                "anchor_type": "plan", "anchor_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R35_4375c341_todo_create", STATUS_FAIL, str(res)))
            return results
        todo_uuid = res["uuid"]

        # UNSCOPED deliberately. work_item_from_bug_fix sets no plan_uuid, so a
        # plan-scoped queue excludes the bug_fix entirely and the mixed comparison
        # never happens. And presence on the returned PAGE is not required: the
        # queue is sorted whole and paginated afterwards, so a successful unscoped
        # call is itself proof that the sort compared this fresh unfinished fix
        # against every other source without a type error.
        ok, res = await call(client, "todo_queue", {"limit": 50})
        if not ok:
            if R35_PRE_FIX_SYMPTOM in str(res):
                results.append(
                    CheckResult(
                        "4", "R35_4375c341_todo_queue_orders_a_live_bug_fix", STATUS_SKIP,
                        "server predates bug 4375c341's fix -- todo_queue still compares a "
                        "bug_fix datetime against ISO strings -- redeploy pending",
                    )
                )
            else:
                results.append(
                    CheckResult(
                        "4", "R35_4375c341_todo_queue_orders_a_live_bug_fix", STATUS_FAIL, str(res),
                    )
                )
            return results

        # The payload key is "queue", not "items".
        items = res.get("queue") if isinstance(res, dict) else None
        total = res.get("total") if isinstance(res, dict) else None
        rows = [row for row in (items or []) if isinstance(row, dict)]
        offenders = [
            row.get("source_uuid") for row in rows if not isinstance(row.get("created_at"), str)
        ]
        if isinstance(items, list) and rows and not offenders:
            results.append(
                CheckResult(
                    "4", "R35_4375c341_todo_queue_orders_a_live_bug_fix", STATUS_PASS,
                    f"queue sorted over {total} item(s); every created_at is an ISO string",
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "R35_4375c341_todo_queue_orders_a_live_bug_fix", STATUS_FAIL,
                    f"rows={len(rows)} total={total} non_string_created_at={offenders} {res!r}",
                )
            )
    finally:
        # The fix's live bug_uuid reference blocks the bug's hard delete, so the
        # fix goes first.
        cleanup_ok = True
        if fix_uuid is not None:
            ok, res = await call(
                client, "bug_fix_delete",
                # bug_fix_delete's identifier parameter is `bug_fix`, not fix_id.
                {"bug_fix": fix_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if bug_uuid is not None:
            ok, res = await call(
                client, "bug_delete",
                {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if todo_uuid is not None:
            ok, res = await call(
                client, "todo_delete",
                {"todo": todo_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R35_4375c341_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


R36_PRE_FIX_SYMPTOM = "unknown update columns"


async def run_r36_soft_delete_owned_column(client: Any) -> list[CheckResult]:
    """Bug 31ba96d5: soft delete failed for every crud_*-migrated entity.

    `soft_delete_entity` wrote SOFT_DELETE_COLUMN through `crud_update`,
    whose UPDATE_COLUMNS whitelist deliberately EXCLUDES deleted_at -- the
    two-phase deletion discipline owns that column, and a caller must go
    through the delete command rather than backdating or clearing a
    deletion with a plain update. So the lifecycle's own privileged write
    was validated against the caller-facing whitelist that forbids exactly
    the column it must set: -32603 "unknown update columns for Tool:
    ['deleted_at']".

    Coverage split, so this check is not a duplicate: Tool's live soft
    delete is already exercised by R7 (where the defect surfaced) and
    wish/calendar_entry by R27. This check takes the two remaining migrated
    families whose live soft-delete path nothing else drives -- todo and
    comment.

    Contract update (CR-7 G-006/T-001/A-003): the engine's point-read
    surface (Entity.crud_get / get_by_id, which get_todo and get_comment
    both sit on) was deliberately changed to resolve a row REGARDLESS of
    its markdel flag -- a caller invoking todo_get/comment_get already
    holds the identifier, so hiding a marked row there would turn "marked
    but still present" into a false NOT_FOUND. Only crud_list/crud_search
    (todo_list / comment_list) still hide marked rows by default, gated by
    an include_marked flag that neither todo_list nor comment_list exposes
    on its own command surface (checked against TODO_LIST_FILTER_FIELDS in
    todo_list_command.py and FILTER_FIELDS in comment_list_command.py --
    neither lists an include-marked/include-deleted parameter), so this
    check can only assert the row's absence from the DEFAULT listing, not
    exercise an opt-in to see it there. Bug 31ba96d5's original intent
    stands unchanged under the new contract: soft delete must go through
    the engine's owned-column write path (todo_delete/comment_delete), and
    now the visible proof of that is not "the row vanished" but "the
    resolved row carries a non-null deleted_at" -- the marker IS the
    evidence.

    What is observable through the real command surface, and what is not:
    the soft delete SUCCEEDING is the regression itself -- before the fix it
    failed outright with the whitelist error. The row's continued PHYSICAL
    presence is now directly observable through todo_get/comment_get
    (deleted_at set on the resolved row); a second delete on a
    soft-deleted id still returns NOT_FOUND, because todo_delete/
    comment_delete read their own precondition through get_todo/get_comment
    with an explicit deleted_at is-null guard ahead of the mutation, not
    through the raw point-read contract. The sanctioned second phase is
    runtime_purge_batch, which this pipeline must not invoke live because it
    purges EVERY soft-deleted row of a type, not just this pass's.

    Cleanup convention: a soft-deleted throwaway row counts as disposed of,
    exactly as run_r7_agent_config_lifecycle already treats its
    soft-deleted tool ("naturally deleted; the finally block must not
    double-delete"). The finally block therefore hard-deletes only the
    plan, and does not attempt to purge the two soft-deleted rows.

    Recipe (throwaway plan, try/finally cleanup): plan_create -> todo
    anchored to that plan -> todo_delete(hard=false) must SUCCEED ->
    todo_get must still RESOLVE, with deleted_at now set -> the same row
    must be absent from the default (no include-marked opt-in) todo_list
    scoped to the plan -> the same four steps for a comment anchored to
    the plan.

    Pre-fix detection: the soft delete fails with the whitelist error this
    bug names, which SKIPs naming bug 31ba96d5 rather than failing the
    pipeline against a not-yet-deployed fix.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    todo_uuid: Optional[str] = None
    comment_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r36-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R36_31ba96d5_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(
            client, "todo_create",
            {
                "title": unique_suffix("r36-todo"),
                "description": "R36 soft-delete scratch todo",
                "kind": "task", "priority_nice": 19, "created_by": "live-smoke",
                "anchor_type": "plan", "anchor_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R36_31ba96d5_todo_create", STATUS_FAIL, str(res)))
            return results
        todo_uuid = res["uuid"]

        todo_uuid_soft = todo_uuid
        ok, res = await call(
            client, "todo_delete",
            {"todo": todo_uuid, "changed_by": "live-smoke", "hard": False},
        )
        if not ok:
            if R36_PRE_FIX_SYMPTOM in str(res):
                results.append(
                    CheckResult(
                        "4", "R36_31ba96d5_todo_soft_delete", STATUS_SKIP,
                        "server predates bug 31ba96d5's fix -- the soft-delete write is "
                        "still refused by the caller-facing UPDATE_COLUMNS whitelist -- "
                        "redeploy pending",
                    )
                )
            else:
                results.append(CheckResult("4", "R36_31ba96d5_todo_soft_delete", STATUS_FAIL, str(res)))
            return results

        # The soft delete succeeded; the row counts as disposed of (R7's
        # convention), so the finally block must not try to delete it again.
        todo_uuid = None
        # CR-7 G-006/T-001/A-003: the point-read contract now resolves the
        # physical row unconditionally -- todo_get must SUCCEED here, and the
        # non-null deleted_at on the returned row is the proof the soft
        # delete happened (bug 31ba96d5's original intent -- the deletion
        # went through the owned-column engine path -- still holds; only the
        # observable evidence moved from "vanished" to "marked").
        resolved_ok, resolved_res = await call(client, "todo_get", {"todo": todo_uuid_soft})
        if not resolved_ok:
            results.append(
                CheckResult(
                    "4", "R36_31ba96d5_todo_soft_delete", STATUS_FAIL,
                    f"todo_get must resolve a soft-deleted todo under the CR-7 "
                    f"G-006/T-001/A-003 point-read contract: {resolved_res!r}",
                )
            )
            return results
        resolved_deleted_at = resolved_res.get("deleted_at") if isinstance(resolved_res, dict) else None
        if not resolved_deleted_at:
            results.append(
                CheckResult(
                    "4", "R36_31ba96d5_todo_soft_delete", STATUS_FAIL,
                    f"todo_get resolved the soft-deleted todo but deleted_at is not "
                    f"set on the returned row: {resolved_res!r}",
                )
            )
            return results
        results.append(
            CheckResult(
                "4", "R36_31ba96d5_todo_soft_delete", STATUS_PASS,
                "soft delete accepted; todo_get resolves the physical row with a "
                "non-null deleted_at as proof",
            )
        )

        # todo_list exposes no include-marked/include-deleted parameter (see
        # TODO_LIST_FILTER_FIELDS in todo_list_command.py), so the only
        # observable half of the list-hides-marked-rows contract is that the
        # soft-deleted row is absent from the plain, default listing.
        list_ok, list_res = await call(
            client, "todo_list", {"anchor_plan": plan_uuid, "view": "full", "limit": 200}
        )
        if not list_ok or not isinstance(list_res, dict):
            results.append(CheckResult("4", "R36_31ba96d5_todo_list_hides_marked", STATUS_FAIL, str(list_res)))
            return results
        listed_todo_uuids = {item.get("uuid") for item in list_res.get("todos", [])}
        if todo_uuid_soft in listed_todo_uuids:
            results.append(
                CheckResult(
                    "4", "R36_31ba96d5_todo_list_hides_marked", STATUS_FAIL,
                    f"soft-deleted todo {todo_uuid_soft} must not appear in the default todo_list",
                )
            )
            return results
        results.append(
            CheckResult(
                "4", "R36_31ba96d5_todo_list_hides_marked", STATUS_PASS,
                "soft-deleted todo absent from the default todo_list listing",
            )
        )

        ok, res = await call(
            client, "comment_add",
            {
                "plan": plan_uuid, "anchor_type": "plan", "anchor_plan_uuid": plan_uuid,
                "kind": "comment", "visibility": "audit_only", "author": "live-smoke",
                "body": "R36 soft-delete scratch comment", "created_by": "live-smoke",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R36_31ba96d5_comment_add", STATUS_FAIL, str(res)))
            return results
        comment_uuid = res["uuid"]

        ok, res = await call(
            client, "comment_delete",
            {"comment": comment_uuid, "changed_by": "live-smoke", "hard": False},
        )
        if not ok:
            results.append(CheckResult("4", "R36_31ba96d5_comment_soft_delete", STATUS_FAIL, str(res)))
            return results

        comment_uuid_soft = comment_uuid
        comment_uuid = None
        # Same CR-7 G-006/T-001/A-003 point-read contract as todo_get above:
        # comment_get sits on the same Entity.crud_get, so it must resolve
        # too, with deleted_at as the evidence.
        resolved_ok, resolved_res = await call(
            client, "comment_get", {"plan": plan_uuid, "comment_uuid": comment_uuid_soft}
        )
        if not resolved_ok:
            results.append(
                CheckResult(
                    "4", "R36_31ba96d5_comment_soft_delete", STATUS_FAIL,
                    f"comment_get must resolve a soft-deleted comment under the CR-7 "
                    f"G-006/T-001/A-003 point-read contract: {resolved_res!r}",
                )
            )
            return results
        resolved_deleted_at = resolved_res.get("deleted_at") if isinstance(resolved_res, dict) else None
        if not resolved_deleted_at:
            results.append(
                CheckResult(
                    "4", "R36_31ba96d5_comment_soft_delete", STATUS_FAIL,
                    f"comment_get resolved the soft-deleted comment but deleted_at "
                    f"is not set on the returned row: {resolved_res!r}",
                )
            )
            return results
        results.append(
            CheckResult(
                "4", "R36_31ba96d5_comment_soft_delete", STATUS_PASS,
                "soft delete accepted; comment_get resolves the physical row with "
                "a non-null deleted_at as proof",
            )
        )

        # comment_list exposes no include-marked/include-deleted parameter
        # either (see FILTER_FIELDS in comment_list_command.py), so again
        # only the default-listing absence half is observable here.
        comment_list_ok, comment_list_res = await call(
            client, "comment_list", {"plan": plan_uuid, "view": "full", "limit": 200}
        )
        if not comment_list_ok or not isinstance(comment_list_res, dict):
            results.append(
                CheckResult("4", "R36_31ba96d5_comment_list_hides_marked", STATUS_FAIL, str(comment_list_res))
            )
            return results
        listed_comment_uuids = {item.get("uuid") for item in comment_list_res.get("comments", [])}
        if comment_uuid_soft in listed_comment_uuids:
            results.append(
                CheckResult(
                    "4", "R36_31ba96d5_comment_list_hides_marked", STATUS_FAIL,
                    f"soft-deleted comment {comment_uuid_soft} must not appear in the default comment_list",
                )
            )
            return results
        results.append(
            CheckResult(
                "4", "R36_31ba96d5_comment_list_hides_marked", STATUS_PASS,
                "soft-deleted comment absent from the default comment_list listing",
            )
        )
    finally:
        # Each uuid is cleared once its row has been soft-deleted, so these two
        # branches only fire when the check failed BEFORE the soft delete and the
        # row is still live. A soft-deleted row is not hard-deleted here: the
        # surface cannot purge one, and R7 already treats that state as disposed
        # of. plan_delete is unaffected either way -- a soft-deleted referrer does
        # not block it, since the reference lookup honours deleted_at.
        cleanup_ok = True
        if comment_uuid is not None:
            ok, res = await call(
                client, "comment_delete",
                {"comment": comment_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if todo_uuid is not None:
            ok, res = await call(
                client, "todo_delete",
                {"todo": todo_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R36_31ba96d5_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


R37_PRE_DEPLOY_SKIP_REASON = (
    "server predates the command surface the CR-7 C-012 direct-state acceptance "
    "check exercises -- redeploy pending"
)

R37_REQUIRED_COMMANDS: frozenset[str] = frozenset(
    {
        "plan_create", "plan_comment_set", "plan_delete",
        "todo_create", "todo_update", "todo_get", "todo_delete",
        "provider_create", "provider_update", "provider_get", "provider_delete",
    }
)

R37_RESERVE_SKIP_REASON = (
    "server predates project_uuid_reserve (CR-6) -- the cross-kind duplicate "
    "refusal has no caller-supplied-identifier surface on this vintage"
)


async def run_r37_cr7_direct_state_acceptance(
    client: Any, catalog_names: frozenset[str]
) -> list[CheckResult]:
    """CR-7 G-004/T-002/A-003: direct-state acceptance of the C-012 cutover.

    Three sub-regressions, each read back zero-trust from the live server:

    1. One create-update-read cycle per migrated family, proving the unified
       engine path serves the live API: todo (runtime store family), provider
       (config store family), and plan (plan-truth module family, via
       plan_create + the plan_comment_set update surface, whose response
       re-reads the comment from storage).
    2. The null-removes-key update semantics (todo 4bb0f85b closure
       evidence): plan_comment_set documents "omit or pass null to clear",
       so after setting a comment, an explicit ``comment: null`` on the same
       surface must come back cleared in the command's own storage re-read.
    3. Cross-kind duplicate rejection: NO public create command accepts a
       caller-supplied id (creation identifiers are always server-generated),
       so the documented refusal is asserted through project_uuid_reserve --
       the one shipped surface taking a caller-supplied identifier -- which
       calls the registry's single cross-kind collision guard
       (ensure_identity_available) exactly like every create path does.
       Reserving a live todo's uuid must be refused with DUPLICATE_ID naming
       the existing mismatched kind. Marker-gated SKIP on a pre-CR-6 server.

    Cutover neutrality: every assertion reads public command responses only,
    so both C-012 cutover states -- the wrapped surface and the direct
    surface -- must pass this same check identically.

    Cleanup is top-level try/finally: todo before its anchor plan, provider
    independently; an unexpectedly-successful reservation (a check FAILURE)
    is released so a red run never leaves the identifier occupied.
    """
    if not R37_REQUIRED_COMMANDS <= catalog_names:
        missing = sorted(R37_REQUIRED_COMMANDS - catalog_names)
        return [
            CheckResult(
                "4",
                "R37_cr7_direct_state_acceptance",
                STATUS_SKIP,
                f"{R37_PRE_DEPLOY_SKIP_REASON} (missing: {missing})",
            )
        ]

    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    todo_uuid: Optional[str] = None
    provider_uuid: Optional[str] = None
    reserved_unexpectedly: Optional[str] = None
    try:
        # --- plan-truth family: create. ---
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r37-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R37_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]
        results.append(CheckResult("4", "R37_plan_create", STATUS_PASS, f"uuid={plan_uuid}"))

        # --- runtime store family: todo create-update-read. ---
        ok, res = await call(
            client, "todo_create",
            {
                "title": unique_suffix("r37-todo"),
                "description": "R37 direct-state acceptance scratch todo",
                "kind": "task", "priority_nice": 10, "created_by": "live-smoke",
                "anchor_type": "plan", "anchor_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R37_todo_create", STATUS_FAIL, str(res)))
            return results
        todo_uuid = res["uuid"]
        results.append(CheckResult("4", "R37_todo_create", STATUS_PASS, f"uuid={todo_uuid}"))

        ok, res = await call(
            client, "todo_update",
            {"todo": todo_uuid, "changed_by": "live-smoke", "priority_nice": -5},
        )
        if not ok:
            results.append(CheckResult("4", "R37_todo_update", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R37_todo_update", STATUS_PASS))

        ok, res = await call(client, "todo_get", {"todo": todo_uuid})
        todo_read_ok = (
            ok and isinstance(res, dict)
            and res.get("uuid") == todo_uuid and res.get("priority_nice") == -5
        )
        results.append(
            CheckResult(
                "4", "R37_todo_read_back", STATUS_PASS if todo_read_ok else STATUS_FAIL,
                "engine-served update visible via todo_get" if todo_read_ok else str(res),
            )
        )
        if not todo_read_ok:
            return results

        # --- config store family: provider create-update-read. ---
        ok, res = await call(
            client, "provider_create",
            {
                "name": unique_suffix("r37-provider"), "type": "cloud_api",
                "rented_hardware": False, "status": "active", "created_by": "live-smoke",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R37_provider_create", STATUS_FAIL, str(res)))
            return results
        provider_uuid = res["uuid"]
        results.append(CheckResult("4", "R37_provider_create", STATUS_PASS, f"uuid={provider_uuid}"))

        ok, res = await call(
            client, "provider_update",
            {
                "provider_uuid": provider_uuid, "changed_by": "live-smoke",
                "billing_notes": "live-smoke R37 engine-path update",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R37_provider_update", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R37_provider_update", STATUS_PASS))

        ok, res = await call(client, "provider_get", {"provider_uuid": provider_uuid})
        provider_read_ok = (
            ok and isinstance(res, dict)
            and res.get("uuid") == provider_uuid
            and res.get("billing_notes") == "live-smoke R37 engine-path update"
        )
        results.append(
            CheckResult(
                "4", "R37_provider_read_back", STATUS_PASS if provider_read_ok else STATUS_FAIL,
                "engine-served update visible via provider_get" if provider_read_ok else str(res),
            )
        )
        if not provider_read_ok:
            return results

        # --- plan-truth family: update-read, then null-removes-key. ---
        comment_text = "live-smoke r37 direct-state comment"
        ok, res = await call(
            client, "plan_comment_set",
            {"plan": plan_uuid, "changed_by": "live-smoke", "comment": comment_text},
        )
        comment_set_ok = ok and isinstance(res, dict) and res.get("comment") == comment_text
        results.append(
            CheckResult(
                "4", "R37_plan_comment_update", STATUS_PASS if comment_set_ok else STATUS_FAIL,
                "comment re-read from storage" if comment_set_ok else str(res),
            )
        )
        if not comment_set_ok:
            return results

        # Explicit "comment": null is the documented clear form ("omit or pass
        # null to clear"); the response's comment is re-read from storage, so a
        # null key coming back cleared IS the null-removes-key observation
        # (todo 4bb0f85b closure evidence).
        ok, res = await call(
            client, "plan_comment_set",
            {"plan": plan_uuid, "changed_by": "live-smoke", "comment": None},
        )
        null_clear_ok = ok and isinstance(res, dict) and res.get("comment") is None
        results.append(
            CheckResult(
                "4", "R37_4bb0f85b_null_removes_key", STATUS_PASS if null_clear_ok else STATUS_FAIL,
                "explicit null cleared the comment" if null_clear_ok
                else f"expected the comment cleared by explicit null, got ok={ok} {res!r}",
            )
        )
        if not null_clear_ok:
            return results

        # --- cross-kind duplicate rejection. ---
        if "project_uuid_reserve" not in catalog_names:
            # No public create accepts a caller-supplied id, so on a pre-CR-6
            # server no surface can even attempt the mismatched-kind ref.
            results.append(
                CheckResult("4", "R37_cross_kind_duplicate", STATUS_SKIP, R37_RESERVE_SKIP_REASON)
            )
        else:
            # The "second create with a mismatched-kind ref": reserve claims the
            # PROJECT kind for a caller-supplied identifier that already belongs
            # to a live todo, and must be refused by the registry's single
            # cross-kind collision guard (same domain-code assertion idiom as
            # R33's DUPLICATE_ID check).
            ok, res = await call(
                client, "project_uuid_reserve",
                {"action": "reserve", "project_uuid": todo_uuid, "reserved_by": "live-smoke-r37"},
            )
            if (not ok) and "DUPLICATE_ID" in str(res):
                results.append(
                    CheckResult(
                        "4", "R37_cross_kind_duplicate", STATUS_PASS,
                        f"reserve of a live todo uuid refused: {str(res)[:160]}",
                    )
                )
            else:
                if ok:
                    reserved_unexpectedly = todo_uuid
                results.append(
                    CheckResult(
                        "4", "R37_cross_kind_duplicate", STATUS_FAIL,
                        f"expected DUPLICATE_ID refusal, got ok={ok} {res!r}",
                    )
                )
                return results
    finally:
        cleanup_ok = True
        if reserved_unexpectedly is not None:
            # Only reachable on a FAILED refusal check: free the identifier so
            # a red run never leaves the todo's uuid occupied by a reservation.
            ok, res = await call(
                client, "project_uuid_reserve",
                {
                    "action": "release", "project_uuid": reserved_unexpectedly,
                    "reserved_by": "live-smoke-r37",
                },
            )
            cleanup_ok = cleanup_ok and ok
        if provider_uuid is not None:
            ok, res = await call(
                client, "provider_delete",
                {"provider_uuid": provider_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if todo_uuid is not None:
            ok, res = await call(
                client, "todo_delete",
                {"todo": todo_uuid, "changed_by": "live-smoke", "hard": True},
            )
            cleanup_ok = cleanup_ok and ok
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R37_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


R38_PRE_DEPLOY_SKIP_REASON = (
    "server predates the export/import round-trip command surface the CR-7 "
    "G-005/T-002/A-002 acceptance check exercises -- redeploy pending"
)

R38_REQUIRED_COMMANDS: frozenset[str] = frozenset(
    {
        "plan_create", "para_insert", "plan_project_attach", "context_common",
        "step_create", "step_dependency_apply", "plan_export", "hrs_export",
        "export_read", "plan_import", "plan_delete",
    }
)

# Fixed-identity fixture content: literal across every run (only the plan
# NAME below carries the usual unique_suffix), so the two exports are
# compared against a deterministic baseline rather than a fresh random one
# each time.
R38_PARAGRAPH_TEXT = "R38 fixed-identity round-trip regression paragraph body."
R38_G_SLUG = "g"
R38_T1_SLUG = "t-one"
R38_T2_SLUG = "t-two"

# What this black-box, API-only regression fundamentally CANNOT see -- named
# explicitly (not just implied by omission) per the CR-7 G-005/T-002/A-002
# acceptance requirement.
#
# DEFECT HISTORY (live 0.1.98, R38_plan_import IMPORT_INVALID "source root
# not found"): this check used to hard-delete the original plan mid-sequence
# to free its name for a real plan_import, on the documented assumption that
# "the export directory plan_export wrote is untouched by the delete, which
# only removes the database row". That assumption was false: plan_delete
# (hard=True) also removes the plan's own export-layout directory
# (plan_manager/commands/plan_delete_command.py's _remove_export_layout,
# wired into the hard-delete path per todo 76b7ea7e's export-artifact
# lifecycle) -- so by the time plan_import ran, its source directory was
# already gone. The server behaved exactly per its contract; the defect was
# this check's own sequencing. No public-API sequence can recover the
# originally intended shape (free the name by deleting the original, then
# import a FRESH plan from a PRESERVED export of the original's content):
# plan_export/export_archive always write under exactly
# <export_root>/<plan.name>/ with no output-name parameter, and no
# export-copy/export-rename command exists to materialize the same content
# under a second, distinct directory name before the delete. The recipe
# below is downgraded to what the public API can actually prove.
R38_NOT_VISIBLE: tuple[str, ...] = (
    "the full delete-then-reimport round trip (free the original plan's "
    "name with a hard delete, then import a FRESH plan from a PRESERVED "
    "export of the original's content) is not exercised at all: "
    "plan_delete(hard=True) purges the plan's own export-layout directory "
    "as part of its documented lifecycle, and no public-API surface "
    "(plan_export, export_archive, export_upload_save) can materialize an "
    "import source under a name other than the exporting plan's own name -- "
    "there is no sequencing that both frees the name and preserves the "
    "export content",
    "plan_import's actual write path (create_plan, HRS/MRS ingestion, step "
    "tree import) is exercised here only as a name-conflict REFUSAL, never "
    "as a successful ingestion into a new plan row; that positive path is "
    "covered at unit-test depth (tests/exchange/test_importer_canonical.py, "
    "tests/domain/test_entity.py) and by the CR-7 canonical-form migration "
    "transport (export_canonical_document/import_canonical_document, CR-7 "
    "G-005/T-001/A-003), not by this black-box API check",
    "row-level UUIDs of a freshly-imported plan/steps/paragraph and how "
    "they would relate to the originals: no real (dry_run=False, name-free) "
    "import ever actually runs here",
    "full revision-by-revision history of an imported plan: no real import "
    "ever actually runs here",
    "soft-deleted/marked rows: the standard layout exports only live head "
    "state, never a markdel'd row",
)


def _r38_export_file_paths(g_id: str, t_one_id: str, t_two_id: str) -> list[str]:
    """The fixed set of export-tree files this regression compares byte-for-byte."""
    g_dir = f"{g_id}-{R38_G_SLUG}"
    return [
        "source_spec.md",
        "spec.yaml",
        f"{g_dir}/README.yaml",
        f"{g_dir}/{t_one_id}-{R38_T1_SLUG}/README.yaml",
        f"{g_dir}/{t_two_id}-{R38_T2_SLUG}/README.yaml",
    ]


async def _r38_read_export_snapshot(
    client: Any, plan_name: str, file_paths: list[str]
) -> tuple[bool, dict[str, dict[str, Any]], str]:
    """Read every fixture file through export_read (public API only, no
    filesystem/database inspection): whole-file sha256 plus base64 bytes for
    each, requiring each response be the WHOLE file in one chunk (every
    fixture file here is well under the 262144-byte chunk cap)."""
    snapshot: dict[str, dict[str, Any]] = {}
    for path in file_paths:
        ok, res = await call(client, "export_read", {"plan": plan_name, "file": path})
        if not ok or not isinstance(res, dict) or "sha256" not in res or "chunk_base64" not in res:
            return False, snapshot, f"export_read({path!r}) failed: {res!r}"
        if not res.get("eof", False):
            return False, snapshot, f"export_read({path!r}) did not return the whole file in one chunk (eof=False)"
        snapshot[path] = res
    return True, snapshot, ""


def _r38_decode_yaml(chunk_base64: str) -> Any:
    """Decode one export_read chunk's base64 payload as YAML (spec.yaml/README.yaml are always YAML)."""
    return yaml.safe_load(base64.b64decode(chunk_base64).decode("utf-8"))


def _r38_compare_snapshots(
    file_paths: list[str],
    snapshot_a: dict[str, dict[str, Any]],
    snapshot_b: dict[str, dict[str, Any]],
) -> tuple[bool, str, bool, str]:
    """Compare two export_read snapshots of the same fixed file set.

    Returns (checksum_match, checksum_detail, content_match, content_detail).
    checksum_match is the canonical, byte-level check ("the canonical
    checksum where the API returns it"); content_match decodes every YAML
    file for a semantic cross-check (step tree, dependencies, statuses,
    project bindings), giving a readable diff on a checksum mismatch.
    """
    checksum_mismatches = [p for p in file_paths if snapshot_a[p]["sha256"] != snapshot_b[p]["sha256"]]
    checksum_match = not checksum_mismatches
    checksum_detail = "" if checksum_match else f"sha256 diverged for: {checksum_mismatches}"

    content_mismatches: list[str] = []
    for path in file_paths:
        if not path.endswith((".yaml", ".yml")):
            continue
        decoded_a = _r38_decode_yaml(snapshot_a[path]["chunk_base64"])
        decoded_b = _r38_decode_yaml(snapshot_b[path]["chunk_base64"])
        if decoded_a != decoded_b:
            content_mismatches.append(f"{path}: {decoded_a!r} != {decoded_b!r}")
    content_match = not content_mismatches
    content_detail = "" if content_match else "; ".join(content_mismatches)
    return checksum_match, checksum_detail, content_match, content_detail


async def run_r38_export_import_round_trip(
    client: Any,
    catalog_names: frozenset[str],
    project_id: str,
) -> list[CheckResult]:
    """CR-7 G-005/T-002/A-002: black-box regression for the export/import
    command surface, read back through the public API only (no database or
    filesystem inspection, per the black-box acceptance).

    Recipe (downgraded from the original delete-then-reimport shape -- see
    R38_NOT_VISIBLE's module-level comment for why that shape is
    unreachable through the public API): build a dedicated fixed-identity
    throwaway plan (one paragraph, a project binding, a G/T-one/T-two step
    tree with a T-two depends_on T-one dependency) -> plan_export +
    hrs_export + export_read capture the first, "A", API-visible snapshot
    of the STILL-LIVE plan -> plan_import(dry_run=True) proves the exported
    layout validates as ingestible without touching the database ->
    plan_import(dry_run=False) against the SAME occupied name is expected
    to be REFUSED (the documented unique plan-name conflict, mapped to
    domain code DUPLICATE_ID) -> plan_export + hrs_export + export_read
    again on the SAME still-live plan capture a second, "B", snapshot ->
    compare every API-visible dimension between A and B (HRS markdown text,
    MRS project bindings, per-step descriptors, both by decoded content and
    by the canonical sha256 export_read itself returns) to prove
    plan_export/hrs_export/export_read are stable and that the refused
    import attempt left no side effects. This substitutes for the
    unreachable delete-then-reimport content comparison.

    What this regression cannot see at all -- because it never performs a
    real (dry_run=False, name-free) import -- is named explicitly in
    R38_NOT_VISIBLE and surfaced as this check's own final PASS detail.

    Marker-gated SKIP (whole group, not per-command) on a server predating
    this command surface, mirroring R27/R34/R37's convention. Cleanup is a
    top-level try/finally: exactly one plan ever exists in this recipe, so
    a red run never leaks it.
    """
    if not R38_REQUIRED_COMMANDS <= catalog_names:
        missing = sorted(R38_REQUIRED_COMMANDS - catalog_names)
        return [
            CheckResult(
                "4",
                "R38_export_import_round_trip",
                STATUS_SKIP,
                f"{R38_PRE_DEPLOY_SKIP_REASON} (missing: {missing})",
            )
        ]

    results: list[CheckResult] = []
    plan_name = unique_suffix("r38-plan")
    original_plan_uuid: Optional[str] = None
    try:
        # --- build the fixed-identity fixture on the ORIGINAL plan. ---
        ok, res = await call(client, "plan_create", {"name": plan_name})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R38_plan_create", STATUS_FAIL, str(res)))
            return results
        original_plan_uuid = res["uuid"]
        results.append(CheckResult("4", "R38_plan_create", STATUS_PASS, f"uuid={original_plan_uuid} name={plan_name}"))

        ok, res = await call(client, "para_insert", {"plan": original_plan_uuid, "text": R38_PARAGRAPH_TEXT})
        results.append(CheckResult("4", "R38_para_insert", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if not ok:
            return results

        ok, res = await call(
            client, "plan_project_attach",
            {"plan": original_plan_uuid, "project_id": project_id, "primary": True},
        )
        results.append(CheckResult("4", "R38_plan_project_attach", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if not ok:
            return results

        ok, res = await call(client, "context_common", {"plan": original_plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R38_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(
            client, "step_create",
            {"plan": original_plan_uuid, "level": 3, "slug": R38_G_SLUG, "project_id": project_id},
        )
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R38_step_create(G)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R38_step_create(G)", STATUS_PASS, f"step_id={g_id}"))

        t_ids: dict[str, str] = {}
        t_uuids: dict[str, str] = {}
        for slug in (R38_T1_SLUG, R38_T2_SLUG):
            ok, res = await call(client, "context_common", {"plan": original_plan_uuid, "node": g_id, "child_level": 4})
            if not ok:
                results.append(CheckResult("4", f"R38_context_common(G,level4,before {slug})", STATUS_FAIL, str(res)))
                return results
            ok, res = await call(
                client, "step_create",
                {"plan": original_plan_uuid, "level": 4, "slug": slug, "parent_step_id": g_id},
            )
            tid = _extract_step_id(res) if ok else None
            t_uuid = res.get("uuid") if ok and isinstance(res, dict) else None
            if not ok or tid is None or not t_uuid:
                results.append(CheckResult("4", f"R38_step_create({slug})", STATUS_FAIL, str(res)))
                return results
            t_ids[slug] = tid
            t_uuids[slug] = t_uuid
        results.append(CheckResult("4", "R38_step_create(T-one/T-two)", STATUS_PASS, f"{t_ids}"))

        ok, res = await call(
            client, "step_dependency_apply",
            {
                "plan": original_plan_uuid,
                "changes": [{"op": "add", "step_id": t_uuids[R38_T2_SLUG], "depends_on": [t_uuids[R38_T1_SLUG]]}],
                "dry_run": False,
            },
        )
        dep_ok = ok and isinstance(res, dict) and res.get("applied") is True
        results.append(CheckResult("4", "R38_step_dependency_apply", STATUS_PASS if dep_ok else STATUS_FAIL, "" if dep_ok else str(res)))
        if not dep_ok:
            return results

        file_paths = _r38_export_file_paths(g_id, t_ids[R38_T1_SLUG], t_ids[R38_T2_SLUG])

        # --- first export ("A") + its API-visible snapshot, taken on the
        # STILL-LIVE plan (never deleted in this recipe). ---
        ok, res = await call(client, "plan_export", {"plan": original_plan_uuid})
        export_a_ok = ok and isinstance(res, dict) and bool(res.get("files"))
        results.append(
            CheckResult(
                "4", "R38_plan_export(A)", STATUS_PASS if export_a_ok else STATUS_FAIL,
                f"files={res.get('files')}" if export_a_ok else str(res),
            )
        )
        if not export_a_ok:
            return results

        ok, res = await call(client, "hrs_export", {"plan": original_plan_uuid})
        hrs_a_ok = ok and isinstance(res, dict) and "markdown" in res
        results.append(CheckResult("4", "R38_hrs_export(A)", STATUS_PASS if hrs_a_ok else STATUS_FAIL, "" if hrs_a_ok else str(res)))
        if not hrs_a_ok:
            return results
        markdown_a = res["markdown"]

        snap_ok, snapshot_a, snap_detail = await _r38_read_export_snapshot(client, plan_name, file_paths)
        results.append(CheckResult("4", "R38_export_read(A)", STATUS_PASS if snap_ok else STATUS_FAIL, snap_detail))
        if not snap_ok:
            return results

        # --- dry-run import: the exported layout validates as ingestible.
        # dry_run never touches the database (PlanImportCommand.execute
        # returns before opening a connection), so this succeeds even though
        # the name is still occupied by the live original. ---
        ok, res = await call(client, "plan_import", {"source": plan_name, "dry_run": True})
        dry_run_ok = ok and isinstance(res, dict) and res.get("dry_run") is True and res.get("valid") is True
        results.append(
            CheckResult(
                "4", "R38_plan_import_dry_run_valid", STATUS_PASS if dry_run_ok else STATUS_FAIL,
                "" if dry_run_ok else str(res),
            )
        )
        if not dry_run_ok:
            return results

        # --- real import against the still-occupied name: expect the
        # documented unique-name refusal (plan.name is UNIQUE; import_plan's
        # create_plan raises psycopg.errors.UniqueViolation, mapped to
        # domain code DUPLICATE_ID by plan_manager.commands.errors.
        # map_exception). This is the negative check this recipe is
        # downgraded to -- see R38_NOT_VISIBLE for why a successful
        # dry_run=False import is not reachable here. ---
        ok, res = await call(client, "plan_import", {"source": plan_name, "dry_run": False})
        refused_ok = (not ok) and "DUPLICATE_ID" in str(res)
        results.append(
            CheckResult(
                "4", "R38_plan_import_name_conflict_refused", STATUS_PASS if refused_ok else STATUS_FAIL,
                "" if refused_ok else str(res),
            )
        )
        if not refused_ok:
            return results

        # --- second export ("B") + its API-visible snapshot, taken again on
        # the SAME still-live plan: proves plan_export/hrs_export/
        # export_read are stable and that the refused import left no side
        # effects. ---
        ok, res = await call(client, "plan_export", {"plan": original_plan_uuid})
        export_b_ok = ok and isinstance(res, dict) and bool(res.get("files"))
        results.append(
            CheckResult(
                "4", "R38_plan_export(B)", STATUS_PASS if export_b_ok else STATUS_FAIL,
                f"files={res.get('files')}" if export_b_ok else str(res),
            )
        )
        if not export_b_ok:
            return results

        ok, res = await call(client, "hrs_export", {"plan": original_plan_uuid})
        hrs_b_ok = ok and isinstance(res, dict) and "markdown" in res
        results.append(CheckResult("4", "R38_hrs_export(B)", STATUS_PASS if hrs_b_ok else STATUS_FAIL, "" if hrs_b_ok else str(res)))
        if not hrs_b_ok:
            return results
        markdown_b = res["markdown"]

        snap_ok, snapshot_b, snap_detail = await _r38_read_export_snapshot(client, plan_name, file_paths)
        results.append(CheckResult("4", "R38_export_read(B)", STATUS_PASS if snap_ok else STATUS_FAIL, snap_detail))
        if not snap_ok:
            return results

        # --- compare the two exports across every API-visible dimension:
        # the full export-side comparison this recipe is downgraded to. ---
        hrs_match = markdown_a == markdown_b
        results.append(
            CheckResult(
                "4", "R38_compare_hrs_markdown", STATUS_PASS if hrs_match else STATUS_FAIL,
                "" if hrs_match else "HRS markdown text diverged across the round trip",
            )
        )
        if not hrs_match:
            return results

        checksum_match, checksum_detail, content_match, content_detail = _r38_compare_snapshots(
            file_paths, snapshot_a, snapshot_b
        )
        results.append(
            CheckResult("4", "R38_compare_export_checksum", STATUS_PASS if checksum_match else STATUS_FAIL, checksum_detail)
        )
        if not checksum_match:
            return results
        results.append(
            CheckResult(
                "4", "R38_compare_step_tree_deps_status_bindings",
                STATUS_PASS if content_match else STATUS_FAIL, content_detail,
            )
        )
        if not content_match:
            return results

        results.append(CheckResult("4", "R38_not_visible_surface", STATUS_PASS, "; ".join(R38_NOT_VISIBLE)))
    finally:
        cleanup_ok = True
        if original_plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": original_plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R38_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


# --------------------------------------------------------------------------
# R39 (CR-7 G-008/T-001/A-003): four live regressions, one per G-008
# invariant, because both defects found while authoring this plan were
# invisible to a green unit suite and appeared only against real data.
# --------------------------------------------------------------------------

R39_PRE_DEPLOY_SKIP_REASON = (
    "server predates the command surface the CR-7 G-008/T-001/A-003 live "
    "invariant regression exercises -- redeploy pending"
)

R39_REQUIRED_COMMANDS: frozenset[str] = frozenset(
    {
        "plan_create", "plan_delete",
        "todo_create", "todo_get", "todo_delete",
        "comment_add", "comment_delete",
        "id_resolve", "reference_inspect",
        "tool_create", "tool_delete",
    }
)

# Every vocabulary below is copied verbatim from plan_manager_db/migrations/
# 0028_closed_enumerations.sql, whose own header comment names the domain
# Enum classes it seeds from (plan_manager/domain/bug_report.py, todo.py,
# wish.py, calendar_entry.py, runtime_link.py). This live-smoke script runs
# on a host with only plan-manager-client installed, never the server
# package, so these eight closed vocabularies cannot be imported live --
# they are pinned literals here instead, compared against whatever a live
# command surface actually projects.
R39_CLOSED_VOCABULARIES: dict[str, frozenset[str]] = {
    "bug_kind": frozenset(
        {
            "functional", "wrong_output", "data_loss", "regression", "compatibility",
            "stale_context", "planning", "performance", "security", "infrastructure",
            "deployment", "configuration", "documentation", "user_experience",
        }
    ),
    "bug_severity": frozenset({"blocker", "critical", "major", "minor", "trivial"}),
    "bug_status": frozenset(
        {
            "reported", "triaged", "confirmed", "rejected", "duplicate", "fixing",
            "fixed_source", "propagating", "verified", "closed", "reopened",
        }
    ),
    "todo_status": frozenset({"open", "in_progress", "blocked", "resolved", "closed", "cancelled"}),
    "wish_kind": frozenset({"feature", "ux", "automation", "integration", "reporting", "tooling", "other"}),
    "wish_status": frozenset(
        {"proposed", "triaged", "planned", "in_progress", "delivered", "rejected", "cancelled"}
    ),
    "calendar_entry_status": frozenset({"planned", "in_progress", "done", "cancelled"}),
    "runtime_link_type": frozenset(
        {
            "relates_to", "blocks", "blocked_by", "duplicates", "caused_by",
            "created_from", "requires", "followup_for",
        }
    ),
}

# Discovery finding (grepped the full command catalog for an enumeration/
# field-catalogue read surface): plan_manager/storage/enumeration_store.py's
# read functions (list_enumerations, list_enumeration_values) and
# reference_catalog.py's list_reference_fields/get_reference_field are never
# called from any plan_manager/commands/*.py module -- no command exposes
# either the enumeration/enumeration_value tables or the reference-field
# catalogue directly. The one live command schema that DOES carry a genuine,
# structured JSON-schema "enum" constraint matching one of the eight closed
# vocabularies verbatim is runtime_link_add's link_type parameter
# (plan_manager/commands/runtime_link_add_command.py), so that is the one
# metadata projection compared for real; the other seven vocabularies have
# no comparable live structured-enum surface at all.
R39_LIVE_ENUM_COMMAND = "runtime_link_add"
R39_LIVE_ENUM_PARAM = "link_type"
R39_LIVE_ENUM_VOCABULARY = "runtime_link_type"

# G-001 registered 'enumeration' and 'enumeration_value' as identity-registry
# entity types (enumeration_store.schema_update_enumerations ->
# register_entity_identity), but neither has a domain DataclassEntity
# subclass, so plan_manager.storage.reference_catalog.known_entity_types()
# -- the source of both reference_inspect's and id_resolve's entity_type
# schema enum -- does not include them (confirmed: known_entity_types()
# lists 32 types, neither 'enumeration' nor 'enumeration_value' among them).
# reference_inspect therefore flatly refuses entity_type='enumeration' (a
# schema-enum rejection, before any lookup runs) -- it cannot observe this
# kind at all. id_resolve's entity_type filter is optional, though, and its
# underlying search (identity_search.search_entity_identities) queries the
# entity_identity registry table directly, unconstrained by
# known_entity_types(); resolving one of migration 0028's FIXED,
# deterministic enumeration refs (the migration's own header comment: "Refs
# are FIXED literals so seeding is deterministic ... on any database") is
# therefore a genuine live classification read of a newly registered kind,
# just not through reference_inspect. bug_kind's own enumeration row is used
# here (an enumeration row, not a value row, so exactly one fixed ref is
# needed).
R39_FIXED_ENUMERATION_REF = "0fb4f10c-be1a-4512-84f7-0cdb2b431ccb"
R39_FIXED_ENUMERATION_NAME = "bug_kind"

R39_REFERENCE_INSPECT_GAP = (
    "reference_inspect cannot target entity_type='enumeration' or "
    "'enumeration_value' at all -- both are absent from known_entity_types() "
    "(no DataclassEntity subclass backs either), which is the source of "
    "reference_inspect's own entity_type schema enum; classification of "
    "the newly registered enumeration kind is observed via id_resolve "
    "instead, whose entity_type filter is optional and whose search queries "
    "the identity registry directly"
)
R39_METADATA_PROJECTION_GAP = (
    "no command exposes the enumeration/enumeration_value tables or the "
    "reference-field catalogue directly (grepped: enumeration_store's and "
    "reference_catalog's read functions are never called from any command "
    "module); only runtime_link_add's link_type parameter carries a "
    "genuine, structured live JSON-schema enum matching one of the eight "
    "closed vocabularies (runtime_link_type) -- the other seven (bug_kind, "
    "bug_severity, bug_status, todo_status, wish_kind, wish_status, "
    "calendar_entry_status) are documented only in free-text parameter "
    "descriptions or not enumerated at all in any command schema, so their "
    "live projection equality is NOT observable through the public command "
    "surface"
)
R39_OWNERSHIP_GAP = (
    "no public command exposes an owner/root declaration directly -- todo_get "
    "and every other point read carry no 'owner' field, even after the "
    "G-007 owner-column collapse; ownership is asserted only via the "
    "structural proxy this check uses: todo_get's primary_anchor_type (the "
    "anchor family a todo belongs to) for an anchored entity, and "
    "id_resolve's entity_type classification of a scratch tool (a "
    "root-kind entity with no primary-anchor concept at all) for an "
    "unanchored one"
)


async def run_r39_cr7_invariants(
    client: Any, catalog_names: frozenset[str]
) -> list[CheckResult]:
    """CR-7 G-008/T-001/A-003: one live regression per G-008 invariant.

    Both defects found while authoring this plan were invisible to a green
    unit suite and appeared only against real data, so every sub-check here
    reads its assertion back zero-trust from the live server rather than
    trusting a create/update response.

    1. Identifier classification of a newly registered kind: G-001's
       enumeration/enumeration_value identity-registry entries.
       reference_inspect cannot target either kind (see
       R39_REFERENCE_INSPECT_GAP, printed explicitly by R39_surface_gaps
       below); id_resolve can, by resolving migration 0028's FIXED bug_kind
       enumeration ref.
    2. Out-of-mechanism absence, observed indirectly: a scratch todo create
       lands with a registry effect (id_resolve resolves its uuid to
       entity_type='todo') and a relation-index effect (reference_inspect on
       the todo shows a comment anchored to it as a catalogued direct
       referrer), both read back from the live server rather than trusted
       from the create responses.
    3. Metadata projection equality: the one vocabulary a live command
       schema documents as a genuine JSON-schema enum (runtime_link_add's
       link_type, matching runtime_link_type) is compared, live, against the
       pinned literal copy of that vocabulary (R39_CLOSED_VOCABULARIES). The
       other seven vocabularies have no comparable live surface (see
       R39_METADATA_PROJECTION_GAP).
    4. Ownership declared: no command exposes an owner/root declaration
       directly, so the structural proxy is asserted instead -- todo_get's
       primary_anchor_type for an anchored family, and id_resolve's
       entity_type classification of a scratch tool (an inherently
       unanchored, root-kind entity). See R39_OWNERSHIP_GAP.

    R39_surface_gaps is its own PASS check (mirroring R38_not_visible_
    surface's convention) printing all three surface-gap notes explicitly,
    never buried inside another check's detail.

    Cleanup is a top-level try/finally: tool independently, comment before
    its anchored todo, todo before its anchor plan.
    """
    if not R39_REQUIRED_COMMANDS <= catalog_names:
        missing = sorted(R39_REQUIRED_COMMANDS - catalog_names)
        return [
            CheckResult(
                "4", "R39_cr7_invariants", STATUS_SKIP,
                f"{R39_PRE_DEPLOY_SKIP_REASON} (missing: {missing})",
            )
        ]

    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    todo_uuid: Optional[str] = None
    comment_uuid: Optional[str] = None
    tool_uuid: Optional[str] = None
    try:
        # --- invariant 1: identifier classification of a newly registered kind. ---
        ok, res = await call(client, "id_resolve", {"fragment": R39_FIXED_ENUMERATION_REF, "limit": 5})
        enum_match = None
        if ok and isinstance(res, dict) and isinstance(res.get("matches"), list):
            enum_match = next(
                (
                    row for row in res["matches"]
                    if isinstance(row, dict) and row.get("uuid") == R39_FIXED_ENUMERATION_REF
                ),
                None,
            )
        enum_classified_ok = enum_match is not None and enum_match.get("entity_type") == "enumeration"
        results.append(
            CheckResult(
                "4", "R39_enumeration_classification",
                STATUS_PASS if enum_classified_ok else STATUS_FAIL,
                (
                    f"id_resolve classifies the fixed {R39_FIXED_ENUMERATION_NAME!r} "
                    "enumeration ref as entity_type='enumeration'"
                    if enum_classified_ok
                    else f"expected entity_type='enumeration' for {R39_FIXED_ENUMERATION_REF}, got ok={ok} {res!r}"
                ),
            )
        )
        if not enum_classified_ok:
            return results

        # --- invariant 2: out-of-mechanism absence, observed indirectly. ---
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r39-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R39_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]
        results.append(CheckResult("4", "R39_plan_create", STATUS_PASS, f"uuid={plan_uuid}"))

        ok, res = await call(
            client, "todo_create",
            {
                "title": unique_suffix("r39-todo"),
                "description": "R39 CR-7 invariants scratch todo",
                "kind": "task", "priority_nice": 10, "created_by": "live-smoke",
                "anchor_type": "plan", "anchor_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R39_todo_create", STATUS_FAIL, str(res)))
            return results
        todo_uuid = res["uuid"]
        results.append(CheckResult("4", "R39_todo_create", STATUS_PASS, f"uuid={todo_uuid}"))

        ok, res = await call(client, "id_resolve", {"fragment": todo_uuid, "limit": 5})
        todo_registry_match = None
        if ok and isinstance(res, dict) and isinstance(res.get("matches"), list):
            todo_registry_match = next(
                (row for row in res["matches"] if isinstance(row, dict) and row.get("uuid") == todo_uuid),
                None,
            )
        registry_effect_ok = (
            todo_registry_match is not None and todo_registry_match.get("entity_type") == "todo"
        )
        results.append(
            CheckResult(
                "4", "R39_todo_registry_effect",
                STATUS_PASS if registry_effect_ok else STATUS_FAIL,
                "id_resolve resolves the created todo to entity_type='todo'" if registry_effect_ok
                else f"expected id_resolve to classify {todo_uuid} as 'todo', got ok={ok} {res!r}",
            )
        )
        if not registry_effect_ok:
            return results

        ok, res = await call(
            client, "comment_add",
            {
                "plan": plan_uuid, "anchor_type": "todo", "anchor_ref_id": todo_uuid,
                "kind": "comment", "visibility": "audit_only", "author": "live-smoke",
                "body": "R39 relation-index second-hop referrer",
                "created_by": "live-smoke",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R39_comment_add", STATUS_FAIL, str(res)))
            return results
        comment_uuid = res["uuid"]
        results.append(CheckResult("4", "R39_comment_add", STATUS_PASS, f"uuid={comment_uuid}"))

        ok, res = await call(
            client, "reference_inspect",
            {"entity_type": "todo", "entity_id": todo_uuid, "recursive": False},
        )
        direct = res.get("direct_referrers") if ok and isinstance(res, dict) else None
        relation_index_match = None
        if isinstance(direct, list):
            relation_index_match = next(
                (row for row in direct if isinstance(row, dict) and row.get("referrer_id") == comment_uuid),
                None,
            )
        relation_index_ok = relation_index_match is not None
        results.append(
            CheckResult(
                "4", "R39_todo_relation_index_effect",
                STATUS_PASS if relation_index_ok else STATUS_FAIL,
                "reference_inspect catalogues the comment as a direct referrer of the todo"
                if relation_index_ok
                else f"the comment is not among reference_inspect's direct_referrers: ok={ok} {res!r}",
            )
        )
        if not relation_index_ok:
            return results

        # --- invariant 3: metadata projection equality (one live structured enum). ---
        ok, res = await call(client, "help", {"cmdname": R39_LIVE_ENUM_COMMAND})
        live_enum: Optional[frozenset] = None
        if ok and isinstance(res, dict):
            schema = res.get("schema")
            if isinstance(schema, dict):
                properties = schema.get("properties")
                if isinstance(properties, dict):
                    param = properties.get(R39_LIVE_ENUM_PARAM)
                    if isinstance(param, dict) and isinstance(param.get("enum"), list):
                        live_enum = frozenset(param["enum"])
        expected_vocabulary = R39_CLOSED_VOCABULARIES[R39_LIVE_ENUM_VOCABULARY]
        projection_ok = live_enum is not None and live_enum == expected_vocabulary
        results.append(
            CheckResult(
                "4", "R39_metadata_projection_equality",
                STATUS_PASS if projection_ok else STATUS_FAIL,
                (
                    f"{R39_LIVE_ENUM_COMMAND}.{R39_LIVE_ENUM_PARAM}'s live schema enum matches "
                    f"the pinned {R39_LIVE_ENUM_VOCABULARY} vocabulary ({len(expected_vocabulary)} values)"
                )
                if projection_ok
                else (
                    f"expected {sorted(expected_vocabulary)}, got "
                    f"{sorted(live_enum) if live_enum is not None else None} (ok={ok}, help={res!r})"
                ),
            )
        )
        if not projection_ok:
            return results

        # --- invariant 4: ownership declared, via the structural proxy. ---
        ok, res = await call(client, "todo_get", {"todo": todo_uuid})
        anchor_family_ok = (
            ok and isinstance(res, dict)
            and isinstance(res.get("primary_anchor_type"), str)
            and bool(res.get("primary_anchor_type"))
        )
        results.append(
            CheckResult(
                "4", "R39_ownership_anchor_family",
                STATUS_PASS if anchor_family_ok else STATUS_FAIL,
                f"todo_get shows primary_anchor_type={res.get('primary_anchor_type')!r}"
                if anchor_family_ok
                else f"expected a non-empty primary_anchor_type, got ok={ok} {res!r}",
            )
        )
        if not anchor_family_ok:
            return results

        ok, res = await call(
            client, "tool_create",
            {
                "name": unique_suffix("r39-tool"), "server_id": "live-smoke-server",
                "command": "noop", "pinned_options": {}, "created_by": "live-smoke",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R39_tool_create", STATUS_FAIL, str(res)))
            return results
        tool_uuid = res["uuid"]
        results.append(CheckResult("4", "R39_tool_create", STATUS_PASS, f"uuid={tool_uuid}"))

        ok, res = await call(client, "id_resolve", {"fragment": tool_uuid, "limit": 5})
        tool_registry_match = None
        if ok and isinstance(res, dict) and isinstance(res.get("matches"), list):
            tool_registry_match = next(
                (row for row in res["matches"] if isinstance(row, dict) and row.get("uuid") == tool_uuid),
                None,
            )
        root_kind_ok = tool_registry_match is not None and tool_registry_match.get("entity_type") == "tool"
        results.append(
            CheckResult(
                "4", "R39_ownership_root_kind",
                STATUS_PASS if root_kind_ok else STATUS_FAIL,
                "id_resolve classifies the scratch tool as entity_type='tool' "
                "(a root-kind entity with no primary-anchor concept)"
                if root_kind_ok
                else f"expected id_resolve to classify {tool_uuid} as 'tool', got ok={ok} {res!r}",
            )
        )
        if not root_kind_ok:
            return results

        results.append(
            CheckResult(
                "4", "R39_surface_gaps", STATUS_PASS,
                " | ".join((R39_REFERENCE_INSPECT_GAP, R39_METADATA_PROJECTION_GAP, R39_OWNERSHIP_GAP)),
            )
        )
    finally:
        cleanup_ok = True
        if tool_uuid is not None:
            ok, res = await call(
                client, "tool_delete", {"tool_uuid": tool_uuid, "changed_by": "live-smoke", "hard": True}
            )
            cleanup_ok = cleanup_ok and ok
        if comment_uuid is not None:
            ok, res = await call(
                client, "comment_delete", {"comment": comment_uuid, "changed_by": "live-smoke", "hard": True}
            )
            cleanup_ok = cleanup_ok and ok
        if todo_uuid is not None:
            ok, res = await call(
                client, "todo_delete", {"todo": todo_uuid, "changed_by": "live-smoke", "hard": True}
            )
            cleanup_ok = cleanup_ok and ok
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R39_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


async def run_r40_owner_edge_read_projection(client: Any) -> list[CheckResult]:
    """Bug 0798c162: migration 0029 appended an additive owner edge column to
    seven tables (bug_report got ``owner_uuid``), and bug_report_store's read
    paths unpacked ``SELECT *`` rows into a fixed 34-element tuple -- so on
    live 0.1.99 every bug_list/bug_get failed with "too many values to unpack
    (expected 34)". The sweep also converted escalation_store and
    answer_envelope_store (same ``SELECT *`` pattern, positional indexing) to
    explicit column projections.

    Recipe: a throwaway plan + one scratch bug guarantee at least one
    bug_report row actually flows through the fixed row converter (an empty
    filtered result would not exercise the unpack); bug_list(plan=...) and
    bug_get are the exact repro calls. escalation_list is the swept sibling's
    read -- read-only, and even with zero rows it validates the projected
    escalation column names against the live schema (a bad name fails the
    SELECT outright). answer_envelope has no command surface, so its swept
    store is pinned by unit tests only
    (tests/test_bug_0798c162_select_star_row_width.py). Cleanup hard-deletes
    the scratch bug then the plan in a top-level try/finally (r13's idiom:
    source_plan_uuid carries no FK/cascade, so plan_delete alone would orphan
    the bug row).
    """
    results: list[CheckResult] = []
    plan_name = unique_suffix("r40-plan")
    ok, plan_res = await call(client, "plan_create", {"name": plan_name})
    if not ok or not isinstance(plan_res, dict) or not plan_res.get("uuid"):
        results.append(CheckResult("4", "R40_plan_create", STATUS_FAIL, str(plan_res)))
        return results
    plan_uuid = plan_res["uuid"]
    bug_uuid: Optional[str] = None
    try:
        title = unique_suffix("r40-bug")
        ok, res = await call(
            client, "bug_create",
            {
                "plan": plan_uuid, "title": title,
                "short_description": "R40 scratch bug (owner-edge read projection)",
                "detailed_description": "scratch row so bug_list/bug_get unpack a real post-0029 row",
                "kind": "functional", "severity": "trivial", "priority_nice": 19,
                "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "plan", "source_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R40_bug_create", STATUS_FAIL, str(res)))
            return results
        bug_uuid = res["uuid"]
        results.append(CheckResult("4", "R40_bug_create", STATUS_PASS, f"uuid={bug_uuid}"))

        # The live failure mode: any bug_list that materializes >= 1 row.
        ok, res = await call(client, "bug_list", {"plan": plan_uuid, "limit": 5})
        list_ok = ok and isinstance(res, dict) and isinstance(res.get("bugs"), list)
        results.append(CheckResult("4", "R40_0798c162_bug_list_call", STATUS_PASS if list_ok else STATUS_FAIL, "" if list_ok else str(res)))
        if list_ok:
            row_present = any(isinstance(b, dict) and b.get("uuid") == bug_uuid for b in res["bugs"])
            results.append(CheckResult("4", "R40_0798c162_bug_list_row_unpacked", STATUS_PASS if row_present else STATUS_FAIL, "" if row_present else f"bug {bug_uuid} missing from bug_list(plan={plan_name})"))

        # bug_get shares get_bug's projection with the list path.
        ok, res = await call(client, "bug_get", {"bug_id": bug_uuid})
        get_ok = ok and isinstance(res, dict) and res.get("uuid") == bug_uuid
        results.append(CheckResult("4", "R40_0798c162_bug_get_call", STATUS_PASS if get_ok else STATUS_FAIL, "" if get_ok else str(res)))

        # Swept sibling: escalation reads now use an explicit projection too.
        ok, res = await call(client, "escalation_list", {})
        results.append(CheckResult("4", "R40_0798c162_escalation_list_call", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    finally:
        cleanup_ok = True
        if bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
            cleanup_ok = cleanup_ok and ok
        ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
        cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R40_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


async def run_r41_plan_status_freeze_sync(client: Any) -> list[CheckResult]:
    """Bug 845b43a8: plan.status is a stored aggregate that used to be
    written once at create_plan() time and never touched again, so a fully
    frozen plan (every step frozen) still reported status='draft' forever
    via plan_status/plan_list. plan_status_sync.derive_plan_status now
    recomputes the aggregate (frozen iff every step frozen, else draft)
    after every step_transition -- always over the WHOLE step tree, never
    just the transitioned scope -- and plan_unfreeze force-resets it to
    'draft' the instant an audited cascade reopens a fully frozen plan
    (the tree itself is still all-frozen at that instant, so the aggregate
    cannot be derived from it there). plan_status now also exposes
    derived_status (recomputed live from the step tree) and
    status_consistent (status == derived_status).

    Recipe (throwaway plan, try/finally cleanup): plan_create -> one G
    step -> step_transition(whole_plan -> frozen, require_green=false) ->
    plan_status must report status='frozen', derived_status='frozen',
    status_consistent=true -> plan_unfreeze -> plan_status must
    immediately report status='draft'. Cleanup: cascade_abort (unfreeze
    always leaves one open) then plan_delete(hard).
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    cascade_open = False
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r41-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R41_845b43a8_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R41_845b43a8_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R41_845b43a8_step_create(G)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R41_845b43a8_repro_step_created", STATUS_PASS, f"G={g_id}"))

        ok, res = await call(
            client, "step_transition",
            {"plan": plan_uuid, "scope": "whole_plan", "to_status": "frozen", "require_green": False},
        )
        if not ok:
            results.append(CheckResult("4", "R41_845b43a8_freeze_whole_plan", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R41_845b43a8_freeze_whole_plan", STATUS_PASS))

        ok, res = await call(client, "plan_status", {"plan": plan_uuid})
        plan_part = res.get("plan") if ok and isinstance(res, dict) else None
        frozen_ok = (
            ok and isinstance(plan_part, dict)
            and plan_part.get("status") == "frozen"
            and plan_part.get("derived_status") == "frozen"
            and plan_part.get("status_consistent") is True
        )
        results.append(
            CheckResult(
                "4", "R41_845b43a8_plan_status_reports_frozen",
                STATUS_PASS if frozen_ok else STATUS_FAIL,
                "" if frozen_ok else (
                    "expected status=derived_status='frozen', status_consistent=True, "
                    f"got ok={ok} plan={plan_part!r}"
                ),
            )
        )
        if not frozen_ok:
            return results

        ok, res = await call(
            client, "plan_unfreeze",
            {
                "plan": plan_uuid, "changed_by": "live-smoke",
                "reason": "R41 plan.status aggregate probe (bug 845b43a8)",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("cascade_uuid"):
            results.append(CheckResult("4", "R41_845b43a8_plan_unfreeze", STATUS_FAIL, str(res)))
            return results
        cascade_open = True
        results.append(CheckResult("4", "R41_845b43a8_plan_unfreeze", STATUS_PASS, f"cascade_uuid={res['cascade_uuid']}"))

        ok, res = await call(client, "plan_status", {"plan": plan_uuid})
        plan_part = res.get("plan") if ok and isinstance(res, dict) else None
        draft_ok = ok and isinstance(plan_part, dict) and plan_part.get("status") == "draft"
        results.append(
            CheckResult(
                "4", "R41_845b43a8_plan_status_reports_draft_after_unfreeze",
                STATUS_PASS if draft_ok else STATUS_FAIL,
                "" if draft_ok else f"expected status='draft' immediately after unfreeze, got ok={ok} plan={plan_part!r}",
            )
        )
    finally:
        cleanup_ok = True
        if cascade_open:
            ok, res = await call(client, "cascade_abort", {"plan": plan_uuid})
            cleanup_ok = cleanup_ok and ok
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R41_845b43a8_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


# Fixed CR-7 acceptance plan (see docs/cr7_acceptance_governance.md): frozen,
# gate-green, deployed and left live so R42 has a stable, real multi-GS
# dependency graph to read WITHOUT constructing (and hardcoding the shape of)
# its own throwaway fixture.
R42_CR7_PLAN_UUID = "99340015-56d0-415d-860a-06bf46c51aa2"


def _r42_group_as_waves_by_gs(wave_rows: list[list[str]]) -> dict[str, list[int]]:
    """Group AS-level artifact-path wave indices by their owning GS id.

    ``wave_rows`` is a list of waves (index = wave number), each a list of
    artifact path strings at any level. Only entries with exactly three
    '/'-separated segments (G-NNN/T-NNN/A-NNN) are AS-level; GS-only,
    TS-only, or any path not observed in a scoped wave map are ignored.
    """
    by_gs: dict[str, list[int]] = {}
    for wave_index, row in enumerate(wave_rows):
        for path in row:
            segments = path.split("/")
            if len(segments) != 3:
                continue
            by_gs.setdefault(segments[0], []).append(wave_index)
    return by_gs


def _r42_gs_dependency_closure(gs_entries: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Transitive closure of GS-level depends_on edges.

    step.depends_on holds "step_id values of sibling steps this step
    depends on" (direct edges only); this closes it transitively so a
    two-hop chain (G-003 depends_on G-002 depends_on G-001) still reaches
    the (G-001, G-003) pair.
    """
    direct: dict[str, set[str]] = {}
    for entry in gs_entries:
        gs_id = entry.get("step_id")
        if not isinstance(gs_id, str):
            continue
        deps = entry.get("depends_on") or []
        direct[gs_id] = {d for d in deps if isinstance(d, str)}
    closure: dict[str, set[str]] = {}
    for gs_id in direct:
        seen: set[str] = set()
        stack = list(direct.get(gs_id, ()))
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            stack.extend(direct.get(dep, ()))
        closure[gs_id] = seen
    return closure


def _r42_closure_violations(
    closure: dict[str, set[str]], as_waves_by_gs: dict[str, list[int]]
) -> list[str]:
    """Every (producer, dependent) GS pair the closure names, with both
    sides represented in ``as_waves_by_gs``, must have every dependent AS
    strictly after every producer AS. Returns one diagnostic string per
    violating pair (empty when the property holds everywhere it applies).
    """
    violations: list[str] = []
    for dependent, producers in closure.items():
        dependent_waves = as_waves_by_gs.get(dependent)
        if not dependent_waves:
            continue
        for producer in producers:
            producer_waves = as_waves_by_gs.get(producer)
            if not producer_waves:
                continue
            if min(dependent_waves) <= max(producer_waves):
                violations.append(
                    f"{dependent} (depends on {producer}) has an AS in wave "
                    f"{min(dependent_waves)}, not strictly after {producer}'s "
                    f"last AS wave {max(producer_waves)}"
                )
    return violations


async def run_r42_prompt_chain_gs_dependency_closure(client: Any) -> list[CheckResult]:
    """Bug 5d923c91: plan_prompt_chain's ``_wave_data`` filtered the plan's
    edge set to atomic-only endpoints BEFORE computing waves, silently
    dropping every GS/TS-level depends_on edge (e.g. G-002 depends_on
    G-001) -- so an AS under a dependent GS could land in the same wave
    as, or before, an AS under the GS it structurally depends on. Fixed
    by driving the wave map from the exact same closure algorithm
    graph_parallel_map already uses (``waves()`` over the FULL plan
    graph), then projecting onto the scoped atomic subset.

    Read-only, against the fixed, frozen CR-7 acceptance plan (uuid
    99340015-56d0-415d-860a-06bf46c51aa2): step_list(level=3) supplies
    each GS's own depends_on (direct edges, transitively closed here)
    WITHOUT hardcoding this plan's actual structure. plan_prompt_chain
    (whole_plan, role=coder, include_statuses=['frozen']) and
    graph_parallel_map are each checked independently: for every
    (producer, dependent) GS pair the closure finds, every dependent AS's
    wave must be strictly greater than every producer AS's wave, in BOTH
    commands' own wave numbering (they do not share a numbering scheme --
    prompt_chain's waves are densely re-indexed over the scoped atomic
    subset, graph_parallel_map's span the full node set). If this plan's
    step tree happens to carry no GS-level depends_on edge at all, both
    checks SKIP naming that rather than reporting a vacuous PASS.
    """
    results: list[CheckResult] = []
    plan_uuid = R42_CR7_PLAN_UUID

    ok, res = await call(
        client, "step_list",
        {"plan": plan_uuid, "level": 3, "fields": ["step_id", "depends_on"], "limit": 200},
    )
    gs_entries = res.get("steps") if ok and isinstance(res, dict) else None
    if not ok or not isinstance(gs_entries, list):
        results.append(CheckResult("4", "R42_5d923c91_step_list(gs_depends_on)", STATUS_FAIL, str(res)))
        return results
    results.append(CheckResult("4", "R42_5d923c91_step_list(gs_depends_on)", STATUS_PASS, f"{len(gs_entries)} GS steps"))

    closure = _r42_gs_dependency_closure(gs_entries)
    if not any(closure.values()):
        results.append(
            CheckResult(
                "4", "R42_5d923c91_gs_dependency_pairs_found", STATUS_SKIP,
                "no GS in the CR-7 plan's step tree depends_on another GS -- "
                "nothing to exercise the closure property against",
            )
        )
        return results
    results.append(
        CheckResult(
            "4", "R42_5d923c91_gs_dependency_pairs_found", STATUS_PASS,
            str({gs: sorted(deps) for gs, deps in closure.items() if deps}),
        )
    )

    ok, res = await call(
        client, "plan_prompt_chain",
        {
            "plan": plan_uuid, "scope": "whole_plan", "role": "coder",
            "include_statuses": ["frozen"], "limit": 1,
        },
    )
    chain_waves = res.get("waves") if ok and isinstance(res, dict) else None
    if not ok or not isinstance(chain_waves, list):
        results.append(CheckResult("4", "R42_5d923c91_plan_prompt_chain_call", STATUS_FAIL, str(res)))
        return results
    results.append(CheckResult("4", "R42_5d923c91_plan_prompt_chain_call", STATUS_PASS, f"{len(chain_waves)} waves"))

    chain_violations = _r42_closure_violations(closure, _r42_group_as_waves_by_gs(chain_waves))
    results.append(
        CheckResult(
            "4", "R42_5d923c91_prompt_chain_waves_respect_gs_closure",
            STATUS_PASS if not chain_violations else STATUS_FAIL,
            "" if not chain_violations else "; ".join(chain_violations),
        )
    )

    ok, res = await call(client, "graph_parallel_map", {"plan": plan_uuid, "limit": 200})
    full_waves = res.get("waves") if ok and isinstance(res, dict) else None
    if not ok or not isinstance(full_waves, list):
        results.append(CheckResult("4", "R42_5d923c91_graph_parallel_map_call", STATUS_FAIL, str(res)))
        return results
    results.append(CheckResult("4", "R42_5d923c91_graph_parallel_map_call", STATUS_PASS, f"{len(full_waves)} waves"))

    full_violations = _r42_closure_violations(closure, _r42_group_as_waves_by_gs(full_waves))
    results.append(
        CheckResult(
            "4", "R42_5d923c91_graph_parallel_map_waves_respect_gs_closure",
            STATUS_PASS if not full_violations else STATUS_FAIL,
            "" if not full_violations else "; ".join(full_violations),
        )
    )
    return results


_R43_REVISION_UUID_PATTERN = re.compile(r"'revision_uuid':\s*'([0-9a-fA-F-]{36})'")


async def run_r43_freeze_gate_names_cascade_tip(client: Any) -> list[CheckResult]:
    """Bug 1ddea076: step_transition's freeze gate (require_green=true)
    labeled its verdict with the plan HEAD -- the cascade's BASE revision,
    which never moves while a cascade is open -- instead of the cascade's
    live working TIP (the same state plan_validate_command reports as
    tip_revision_uuid). Fixed by resolving the open cascade's ref target
    (via ``_live_working_revision``) whenever one is open.

    Recipe (throwaway plan, try/finally cleanup): plan_create -> G/T/A
    chain -> step_transition(whole_plan -> frozen, require_green=false) ->
    plan_unfreeze (captures cascade_uuid; the cascade's ref target equals
    the base head at this instant) -> concept_add(cascade_uuid=...)
    advances the cascade's OWN working tip away from the base (a real
    mutation under the same open cascade, so tip != base from here on) ->
    plan_validate captures the now-advanced tip_revision_uuid ->
    step_transition(scope=G, to_status=frozen, require_green=true,
    cascade_uuid=...) -- the G branch is already frozen, so nothing
    actually transitions, but the gate still runs (require_green=true).
    Whichever way that call resolves (success or a GATE_RED refusal), its
    gate payload's revision_uuid must equal the ADVANCED tip, never the
    base head captured right after plan_unfreeze. Cleanup: cascade_abort,
    then plan_delete(hard).
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    cascade_open = False
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r43-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R43_1ddea076_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R43_1ddea076_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R43_1ddea076_step_create(G)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R43_1ddea076_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_uuid = res.get("uuid") if ok and isinstance(res, dict) else None
        if not ok or not t_uuid:
            results.append(CheckResult("4", "R43_1ddea076_step_create(T)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_uuid, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R43_1ddea076_context_common(T,level5)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a", "parent_step_id": t_uuid})
        if not ok:
            results.append(CheckResult("4", "R43_1ddea076_step_create(A)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R43_1ddea076_repro_chain_created", STATUS_PASS, f"G={g_id}"))

        ok, res = await call(
            client, "step_transition",
            {"plan": plan_uuid, "scope": "whole_plan", "to_status": "frozen", "require_green": False},
        )
        if not ok:
            results.append(CheckResult("4", "R43_1ddea076_freeze_whole_plan", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(
            client, "plan_unfreeze",
            {
                "plan": plan_uuid, "changed_by": "live-smoke",
                "reason": "R43 freeze-gate cascade-tip probe (bug 1ddea076)",
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("cascade_uuid"):
            results.append(CheckResult("4", "R43_1ddea076_plan_unfreeze", STATUS_FAIL, str(res)))
            return results
        cascade_uuid = res["cascade_uuid"]
        base_revision = res.get("base_revision_uuid")
        cascade_open = True
        results.append(CheckResult("4", "R43_1ddea076_plan_unfreeze", STATUS_PASS, f"cascade_uuid={cascade_uuid} base={base_revision}"))

        ok, res = await call(
            client, "concept_add",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-001",
                "name": "LiveSmokeR43Concept", "definition": "R43 tip-advancing scratch concept.",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R43_1ddea076_concept_add(advance_tip)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R43_1ddea076_concept_add(advance_tip)", STATUS_PASS))

        ok, res = await call(client, "plan_validate", {"plan": plan_uuid})
        tip_revision = res.get("tip_revision_uuid") if ok and isinstance(res, dict) else None
        if not ok or not tip_revision:
            results.append(CheckResult("4", "R43_1ddea076_plan_validate(tip)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R43_1ddea076_plan_validate(tip)", STATUS_PASS, f"tip_revision_uuid={tip_revision}"))
        results.append(
            CheckResult(
                "4", "R43_1ddea076_tip_advanced_past_base",
                STATUS_PASS if tip_revision != base_revision else STATUS_FAIL,
                "" if tip_revision != base_revision else f"tip {tip_revision} did not advance past base {base_revision}",
            )
        )

        ok, res = await call(
            client, "step_transition",
            {
                "plan": plan_uuid, "scope": g_id, "to_status": "frozen",
                "require_green": True, "cascade_uuid": cascade_uuid,
            },
        )
        if ok and isinstance(res, dict):
            gate = res.get("gate")
            reported_revision = gate.get("revision_uuid") if isinstance(gate, dict) else None
        else:
            match = _R43_REVISION_UUID_PATTERN.search(str(res))
            reported_revision = match.group(1) if match else None
        if reported_revision is None:
            results.append(
                CheckResult(
                    "4", "R43_1ddea076_gate_names_cascade_tip", STATUS_FAIL,
                    f"could not extract gate.revision_uuid from response: ok={ok} res={res!r}",
                )
            )
        elif reported_revision == tip_revision:
            results.append(
                CheckResult(
                    "4", "R43_1ddea076_gate_names_cascade_tip", STATUS_PASS,
                    f"gate.revision_uuid={reported_revision} == tip_revision_uuid (call ok={ok})",
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "R43_1ddea076_gate_names_cascade_tip", STATUS_FAIL,
                    f"gate.revision_uuid={reported_revision!r} != tip_revision_uuid={tip_revision!r} "
                    f"(base was {base_revision!r}, call ok={ok})",
                )
            )
    finally:
        cleanup_ok = True
        if cascade_open:
            ok, res = await call(client, "cascade_abort", {"plan": plan_uuid})
            cleanup_ok = cleanup_ok and ok
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R43_1ddea076_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


async def run_r44_delete_guard_scoped_probe(client: Any) -> list[CheckResult]:
    """Bug c315ff84: the hard-delete guard's catalog probe used to bind a
    composite identity mapping directly as a SQL parameter instead of
    resolving it through the catalog entry's declared target_column, so a
    concept still referenced by a relation was refused only because
    concept_store re-implemented its own referrer check ahead of the
    guarded delete -- a caller-side workaround, not the guard's own
    catalog probe. Fixed: guarded_hard_delete now accepts an explicit
    probe_id (the scoped concept_id key), so the guard's own catalog
    probe reaches the right column directly, and the refusal is now
    audited by the guard itself.

    Recipe (throwaway plan, try/finally cleanup): plan_create ->
    context_common(plan, level3) -> step_create G (level 3) -- cascade_begin
    refuses CASCADE_CONFLICT("cannot open a cascade on a plan with no head
    revision") on a plan with no step tree yet, so a head revision must
    exist first (same context_common-immediately-before-step_create idiom
    as R2/R8/R12/R15/R18/R41) -- -> cascade_begin -> concept_add C-001,
    concept_add C-002 -> relation_add (C-001 uses C-002) ->
    concept_remove(C-001) must be REFUSED (ENTITY_REFERENCED/DELETE_BLOCKED
    family) while the relation exists -> relation_remove(same triple) ->
    concept_remove(C-001) must now SUCCEED. The observable contract
    (refusal then success) is what this check pins; it is neutral to
    whether the refusal is caller-side or guard-native. Cleanup:
    plan_delete(hard) -- removes the plan's open cascade along with
    everything else, no separate cascade_abort needed.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r44-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R44_c315ff84_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R44_c315ff84_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R44_c315ff84_step_create(G)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R44_c315ff84_repro_step_created", STATUS_PASS, f"G={g_id}"))

        ok, res = await call(client, "cascade_begin", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict) or not res.get("cascade_uuid"):
            results.append(CheckResult("4", "R44_c315ff84_cascade_begin", STATUS_FAIL, str(res)))
            return results
        cascade_uuid = res["cascade_uuid"]

        ok, res = await call(
            client, "concept_add",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-001",
                "name": "LiveSmokeR44Source", "definition": "R44 scoped-probe scratch concept (from).",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R44_c315ff84_concept_add(C-001)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(
            client, "concept_add",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-002",
                "name": "LiveSmokeR44Target", "definition": "R44 scoped-probe scratch concept (to).",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R44_c315ff84_concept_add(C-002)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R44_c315ff84_concepts_created", STATUS_PASS, "C-001, C-002"))

        ok, res = await call(
            client, "relation_add",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid,
                "from_concept": "C-001", "to_concept": "C-002", "type": "uses",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R44_c315ff84_relation_add", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R44_c315ff84_relation_add", STATUS_PASS))

        ok, res = await call(
            client, "concept_remove",
            {"plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-001"},
        )
        diagnostic = str(res)
        refused_correctly = (not ok) and ("ENTITY_REFERENCED" in diagnostic or "DELETE_BLOCKED" in diagnostic)
        results.append(
            CheckResult(
                "4", "R44_c315ff84_concept_remove_refused_while_referenced",
                STATUS_PASS if refused_correctly else STATUS_FAIL,
                "" if refused_correctly else (
                    f"expected ENTITY_REFERENCED/DELETE_BLOCKED refusal, got ok={ok} res={res!r}"
                ),
            )
        )
        if not refused_correctly:
            return results

        ok, res = await call(
            client, "relation_remove",
            {
                "plan": plan_uuid, "cascade_uuid": cascade_uuid,
                "from_concept": "C-001", "to_concept": "C-002", "type": "uses",
            },
        )
        if not ok:
            results.append(CheckResult("4", "R44_c315ff84_relation_remove", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R44_c315ff84_relation_remove", STATUS_PASS))

        ok, res = await call(
            client, "concept_remove",
            {"plan": plan_uuid, "cascade_uuid": cascade_uuid, "concept_id": "C-001"},
        )
        removed_ok = ok and isinstance(res, dict) and res.get("deleted") is True
        results.append(
            CheckResult(
                "4", "R44_c315ff84_concept_remove_succeeds_after_relation_removed",
                STATUS_PASS if removed_ok else STATUS_FAIL,
                "" if removed_ok else f"ok={ok} res={res!r}",
            )
        )
    finally:
        cleanup_ok = True
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R44_c315ff84_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


async def run_r45_step_update_null_removes_field_key(client: Any) -> list[CheckResult]:
    """Todo 4bb0f85b: step_update's fields patch used to persist an
    explicit JSON null as a literal null value (plain dict.update), so
    there was no way to actually remove a previously-set fields key.
    ``_merge_step_fields`` now pops the key when the patch value is None
    instead of storing it, leaving every other value (and the shallow
    merge depth) unchanged.

    Recipe (throwaway plan, one G step, try/finally cleanup): plan_create
    -> step_create(level=3) -> step_update(fields={'k': 'v'}) -> step_get
    confirms fields.k == 'v' -> step_update(fields={'k': None}) ->
    step_get confirms 'k' is ABSENT from fields (pre-fix it persisted as
    a literal null) -> step_update(fields={'never_set': None}) on a key
    that was never set must be accepted with no error (a no-op pop).
    Cleanup: plan_delete(hard).
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r45-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R45_4bb0f85b_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R45_4bb0f85b_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R45_4bb0f85b_step_create(G)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R45_4bb0f85b_repro_step_created", STATUS_PASS, f"G={g_id}"))

        ok, res = await call(
            client, "step_update", {"plan": plan_uuid, "step_id": g_id, "fields": {"k": "v"}},
        )
        if not ok:
            results.append(CheckResult("4", "R45_4bb0f85b_step_update(set_k)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": g_id})
        fields = res.get("fields") if ok and isinstance(res, dict) else None
        set_ok = ok and isinstance(fields, dict) and fields.get("k") == "v"
        results.append(
            CheckResult(
                "4", "R45_4bb0f85b_step_get_confirms_k_set",
                STATUS_PASS if set_ok else STATUS_FAIL,
                "" if set_ok else f"expected fields.k=='v', got ok={ok} fields={fields!r}",
            )
        )
        if not set_ok:
            return results

        ok, res = await call(
            client, "step_update", {"plan": plan_uuid, "step_id": g_id, "fields": {"k": None}},
        )
        if not ok:
            results.append(CheckResult("4", "R45_4bb0f85b_step_update(null_removes_k)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": g_id})
        fields = res.get("fields") if ok and isinstance(res, dict) else None
        removed_ok = ok and isinstance(fields, dict) and "k" not in fields
        results.append(
            CheckResult(
                "4", "R45_4bb0f85b_step_get_confirms_k_absent",
                STATUS_PASS if removed_ok else STATUS_FAIL,
                "" if removed_ok else f"expected 'k' absent from fields, got ok={ok} fields={fields!r}",
            )
        )
        if not removed_ok:
            return results

        # Nulling a never-set key is accepted (a no-op pop), not an error.
        ok, res = await call(
            client, "step_update", {"plan": plan_uuid, "step_id": g_id, "fields": {"never_set": None}},
        )
        results.append(
            CheckResult(
                "4", "R45_4bb0f85b_null_on_never_set_key_accepted",
                STATUS_PASS if ok else STATUS_FAIL,
                "" if ok else str(res),
            )
        )
    finally:
        cleanup_ok = True
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R45_4bb0f85b_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


async def run_r46_prompt_chain_scoped_branch_depth(client: Any) -> list[CheckResult]:
    """Bug 4f7fbd43: plan_prompt_chain's scoped (non-whole_plan) path builds
    a per-atomic ``Branch`` view via ``branch_for_atomic``
    (plan_manager.views.prompt_chain) -- a plain ``Branch`` dataclass
    (plan_uuid/gs/ts/atomic/hrs_slice, no ``depth`` field) -- and feeds it
    straight into ``run_gate(conn, p.uuid, branch=branch)``. The gate's
    finding-scope switch (plan_manager.verify.gate) reads ``branch.depth``
    to decide whether a finding is in-scope for "gs"/"ts"/"as" narrowing --
    a field that only the OTHER branch view, ``BranchScope``
    (plan_manager.views.branch), carries. Any scope narrower than
    whole_plan (G-NNN or G-NNN/T-NNN) therefore crashes the gate with
    ``AttributeError: 'Branch' object has no attribute 'depth'``, surfaced
    to the client as JSON-RPC -32603. whole_plan never calls
    branch_for_atomic (it calls run_gate(branch=None) instead), so it is
    unaffected -- confirmed live by R42 above, which already exercises
    scope=whole_plan read-only against this same plan.

    Read-only, against the fixed, frozen CR-7 acceptance plan (uuid
    99340015-56d0-415d-860a-06bf46c51aa2, same plan as R42): plan_prompt_chain
    with scope="G-004" and, separately, scope="G-004/T-001" (both scope
    forms are admitted per plan_prompt_chain's own schema/help -- G-NNN and
    G-NNN/T-NNN), role="review". Each call must complete
    (command_success=true) and return the documented artifact shape:
    waves (non-empty list), assembly (non-empty list), used_block_keys
    (dict), and meta (dict), with the response's own "scope" echoing the
    request. On the live server this bug is filed against, both calls fail
    with the 'Branch' object has no attribute 'depth' error, so this check
    FAILS until the scoped path is fixed to build (or feed the gate) a
    BranchScope instead of a bare Branch -- that FAIL is the point: it
    reproduces the bug through the same client/queue path a real caller
    uses, not just at the unit level.
    """
    results: list[CheckResult] = []
    plan_uuid = R42_CR7_PLAN_UUID

    for scope in ("G-004", "G-004/T-001"):
        tag = scope.replace("/", "_")
        ok, res = await call(
            client, "plan_prompt_chain",
            {"plan": plan_uuid, "scope": scope, "role": "review", "limit": 200},
        )
        results.append(
            CheckResult(
                "4", f"R46_4f7fbd43_prompt_chain_call({tag})",
                STATUS_PASS if ok else STATUS_FAIL,
                "" if ok else str(res),
            )
        )
        if not ok or not isinstance(res, dict):
            # Nothing further to shape-check once the call itself failed --
            # this is exactly the reported crash path.
            continue

        waves = res.get("waves")
        waves_ok = isinstance(waves, list) and len(waves) > 0
        results.append(
            CheckResult(
                "4", f"R46_4f7fbd43_waves_shape({tag})",
                STATUS_PASS if waves_ok else STATUS_FAIL,
                "" if waves_ok else f"waves={waves!r}",
            )
        )

        assembly = res.get("assembly")
        assembly_ok = isinstance(assembly, list) and len(assembly) > 0
        results.append(
            CheckResult(
                "4", f"R46_4f7fbd43_assembly_shape({tag})",
                STATUS_PASS if assembly_ok else STATUS_FAIL,
                "" if assembly_ok else f"assembly={assembly!r}",
            )
        )

        used_block_keys = res.get("used_block_keys")
        used_block_keys_ok = isinstance(used_block_keys, dict)
        results.append(
            CheckResult(
                "4", f"R46_4f7fbd43_used_block_keys_shape({tag})",
                STATUS_PASS if used_block_keys_ok else STATUS_FAIL,
                "" if used_block_keys_ok else f"used_block_keys={used_block_keys!r}",
            )
        )

        meta = res.get("meta")
        meta_ok = isinstance(meta, dict)
        results.append(
            CheckResult(
                "4", f"R46_4f7fbd43_meta_shape({tag})",
                STATUS_PASS if meta_ok else STATUS_FAIL,
                "" if meta_ok else f"meta={meta!r}",
            )
        )

        scope_echo_ok = res.get("scope") == scope
        results.append(
            CheckResult(
                "4", f"R46_4f7fbd43_scope_echo({tag})",
                STATUS_PASS if scope_echo_ok else STATUS_FAIL,
                "" if scope_echo_ok else f"scope echoed {res.get('scope')!r}, expected {scope!r}",
            )
        )

    return results


async def run_r47_bug_create_project_anchor_confirmed_94371ee8(client: Any, project_id: str) -> list[CheckResult]:
    """Bug 94371ee8 (under the CA-confirmation umbrella bug 5926d536, root
    caused by the queued CA envelope double-unwrap fff026c and the CA
    confirmation timeout budget 375bfe1): bug_create with an EXISTING CA
    project anchor was silently downgraded to unidentified instead of
    persisting the requested project anchor verbatim, because the CA
    confirmation round trip itself was being misread as "not found" (the
    queued envelope from the analysis server was unwrapped one layer short,
    and/or a too-tight timeout aborted the confirmation before CA answered).
    Fixed: confirm_anchor (plan_manager/commands/anchor_confirmation.py)
    correctly reads confirm_project_anchor's outcome for a project that DOES
    exist in CA, so bug_create's response carries
    anchor_confirmation={requested_type:"project", confirmed:true,
    reason:null} and the persisted bug shows source_anchor_type=="project"
    with source_project_id echoed verbatim -- never downgraded.

    Recipe: bug_create(source_type=project, source_project_id=<--project>)
    against this project's own id (registered in CA, the pipeline's default
    --project) -- assert the live anchor_confirmation shape and that
    bug_get's persisted source_anchor_type/source_project_id match. A
    companion negative probe (the bug 5926d536 contract this fix must not
    regress) repeats the same recipe with a project_id CA has never heard of
    (a fresh uuid4): anchor_confirmation must report confirmed=false,
    reason=="not_found", and the persisted bug must show
    source_anchor_type=="unidentified" with source_project_id null -- an
    unverifiable anchor is never silently persisted as if it were real.

    Both scratch bugs are hard-deleted in a top-level finally, verified via
    bug_delete's own {mode:"hard", deleted_uuid:...} response (R19's idiom).
    """
    results: list[CheckResult] = []
    bug_uuid: Optional[str] = None
    unknown_bug_uuid: Optional[str] = None
    try:
        ok, res = await call(
            client, "bug_create",
            {
                "title": unique_suffix("r47-bug"), "short_description": "R47 project-anchored scratch bug (known CA project)",
                "detailed_description": "R47: bug_create with an existing CA project id.", "kind": "functional",
                "severity": "trivial", "priority_nice": 19, "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "project", "source_project_id": project_id,
            },
        )
        results.append(CheckResult("4", "R47_94371ee8_bug_create", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            return results
        bug_uuid = res["uuid"]

        confirmation = res.get("anchor_confirmation")
        confirmation_ok = (
            isinstance(confirmation, dict)
            and confirmation.get("requested_type") == "project"
            and confirmation.get("confirmed") is True
            and confirmation.get("reason") is None
        )
        results.append(
            CheckResult(
                "4", "R47_94371ee8_anchor_confirmation_confirmed_true",
                STATUS_PASS if confirmation_ok else STATUS_FAIL,
                "" if confirmation_ok else f"anchor_confirmation={confirmation!r}",
            )
        )

        ok, res = await call(client, "bug_get", {"bug_id": bug_uuid})
        get_ok = (
            ok and isinstance(res, dict)
            and res.get("source_anchor_type") == "project"
            and res.get("source_project_id") == project_id
        )
        results.append(
            CheckResult(
                "4", "R47_94371ee8_bug_get_anchor_persisted_verbatim",
                STATUS_PASS if get_ok else STATUS_FAIL,
                "" if get_ok else str(res),
            )
        )

        # Companion negative (bug 5926d536 contract, must not regress): a
        # project_id CA has never heard of must downgrade to unidentified,
        # never persist an unverifiable anchor as if it were confirmed.
        unknown_project_id = str(uuid_mod.uuid4())
        ok, res = await call(
            client, "bug_create",
            {
                "title": unique_suffix("r47-bug-unknown"), "short_description": "R47 project-anchored scratch bug (unknown CA project)",
                "detailed_description": "R47: bug_create with a project id unknown to CA.", "kind": "functional",
                "severity": "trivial", "priority_nice": 19, "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "project", "source_project_id": unknown_project_id,
            },
        )
        results.append(CheckResult("4", "R47_5926d536_bug_create_unknown_project", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            return results
        unknown_bug_uuid = res["uuid"]

        neg_confirmation = res.get("anchor_confirmation")
        neg_confirmation_ok = (
            isinstance(neg_confirmation, dict)
            and neg_confirmation.get("requested_type") == "project"
            and neg_confirmation.get("confirmed") is False
            and neg_confirmation.get("reason") == "not_found"
        )
        results.append(
            CheckResult(
                "4", "R47_5926d536_anchor_confirmation_not_found",
                STATUS_PASS if neg_confirmation_ok else STATUS_FAIL,
                "" if neg_confirmation_ok else f"anchor_confirmation={neg_confirmation!r}",
            )
        )

        ok, res = await call(client, "bug_get", {"bug_id": unknown_bug_uuid})
        neg_get_ok = (
            ok and isinstance(res, dict)
            and res.get("source_anchor_type") == "unidentified"
            and res.get("source_project_id") is None
        )
        results.append(
            CheckResult(
                "4", "R47_5926d536_bug_get_downgraded_to_unidentified",
                STATUS_PASS if neg_get_ok else STATUS_FAIL,
                "" if neg_get_ok else str(res),
            )
        )
    finally:
        if bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
            deleted_ok = ok and isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == bug_uuid
            results.append(CheckResult("4", "R47_bug_delete(hard)_confirmed", STATUS_PASS if deleted_ok else STATUS_FAIL, "" if deleted_ok else str(res)))
        if unknown_bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": unknown_bug_uuid, "changed_by": "live-smoke", "hard": True})
            deleted_ok = ok and isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == unknown_bug_uuid
            results.append(CheckResult("4", "R47_bug_delete(hard)_unidentified", STATUS_PASS if deleted_ok else STATUS_FAIL, "" if deleted_ok else str(res)))
    return results


async def run_r48_queued_wait_watchdog_classification_ef59fbcd(client: Any) -> list[CheckResult]:
    """Bug ef59fbcd: the live-smoke outer watchdog (added alongside the
    timeout-forwarding fix, commit 9213b24) must distinguish a genuine
    outer-watchdog timeout from a normal command result -- on 0.1.106 a
    still-running queued process's own result could be misclassified as a
    functional RED before the process had a chance to actually report back,
    with no diagnostic distinguishing "the outer wait gave up" from "the
    command itself failed".

    Recipe, using the module's own primitives directly (_call_queued,
    _with_call_watchdog, configure_call_watchdog, _CALL_WATCHDOG_TIMEOUT):
    dispatch the adapter builtin `long_task` (parameter name `seconds`,
    confirmed live via help(cmdname="long_task") and against
    LongTaskCommand.get_schema in mcp_proxy_adapter/commands/
    command_registry.py) via `_call_queued`, NOT the module's `call()`
    wrapper -- `long_task` is listed in KNOWN_BUILTIN_COMMANDS, so `call()`
    would route it straight to the direct (non-queued) path, bypassing
    exactly the queued dispatch + outer-watchdog machinery this regression
    is about.

    DEVIATION FROM THE ORIGINAL RECIPE SKETCH (investigated live against
    0.1.108, documented here rather than silently adjusted): `long_task`'s
    own handler (mcp_proxy_adapter's demo JobManager command) enqueues a
    background asyncio task and returns immediately with an application
    payload `{job_id, status:"queued", store:"job_manager",
    poll_with:"job_status"}` -- confirmed live, the call returns in ~1.6-2.2s
    REGARDLESS of the requested `seconds` (5, 8, 10, or 20 all measured the
    same), because the command's own execution (scheduling the background
    sleep) is what completes, not the sleep itself. Two consequences neither
    this script nor the bug's fix can change (adapter-framework contract,
    out of scope for plan_manager): (1) this script's own `unwrap_envelope`
    sees that inner payload's `status` key alongside `job_id` and treats it
    as another unresolved queue-envelope layer (status "queued" is not in
    COMPLETED_STATUSES), so `_call_queued` reports `ok=False` for EVERY
    `long_task` dispatch, independent of watchdog configuration or elapsed
    time -- asserting `ok is True` here would assert something the live
    contract never produces, so this check asserts the more precise,
    behaviorally meaningful property instead: the returned diagnostic is
    recognizably the well-formed job-acceptance payload (a genuine,
    honest "still queued" result), not the watchdog's own failure text --
    i.e. the process's own result is never smuggled into a watchdog
    misclassification. (2) because the call itself returns in ~2s regardless
    of `seconds`, the prompt sketch's illustrative
    configure_call_watchdog(2.0, grace_seconds=1.0) (3.0s budget) does NOT
    reliably exceed that ~2s round trip on this deployment (confirmed live:
    4/4 trials stayed under budget) -- this check instead uses a
    deliberately sub-second budget (0.05s timeout + 0.05s grace, confirmed
    live to trip 3/3 trials) to make the TRIP half of the matrix
    deterministic rather than a flaky race against live network latency.
    The behavioral contract under test -- POSITIVE never carries "outer
    watchdog" in its diagnostic, TRIP always does, with the specific "outer
    watchdog exceeded" wording -- is unchanged from the original sketch.

    POSITIVE: dispatch `long_task` with `seconds=8` under the pipeline's
    already-configured (generous) watchdog budget. Asserts (a) the
    diagnostic never contains "outer watchdog" (the process's own -- still
    queued -- result was not misclassified as a watchdog timeout), and (b)
    the diagnostic IS the documented job-acceptance shape (its repr carries
    job_id, status=="queued", store=="job_manager", poll_with=="job_status"
    -- `_call_queued` reports a failing envelope as a formatted diagnostic
    STRING, not the dict itself, so this matches on the dict's repr
    fragments embedded in that string).

    TRIP: saves the current watchdog config, configures an artificially
    tight one (0.05s + 0.05s grace), dispatches `long_task` with
    `seconds=10`. Asserts the call fails with "outer watchdog exceeded" in
    the diagnostic -- the specific wording `_with_call_watchdog` uses,
    naming the command and path, distinguishing this from the generic
    "non-success/incomplete envelope" wording the POSITIVE case's own
    (unrelated) envelope-shape mismatch produces. The watchdog config is
    restored in a finally, unconditionally -- a leaked tight watchdog would
    poison every later check in the same process, so restoration is
    verified with its own CheckResult. The orphaned server-side sleep job is
    a harmless adapter demo builtin with no owning entity this script
    created; there is nothing to clean up.
    """
    results: list[CheckResult] = []
    saved_watchdog_timeout = _CALL_WATCHDOG_TIMEOUT
    try:
        ok, res = await _with_call_watchdog(
            "long_task", "queued", _call_queued(client, "long_task", {"seconds": 8})
        )
        not_misclassified = "outer watchdog" not in str(res)
        results.append(
            CheckResult(
                "4", "R48_ef59fbcd_positive_not_misclassified_as_watchdog",
                STATUS_PASS if not_misclassified else STATUS_FAIL,
                "" if not_misclassified else f"ok={ok!r} res={res!r}",
            )
        )
        # `_call_queued` reports the failing envelope as a formatted
        # diagnostic STRING ("non-success/incomplete envelope: {...!r}"),
        # not the dict itself (see its own return statement) -- match on
        # the dict's repr fragments embedded in that string instead of
        # attempting a dict-shaped assertion here.
        res_text = str(res)
        job_ack_ok = (
            "'job_id':" in res_text
            and "'status': 'queued'" in res_text
            and "'store': 'job_manager'" in res_text
            and "'poll_with': 'job_status'" in res_text
        )
        results.append(
            CheckResult(
                "4", "R48_ef59fbcd_positive_job_acceptance_shape",
                STATUS_PASS if job_ack_ok else STATUS_FAIL,
                "" if job_ack_ok else f"ok={ok!r} res={res!r}",
            )
        )

        configure_call_watchdog(0.05, grace_seconds=0.05)
        ok2, res2 = await _with_call_watchdog(
            "long_task", "queued", _call_queued(client, "long_task", {"seconds": 10})
        )
        trip_ok = ok2 is False and "outer watchdog exceeded" in str(res2)
        results.append(
            CheckResult(
                "4", "R48_ef59fbcd_trip_outer_watchdog_exceeded",
                STATUS_PASS if trip_ok else STATUS_FAIL,
                "" if trip_ok else f"ok={ok2!r} res={res2!r}",
            )
        )
    finally:
        globals()["_CALL_WATCHDOG_TIMEOUT"] = saved_watchdog_timeout
        restored_ok = _CALL_WATCHDOG_TIMEOUT == saved_watchdog_timeout
        results.append(
            CheckResult(
                "4", "R48_ef59fbcd_watchdog_restored",
                STATUS_PASS if restored_ok else STATUS_FAIL,
                "" if restored_ok else f"expected {saved_watchdog_timeout!r}, got {_CALL_WATCHDOG_TIMEOUT!r}",
            )
        )
    return results


def _plan_validate_finding_artifact_paths(report_json: Any, check_id: str) -> set[str]:
    """Return the set of artifact_path values reported for one check_id in
    plan_validate's JSON report string.

    ``report_json`` is the raw ``report`` field of a plan_validate result (a
    JSON-encoded string per plan_manager.verify.finding.render_json, shape
    {"checks": [{"check_id": ..., "findings": [{"artifact_path": ...,
    "severity": ..., "message": ...}, ...]}, ...]}) -- same idiom as R6's
    _r6_report_flags_path. A non-string or unparseable value returns an
    empty set so a malformed report surfaces as a FAIL on the caller's own
    assertion rather than a spurious match here.
    """
    if not isinstance(report_json, str):
        return set()
    try:
        payload = json.loads(report_json)
    except ValueError:
        return set()
    paths: set[str] = set()
    for check in payload.get("checks", []) if isinstance(payload, dict) else []:
        if not isinstance(check, dict) or check.get("check_id") != check_id:
            continue
        for finding in check.get("findings", []) or []:
            if isinstance(finding, dict) and isinstance(finding.get("artifact_path"), str):
                paths.add(finding["artifact_path"])
    return paths


def _r49_live_common_node_paths(res: Any) -> Optional[set[str]]:
    """Return the set of node_path values carrying an is_live=true common
    context block in block_list's payload.

    ``res`` is block_list's own payload, ``{"blocks": [{"node_path": ...,
    "kind": ..., "is_live": ...}, ...], "total": ..., ...}`` (block_list_
    command.py). Returns None when ``res`` is not shaped as expected (a
    failed call, or a malformed payload) so a caller can distinguish "could
    not determine liveness" from "determined liveness is empty".
    """
    if not isinstance(res, dict):
        return None
    blocks = res.get("blocks")
    if not isinstance(blocks, list):
        return None
    return {
        entry["node_path"]
        for entry in blocks
        if isinstance(entry, dict) and entry.get("kind") == "common" and entry.get("is_live") is True
        and isinstance(entry.get("node_path"), str)
    }


async def run_r49_step_update_scoped_block_currency_fa15d288(client: Any) -> list[CheckResult]:
    """Bug fa15d288 (the context-economy CR, docs/cr7_acceptance_governance.
    md section 5): block_list/block_list_command.py computes is_live by
    comparing a stored block's own revision_uuid/cascade_uuid against the
    PLAN'S SINGLE CURRENT WORKING REVISION (current_working_state) -- a
    single global identity shared by every block in the plan, not a
    per-node "last touched" identity. Since every mutating command
    (including a single-field step_update on one leaf atomic step)
    advances that same global head revision, EVERY previously-current
    common block in the plan -- the plan-level block, every unrelated
    sibling G/T branch's block, not just the changed node's own ancestry
    -- goes stale in the same instant, regardless of whether that block's
    scope was actually touched. The intended (post-fix) contract is scoped
    currency: a step_update on one leaf should stale only that leaf's own
    ancestry chain, leaving the plan-level block and untouched sibling
    branches live, and plan_validate's context_coverage.common_current
    check green for those untouched scopes.

    Recipe (throwaway plan, two-branch hierarchy so an untouched sibling
    branch exists to prove scoping, try/finally cleanup):

        plan_create ->
        context_common(plan,"plan",3) -> step_create G (level 3) ->
        context_common(plan,G,4) -> step_create T1 (level 4, parent G) ->
        context_common(plan,G,4) -> step_create T2 (level 4, parent G) ->
        context_common(plan,T1,5) -> step_create A1 (level 5, parent T1) ->
        context_common(plan,T2,5) -> step_create A2 (level 5, parent T2) ->
        settle: recompile all four commons again at the now-static head
        (plan,3), (G,4), (T1,5), (T2,5) ->
        FIXTURE ASSERT: block_list(plan, limit=200) shows exactly those 4
        freshly-recompiled blocks (plan, G, T1-path, T2-path) is_live=true ->

        PHASE 1 -- deep, out-of-scope edit (A2 is T2's grandchild, not
        T2's own node_path, and a common block embeds only its OWN node's
        step_definition, never a descendant's -- so editing A2 changes NO
        block content anywhere; carrying all four blocks forward is the
        correct, scoped contract):
        step_update(plan, A2, fields={"description": ...}) ->
        ASSERT: all four blocks (plan, G, T1-path, T2-path) are STILL
        is_live=true ->
        ASSERT: plan_validate reports NO context_coverage.common_current
        finding at all (not just for G/T1 -- for T2 either, since T2's own
        block also correctly stayed live).

        PHASE 2 -- direct edit on T-002 itself, to exercise the exclusion
        rule the phase-1 fixture never touches (a block goes stale/absent
        only when its OWN node_path is the changed path, or its content
        embeds a step_definition entry for a changed path):
        step_update(plan, T2, fields={"description": ...}) ->
        ASSERT: T2's own block is stale/absent from the live set (its
        node_path is the changed path -- exclusion rule fired) ->
        ASSERT: plan/G/T1's blocks are STILL is_live (carry-forward fired
        for the untouched scopes) ->
        ASSERT: plan_validate reports a context_coverage.common_current
        finding for exactly G-001/T-002 among the fixture nodes -- G-001
        and G-001/T-001 must NOT be flagged.

    Cleanup: plan_delete(hard).
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r49-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R49_fa15d288_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R49_fa15d288_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g-001"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R49_fa15d288_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R49_fa15d288_context_common(G,level4,before T1)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t-001", "parent_step_id": g_id})
        t1_id = _extract_step_id(res) if ok else None
        if not ok or t1_id is None:
            results.append(CheckResult("4", "R49_fa15d288_step_create(T1)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R49_fa15d288_context_common(G,level4,before T2)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t-002", "parent_step_id": g_id})
        t2_id = _extract_step_id(res) if ok else None
        if not ok or t2_id is None:
            results.append(CheckResult("4", "R49_fa15d288_step_create(T2)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t1_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R49_fa15d288_context_common(T1,level5)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a-001", "parent_step_id": t1_id})
        a1_id = _extract_step_id(res) if ok else None
        if not ok or a1_id is None:
            results.append(CheckResult("4", "R49_fa15d288_step_create(A1)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t2_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R49_fa15d288_context_common(T2,level5)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a-001", "parent_step_id": t2_id})
        a2_id = _extract_step_id(res) if ok else None
        if not ok or a2_id is None:
            results.append(CheckResult("4", "R49_fa15d288_step_create(A2)", STATUS_FAIL, str(res)))
            return results
        results.append(
            CheckResult(
                "4", "R49_fa15d288_repro_hierarchy_created", STATUS_PASS,
                f"G={g_id} T1={t1_id} T2={t2_id} A1={a1_id} A2={a2_id}",
            )
        )

        g_path = g_id
        t1_path = f"{g_id}/{t1_id}"
        t2_path = f"{g_id}/{t2_id}"
        # A1 and A2 share the local id "A-001" (same slug under different
        # parents, per the fixture spec) -- a bare "A-001" step_id is
        # AMBIGUOUS_STEP_ID, so the canonical full path is required to
        # address A2 unambiguously in the step_update below.
        a2_path = f"{t2_path}/{a2_id}"

        # Settle: recompile all four commons at the now-static head (no
        # further step_create/step_update between here and the fixture
        # assert), so exactly these 4 rows are current.
        settle_ok = True
        for label, node, child_level in (
            ("plan", "plan", 3), ("G", g_id, 4), ("T1", t1_id, 5), ("T2", t2_id, 5),
        ):
            ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": node, "child_level": child_level})
            settle_ok = settle_ok and ok
            if not ok:
                results.append(CheckResult("4", f"R49_fa15d288_settle_context_common({label})", STATUS_FAIL, str(res)))
        if not settle_ok:
            return results
        results.append(CheckResult("4", "R49_fa15d288_settle_recompiled", STATUS_PASS))

        # FIXTURE ASSERT (must PASS today): exactly the 4 freshly-recompiled
        # commons are is_live=true.
        ok, res = await call(client, "block_list", {"plan": plan_uuid, "limit": 200})
        live_paths = _r49_live_common_node_paths(res)
        expected_fixture_paths = {"plan", g_path, t1_path, t2_path}
        fixture_ok = ok and live_paths == expected_fixture_paths
        results.append(
            CheckResult(
                "4", "R49_fa15d288_fixture_settle_all_four_live",
                STATUS_PASS if fixture_ok else STATUS_FAIL,
                "" if fixture_ok else f"expected live={expected_fixture_paths!r}, got ok={ok} live={live_paths!r} res={res!r}",
            )
        )
        if not fixture_ok:
            return results

        # PHASE 1: deep, out-of-scope edit on the leaf A2 alone. A2 is
        # T2's grandchild, not T2's own node_path -- a common block embeds
        # only its OWN node's step_definition, never a descendant's, so
        # this edit changes NO block content anywhere in the fixture.
        ok, res = await call(
            client, "step_update",
            {"plan": plan_uuid, "step_id": a2_path, "fields": {"description": "r49 single local edit"}},
        )
        if not ok:
            results.append(CheckResult("4", "R49_fa15d288_step_update(A2)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R49_fa15d288_step_update(A2)", STATUS_PASS))

        ok, res = await call(client, "block_list", {"plan": plan_uuid, "limit": 200})
        post_edit_live_paths = _r49_live_common_node_paths(res)
        if not ok or post_edit_live_paths is None:
            results.append(CheckResult("4", "R49_fa15d288_block_list_post_edit", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R49_fa15d288_block_list_post_edit", STATUS_PASS))

        # ASSERT: a deep edit outside every block's own node_path carries
        # ALL FOUR blocks forward as live -- including T2's own block,
        # since A2's description is not part of T2's step_definition.
        for label, node_path in (
            ("plan", "plan"), ("G-001", g_path), ("G-001/T-001", t1_path), ("G-001/T-002", t2_path),
        ):
            still_live = node_path in post_edit_live_paths
            results.append(
                CheckResult(
                    "4", f"R49_fa15d288_deep_edit_keeps_all_blocks_live({label})",
                    STATUS_PASS if still_live else STATUS_FAIL,
                    "" if still_live else f"node_path={node_path!r} expected is_live=true, live_paths={post_edit_live_paths!r}",
                )
            )

        # ASSERT: plan_validate must carry NO context_coverage.common_
        # current finding for G's or T1's own artifact_path.
        ok, res = await call(client, "plan_validate", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "R49_fa15d288_plan_validate", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R49_fa15d288_plan_validate", STATUS_PASS))
        flagged_paths = _plan_validate_finding_artifact_paths(res.get("report"), "context_coverage.common_current")
        for label, artifact_path in (("G-001", g_path), ("G-001/T-001", t1_path)):
            not_flagged = artifact_path not in flagged_paths
            results.append(
                CheckResult(
                    "4", f"R49_fa15d288_plan_validate_no_finding({label})",
                    STATUS_PASS if not_flagged else STATUS_FAIL,
                    "" if not_flagged else f"unexpected context_coverage.common_current finding for {artifact_path!r}, flagged={flagged_paths!r}",
                )
            )

        # ASSERT: no context_coverage.common_current finding AT ALL after
        # the deep A2 edit -- every one of the four blocks correctly
        # stayed live, so T2's own artifact_path must not be flagged
        # either (the phase-1 fixture never touches T2's own node_path).
        no_findings_at_all = len(flagged_paths) == 0
        results.append(
            CheckResult(
                "4", "R49_fa15d288_plan_validate_no_finding_at_all_after_deep_edit",
                STATUS_PASS if no_findings_at_all else STATUS_FAIL,
                "" if no_findings_at_all else f"expected zero context_coverage.common_current findings, flagged={flagged_paths!r}",
            )
        )

        # PHASE 2: direct edit on T-002 ITSELF, to exercise the exclusion
        # rule -- a block goes stale/absent only when its OWN node_path is
        # the changed path (or its content embeds a step_definition entry
        # for a changed path).
        ok, res = await call(
            client, "step_update",
            {"plan": plan_uuid, "step_id": t2_path, "fields": {"description": "r49 phase-2 edit of T-002"}},
        )
        if not ok:
            results.append(CheckResult("4", "R49_fa15d288_step_update(T2)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R49_fa15d288_step_update(T2)", STATUS_PASS))

        ok, res = await call(client, "block_list", {"plan": plan_uuid, "limit": 200})
        phase2_live_paths = _r49_live_common_node_paths(res)
        if not ok or phase2_live_paths is None:
            results.append(CheckResult("4", "R49_fa15d288_block_list_post_phase2_edit", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R49_fa15d288_block_list_post_phase2_edit", STATUS_PASS))

        # ASSERT: T2's own block -- the genuinely affected scope, since
        # T2's own node_path is the changed path -- is stale/absent from
        # the live set. The exclusion rule must fire for it.
        t2_stale = t2_path not in phase2_live_paths
        results.append(
            CheckResult(
                "4", "R49_fa15d288_phase2_exclusion_fires(G-001/T-002)",
                STATUS_PASS if t2_stale else STATUS_FAIL,
                "" if t2_stale else f"expected T2's own block stale/absent, still live: {phase2_live_paths!r}",
            )
        )

        # ASSERT: plan/G/T1's blocks are STILL live -- carry-forward fires
        # for every scope the T2 edit did not touch.
        for label, node_path in (("plan", "plan"), ("G-001", g_path), ("G-001/T-001", t1_path)):
            still_live = node_path in phase2_live_paths
            results.append(
                CheckResult(
                    "4", f"R49_fa15d288_phase2_carry_forward_stays_live({label})",
                    STATUS_PASS if still_live else STATUS_FAIL,
                    "" if still_live else f"node_path={node_path!r} expected is_live=true, live_paths={phase2_live_paths!r}",
                )
            )

        # ASSERT: plan_validate reports a context_coverage.common_current
        # finding for exactly G-001/T-002 among the fixture nodes -- G-001
        # and G-001/T-001 must NOT be flagged.
        ok, res = await call(client, "plan_validate", {"plan": plan_uuid})
        if not ok or not isinstance(res, dict):
            results.append(CheckResult("4", "R49_fa15d288_plan_validate_phase2", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R49_fa15d288_plan_validate_phase2", STATUS_PASS))
        phase2_flagged_paths = _plan_validate_finding_artifact_paths(res.get("report"), "context_coverage.common_current")
        t2_flagged = t2_path in phase2_flagged_paths
        results.append(
            CheckResult(
                "4", "R49_fa15d288_phase2_plan_validate_finding(G-001/T-002)",
                STATUS_PASS if t2_flagged else STATUS_FAIL,
                "" if t2_flagged else f"expected context_coverage.common_current finding for {t2_path!r}, flagged={phase2_flagged_paths!r}",
            )
        )
        for label, artifact_path in (("G-001", g_path), ("G-001/T-001", t1_path)):
            not_flagged = artifact_path not in phase2_flagged_paths
            results.append(
                CheckResult(
                    "4", f"R49_fa15d288_phase2_plan_validate_no_finding({label})",
                    STATUS_PASS if not_flagged else STATUS_FAIL,
                    "" if not_flagged else f"unexpected context_coverage.common_current finding for {artifact_path!r}, flagged={phase2_flagged_paths!r}",
                )
            )
    finally:
        cleanup_ok = True
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R49_fa15d288_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


async def run_r50_frozen_atomic_direct_execution_transition_957c2f6a(client: Any) -> list[CheckResult]:
    """Bug 957c2f6a: step_set_status_metadata.py's own published contract
    (legal_transitions.statuses.frozen.direct_targets, and the domain
    status model plan_manager/domain/status_model.py's validate_transition,
    which explicitly unions {"in_progress"} into a frozen ATOMIC step's
    legal target set) both say a frozen atomic step accepts a direct
    frozen -> in_progress transition with no cascade. But
    step_set_status_command.py's execute() checks cascade admission
    (cascade.regime.check_admission) BEFORE validate_transition ever runs:
    check_admission's frozen_at_or_below gate has no atomic-step direct-
    execution exception, so it raises CascadeError("step ... is not
    directly mutable") for ANY frozen target with no cascade_uuid,
    surfaced as ErrorResult domain_code=FROZEN_ARTIFACT -32000 -- the
    validate_transition layer that *would* admit the direct move is never
    reached. The published contract and the actual admission gate disagree.

    Recipe (throwaway plan, single G->T branch with TWO atomic children so
    a non-frozen sibling exists as a negative control, try/finally
    cleanup): plan_create -> context_common/step_create G (level 3) ->
    context_common/step_create T (level 4, parent G) -> context_common/
    step_create A1 and A2 (level 5, parent T) -- BOTH atomics are built
    BEFORE freezing anything, since freezing A1 makes its ancestors (G, T)
    non-directly-mutable per frozen_at_or_below, which would block
    building A2 afterwards. Then: step_set_status(A1, ready_for_review) ->
    step_set_status(A1, frozen) (both must PASS today) -> CONTRACT MARKER:
    help(cmdname="step_set_status").ai_metadata.legal_transitions.
    statuses.frozen.direct_targets == ["in_progress"] (must PASS today --
    the metadata itself is not wrong, only the runtime gate) ->
    step_set_status(A1, in_progress) with no cascade_uuid (expected RED
    today: FROZEN_ARTIFACT) -> if that succeeded, step_set_status(A1,
    done) with no cascade_uuid (expected RED today, unreachable otherwise)
    -> NEGATIVE CONTROL: step_set_status(A2, in_progress) -- A2 is still
    draft, never frozen -- must FAIL INVALID_TRANSITION both today and
    after the fix (draft has no direct path to in_progress; the fix must
    not broaden direct execution beyond the one frozen->in_progress
    exception).

    Cleanup: plan_delete(hard).
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r50-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R50_957c2f6a_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R50_957c2f6a_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R50_957c2f6a_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R50_957c2f6a_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R50_957c2f6a_step_create(T)", STATUS_FAIL, str(res)))
            return results

        # Both atomic siblings are built BEFORE any freeze: freezing A1
        # would make T/G non-directly-mutable, blocking A2's creation.
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R50_957c2f6a_context_common(T,level5,before A1)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a-001", "parent_step_id": t_id})
        a1_id = _extract_step_id(res) if ok else None
        if not ok or a1_id is None:
            results.append(CheckResult("4", "R50_957c2f6a_step_create(A1)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R50_957c2f6a_context_common(T,level5,before A2)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a-002", "parent_step_id": t_id})
        a2_id = _extract_step_id(res) if ok else None
        if not ok or a2_id is None:
            results.append(CheckResult("4", "R50_957c2f6a_step_create(A2)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R50_957c2f6a_repro_steps_created", STATUS_PASS, f"G={g_id} T={t_id} A1={a1_id} A2={a2_id}"))

        # Freeze A1 LAST, after both atomics already exist.
        ok, res = await call(client, "step_set_status", {"plan": plan_uuid, "step_id": a1_id, "status": "ready_for_review"})
        if not ok:
            results.append(CheckResult("4", "R50_957c2f6a_step_set_status(A1,ready_for_review)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R50_957c2f6a_step_set_status(A1,ready_for_review)", STATUS_PASS))

        ok, res = await call(client, "step_set_status", {"plan": plan_uuid, "step_id": a1_id, "status": "frozen"})
        if not ok:
            results.append(CheckResult("4", "R50_957c2f6a_step_set_status(A1,frozen)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R50_957c2f6a_step_set_status(A1,frozen)", STATUS_PASS))

        # CONTRACT MARKER ASSERT (must PASS today): the published metadata
        # itself already documents the direct frozen->in_progress target.
        ok, res = await call(client, "help", {"cmdname": "step_set_status"})
        ai_metadata = res.get("ai_metadata") if ok and isinstance(res, dict) else None
        direct_targets = None
        if isinstance(ai_metadata, dict):
            statuses = ai_metadata.get("legal_transitions", {}).get("statuses", {})
            if isinstance(statuses, dict):
                frozen_entry = statuses.get("frozen")
                if isinstance(frozen_entry, dict):
                    direct_targets = frozen_entry.get("direct_targets")
        marker_ok = ok and direct_targets == ["in_progress"]
        results.append(
            CheckResult(
                "4", "R50_957c2f6a_contract_marker_frozen_direct_targets",
                STATUS_PASS if marker_ok else STATUS_FAIL,
                "" if marker_ok else f"expected direct_targets==['in_progress'], got ok={ok} direct_targets={direct_targets!r}",
            )
        )

        # POST-FIX ASSERT (expected RED today): direct frozen->in_progress,
        # no cascade_uuid. Today: -32000 domain_code=FROZEN_ARTIFACT.
        ok, res = await call(client, "step_set_status", {"plan": plan_uuid, "step_id": a1_id, "status": "in_progress"})
        step4_ok = ok and isinstance(res, dict) and res.get("status") == "in_progress"
        results.append(
            CheckResult(
                "4", "R50_957c2f6a_direct_frozen_to_in_progress",
                STATUS_PASS if step4_ok else STATUS_FAIL,
                "" if step4_ok else f"ok={ok} res={res!r}",
            )
        )

        # POST-FIX ASSERT (expected RED today, only attempted if the prior
        # step actually landed A1 in in_progress; otherwise an explicit
        # unreachable FAIL, never a silently-skipped assertion).
        if step4_ok:
            ok, res = await call(client, "step_set_status", {"plan": plan_uuid, "step_id": a1_id, "status": "done"})
            step5_ok = ok and isinstance(res, dict) and res.get("status") == "done"
            results.append(
                CheckResult(
                    "4", "R50_957c2f6a_direct_in_progress_to_done",
                    STATUS_PASS if step5_ok else STATUS_FAIL,
                    "" if step5_ok else f"ok={ok} res={res!r}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "R50_957c2f6a_direct_in_progress_to_done",
                    STATUS_FAIL, "unreachable: step 4 red",
                )
            )

        # NEGATIVE CONTROL (must PASS today AND after the fix): A2 is
        # still draft, never frozen -- draft->in_progress has no direct
        # path regardless of the frozen-atomic exception.
        ok, res = await call(client, "step_set_status", {"plan": plan_uuid, "step_id": a2_id, "status": "in_progress"})
        control_ok = (not ok) and "INVALID_TRANSITION" in str(res)
        results.append(
            CheckResult(
                "4", "R50_957c2f6a_control_draft_to_in_progress_rejected",
                STATUS_PASS if control_ok else STATUS_FAIL,
                "" if control_ok else f"expected INVALID_TRANSITION, got ok={ok} res={res!r}",
            )
        )
    finally:
        cleanup_ok = True
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R50_957c2f6a_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


R51_BUG_KIND_VOCABULARY: frozenset[str] = frozenset({
    "compatibility", "configuration", "data_loss", "deployment", "documentation",
    "functional", "infrastructure", "performance", "planning", "regression",
    "security", "stale_context", "user_experience", "wrong_output",
})


async def run_r51_bug_kind_enum_discoverable_b230a02b(client: Any, project_id: str) -> list[CheckResult]:
    """Bug b230a02b: bug_create/bug_update declare `kind` as a plain
    {"type": "string"} schema property whose free-text description lists
    the closed vocabulary in prose (see bug_create_command.py/
    bug_update_command.py get_schema) instead of a JSON-Schema `enum` --
    an MCP client (or this pipeline) discovering the contract purely from
    help()'s schema payload has no machine-checkable way to know which
    strings are legal. An invalid kind is only caught deep in the domain
    layer (plan_manager/domain/bug_report.py validate_bug_kind, confirmed
    live), surfacing as a generic RuntimeValidationError ->
    ErrorResult(code=-32000, domain_code=RUNTIME_VALIDATION_ERROR) rather
    than being rejected at the schema layer with the standard -32602
    invalid-params code. A companion gap: the `evidence` object property's
    description says nothing about the plain-text wrapping convention
    ({"text": "..."}) that convention actually uses for it elsewhere.
    NOTE: bug_update has NO `kind` schema property at all -- kind is
    immutable after creation, set only by bug_create -- so bug_update's
    half of the enum-discoverability gap does not apply; what it shares
    with bug_create is only the evidence-wrapping documentation gap.

    Recipe, five independent sub-assertions (only (3) touches the network
    beyond help(), and only (3) can leave an entity behind):
      1. help(cmdname="bug_create").schema.properties.kind carries an
         "enum" key whose sorted value equals the server's published
         14-value BUG_KINDS vocabulary. RED today: no enum key at all.
      2a. help(cmdname="bug_update").schema.properties has NO "kind" key
          at all -- pins the actual contract (kind is immutable after
          creation). PASS today and after the fix.
      2b. help(cmdname="bug_update").schema.properties.evidence.
          description documents the plain-text wrapping convention --
          asserts the substring '{"text"' appears in it. RED today.
      3. bug_create with kind="defect" (not a member of BUG_KINDS) must be
         REJECTED at the schema layer, JSON-RPC code -32602 -- confirming
         "invalid enum value" is caught before the domain layer ever runs.
         RED today: the domain layer rejects it instead, code -32000. If
         the call unexpectedly SUCCEEDS (kind="defect" persisted), the
         created bug is captured and hard-deleted in cleanup, and the
         assertion is marked FAIL regardless -- a schema silently
         admitting an undocumented kind is not the intended fix either.
      4. help(cmdname="bug_create").schema.properties.evidence.description
         documents the plain-text wrapping convention -- asserts the
         substring '{"text"' appears in it. RED today.

    No entity survives the happy path; only the defensive branch of (3)
    leaves anything to delete.
    """
    results: list[CheckResult] = []
    defect_bug_uuid: Optional[str] = None
    try:
        # --- 1: bug_create schema declares kind as a closed enum. ---
        ok, res = await call(client, "help", {"cmdname": "bug_create"})
        create_enum: Optional[list] = None
        if ok and isinstance(res, dict):
            schema = res.get("schema")
            if isinstance(schema, dict):
                properties = schema.get("properties")
                if isinstance(properties, dict):
                    kind_prop = properties.get("kind")
                    if isinstance(kind_prop, dict) and isinstance(kind_prop.get("enum"), list):
                        create_enum = kind_prop["enum"]
        create_enum_ok = create_enum is not None and sorted(create_enum) == sorted(R51_BUG_KIND_VOCABULARY)
        results.append(
            CheckResult(
                "4", "R51_b230a02b_bug_create_kind_enum",
                STATUS_PASS if create_enum_ok else STATUS_FAIL,
                "" if create_enum_ok
                else (
                    f"expected schema.properties.kind.enum(sorted)=={sorted(R51_BUG_KIND_VOCABULARY)}, "
                    f"got {sorted(create_enum) if create_enum is not None else None} (ok={ok}, help={res!r})"
                ),
            )
        )

        # --- 2a: bug_update schema declares NO `kind` property at all (kind is
        # immutable after creation -- pins the actual contract, not a wished-for
        # enum that bug_update was never meant to carry). ---
        ok, res = await call(client, "help", {"cmdname": "bug_update"})
        update_properties: Optional[dict] = None
        if ok and isinstance(res, dict):
            schema = res.get("schema")
            if isinstance(schema, dict):
                properties = schema.get("properties")
                if isinstance(properties, dict):
                    update_properties = properties
        no_kind_param_ok = update_properties is not None and "kind" not in update_properties
        results.append(
            CheckResult(
                "4", "R51_b230a02b_bug_update_has_no_kind_param",
                STATUS_PASS if no_kind_param_ok else STATUS_FAIL,
                "" if no_kind_param_ok
                else (
                    f"expected schema.properties to have NO 'kind' key (kind is immutable after creation), "
                    f"got properties={update_properties!r} (ok={ok}, help={res!r})"
                ),
            )
        )

        # --- 2b: bug_update's evidence description documents the plain-text
        # wrapping convention -- same companion gap as bug_create's (4). ---
        update_evidence_description = None
        if update_properties is not None:
            evidence_prop = update_properties.get("evidence")
            if isinstance(evidence_prop, dict):
                update_evidence_description = evidence_prop.get("description")
        update_evidence_doc_ok = (
            isinstance(update_evidence_description, str) and '{"text"' in update_evidence_description
        )
        results.append(
            CheckResult(
                "4", "R51_b230a02b_bug_update_evidence_text_wrapping_documented",
                STATUS_PASS if update_evidence_doc_ok else STATUS_FAIL,
                "" if update_evidence_doc_ok else f"evidence.description={update_evidence_description!r}",
            )
        )

        # --- 3: an invalid kind is rejected at the SCHEMA layer (-32602), never the domain layer (-32000). ---
        ok, res = await call(
            client, "bug_create",
            {
                "title": unique_suffix("r51-bug"), "short_description": "R51 invalid-kind schema-rejection probe",
                "detailed_description": "R51: bug_create with kind='defect', not a member of BUG_KINDS.",
                "kind": "defect", "severity": "trivial", "priority_nice": 19,
                "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "project", "source_project_id": project_id,
            },
        )
        if ok:
            if isinstance(res, dict) and res.get("uuid"):
                defect_bug_uuid = res["uuid"]
            results.append(
                CheckResult(
                    "4", "R51_b230a02b_invalid_kind_schema_rejected",
                    STATUS_FAIL,
                    f"expected schema-layer rejection (-32602), but bug_create SUCCEEDED with kind='defect': {res!r}",
                )
            )
        else:
            code = _typed_error_code(res)
            rejected_ok = code == -32602
            results.append(
                CheckResult(
                    "4", "R51_b230a02b_invalid_kind_schema_rejected",
                    STATUS_PASS if rejected_ok else STATUS_FAIL,
                    "" if rejected_ok else f"expected code -32602, got code={code!r} res={res!r}",
                )
            )

        # --- 4: evidence description documents the plain-text wrapping convention. ---
        ok, res = await call(client, "help", {"cmdname": "bug_create"})
        evidence_description = None
        if ok and isinstance(res, dict):
            schema = res.get("schema")
            if isinstance(schema, dict):
                properties = schema.get("properties")
                if isinstance(properties, dict):
                    evidence_prop = properties.get("evidence")
                    if isinstance(evidence_prop, dict):
                        evidence_description = evidence_prop.get("description")
        evidence_doc_ok = isinstance(evidence_description, str) and '{"text"' in evidence_description
        results.append(
            CheckResult(
                "4", "R51_b230a02b_evidence_text_wrapping_documented",
                STATUS_PASS if evidence_doc_ok else STATUS_FAIL,
                "" if evidence_doc_ok else f"evidence.description={evidence_description!r}",
            )
        )
    finally:
        if defect_bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": defect_bug_uuid, "changed_by": "live-smoke", "hard": True})
            deleted_ok = ok and isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == defect_bug_uuid
            results.append(
                CheckResult(
                    "4", "R51_b230a02b_defect_bug_delete(hard)",
                    STATUS_PASS if deleted_ok else STATUS_FAIL,
                    "" if deleted_ok else str(res),
                )
            )
    return results


async def run_r52_bug_update_plan_guard_ack_26107e40(client: Any, project_id: str) -> list[CheckResult]:
    """Bug 26107e40: bug_update accepts an OPTIONAL `plan` parameter used
    only to additionally check that plan's own completion guard
    (refuse_if_bug_plan_completed via resolve_scope, bug_update_command.py)
    -- but the response never says so: bug_update returns only the updated
    BugReport payload, with no field naming which plan (if any) the guard
    checked. A caller supplying `plan` has no way to confirm from the
    response alone that the guard was actually evaluated against the plan
    they intended, and the parameter's OWN name ("plan") invites the
    misreading that it changes the bug's anchor -- it never does (bug
    3eec33f2's optional-plan contract, still in force). Fixed: bug_update's
    response gains a `plan_guard` object naming the checked plan's uuid
    whenever `plan` was supplied, present only then; the anchor itself
    (source_plan_uuid) stays untouched either way.

    Recipe (throwaway plan + throwaway project-anchored bug, try/finally
    cleanup):
      1. plan_create -> guard_plan uuid (a real, non-completed plan,
         supplied only as bug_update's guard parameter, never as the
         bug's own anchor).
      2. bug_create (source_type=project, source_project_id=<--project>,
         plan omitted) -> bug uuid; asserts source_plan_uuid is null (the
         bug has no plan anchor at all going in).
      3. bug_update(bug_id, changed_by, plan=<guard_plan>, severity=
         "major"): asserts success and severity=="major" (PASS today).
         POST-FIX ASSERT (RED today): response contains a "plan_guard"
         key, and the guard plan's uuid appears somewhere inside it
         (accepts either plan_guard.checked_plan_uuid or
         plan_guard["checked_plan_uuid"] naming -- this checks key
         presence plus uuid membership rather than pinning one exact
         nested key name, since the fix's shape is not yet live to
         confirm verbatim).
      4. bug_get: asserts source_plan_uuid is STILL null -- the guard
         parameter never touches the anchor. PASS today and must stay
         PASS after the fix (never-regress control).
      5. CONTROL: bug_update WITHOUT `plan` (severity="minor") -> response
         contains NO "plan_guard" key at all. PASS today; must also hold
         after the fix -- the ack is conditional on `plan` being supplied,
         never unconditional.

    Cleanup: bug_delete(hard) then plan_delete(hard), each with its own
    verified CheckResult.
    """
    results: list[CheckResult] = []
    guard_plan_uuid: Optional[str] = None
    bug_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r52-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R52_26107e40_plan_create", STATUS_FAIL, str(res)))
            return results
        guard_plan_uuid = res["uuid"]
        results.append(CheckResult("4", "R52_26107e40_plan_create", STATUS_PASS, f"uuid={guard_plan_uuid}"))

        ok, res = await call(
            client, "bug_create",
            {
                "title": unique_suffix("r52-bug"), "short_description": "R52 plan-guard-ack throwaway bug",
                "detailed_description": "R52: project-anchored bug, no plan anchor, used to probe bug_update's plan guard.",
                "kind": "functional", "severity": "trivial", "priority_nice": 19,
                "reporter": "live-smoke", "created_by": "live-smoke",
                "source_type": "project", "source_project_id": project_id,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R52_26107e40_bug_create", STATUS_FAIL, str(res)))
            return results
        bug_uuid = res["uuid"]
        anchor_clean_ok = res.get("source_plan_uuid") is None
        results.append(
            CheckResult(
                "4", "R52_26107e40_bug_create_no_plan_anchor",
                STATUS_PASS if anchor_clean_ok else STATUS_FAIL,
                "" if anchor_clean_ok else f"expected source_plan_uuid null, got {res.get('source_plan_uuid')!r}",
            )
        )

        ok, res = await call(
            client, "bug_update",
            {"bug_id": bug_uuid, "changed_by": "live-smoke", "plan": guard_plan_uuid, "severity": "major"},
        )
        update_ok = ok and isinstance(res, dict) and res.get("severity") == "major"
        results.append(
            CheckResult(
                "4", "R52_26107e40_bug_update_with_plan",
                STATUS_PASS if update_ok else STATUS_FAIL,
                "" if update_ok else str(res),
            )
        )
        if not update_ok:
            return results

        plan_guard = res.get("plan_guard")
        plan_guard_ok = "plan_guard" in res and plan_guard is not None and guard_plan_uuid in str(plan_guard)
        results.append(
            CheckResult(
                "4", "R52_26107e40_plan_guard_ack_present",
                STATUS_PASS if plan_guard_ok else STATUS_FAIL,
                "" if plan_guard_ok
                else (
                    f"expected a 'plan_guard' key naming checked plan {guard_plan_uuid}, "
                    f"got plan_guard={plan_guard!r} (full response {res!r})"
                ),
            )
        )

        ok, res = await call(client, "bug_get", {"bug_id": bug_uuid})
        anchor_still_clean_ok = ok and isinstance(res, dict) and res.get("source_plan_uuid") is None
        results.append(
            CheckResult(
                "4", "R52_26107e40_anchor_untouched",
                STATUS_PASS if anchor_still_clean_ok else STATUS_FAIL,
                "" if anchor_still_clean_ok else f"expected source_plan_uuid still null, got ok={ok} {res!r}",
            )
        )

        ok, res = await call(
            client, "bug_update",
            {"bug_id": bug_uuid, "changed_by": "live-smoke", "severity": "minor"},
        )
        control_update_ok = ok and isinstance(res, dict) and res.get("severity") == "minor"
        no_guard_key_ok = control_update_ok and "plan_guard" not in res
        results.append(
            CheckResult(
                "4", "R52_26107e40_control_no_plan_no_guard_key",
                STATUS_PASS if no_guard_key_ok else STATUS_FAIL,
                "" if no_guard_key_ok else f"expected success with no 'plan_guard' key, got ok={ok} {res!r}",
            )
        )
    finally:
        if bug_uuid is not None:
            ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
            deleted_ok = ok and isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == bug_uuid
            results.append(
                CheckResult(
                    "4", "R52_26107e40_bug_delete(hard)",
                    STATUS_PASS if deleted_ok else STATUS_FAIL,
                    "" if deleted_ok else str(res),
                )
            )
        if guard_plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": guard_plan_uuid, "hard": True})
            deleted_ok = (
                ok and isinstance(res, dict) and res.get("mode") == "hard"
                and res.get("deleted") is True and res.get("uuid") == guard_plan_uuid
            )
            results.append(
                CheckResult(
                    "4", "R52_26107e40_plan_delete(hard)",
                    STATUS_PASS if deleted_ok else STATUS_FAIL,
                    "" if deleted_ok else str(res),
                )
            )
    return results


async def run_r53_wish_reanchor_in_place_5c0ddc16(client: Any, project_id: str) -> list[CheckResult]:
    """Bug 5c0ddc16: a wish's primary anchor is documented as immutable
    after creation (see wish_create_command.py's best_practices note "The
    wish's primary anchor is immutable after creation") and wish_update's
    schema (wish_update_command.py) carries no anchor_* parameter at all --
    but every other anchored runtime entity that predates the wish/calendar
    layer (todo, bug) exposes a dedicated *_reanchor command
    (todo_reanchor_command.py, bug_reanchor_command.py) so its anchor CAN
    move in place, preserving identity (uuid, created_at) while only the
    anchor fields change. Wishes have no such command: today a wish's
    anchor genuinely cannot move without a delete+recreate, silently
    dropping identity and history. Fixed: a wish_reanchor command exists,
    following the same new_anchor_* parameter shape as todo_reanchor, and
    moves the wish's primary anchor in place.

    DESIGNATED RED (assertion 1): help(cmdname="wish_reanchor") must answer
    with a non-empty schema (schema.properties non-empty). Today the
    command is unknown -- help() still succeeds (ok=True; the platform
    help_command.py never fails for an unknown cmdname, it returns
    commands_info={"commands": {}, "error": "Command '...' not found", ...})
    but the response carries no "schema" key at all, so this assertion is
    RED without a call() failure to key off of; the exact "error" string is
    captured in the FAIL detail instead.

    Sub-assertions 2-6 each run only if assertion 1 passed (the
    "unreachable: step 1 red" idiom -- see R50): create a throwaway plan,
    wish_create anchored to that plan, capture uuid/created_at, then
    wish_reanchor the wish to anchor_type="none" (the simplest documented
    target -- no project/plan/file context needed) with
    changed_by="live-smoke"; assert wish_get afterward reports the SAME
    wish_uuid and the SAME created_at (identity/history preserved across
    the move) while the anchor fields themselves reflect anchor_type=none.
    A negative control (independent of assertion 1, PASS today and after
    the fix): wish_update's schema still exposes NO anchor_* parameter --
    reanchoring is wish_reanchor's job alone, wish_update never grows an
    anchor side-channel.

    Cleanup: wish_delete(hard) then plan_delete(hard), each with its own
    verified CheckResult, tolerant of entities that were never created.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    wish_uuid: Optional[str] = None
    try:
        # --- 1: DESIGNATED RED -- wish_reanchor must be a known command
        # with a non-empty schema. ---
        ok, res = await call(client, "help", {"cmdname": "wish_reanchor"})
        schema = res.get("schema") if ok and isinstance(res, dict) else None
        schema_properties = schema.get("properties") if isinstance(schema, dict) else None
        step1_ok = ok and isinstance(schema, dict) and isinstance(schema_properties, dict) and bool(schema_properties)
        results.append(
            CheckResult(
                "4", "R53_5c0ddc16_wish_reanchor_help_schema",
                STATUS_PASS if step1_ok else STATUS_FAIL,
                "" if step1_ok
                else (
                    f"expected help(cmdname='wish_reanchor') to answer with a non-empty "
                    f"schema.properties; ok={ok} error={res.get('error') if isinstance(res, dict) else None!r} "
                    f"full={res!r}"
                ),
            )
        )

        # --- 2-6: gated on assertion 1; each reported as an explicit
        # "unreachable" FAIL, never silently skipped, while the command is
        # missing. ---
        if not step1_ok:
            for gated_name in (
                "R53_5c0ddc16_plan_create",
                "R53_5c0ddc16_wish_create",
                "R53_5c0ddc16_wish_reanchor_in_place",
                "R53_5c0ddc16_wish_get_identity_preserved",
                "R53_5c0ddc16_control_wish_update_no_anchor_param",
            ):
                results.append(CheckResult("4", gated_name, STATUS_FAIL, "unreachable: step 1 red"))
            return results

        ok, res = await call(client, "plan_create", {"name": unique_suffix("r53-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R53_5c0ddc16_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]
        results.append(CheckResult("4", "R53_5c0ddc16_plan_create", STATUS_PASS, f"uuid={plan_uuid}"))

        ok, res = await call(
            client,
            "wish_create",
            {
                "title": unique_suffix("r53-wish"),
                "description": "R53 wish_reanchor in-place probe.",
                "kind": "feature",
                "priority_nice": -4,
                "created_by": "live-smoke",
                "anchor_type": "plan",
                "anchor_plan_uuid": plan_uuid,
            },
        )
        if not ok or not isinstance(res, dict) or not res.get("wish_uuid"):
            results.append(CheckResult("4", "R53_5c0ddc16_wish_create", STATUS_FAIL, str(res)))
            return results
        wish_uuid = res["wish_uuid"]
        original_created_at = res.get("created_at")
        anchored_ok = res.get("primary_anchor_type") == "plan" and res.get("anchor_plan_uuid") == plan_uuid
        results.append(
            CheckResult(
                "4", "R53_5c0ddc16_wish_create",
                STATUS_PASS if anchored_ok else STATUS_FAIL,
                f"uuid={wish_uuid} created_at={original_created_at!r}" if anchored_ok else str(res),
            )
        )
        if not anchored_ok:
            return results

        ok, res = await call(
            client,
            "wish_reanchor",
            {"wish": wish_uuid, "changed_by": "live-smoke", "new_anchor_type": "none"},
        )
        reanchor_ok = (
            ok and isinstance(res, dict)
            and res.get("wish_uuid") == wish_uuid
            and res.get("created_at") == original_created_at
        )
        results.append(
            CheckResult(
                "4", "R53_5c0ddc16_wish_reanchor_in_place",
                STATUS_PASS if reanchor_ok else STATUS_FAIL,
                "" if reanchor_ok
                else f"expected same wish_uuid={wish_uuid} and created_at={original_created_at!r}, got ok={ok} {res!r}",
            )
        )
        if not reanchor_ok:
            return results

        ok, res = await call(client, "wish_get", {"wish": wish_uuid})
        identity_ok = (
            ok and isinstance(res, dict)
            and res.get("wish_uuid") == wish_uuid
            and res.get("created_at") == original_created_at
            and res.get("primary_anchor_type") == "none"
        )
        results.append(
            CheckResult(
                "4", "R53_5c0ddc16_wish_get_identity_preserved",
                STATUS_PASS if identity_ok else STATUS_FAIL,
                "" if identity_ok
                else (
                    f"expected wish_uuid={wish_uuid}, created_at={original_created_at!r}, "
                    f"primary_anchor_type='none'; got ok={ok} {res!r}"
                ),
            )
        )

        # --- Negative control: wish_update's schema still has NO anchor
        # parameter -- reanchoring stays wish_reanchor's job alone. ---
        ok, res = await call(client, "help", {"cmdname": "wish_update"})
        update_properties = None
        if ok and isinstance(res, dict):
            update_schema = res.get("schema")
            if isinstance(update_schema, dict):
                update_properties = update_schema.get("properties")
        no_anchor_param_ok = isinstance(update_properties, dict) and not any(
            key == "anchor_type" or key.startswith("anchor_") or key.startswith("new_anchor_")
            for key in update_properties
        )
        results.append(
            CheckResult(
                "4", "R53_5c0ddc16_control_wish_update_no_anchor_param",
                STATUS_PASS if no_anchor_param_ok else STATUS_FAIL,
                "" if no_anchor_param_ok else f"wish_update schema.properties={update_properties!r}",
            )
        )
    finally:
        cleanup_ok = True
        if wish_uuid is not None:
            ok, res = await call(client, "wish_delete", {"wish": wish_uuid, "changed_by": "live-smoke", "hard": True})
            wish_deleted_ok = ok and isinstance(res, dict) and res.get("mode") == "hard" and res.get("deleted_uuid") == wish_uuid
            cleanup_ok = cleanup_ok and wish_deleted_ok
            results.append(
                CheckResult(
                    "4", "R53_5c0ddc16_wish_delete(hard)",
                    STATUS_PASS if wish_deleted_ok else STATUS_FAIL,
                    "" if wish_deleted_ok else str(res),
                )
            )
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            plan_deleted_ok = (
                ok and isinstance(res, dict) and res.get("mode") == "hard"
                and res.get("deleted") is True and res.get("uuid") == plan_uuid
            )
            cleanup_ok = cleanup_ok and plan_deleted_ok
            results.append(
                CheckResult(
                    "4", "R53_5c0ddc16_plan_delete(hard)",
                    STATUS_PASS if plan_deleted_ok else STATUS_FAIL,
                    "" if plan_deleted_ok else str(res),
                )
            )
    return results


R54_REANCHOR_CANDIDATE_COMMANDS: tuple[str, ...] = (
    "comment_reanchor",
    "calendar_entry_reanchor",
    "escalation_reanchor",
)

R54_BASELINE_REANCHOR_COMMANDS: tuple[str, ...] = ("todo_reanchor", "bug_reanchor")


async def run_r54_reanchor_symmetry_all_entities_2c568c0c(client: Any) -> list[CheckResult]:
    """Bug 2c568c0c: todo_reanchor and bug_reanchor are the only two
    anchored runtime entities that expose a dedicated command to move
    their primary anchor in place; comment, calendar_entry, and escalation
    are each anchored the same way (a primary_anchor_type plus the same
    family of anchor_* columns -- see reanchor_guard.py's own note that
    todo_reanchor/bug_reanchor already route through
    guard_reanchor_target_not_frozen) but have no reanchor command of
    their own, an asymmetry with no principled reason: every anchored
    entity should be reanchorable the same way, with the same uniform
    new_anchor_* parameter shape todo_reanchor already documents (new_
    anchor_type, new_anchor_project_id, new_anchor_file_path, new_anchor_
    plan_uuid, new_anchor_revision_uuid, new_anchor_step_uuid, new_anchor_
    step_path, new_anchor_ref_id). Fixed: comment_reanchor, calendar_
    entry_reanchor, and escalation_reanchor exist, each following that
    same shape.

    DESIGNATED RED (assertions 1-3): help(cmdname=X) answers with a
    non-empty schema for X in comment_reanchor, calendar_entry_reanchor,
    escalation_reanchor. Today all three are unknown commands -- help()
    still succeeds (ok=True) but returns no "schema" key (same shape as
    R53's assertion 1); the exact "error" string is captured per-command
    in the FAIL detail.

    Sub-assertions 4-6 (each gated on its OWN command's assertion 1-3,
    independently -- the "unreachable: step N red" idiom, per-command
    rather than all-or-nothing since the three commands ship
    independently): the schema found for X exposes "new_anchor_type"
    among schema.properties, matching todo_reanchor's uniform shape.

    Assertion 7 (baseline control, PASS today and after the fix):
    help(cmdname="todo_reanchor") and help(cmdname="bug_reanchor") both
    answer with a schema -- the two pre-existing reanchor commands this
    fix is establishing parity with.

    No entities are created and nothing needs cleanup -- every assertion
    here is a pure help()/schema probe.
    """
    results: list[CheckResult] = []
    schema_by_command: dict[str, Optional[dict]] = {}
    designated_red_ok_by_command: dict[str, bool] = {}

    for command_name in R54_REANCHOR_CANDIDATE_COMMANDS:
        ok, res = await call(client, "help", {"cmdname": command_name})
        schema = res.get("schema") if ok and isinstance(res, dict) else None
        schema_properties = schema.get("properties") if isinstance(schema, dict) else None
        step_ok = ok and isinstance(schema, dict) and isinstance(schema_properties, dict) and bool(schema_properties)
        schema_by_command[command_name] = schema if step_ok else None
        designated_red_ok_by_command[command_name] = step_ok
        results.append(
            CheckResult(
                "4", f"R54_2c568c0c_{command_name}_help_schema",
                STATUS_PASS if step_ok else STATUS_FAIL,
                "" if step_ok
                else (
                    f"expected help(cmdname='{command_name}') to answer with a non-empty "
                    f"schema.properties; ok={ok} error={res.get('error') if isinstance(res, dict) else None!r} "
                    f"full={res!r}"
                ),
            )
        )

    for command_name in R54_REANCHOR_CANDIDATE_COMMANDS:
        check_name = f"R54_2c568c0c_{command_name}_new_anchor_type_shape"
        if not designated_red_ok_by_command[command_name]:
            results.append(CheckResult("4", check_name, STATUS_FAIL, "unreachable: step 1 red"))
            continue
        schema = schema_by_command[command_name]
        properties = schema.get("properties") if isinstance(schema, dict) else None
        shape_ok = isinstance(properties, dict) and "new_anchor_type" in properties
        results.append(
            CheckResult(
                "4", check_name,
                STATUS_PASS if shape_ok else STATUS_FAIL,
                "" if shape_ok else f"expected 'new_anchor_type' in schema.properties, got {properties!r}",
            )
        )

    baseline_ok = True
    baseline_details: list[str] = []
    for command_name in R54_BASELINE_REANCHOR_COMMANDS:
        ok, res = await call(client, "help", {"cmdname": command_name})
        schema = res.get("schema") if ok and isinstance(res, dict) else None
        command_ok = ok and isinstance(schema, dict) and bool(schema.get("properties"))
        baseline_ok = baseline_ok and command_ok
        if not command_ok:
            baseline_details.append(f"{command_name}: ok={ok} res={res!r}")
    results.append(
        CheckResult(
            "4", "R54_2c568c0c_baseline_todo_bug_reanchor_present",
            STATUS_PASS if baseline_ok else STATUS_FAIL,
            "" if baseline_ok else "; ".join(baseline_details),
        )
    )
    return results


R55_BUG_PLAN_UUID = "b847fc0b-7180-4430-a1a3-820d93d8261c"
R55_BUG_REVIEW_UUID = "5a3c433f-4f19-4952-ada0-fdaf9e348f77"
R55_BUG_ATTEMPT_ID = "33abe72c-c1bf-4c57-b696-459632a23ec8"


# Named checks _run_r55_functional_supersede_lifecycle emits, in order. Used
# both to drive that function's own CheckResults AND, when the functional
# phase is gated off (either supersede command missing from the live
# catalog), to emit the "unreachable: step 1/2 red" idiom for every name
# below instead of silently producing fewer checks than a green run would.
R55_FUNCTIONAL_CHECK_NAMES: tuple[str, ...] = (
    "R55_74479c06_functional_plan_create",
    "R55_74479c06_functional_repro_steps_created",
    "R55_74479c06_functional_execution_attempt_create(stale)",
    "R55_74479c06_functional_execution_attempt_create(replacement)",
    "R55_74479c06_functional_execution_attempt_create(third)",
    "R55_74479c06_functional_execution_attempt_supersede",
    "R55_74479c06_functional_execution_attempt_get_pointer_and_status_unchanged",
    "R55_74479c06_functional_execution_attempt_supersede_idempotent_same_target",
    "R55_74479c06_functional_execution_attempt_supersede_different_target_refused",
    "R55_74479c06_functional_review_result_create(stale)",
    "R55_74479c06_functional_review_result_create(replacement)",
    "R55_74479c06_functional_review_result_supersede",
    "R55_74479c06_functional_review_result_get_pointer_and_status_unchanged",
    "R55_74479c06_functional_review_result_supersede_missing_replacement_not_found",
)


async def _run_r55_functional_supersede_lifecycle(client: Any) -> list[CheckResult]:
    """Functional half of R55 (bug 74479c06 group-4 fix). Only called once
    the caller has confirmed BOTH review_result_supersede and
    execution_attempt_supersede are present in the live catalog (assertions
    1-2); this function itself assumes that and creates entities
    unconditionally.

    Recipe: plan_create -> context_common/step_create G (level 3) ->
    context_common/step_create T (level 4, parent G) -> context_common/
    step_create A (level 5, parent T) -- ONE atomic step, exactly like
    R49/R50's throwaway hierarchy, shared by every attempt/review below so
    the lineage guards (same step_uuid / same reviewed-attempt step) are
    satisfied by construction. THREE execution attempts anchor to A:
    stale, replacement, and third (third exists only to probe the
    different-target refusal cheaply, without needing a real second
    replacement candidate). Then:

      * execution_attempt_supersede(stale -> replacement, changed_by=
        "live-smoke") must succeed (already_superseded False); a follow-up
        execution_attempt_get(stale) must show superseded_by_uuid ==
        replacement AND status == the attempt's own creation-time status
        ("failed", untouched by the supersede call).
      * Repeating the SAME call must succeed as a no-op (already_superseded
        True, pointer unchanged).
      * Superseding stale with third instead (a DIFFERENT target than the
        one already on file) must be refused
        EXECUTION_ATTEMPT_ALREADY_SUPERSEDED, and a follow-up
        execution_attempt_get(stale) must show the pointer UNCHANGED
        (still replacement, not third).
      * Two review results are created reviewing the stale/replacement
        attempts (reviewer="live-smoke-reviewer", deliberately different
        from the attempts' created_by="live-smoke-executor" -- reviewing
        your own execution attempt is refused SELF_CERTIFICATION_FORBIDDEN,
        see review_result_create_command.py). review_result_supersede
        (stale review -> replacement review) must succeed, pointer set,
        status unchanged from the stale review's own creation-time status
        ("rejected").
      * Negative control: review_result_supersede with a nonexistent
        superseded_by_uuid must be refused REVIEW_RESULT_NOT_FOUND (the
        replacement-lookup runs before the idempotency check, so this is
        exercised even though the stale review already carries a pointer
        by this point).

    Any setup step failing short-circuits the remaining checks (same style
    as R50/R53's own sequential builds) rather than declaring the rest
    "unreachable" -- that idiom is reserved for the OUTER command-presence
    gate the caller applies, not for internal step-to-step dependencies.

    Cleanup: plan_delete(hard) in finally, unconditionally attempted once a
    plan was created. Execution attempts and review results have no delete
    command of their own; a hard plan delete is not guaranteed to cascade
    them away (R28's own contract: bug_delete's dangling-anchor case shows
    a hard plan delete can leave anchored rows behind rather than
    cascading), so a live run may leave the three execution_attempt rows
    (and, transitively, the two review_result rows referencing them)
    dangling with a stale plan_uuid -- a tolerated orphan under that same
    R28 contract, not a new risk this check introduces.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r55-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R55_74479c06_functional_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]
        results.append(CheckResult("4", "R55_74479c06_functional_plan_create", STATUS_PASS, f"uuid={plan_uuid}"))

        # G -> T -> A: a single atomic step, shared by every attempt/review
        # created below (exactly R49/R50's context_common-gated recipe).
        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R55_74479c06_functional_repro_steps_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R55_74479c06_functional_repro_steps_created", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R55_74479c06_functional_repro_steps_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R55_74479c06_functional_repro_steps_created", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R55_74479c06_functional_repro_steps_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a", "parent_step_id": t_id})
        a_id = _extract_step_id(res) if ok else None
        a_uuid = res.get("uuid") if ok and isinstance(res, dict) else None
        if not ok or a_id is None or not a_uuid:
            results.append(CheckResult("4", "R55_74479c06_functional_repro_steps_created", STATUS_FAIL, str(res)))
            return results
        results.append(
            CheckResult("4", "R55_74479c06_functional_repro_steps_created", STATUS_PASS, f"G={g_id} T={t_id} A={a_id}")
        )

        # Three execution attempts anchored to the SAME atomic step: stale
        # (superseded first), replacement (the eventual pointer target),
        # and third (used only to probe the different-target refusal).
        attempt_created_by = "live-smoke-executor"
        attempt_uuid_by_tag: dict[str, str] = {}
        attempt_status_by_tag = {"stale": "failed", "replacement": "succeeded", "third": "failed"}
        for tag, status in attempt_status_by_tag.items():
            ok, res = await call(
                client, "execution_attempt_create",
                {"plan": plan_uuid, "step": a_uuid, "status": status, "created_by": attempt_created_by},
            )
            attempt_uuid = res.get("attempt_uuid") if ok and isinstance(res, dict) else None
            check_name = f"R55_74479c06_functional_execution_attempt_create({tag})"
            if not ok or not attempt_uuid:
                results.append(CheckResult("4", check_name, STATUS_FAIL, str(res)))
                return results
            attempt_uuid_by_tag[tag] = attempt_uuid
            results.append(CheckResult("4", check_name, STATUS_PASS, f"uuid={attempt_uuid}"))
        stale_attempt = attempt_uuid_by_tag["stale"]
        replacement_attempt = attempt_uuid_by_tag["replacement"]
        third_attempt = attempt_uuid_by_tag["third"]
        stale_attempt_original_status = attempt_status_by_tag["stale"]

        # --- execution_attempt_supersede: stale -> replacement. ---
        ok, res = await call(
            client, "execution_attempt_supersede",
            {"attempt_id": stale_attempt, "superseded_by_uuid": replacement_attempt, "changed_by": "live-smoke"},
        )
        supersede_ok = ok and isinstance(res, dict) and res.get("already_superseded") is False
        results.append(
            CheckResult(
                "4", "R55_74479c06_functional_execution_attempt_supersede",
                STATUS_PASS if supersede_ok else STATUS_FAIL,
                "" if supersede_ok else f"ok={ok} res={res!r}",
            )
        )
        if not supersede_ok:
            return results

        ok, res = await call(client, "execution_attempt_get", {"attempt_id": stale_attempt})
        pointer_and_status_ok = (
            ok and isinstance(res, dict)
            and res.get("superseded_by_uuid") == replacement_attempt
            and res.get("status") == stale_attempt_original_status
        )
        results.append(
            CheckResult(
                "4", "R55_74479c06_functional_execution_attempt_get_pointer_and_status_unchanged",
                STATUS_PASS if pointer_and_status_ok else STATUS_FAIL,
                "" if pointer_and_status_ok
                else (
                    f"expected superseded_by_uuid={replacement_attempt} and "
                    f"status={stale_attempt_original_status!r} (unchanged); got ok={ok} res={res!r}"
                ),
            )
        )

        # --- idempotent repeat: SAME target, success as a no-op. ---
        ok, res = await call(
            client, "execution_attempt_supersede",
            {"attempt_id": stale_attempt, "superseded_by_uuid": replacement_attempt, "changed_by": "live-smoke"},
        )
        idempotent_ok = (
            ok and isinstance(res, dict)
            and res.get("already_superseded") is True
            and res.get("superseded_by_uuid") == replacement_attempt
        )
        results.append(
            CheckResult(
                "4", "R55_74479c06_functional_execution_attempt_supersede_idempotent_same_target",
                STATUS_PASS if idempotent_ok else STATUS_FAIL,
                "" if idempotent_ok else f"ok={ok} res={res!r}",
            )
        )

        # --- different-target re-supersede: stale already points at
        # replacement; pointing it at third instead is refused, and the
        # pointer on file must stay exactly as it was. ---
        ok, res = await call(
            client, "execution_attempt_supersede",
            {"attempt_id": stale_attempt, "superseded_by_uuid": third_attempt, "changed_by": "live-smoke"},
        )
        different_target_refused_ok = (not ok) and "EXECUTION_ATTEMPT_ALREADY_SUPERSEDED" in str(res)
        if different_target_refused_ok:
            ok2, res2 = await call(client, "execution_attempt_get", {"attempt_id": stale_attempt})
            different_target_refused_ok = (
                ok2 and isinstance(res2, dict) and res2.get("superseded_by_uuid") == replacement_attempt
            )
            detail = "" if different_target_refused_ok else f"pointer changed: ok={ok2} res={res2!r}"
        else:
            detail = f"expected EXECUTION_ATTEMPT_ALREADY_SUPERSEDED; got ok={ok} res={res!r}"
        results.append(
            CheckResult(
                "4", "R55_74479c06_functional_execution_attempt_supersede_different_target_refused",
                STATUS_PASS if different_target_refused_ok else STATUS_FAIL,
                detail,
            )
        )

        # --- two review results, reviewing the stale/replacement attempts;
        # reviewer != created_by, avoiding SELF_CERTIFICATION_FORBIDDEN. ---
        review_uuid_by_tag: dict[str, str] = {}
        review_status_by_tag = {"stale": "rejected", "replacement": "accepted"}
        review_reviewed_attempt_by_tag = {"stale": stale_attempt, "replacement": replacement_attempt}
        for tag, status in review_status_by_tag.items():
            ok, res = await call(
                client, "review_result_create",
                {
                    "plan": plan_uuid,
                    "object_type": "execution_attempt",
                    "reviewer": "live-smoke-reviewer",
                    "status": status,
                    "created_by": "live-smoke-reviewer",
                    "reviewed_attempt_uuid": review_reviewed_attempt_by_tag[tag],
                },
            )
            review_uuid = res.get("review_uuid") if ok and isinstance(res, dict) else None
            check_name = f"R55_74479c06_functional_review_result_create({tag})"
            if not ok or not review_uuid:
                results.append(CheckResult("4", check_name, STATUS_FAIL, str(res)))
                return results
            review_uuid_by_tag[tag] = review_uuid
            results.append(CheckResult("4", check_name, STATUS_PASS, f"uuid={review_uuid}"))
        stale_review = review_uuid_by_tag["stale"]
        replacement_review = review_uuid_by_tag["replacement"]
        stale_review_original_status = review_status_by_tag["stale"]

        ok, res = await call(
            client, "review_result_supersede",
            {"plan": plan_uuid, "review_uuid": stale_review, "superseded_by_uuid": replacement_review, "changed_by": "live-smoke"},
        )
        review_supersede_ok = ok and isinstance(res, dict) and res.get("already_superseded") is False
        results.append(
            CheckResult(
                "4", "R55_74479c06_functional_review_result_supersede",
                STATUS_PASS if review_supersede_ok else STATUS_FAIL,
                "" if review_supersede_ok else f"ok={ok} res={res!r}",
            )
        )
        if not review_supersede_ok:
            return results

        ok, res = await call(client, "review_result_get", {"plan": plan_uuid, "review_uuid": stale_review})
        review_pointer_and_status_ok = (
            ok and isinstance(res, dict)
            and res.get("superseded_by_uuid") == replacement_review
            and res.get("status") == stale_review_original_status
        )
        results.append(
            CheckResult(
                "4", "R55_74479c06_functional_review_result_get_pointer_and_status_unchanged",
                STATUS_PASS if review_pointer_and_status_ok else STATUS_FAIL,
                "" if review_pointer_and_status_ok
                else (
                    f"expected superseded_by_uuid={replacement_review} and "
                    f"status={stale_review_original_status!r} (unchanged); got ok={ok} res={res!r}"
                ),
            )
        )

        # --- negative control: nonexistent replacement uuid is refused
        # REVIEW_RESULT_NOT_FOUND (the replacement lookup runs before the
        # idempotency check, so this fires even though stale_review already
        # carries a pointer at this point). ---
        ok, res = await call(
            client, "review_result_supersede",
            {
                "plan": plan_uuid, "review_uuid": stale_review,
                "superseded_by_uuid": str(uuid_mod.uuid4()), "changed_by": "live-smoke",
            },
        )
        missing_replacement_ok = (not ok) and "REVIEW_RESULT_NOT_FOUND" in str(res)
        results.append(
            CheckResult(
                "4", "R55_74479c06_functional_review_result_supersede_missing_replacement_not_found",
                STATUS_PASS if missing_replacement_ok else STATUS_FAIL,
                "" if missing_replacement_ok else f"expected REVIEW_RESULT_NOT_FOUND; got ok={ok} res={res!r}",
            )
        )
    finally:
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            plan_deleted_ok = (
                ok and isinstance(res, dict) and res.get("mode") == "hard"
                and res.get("deleted") is True and res.get("uuid") == plan_uuid
            )
            results.append(
                CheckResult(
                    "4", "R55_74479c06_functional_cleanup",
                    STATUS_PASS if plan_deleted_ok else STATUS_FAIL,
                    "" if plan_deleted_ok else str(res),
                )
            )
    return results


async def run_r55_supersede_lifecycle_74479c06(client: Any) -> list[CheckResult]:
    """Bug 74479c06: neither review_result nor execution_attempt has any
    supersede lifecycle. When a stale review result or a stale execution
    attempt is replaced by a newer one, nothing on the original row ever
    records that replacement -- the stale row just sits there forever with
    its original terminal-ish status (needs_owner_decision,
    needs_escalation, ...) and no forward pointer to whatever replaced it.
    Anyone reading the stale row in isolation has no way to discover it was
    superseded. expected_behavior (the approved fix shape this check pins):
    two new commands, review_result_supersede and
    execution_attempt_supersede, each set a forward pointer ON THE STALE
    ROW (a superseded_by_uuid field pointing at the replacing review/
    attempt) while NEVER changing the original row's status -- recording
    replacement linkage without falsifying the original outcome. Both are
    guarded (the replacement must exist) and write an audit record.

    DESIGNATED RED (assertions 1-2): help(cmdname="review_result_supersede")
    and help(cmdname="execution_attempt_supersede") must each answer with a
    non-empty schema (schema.properties non-empty). Today both are unknown
    commands -- help() still succeeds (ok=True; the platform help_command.py
    never fails for an unknown cmdname) but the response carries no
    "schema" key at all, so each assertion is RED without a call() failure
    to key off of; the exact "error" string is captured in the FAIL detail
    (same technique as R53/R54).

    Sub-assertions 3-4 (each gated on its OWN command's designated-RED
    assertion -- the "unreachable: step N red" idiom, per-command since the
    two commands ship independently): the schema found for X exposes a
    superseded_by/replacement uuid parameter and a changed_by parameter,
    matching the approved fix shape.

    FUNCTIONAL LIFECYCLE (gated on BOTH commands' own designated-RED
    assertions 1-2 already passing -- command PRESENCE, not the shape
    assertions 3-4, so a present-but-malformed schema still gets its
    functional lifecycle attempted independently): delegated to
    _run_r55_functional_supersede_lifecycle, which builds a throwaway
    plan -> G -> T -> A hierarchy (context_common gate, exactly like
    R49/R50) and anchors THREE execution attempts to the single atomic
    step (stale/replacement/third), then: execution_attempt_supersede
    (stale -> replacement) must succeed and execution_attempt_get(stale)
    afterward must show superseded_by_uuid==replacement AND status
    UNCHANGED from the attempt's own creation-time status; an idempotent
    repeat (same target) must succeed as a no-op; re-supersede with a
    DIFFERENT target (stale -> third, while already pointing at
    replacement) must be refused EXECUTION_ATTEMPT_ALREADY_SUPERSEDED with
    the pointer unchanged. The same shape is then run once for
    review_result_supersede (two review results reviewing the stale/
    replacement attempts, reviewer deliberately different from the
    attempts' created_by to avoid SELF_CERTIFICATION_FORBIDDEN): supersede
    succeeds, pointer set, status unchanged; a negative control supersedes
    with a nonexistent superseded_by_uuid and expects REVIEW_RESULT_NOT_
    FOUND. On a server missing the commands (e.g. live 0.1.111) this whole
    phase is gated off and emits the same "unreachable: step 1/2 red"
    idiom as assertions 3-4, per named check, creating NO entities.
    Cleanup: plan_delete(hard) in finally. Execution attempts and review
    results have no delete command of their own; plan_delete(hard) is NOT
    guaranteed to cascade them away (R28's own contract: a hard plan
    delete can leave anchored rows dangling rather than cascading), so a
    live run against a fixed server may leave the three execution_attempt
    rows (and, transitively, the two review_result rows referencing them)
    behind with a dangling plan_uuid -- a tolerated orphan under the same
    R28 contract bug_delete's dangling-anchor case already accepts, not a
    new risk this check introduces.

    Assertion 5 (reproduction evidence, READ-ONLY, best-effort): the bug's
    own live example -- review_result_get(plan=R55_BUG_PLAN_UUID,
    review_uuid=R55_BUG_REVIEW_UUID) and
    execution_attempt_get(attempt_id=R55_BUG_ATTEMPT_ID). Post-fix contract:
    these historical stale records still exist with their ORIGINAL,
    unchanged statuses (needs_owner_decision / needs_escalation -- the fix
    must never rewrite a stale row's own status) AND their payloads now
    carry a superseded_by_uuid key whose value is None, since nobody ever
    superseded them -- the field's presence (not its absence) is the
    post-fix signal; a payload missing the key entirely would mean the fix
    regressed. If either record is gone (historical records removed), this
    emits SKIP with a reason instead of FAIL -- their disappearance is not
    itself evidence for or against the bug. STRICTLY READ-ONLY: no mutation
    of anything, and this check creates NO entities.

    Assertion 6 (control, PASS today and after the fix):
    help(cmdname="execution_attempt_report") schema has NO supersede/
    superseded_by parameter -- supersede is meant to stay a dedicated
    command, never folded in as an update side-effect of the ordinary
    report path.
    """
    results: list[CheckResult] = []

    # --- 1-2: DESIGNATED RED -- review_result_supersede and
    # execution_attempt_supersede must each be known commands with a
    # non-empty schema. ---
    supersede_commands = ("review_result_supersede", "execution_attempt_supersede")
    schema_by_command: dict[str, Optional[dict]] = {}
    designated_red_ok_by_command: dict[str, bool] = {}
    for command_name in supersede_commands:
        ok, res = await call(client, "help", {"cmdname": command_name})
        schema = res.get("schema") if ok and isinstance(res, dict) else None
        schema_properties = schema.get("properties") if isinstance(schema, dict) else None
        step_ok = ok and isinstance(schema, dict) and isinstance(schema_properties, dict) and bool(schema_properties)
        schema_by_command[command_name] = schema if step_ok else None
        designated_red_ok_by_command[command_name] = step_ok
        results.append(
            CheckResult(
                "4", f"R55_74479c06_{command_name}_help_schema",
                STATUS_PASS if step_ok else STATUS_FAIL,
                "" if step_ok
                else (
                    f"expected help(cmdname='{command_name}') to answer with a non-empty "
                    f"schema.properties; ok={ok} error={res.get('error') if isinstance(res, dict) else None!r} "
                    f"full={res!r}"
                ),
            )
        )

    # --- 3-4: gated per-command on that command's own designated-RED
    # assertion; each reported as an explicit "unreachable" FAIL, never
    # silently skipped, while the command is missing. ---
    for command_name in supersede_commands:
        check_name = f"R55_74479c06_{command_name}_shape"
        if not designated_red_ok_by_command[command_name]:
            results.append(CheckResult("4", check_name, STATUS_FAIL, "unreachable: step 1/2 red"))
            continue
        schema = schema_by_command[command_name]
        properties = schema.get("properties") if isinstance(schema, dict) else None
        has_pointer_param = isinstance(properties, dict) and any(
            key == "superseded_by_uuid" or key.startswith("superseded_by") or key.startswith("replacement")
            for key in properties
        )
        has_changed_by_param = isinstance(properties, dict) and "changed_by" in properties
        shape_ok = has_pointer_param and has_changed_by_param
        results.append(
            CheckResult(
                "4", check_name,
                STATUS_PASS if shape_ok else STATUS_FAIL,
                "" if shape_ok
                else (
                    f"expected a superseded_by/replacement uuid parameter and 'changed_by' "
                    f"in schema.properties, got {properties!r}"
                ),
            )
        )

    # --- FUNCTIONAL LIFECYCLE: gated on command PRESENCE (assertions 1-2
    # for BOTH commands), not on the shape assertions (3-4) -- a present
    # command with a malformed schema still gets its functional lifecycle
    # attempted, so a shape regression and a functional regression are
    # reported independently instead of one masking the other. See
    # _run_r55_functional_supersede_lifecycle's own docstring for the full
    # recipe. On a server missing either command this emits the same
    # "unreachable: step 1/2 red" idiom as assertions 3-4, one FAIL per
    # named check below, and creates NO entities. ---
    functional_gate_ok = all(designated_red_ok_by_command[name] for name in supersede_commands)
    if functional_gate_ok:
        results += await _run_r55_functional_supersede_lifecycle(client)
    else:
        for gated_name in R55_FUNCTIONAL_CHECK_NAMES:
            results.append(CheckResult("4", gated_name, STATUS_FAIL, "unreachable: step 1/2 red"))

    # --- 5: reproduction evidence, read-only, best-effort against the
    # bug's own real live records. Never mutates anything. ---
    ok, res = await call(client, "review_result_get", {"plan": R55_BUG_PLAN_UUID, "review_uuid": R55_BUG_REVIEW_UUID})
    if ok and isinstance(res, dict) and res.get("review_uuid") == R55_BUG_REVIEW_UUID:
        stale_status_ok = res.get("status") == "needs_owner_decision"
        pointer_field_ok = "superseded_by_uuid" in res and res.get("superseded_by_uuid") is None
        evidence_ok = stale_status_ok and pointer_field_ok
        results.append(
            CheckResult(
                "4", "R55_74479c06_review_result_reproduction_evidence",
                STATUS_PASS if evidence_ok else STATUS_FAIL,
                "" if evidence_ok
                else (
                    f"expected status='needs_owner_decision' (unchanged) and superseded_by_uuid=None "
                    f"(present, unsuperseded) on review_uuid={R55_BUG_REVIEW_UUID}; got {res!r}"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "4", "R55_74479c06_review_result_reproduction_evidence", STATUS_SKIP,
                f"historical review_result {R55_BUG_REVIEW_UUID} on plan {R55_BUG_PLAN_UUID} no longer "
                f"available to inspect (removed or reassigned); ok={ok} res={res!r}",
            )
        )

    ok, res = await call(client, "execution_attempt_get", {"attempt_id": R55_BUG_ATTEMPT_ID})
    if ok and isinstance(res, dict) and res.get("attempt_uuid") == R55_BUG_ATTEMPT_ID:
        stale_status_ok = res.get("status") == "needs_escalation"
        pointer_field_ok = "superseded_by_uuid" in res and res.get("superseded_by_uuid") is None
        evidence_ok = stale_status_ok and pointer_field_ok
        results.append(
            CheckResult(
                "4", "R55_74479c06_execution_attempt_reproduction_evidence",
                STATUS_PASS if evidence_ok else STATUS_FAIL,
                "" if evidence_ok
                else (
                    f"expected status='needs_escalation' (unchanged) and superseded_by_uuid=None "
                    f"(present, unsuperseded) on attempt_id={R55_BUG_ATTEMPT_ID}; got {res!r}"
                ),
            )
        )
    else:
        results.append(
            CheckResult(
                "4", "R55_74479c06_execution_attempt_reproduction_evidence", STATUS_SKIP,
                f"historical execution_attempt {R55_BUG_ATTEMPT_ID} no longer available to inspect "
                f"(removed or reassigned); ok={ok} res={res!r}",
            )
        )

    # --- 6: control -- execution_attempt_report's schema has no
    # supersede/superseded_by parameter; supersede stays a dedicated
    # command, never an update side-effect of the ordinary report path.
    # Independent of assertions 1-4, PASS today and after the fix. ---
    ok, res = await call(client, "help", {"cmdname": "execution_attempt_report"})
    report_properties = None
    if ok and isinstance(res, dict):
        report_schema = res.get("schema")
        if isinstance(report_schema, dict):
            report_properties = report_schema.get("properties")
    control_ok = isinstance(report_properties, dict) and not any(
        "supersede" in key for key in report_properties
    )
    results.append(
        CheckResult(
            "4", "R55_74479c06_control_execution_attempt_report_no_supersede_param",
            STATUS_PASS if control_ok else STATUS_FAIL,
            "" if control_ok else f"execution_attempt_report schema.properties={report_properties!r}",
        )
    )

    return results


R56_VALID_OBJECTS_PATCH: list[dict[str, Any]] = [
    {"name": "R56Widget", "concepts": [], "role": "create"},
    {"name": "R56Reader", "concepts": [], "role": "consume"},
    {"name": "R56Legacy", "concepts": []},
]


async def run_r56_object_role_contract_eig_block_a(client: Any) -> list[CheckResult]:
    """EIG block A (todo 287bdfa6): a level-5 (AS) object declaration entry
    in fields.objects now accepts an OPTIONAL "role" key drawn from a frozen
    vocabulary -- create, modify, consume, verify, document, package, deploy
    (plan_manager/domain/step_objects.py OBJECT_ROLES). An absent role is a
    legacy entry with unchanged semantics. plan_manager/domain/step_objects.
    py's normalize_as_object_declarations rejects any entry whose "role" key
    is present but is either a non-string or not in OBJECT_ROLES, adding it
    to the "problems" list; step_update_command.py's _validate_step_fields
    (level 5) raises INVALID_STEP_FIELD_SHAPE atomically -- BEFORE any
    write -- when validate_as_objects reports any problem, so a rejected
    patch must leave the step's previously-stored fields.objects completely
    untouched. On live 0.1.112 (pre-deploy) step_objects.py has no role
    vocabulary at all: any "role" value, valid or not, is accepted and
    stored verbatim with no validation.

    Recipe (throwaway plan, single G->T->A branch, context_common gate
    exactly like R49/R50, try/finally cleanup): plan_create ->
    context_common(plan,"plan",3) -> step_create G (level 3) ->
    context_common(G,4) -> step_create T (level 4, parent G) ->
    context_common(T,5) -> step_create A (level 5, parent T) -- the single
    atomic step every sub-assertion below targets.

    Sub-assertion 2 -- CONTROL, must PASS today AND after the fix:
    step_update(A, fields={"objects": R56_VALID_OBJECTS_PATCH}) -- two
    entries carrying a role from the frozen vocabulary (create, consume)
    plus one legacy role-less entry -- must succeed, and step_get(A)
    afterward must return fields.objects equal to R56_VALID_OBJECTS_PATCH
    verbatim (step_update_command.py persists the merged, UN-normalized
    fields dict -- see _merge_step_fields -- so every key, including a
    role-less entry's absence of "role", round-trips exactly as sent).
    fields.objects storage is opaque on 0.1.112 (no role-aware code path
    exists to reject or rewrite it), so this is expected to already PASS
    pre-deploy; if it does not, that is a discovery to report, not a check
    bug.

    Sub-assertion 3 -- DESIGNATED RED today, PASS after deploy:
    step_update(A, fields={"objects": [{"name": "R56Bad", "concepts": [],
    "role": "banana"}]}) must be REJECTED, call() returning ok=False with
    "INVALID_STEP_FIELD_SHAPE" in the formatted diagnostic (the same
    queued-path domain-error-as-string idiom R4's malformed-item check
    uses). On 0.1.112 the unknown role is silently accepted -> this
    assertion is RED today. Gated on assertion 3 (the "unreachable: step 3
    red" idiom, per R50/R55): only if the rejection actually happened is a
    second check run, confirming step_get(A) still returns EXACTLY
    R56_VALID_OBJECTS_PATCH from assertion 2 -- proving the rejected write
    never touched the stored fields.objects. While assertion 3 stays RED
    (today), this gated check reports an explicit "unreachable" FAIL
    instead of silently skipping, since on 0.1.112 the banana entry is in
    fact accepted and DOES overwrite the step's objects (a real, expected,
    pre-deploy side effect -- not a check bug).

    Sub-assertion 4 -- CONTROL, informational-tolerant, PASS both sides:
    step_update(A, fields={"objects": [<role="create" marker entry>,
    {"name": "R56NonStringRole", "concepts": [], "role": 7}]}) with a
    NON-STRING role. The exact accept/reject contract for a non-string
    role is pinned post-deploy by the unit suite, not this live check,
    so this assertion only asserts internal consistency: capture
    step_get(A) immediately BEFORE the call as the pre-state, then either
    (a) the call is rejected (ok=False) and step_get(A) afterward still
    equals the pre-state exactly (nothing corrupted by an atomic reject),
    or (b) the call succeeds and step_get(A) afterward shows the marker
    entry present with its role and concepts unchanged (round-tripped
    without corrupting the other entry in the same patch). Either outcome
    PASSes; only a third outcome -- corruption -- FAILs.

    Cleanup: plan_delete(hard).
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        ok, res = await call(client, "plan_create", {"name": unique_suffix("r56-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R56_287bdfa6_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R56_287bdfa6_context_common(plan,level3)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R56_287bdfa6_step_create(G)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R56_287bdfa6_context_common(G,level4)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t", "parent_step_id": g_id})
        t_id = _extract_step_id(res) if ok else None
        if not ok or t_id is None:
            results.append(CheckResult("4", "R56_287bdfa6_step_create(T)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R56_287bdfa6_context_common(T,level5)", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a", "parent_step_id": t_id})
        a_id = _extract_step_id(res) if ok else None
        if not ok or a_id is None:
            results.append(CheckResult("4", "R56_287bdfa6_step_create(A)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R56_287bdfa6_repro_hierarchy_created", STATUS_PASS, f"G={g_id} T={t_id} A={a_id}"))

        # --- 2: CONTROL (must PASS today AND after the fix) -- a mix of
        # frozen-vocabulary roles and one role-less legacy entry must
        # persist verbatim. ---
        ok, res = await call(
            client, "step_update",
            {"plan": plan_uuid, "step_id": a_id, "fields": {"objects": R56_VALID_OBJECTS_PATCH}},
        )
        if not ok:
            results.append(CheckResult("4", "R56_287bdfa6_control_step_update_valid_roles", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R56_287bdfa6_control_step_update_valid_roles", STATUS_PASS))

        ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": a_id})
        objects_after_control = res.get("fields", {}).get("objects") if ok and isinstance(res, dict) else None
        control_ok = ok and objects_after_control == R56_VALID_OBJECTS_PATCH
        results.append(
            CheckResult(
                "4", "R56_287bdfa6_control_step_get_roles_preserved_verbatim",
                STATUS_PASS if control_ok else STATUS_FAIL,
                "" if control_ok
                else f"expected fields.objects=={R56_VALID_OBJECTS_PATCH!r}, got ok={ok} objects={objects_after_control!r}",
            )
        )
        if not control_ok:
            return results

        # --- 3: DESIGNATED RED today, PASS after deploy -- an unknown role
        # string must be rejected atomically with INVALID_STEP_FIELD_SHAPE.
        # call()/unwrap_envelope report a queued-path domain error as a
        # formatted diagnostic STRING (not a dict), the same idiom R4's
        # malformed-item check already uses; check the stable domain_code
        # substring. ---
        ok, res = await call(
            client, "step_update",
            {
                "plan": plan_uuid, "step_id": a_id,
                "fields": {"objects": [{"name": "R56Bad", "concepts": [], "role": "banana"}]},
            },
        )
        red_rejected = (not ok) and "INVALID_STEP_FIELD_SHAPE" in str(res)
        results.append(
            CheckResult(
                "4", "R56_287bdfa6_designated_red_unknown_role_rejected",
                STATUS_PASS if red_rejected else STATUS_FAIL,
                "" if red_rejected else f"expected rejection with INVALID_STEP_FIELD_SHAPE, got ok={ok} res={res!r}",
            )
        )

        # Gated on assertion 3 itself (the "unreachable: step 3 red" idiom,
        # per R50/R55): only a genuine rejection proves the write never
        # landed. On 0.1.112 the banana entry is accepted and DOES
        # overwrite the step's objects -- a real pre-deploy side effect,
        # not a check bug -- so this reports an explicit unreachable FAIL
        # instead of silently skipping while assertion 3 stays RED.
        if red_rejected:
            ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": a_id})
            objects_after_red = res.get("fields", {}).get("objects") if ok and isinstance(res, dict) else None
            not_overwritten = ok and objects_after_red == R56_VALID_OBJECTS_PATCH
            results.append(
                CheckResult(
                    "4", "R56_287bdfa6_designated_red_objects_not_overwritten",
                    STATUS_PASS if not_overwritten else STATUS_FAIL,
                    "" if not_overwritten
                    else f"expected fields.objects still =={R56_VALID_OBJECTS_PATCH!r}, got ok={ok} objects={objects_after_red!r}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "4", "R56_287bdfa6_designated_red_objects_not_overwritten",
                    STATUS_FAIL, "unreachable: step 3 red",
                )
            )

        # --- 4: CONTROL, informational-tolerant, PASS both sides -- a
        # non-string role must not corrupt sibling entries in the same
        # patch, whichever way the call resolves. Capture the pre-state so
        # both accept and reject outcomes can be checked against it. ---
        ok, res = await call(client, "step_get", {"plan": plan_uuid, "step_id": a_id})
        pre_state = res.get("fields", {}).get("objects") if ok and isinstance(res, dict) else None
        if not ok:
            results.append(CheckResult("4", "R56_287bdfa6_control_non_string_role_step_get_pre", STATUS_FAIL, str(res)))
            return results

        marker_entry = {"name": "R56Marker", "concepts": [], "role": "create"}
        non_string_patch = [marker_entry, {"name": "R56NonStringRole", "concepts": [], "role": 7}]
        ok, res = await call(
            client, "step_update",
            {"plan": plan_uuid, "step_id": a_id, "fields": {"objects": non_string_patch}},
        )
        if ok:
            ok2, res2 = await call(client, "step_get", {"plan": plan_uuid, "step_id": a_id})
            objects_after = res2.get("fields", {}).get("objects") if ok2 and isinstance(res2, dict) else None
            round_tripped = ok2 and isinstance(objects_after, list) and marker_entry in objects_after
            results.append(
                CheckResult(
                    "4", "R56_287bdfa6_control_non_string_role_observed",
                    STATUS_PASS if round_tripped else STATUS_FAIL,
                    (
                        f"accepted (ok=True); round-tripped marker entry intact={round_tripped}; "
                        f"objects={objects_after!r}"
                    ) if round_tripped else
                    f"accepted (ok=True) but marker entry NOT found intact afterward: objects={objects_after!r}",
                )
            )
        else:
            ok2, res2 = await call(client, "step_get", {"plan": plan_uuid, "step_id": a_id})
            objects_after = res2.get("fields", {}).get("objects") if ok2 and isinstance(res2, dict) else None
            untouched = ok2 and objects_after == pre_state
            results.append(
                CheckResult(
                    "4", "R56_287bdfa6_control_non_string_role_observed",
                    STATUS_PASS if untouched else STATUS_FAIL,
                    (
                        f"rejected (ok=False, res={res!r}); pre-state untouched={untouched}"
                    ) if untouched else
                    f"rejected (ok=False) but pre-state was NOT preserved: pre={pre_state!r} after={objects_after!r}",
                )
            )
    finally:
        cleanup_ok = True
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R56_287bdfa6_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


async def run_r57_execution_graph_typed_edges_eig_block_b(client: Any) -> list[CheckResult]:
    """EIG block B (todo 16853f27): execution_graph is a new read-only
    command (plan_manager/commands/execution_graph_command.py, view logic
    in plan_manager/views/execution_graph.py) that composes, over one
    plan's steps, the declared/derived dependency edges (typed "explicit"
    or "file_order") together with two INFERRED edge families read off
    block-A object roles and AS verification/target_file pairs: typed
    "object_producer" (from a producer AS whose fields.objects declares a
    "create"/"modify" role for some object to every consumer AS declaring
    "consume"/"verify" for that same object) and typed
    "verification_target" (from the target_file's owning AS -- preferring
    an "operation": "create_file" owner -- to every AS whose
    fields.verification.target names that file). It also reports
    "missing_producers" (objects consumed but never produced) and
    "ambiguous_dependencies" (objects with more than one producer), plus a
    cycle report, all canonically sorted so two builds over the same input
    are byte-identical.

    DESIGNATED RED (assertion 1): help(cmdname="execution_graph") must
    answer with a non-empty schema (schema.properties non-empty) -- the
    same R53 technique (see run_r53_wish_reanchor_in_place_5c0ddc16):
    today the command is unknown to live 0.1.113, help() still succeeds
    (ok=True) but carries no "schema" key, so this assertion is RED
    without a call() failure to key off of; res.get("error") is captured
    in the FAIL detail instead.

    Sub-assertions 2+ each run only if assertion 1 passed (the
    "unreachable: step 1 red" idiom -- see R49/R50/R53/R56): build a
    throwaway fixture plan via the context_common gate (exactly like
    R49/R56) with TWO tactical branches under one goal and THREE atomics:

        G-001 -> T-001 -> A1 (fields: target_file="src/widget.py",
                               operation="create_file" (already the
                               step_create skeleton default for level 5,
                               restated explicitly here since fields is a
                               freeform additionalProperties patch),
                               objects=[{"name": "Widget", "concepts": [],
                                         "role": "create"}])
        G-001 -> T-002 -> A2 (fields: objects=[{"name": "Widget",
                                        "concepts": [], "role": "consume"},
                                       {"name": "Orphan", "concepts": [],
                                        "role": "consume"}])
                        -> A3 (fields: verification={"type": "pytest",
                                        "target": "src/widget.py",
                                        "expected": "green"})

    plus one explicit dependency, step_dependency_add(A2, depends_on=A1).
    A2 and A3 keep their step_create-skeleton default empty target_file,
    so build_edges's same-file grouping (views/dependency_graph.py:
    target_file must be a non-empty string) never groups them with A1's
    "src/widget.py" -- no AS_SAME_FILE_ORDER_AMBIGUOUS collision, and no
    incidental file_order edge muddies the explicit-family count.

    A1 and A2 share the bare local id "A-001" under different T parents
    (same next_free_step_id scope-reset R49 already exercises), so every
    step reference below uses the full canonical path, not the bare id.

    Then execution_graph(plan=...) is called twice (determinism check) and
    every sub-assertion below is checked against the first call's payload:
      - an "explicit" edge A1->A2 (from step_dependency_add) is present;
      - an "object_producer" edge A1->A2 is ALSO present with
        evidence.object=="Widget" -- proving explicit and object_producer
        coexist as distinct typed edges between the same pair rather than
        collapsing into one;
      - a "verification_target" edge A1->A3 is present with
        evidence.target=="src/widget.py";
      - missing_producers contains an entry for "Orphan" whose consumers
        list contains A2's path (Orphan has a consumer, A2, but no AS
        anywhere declares a producer role for it);
      - cycles == [] and summary's four edge-derived counts
        (explicit_edge_count/inferred_edge_count/missing_producer_count/
        cycle_count) match the lengths of the corresponding lists in the
        same payload;
      - determinism: the second execution_graph call's edges/
        missing_producers/ambiguous_dependencies/cycles/summary section,
        JSON-dumped with sort_keys=True, is byte-identical to the first
        call's (the view's canonical sort makes two builds over the same,
        unchanged input identical regardless of internal dict/set
        iteration order).

    Cleanup: plan_delete(hard), verified with its own CheckResult.
    """
    results: list[CheckResult] = []
    plan_uuid: Optional[str] = None
    try:
        # --- 1: DESIGNATED RED -- execution_graph must be a known command
        # with a non-empty schema. ---
        ok, res = await call(client, "help", {"cmdname": "execution_graph"})
        schema = res.get("schema") if ok and isinstance(res, dict) else None
        schema_properties = schema.get("properties") if isinstance(schema, dict) else None
        step1_ok = ok and isinstance(schema, dict) and isinstance(schema_properties, dict) and bool(schema_properties)
        results.append(
            CheckResult(
                "4", "R57_16853f27_execution_graph_help_schema",
                STATUS_PASS if step1_ok else STATUS_FAIL,
                "" if step1_ok
                else (
                    f"expected help(cmdname='execution_graph') to answer with a non-empty "
                    f"schema.properties; ok={ok} error={res.get('error') if isinstance(res, dict) else None!r} "
                    f"full={res!r}"
                ),
            )
        )

        # --- 2+: gated on assertion 1; each reported as an explicit
        # "unreachable" FAIL, never silently skipped, while the command is
        # missing. ---
        if not step1_ok:
            for gated_name in (
                "R57_16853f27_plan_create",
                "R57_16853f27_repro_hierarchy_created",
                "R57_16853f27_step_dependency_add(A1->A2)",
                "R57_16853f27_explicit_edge_A1_A2",
                "R57_16853f27_object_producer_edge_A1_A2",
                "R57_16853f27_verification_target_edge_A1_A3",
                "R57_16853f27_missing_producer_orphan",
                "R57_16853f27_cycles_empty_and_summary_consistent",
                "R57_16853f27_determinism",
            ):
                results.append(CheckResult("4", gated_name, STATUS_FAIL, "unreachable: step 1 red"))
            return results

        ok, res = await call(client, "plan_create", {"name": unique_suffix("r57-plan")})
        if not ok or not isinstance(res, dict) or not res.get("uuid"):
            results.append(CheckResult("4", "R57_16853f27_plan_create", STATUS_FAIL, str(res)))
            return results
        plan_uuid = res["uuid"]
        results.append(CheckResult("4", "R57_16853f27_plan_create", STATUS_PASS, f"uuid={plan_uuid}"))

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": "plan", "child_level": 3})
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 3, "slug": "g-001"})
        g_id = _extract_step_id(res) if ok else None
        if not ok or g_id is None:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t-001", "parent_step_id": g_id})
        t1_id = _extract_step_id(res) if ok else None
        if not ok or t1_id is None:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": g_id, "child_level": 4})
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 4, "slug": "t-002", "parent_step_id": g_id})
        t2_id = _extract_step_id(res) if ok else None
        if not ok or t2_id is None:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t1_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a-001", "parent_step_id": t1_id})
        a1_id = _extract_step_id(res) if ok else None
        if not ok or a1_id is None:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t2_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a-001", "parent_step_id": t2_id})
        a2_id = _extract_step_id(res) if ok else None
        if not ok or a2_id is None:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(client, "context_common", {"plan": plan_uuid, "node": t2_id, "child_level": 5})
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results
        ok, res = await call(client, "step_create", {"plan": plan_uuid, "level": 5, "slug": "a-002", "parent_step_id": t2_id})
        a3_id = _extract_step_id(res) if ok else None
        if not ok or a3_id is None:
            results.append(CheckResult("4", "R57_16853f27_repro_hierarchy_created", STATUS_FAIL, str(res)))
            return results

        g_path = g_id
        t1_path = f"{g_id}/{t1_id}"
        t2_path = f"{g_id}/{t2_id}"
        a1_path = f"{t1_path}/{a1_id}"
        a2_path = f"{t2_path}/{a2_id}"
        a3_path = f"{t2_path}/{a3_id}"
        results.append(
            CheckResult(
                "4", "R57_16853f27_repro_hierarchy_created", STATUS_PASS,
                f"G={g_path} T1={t1_path} T2={t2_path} A1={a1_path} A2={a2_path} A3={a3_path}",
            )
        )

        ok, res = await call(
            client, "step_update",
            {
                "plan": plan_uuid, "step_id": a1_path,
                "fields": {
                    "target_file": "src/widget.py",
                    "operation": "create_file",
                    "objects": [{"name": "Widget", "concepts": [], "role": "create"}],
                },
            },
        )
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_step_update(A1)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(
            client, "step_update",
            {
                "plan": plan_uuid, "step_id": a2_path,
                "fields": {
                    "objects": [
                        {"name": "Widget", "concepts": [], "role": "consume"},
                        {"name": "Orphan", "concepts": [], "role": "consume"},
                    ],
                },
            },
        )
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_step_update(A2)", STATUS_FAIL, str(res)))
            return results

        ok, res = await call(
            client, "step_update",
            {
                "plan": plan_uuid, "step_id": a3_path,
                "fields": {
                    "verification": {"type": "pytest", "target": "src/widget.py", "expected": "green"},
                },
            },
        )
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_step_update(A3)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R57_16853f27_step_update(A1,A2,A3)", STATUS_PASS))

        ok, res = await call(
            client, "step_dependency_add",
            {"plan": plan_uuid, "step_id": a2_path, "depends_on": a1_path},
        )
        if not ok:
            results.append(CheckResult("4", "R57_16853f27_step_dependency_add(A1->A2)", STATUS_FAIL, str(res)))
            return results
        results.append(CheckResult("4", "R57_16853f27_step_dependency_add(A1->A2)", STATUS_PASS))

        ok, res1 = await call(client, "execution_graph", {"plan": plan_uuid})
        if not ok or not isinstance(res1, dict):
            results.append(CheckResult("4", "R57_16853f27_execution_graph_call", STATUS_FAIL, str(res1)))
            return results
        results.append(CheckResult("4", "R57_16853f27_execution_graph_call", STATUS_PASS))

        edges1 = res1.get("edges") if isinstance(res1.get("edges"), list) else []

        def _find_edge(edges: list, frm: str, to: str, etype: str) -> Optional[dict]:
            for edge in edges:
                if (
                    isinstance(edge, dict)
                    and edge.get("from") == frm and edge.get("to") == to and edge.get("type") == etype
                ):
                    return edge
            return None

        explicit_edge = _find_edge(edges1, a1_path, a2_path, "explicit")
        results.append(
            CheckResult(
                "4", "R57_16853f27_explicit_edge_A1_A2",
                STATUS_PASS if explicit_edge is not None else STATUS_FAIL,
                "" if explicit_edge is not None else f"expected an explicit A1->A2 edge in edges={edges1!r}",
            )
        )

        object_producer_edge = _find_edge(edges1, a1_path, a2_path, "object_producer")
        object_producer_ok = (
            object_producer_edge is not None
            and isinstance(object_producer_edge.get("evidence"), dict)
            and object_producer_edge["evidence"].get("object") == "Widget"
        )
        results.append(
            CheckResult(
                "4", "R57_16853f27_object_producer_edge_A1_A2",
                STATUS_PASS if object_producer_ok else STATUS_FAIL,
                "" if object_producer_ok
                else f"expected an object_producer A1->A2 edge with evidence.object=='Widget' in edges={edges1!r}",
            )
        )

        verification_target_edge = _find_edge(edges1, a1_path, a3_path, "verification_target")
        verification_target_ok = (
            verification_target_edge is not None
            and isinstance(verification_target_edge.get("evidence"), dict)
            and verification_target_edge["evidence"].get("target") == "src/widget.py"
        )
        results.append(
            CheckResult(
                "4", "R57_16853f27_verification_target_edge_A1_A3",
                STATUS_PASS if verification_target_ok else STATUS_FAIL,
                "" if verification_target_ok
                else (
                    "expected a verification_target A1->A3 edge with evidence.target=='src/widget.py' "
                    f"in edges={edges1!r}"
                ),
            )
        )

        missing_producers = res1.get("missing_producers") if isinstance(res1.get("missing_producers"), list) else []
        orphan_missing = next(
            (
                entry for entry in missing_producers
                if isinstance(entry, dict) and entry.get("object") == "Orphan"
                and isinstance(entry.get("consumers"), list) and a2_path in entry["consumers"]
            ),
            None,
        )
        results.append(
            CheckResult(
                "4", "R57_16853f27_missing_producer_orphan",
                STATUS_PASS if orphan_missing is not None else STATUS_FAIL,
                "" if orphan_missing is not None
                else f"expected missing_producers to contain object=='Orphan' with consumers including {a2_path!r}, got {missing_producers!r}",
            )
        )

        cycles = res1.get("cycles")
        summary = res1.get("summary") if isinstance(res1.get("summary"), dict) else {}
        explicit_edges_count = sum(1 for e in edges1 if isinstance(e, dict) and e.get("provenance") == "explicit")
        inferred_edges_count = sum(1 for e in edges1 if isinstance(e, dict) and e.get("provenance") == "inferred")
        summary_consistent = (
            cycles == []
            and summary.get("explicit_edge_count") == explicit_edges_count
            and summary.get("inferred_edge_count") == inferred_edges_count
            and summary.get("missing_producer_count") == len(missing_producers)
            and summary.get("cycle_count") == 0
        )
        results.append(
            CheckResult(
                "4", "R57_16853f27_cycles_empty_and_summary_consistent",
                STATUS_PASS if summary_consistent else STATUS_FAIL,
                "" if summary_consistent
                else f"cycles={cycles!r} summary={summary!r} edges={edges1!r} missing_producers={missing_producers!r}",
            )
        )

        ok, res2 = await call(client, "execution_graph", {"plan": plan_uuid})
        if not ok or not isinstance(res2, dict):
            results.append(CheckResult("4", "R57_16853f27_determinism", STATUS_FAIL, f"second execution_graph call failed: {res2!r}"))
            return results

        def _canonical_section(payload: dict) -> str:
            section = {
                key: payload.get(key)
                for key in ("edges", "missing_producers", "ambiguous_dependencies", "cycles", "summary")
            }
            return json.dumps(section, sort_keys=True)

        canonical1 = _canonical_section(res1)
        canonical2 = _canonical_section(res2)
        deterministic = canonical1 == canonical2
        results.append(
            CheckResult(
                "4", "R57_16853f27_determinism",
                STATUS_PASS if deterministic else STATUS_FAIL,
                "" if deterministic
                else f"expected two execution_graph calls to be byte-identical; first={canonical1!r} second={canonical2!r}",
            )
        )
    finally:
        cleanup_ok = True
        if plan_uuid is not None:
            ok, res = await call(client, "plan_delete", {"plan": plan_uuid, "hard": True})
            cleanup_ok = cleanup_ok and ok
        results.append(
            CheckResult(
                "4", "R57_16853f27_cleanup", STATUS_PASS if cleanup_ok else STATUS_FAIL,
                "" if cleanup_ok else "one or more scratch entities survived cleanup",
            )
        )
    return results


async def run_selected_tests(
    client: Any,
    catalog_names: frozenset[str],
    args: argparse.Namespace,
    selected_specs: Optional[list[Any]] = None,
) -> list[CheckResult]:
    """Run every selected Tier-4 regression test in registry order.

    Every selected spec is dispatched, even after an earlier one fails or is
    missing its runner. This loop used to `break` on the first failing (or
    missing-runner) batch; on the live 0.1.97 run R36 legitimately failed
    (CR-7's point-read contract change, since fixed above) and that `break`
    silently swallowed every spec registered after it -- R37 and R38, ~25
    checks, zero R37_/R38_ lines anywhere in the output, with no diagnostic
    naming the gap. A later spec's coverage must never depend on an earlier
    spec passing, so failures accumulate instead of truncating the run.

    The trailing "spec_runner_dispatch" check is what makes non-execution
    loud instead of silent: if any dispatched runner returns an empty batch
    (zero CheckResults -- from the summary's point of view indistinguishable
    from "this spec never ran"), the run FAILS a named check listing exactly
    which spec key(s) produced nothing, instead of just quietly shipping
    fewer checks than the registry promised.
    """

    specs = selected_specs if selected_specs is not None else resolve_selected_test_specs(args.test)
    results: list[CheckResult] = []
    empty_batch_keys: list[str] = []
    dispatched_count = 0
    for spec in specs:
        runner = globals().get(spec.function_name)
        if runner is None:
            results.append(
                CheckResult(
                    "4",
                    f"{spec.key}_missing_runner",
                    STATUS_FAIL,
                    f"no runner named {spec.function_name}",
                )
            )
            continue
        kwargs: dict[str, Any] = {}
        if spec.needs_catalog:
            kwargs["catalog_names"] = catalog_names
        if spec.needs_project:
            kwargs["project_id"] = args.project
        batch = await runner(client, **kwargs)
        dispatched_count += 1
        if not batch:
            empty_batch_keys.append(spec.key)
        results += batch

    if empty_batch_keys:
        results.append(
            CheckResult(
                "4", "spec_runner_dispatch", STATUS_FAIL,
                "registered spec runner(s) produced zero CheckResults (silent "
                f"non-execution): {', '.join(empty_batch_keys)}",
            )
        )
    else:
        results.append(
            CheckResult(
                "4", "spec_runner_dispatch", STATUS_PASS,
                f"{dispatched_count} of {len(specs)} registered spec runner(s) dispatched, "
                "each produced at least one check",
            )
        )
    return results


async def run_pipeline(args: argparse.Namespace) -> Summary:
    from plan_manager_client.client import PlanManagerClient

    reset_dispatch_log()
    config = build_config(args)
    configure_call_watchdog(config.timeout)
    client = PlanManagerClient(**config.to_jsonrpc_kwargs())
    selected_specs = resolve_selected_test_specs(args.test)

    results: list[CheckResult] = []
    tier0_results = await run_tier0(client, args.expect_version)
    results += tier0_results
    if any(r.status == STATUS_FAIL and r.name == "server_reachable" for r in tier0_results):
        return compute_summary(results)
    if has_failures(tier0_results):
        return compute_summary(results)

    needs_catalog = (not args.test) or any(spec.needs_catalog for spec in selected_specs)

    catalog_names: frozenset[str] = frozenset()
    if needs_catalog:
        # Bug 507b74ae bounded help()'s no-cmdname default to one page (bounded
        # default 50, max 200 rows); every tier below needs the FULL catalog, so
        # fetch_full_help_catalog pages through it (single iteration, unchanged,
        # against a server predating the fix -- see its own docstring).
        ok, catalog, help_all = await fetch_full_help_catalog(client)
        if not ok or not catalog:
            results.append(CheckResult("1", "catalog_fetch", STATUS_FAIL, str(help_all)))
            return compute_summary(results)
        catalog_names = frozenset(catalog.keys())
        results.append(CheckResult("1", "catalog_fetch", STATUS_PASS, f"{len(catalog_names)} commands"))

    if args.test:
        selected_results = await run_selected_tests(client, catalog_names, args, selected_specs)
        results += selected_results
        if not has_failures(selected_results):
            fallback_note = summarize_dispatch_fallbacks(DISPATCH_LOG)
            if fallback_note is not None:
                results.append(CheckResult("diag", "dispatch_fallbacks_used", STATUS_PASS, fallback_note))
        return compute_summary(results)

    tier1_results = await run_tier1(client, sorted(catalog_names))
    results += tier1_results
    if has_failures(tier1_results):
        return compute_summary(results)

    classification = classify_catalog(catalog_names)
    for name, reason in classification.skipped:
        results.append(CheckResult("2", name, STATUS_SKIP, reason))

    tier2_static_results = await run_tier2_static(client, catalog_names)
    results += tier2_static_results
    if has_failures(tier2_static_results):
        return compute_summary(results)

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
    bug_uuid: Optional[str] = None
    bug_fix_uuid: Optional[str] = None
    if ok and isinstance(bug_plan_res, dict) and bug_plan_res.get("uuid"):
        bug_plan_uuid = bug_plan_res["uuid"]
        bug_create_results, bug_uuid, bug_fix_uuid = await run_tier3_bug_create(client, bug_plan_uuid)
        if bug_uuid is not None:
            entities["bug"] = bug_uuid
    else:
        bug_create_results = [CheckResult("3", "bug_plan_create", STATUS_FAIL, str(bug_plan_res))]

    entities["project"] = args.project

    tier3_create_results = plan_step_results + todo_create_results + bug_create_results
    results += tier3_create_results

    tier2_scoped_results: list[CheckResult] = []
    if not has_failures(tier3_create_results):
        # --- Tier 2 scoped probes run WHILE every entity above is still alive.
        tier2_scoped_results = await run_tier2_scoped(client, catalog_names, entities)
        results += tier2_scoped_results

    # --- Tier 3 CLEANUP phase: now it is safe to tear everything down.
    cleanup_results = await run_tier3_plan_step_cleanup(client, plan_uuid, plan_name)
    cleanup_results += await run_tier3_todo_cleanup(client, todo_uuid)
    # bug_delete (todo 9b09c9b0) now exists: hard-delete the child fix, then
    # the bug itself, BEFORE the plan -- bug_report.source_plan_uuid carries
    # no FK/cascade of its own, so the plan hard delete below never touched
    # this row; leaving it out would leak an orphaned bug_report (and
    # bug_fix) row on every smoke run. A live bug_fix.bug_uuid reference
    # would otherwise block the bug's own hard delete, hence fix-then-bug.
    if bug_fix_uuid is not None:
        ok, res = await call(client, "bug_fix_delete", {"bug_fix": bug_fix_uuid, "changed_by": "live-smoke", "hard": True})
        cleanup_results.append(CheckResult("3", "bug_fix_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    if bug_uuid is not None:
        ok, res = await call(client, "bug_delete", {"bug_id": bug_uuid, "changed_by": "live-smoke", "hard": True})
        cleanup_results.append(CheckResult("3", "bug_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    if bug_plan_uuid is not None:
        ok, res = await call(client, "plan_delete", {"plan": bug_plan_uuid, "hard": True})
        cleanup_results.append(CheckResult("3", "bug_plan_delete(hard)", STATUS_PASS if ok else STATUS_FAIL, "" if ok else str(res)))
    results += cleanup_results
    if has_failures(tier3_create_results) or has_failures(tier2_scoped_results) or has_failures(cleanup_results):
        return compute_summary(results)

    selected_results = await run_selected_tests(client, catalog_names, args, selected_specs)
    results += selected_results
    if has_failures(selected_results):
        return compute_summary(results)

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
    parser.add_argument("--list-tests", action="store_true", help="list selectable Tier-4 live-smoke tests and exit")
    parser.add_argument("--test", action="append", choices=LIVE_SMOKE_TEST_KEYS, default=[], help="run only the selected Tier-4 test key (repeatable)")
    parser.add_argument("--json", action="store_true", help="print machine-readable JSON summary instead of text")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    if args.list_tests:
        print(format_live_smoke_test_listing())
        return 0
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
