"""Shared CA external-file probe resolution for every gate caller (EIG block G).

EIG block F wired the live CA project-file inventory
(``runtime.ca_files_probe.list_project_files_probe``) into exactly ONE
``run_gate`` caller, ``commands.plan_validate_command``; every other caller
-- the freeze gate, cascade preview and commit, plan_prompt_chain,
plan_status, and the scoring index -- deliberately stayed probe-less and was
recorded as the block-F residual. Block G closes that residual, which means
the resolution logic needs a home that all of ``commands``, ``cascade``, and
``scoring`` can import without any of them importing each other. This module
is that home; ``plan_validate_command`` re-exports ``resolve_external_files``
so its own public name is unchanged.

Nothing here ever raises. A caller that cannot reach the CA, cannot read the
plan, or has no project binding at all gets ``(None-or-unavailable probe,
False, payload)`` and therefore exactly the pre-block-F gate behaviour --
absence of knowledge is never a violation (see
``verify.gate_execution_existence``'s degraded-policy matrix).

ASYNC BOUNDARY. ``list_project_files_probe`` bridges its own async transport
through ``ca_client._run_blocking``, which detects a running event loop and
runs the coroutine on a worker thread. Both synchronous callers (cascade,
scoring) and ``async def execute`` command bodies therefore call this module
the same way, exactly as ``plan_validate_command`` already did.
"""

from __future__ import annotations

import uuid
from typing import Any

from plan_manager.domain.plan import get_plan
from plan_manager.runtime.ca_files_probe import (
    ExternalFilesProbe,
    list_project_files_probe,
)
from plan_manager.runtime.context import app_config

ProbeResolution = tuple["ExternalFilesProbe | None", bool, dict[str, Any]]


def resolve_external_files(plan: Any) -> ProbeResolution:
    """Fetch the live CA file inventory of ``plan``'s PRIMARY project (EIG block F).

    Returns ``(probe, require_project_verification, payload)`` where
    ``payload`` is the additive ``external_verification`` response key:

    - ``{"status": "skipped", "reason": "no_primary_project"}`` when the plan
      has no primary project binding (``plan.primary_project_id``), or that
      binding is not a UUID. No probe is fetched and ``probe`` is None, so
      every block-F check stays silent -- a plan bound to nothing is never
      redded for it.
    - ``{"status": "unavailable", "reason": "ca_unreachable"}`` when the
      probe was attempted but the listing could not be read.
    - ``{"status": "ok", "reason": None}`` when the full inventory was read.

    Never raises: ``list_project_files_probe`` already folds every transport
    failure into an unavailable probe, and a runtime whose configuration is
    not initialized (``app_config`` raising) is treated the same way -- the
    gate must degrade, never fail a read-only call. ``getattr`` is used for
    ``primary_project_id`` so a caller-supplied plan projection that predates
    project bindings is a "skipped", not an AttributeError.
    """
    primary = getattr(plan, "primary_project_id", None)
    if not primary:
        return None, False, {"status": "skipped", "reason": "no_primary_project"}
    try:
        project_id = uuid.UUID(str(primary))
        config = app_config()
        probe = list_project_files_probe(
            ca_url=config.code_analysis_url,
            project_id=project_id,
            timeout=config.code_analysis_timeout,
            cert=config.code_analysis_cert,
            key=config.code_analysis_key,
            ca=config.code_analysis_ca,
        )
        require = config.require_project_verification
    except ValueError:
        return None, False, {"status": "skipped", "reason": "no_primary_project"}
    except Exception:
        probe = ExternalFilesProbe(available=False, reason="ca_unreachable")
        require = False
    if probe.available:
        return probe, require, {"status": "ok", "reason": None}
    return probe, require, {"status": "unavailable", "reason": probe.reason}


def resolve_external_files_for_plan(conn: Any, plan_uuid: uuid.UUID) -> ProbeResolution:
    """Resolve the probe for a plan the caller holds only by uuid.

    ``plan_validate`` already has the resolved plan aggregate in hand; the
    other gate callers (cascade preview/commit, the freeze gate, the scoring
    index) only have ``(conn, plan_uuid)``, so the plan row is read here.

    Never raises. A plan row that cannot be read -- a hard-deleted plan, a
    caller-supplied connection that does not serve this query -- degrades to
    ``{"status": "skipped", "reason": "plan_unreadable"}`` with no probe,
    which is behaviourally identical to having no project binding: the
    block-F existence checks stay silent and the gate keeps exactly its
    pre-block-G verdict.
    """
    try:
        plan = get_plan(conn, plan_uuid)
    except Exception:
        return None, False, {"status": "skipped", "reason": "plan_unreadable"}
    if plan is None:
        return None, False, {"status": "skipped", "reason": "plan_unreadable"}
    return resolve_external_files(plan)
