"""Live CA project-file inventory probe for the mechanical gate (EIG block F).

``runtime.ca_client.confirm_project_anchor`` answers one narrow question --
"does THIS project (or THIS file) exist?" -- with a per-file
``list_project_files`` call filtered by ``file_pattern``. The
execution-integrity existence checks (``verify.gate_execution_existence``)
need the opposite shape: the WHOLE project-relative file inventory once, so a
gate pass over a plan with N atomic steps stays independent of N and every
check answers from one in-memory snapshot.

This module is that snapshot. It reuses ``ca_client``'s transport pieces
verbatim (``_client_from_url``, ``_call_ca_command``, ``_unwrap_command_data``
via that call, ``_run_blocking``) and therefore inherits their never-raise
contract: CA unconfigured, unreachable, TLS-broken, malformed, or slow all
fold into ``ExternalFilesProbe(available=False, reason="ca_unreachable")``.
It lives in its own module rather than inside ``ca_client`` only to keep that
file under the repository's ~400-line cap.

PAGINATION. Unlike the single-file confirmation, a whole-project listing must
page: the live ``list_project_files`` command (casmgr 1.3.0) returns at most
``page_size`` rows (default 20, maximum 200) plus a ``total`` counted BEFORE
pagination, and advances by 1-based ``block_position``. The probe therefore
issues one call per page at the maximum page size and stops as soon as
``total`` rows are collected. A project too large for ``_MAX_FILE_PAGES``
pages is NOT truncated silently: a partial inventory would make files that
genuinely exist look missing and red an innocent plan, so an incomplete read
folds to ``available=False`` exactly like an unreachable server. That is the
whole safety principle of this module -- the probe reports "I do not know"
far more readily than it reports "that file is absent".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from plan_manager.runtime.ca_client import (
    _CAUnavailable,
    _call_ca_command,
    _client_from_url,
    _run_blocking,
)

# Maximum rows the live list_project_files command accepts per page.
_PAGE_SIZE = 200
# Hard cap on sequential paged CA calls for one probe. 25 pages x 200 rows =
# 5000 project-relative files; a project above that folds to unavailable
# rather than being read partially (see the module docstring).
_MAX_FILE_PAGES = 25


@dataclass(frozen=True)
class ExternalFilesProbe:
    """One project's project-relative file inventory, as read from the live CA.

    Attributes:
        available: True only when the full inventory was read cleanly. False
            for every failure mode -- CA unconfigured, unreachable, malformed
            response, or a listing too large to read completely.
        reason: None when ``available`` is True, else ``"ca_unreachable"``
            (the single failure reason this probe distinguishes: unlike an
            anchor confirmation there is no "not_found" case, because the
            question is "what exists", not "does X exist").
        files: Project-relative POSIX paths (``relative_path`` as CA reports
            it), empty and meaningless whenever ``available`` is False.
    """

    available: bool
    reason: str | None
    files: frozenset[str] = field(default_factory=frozenset)


def _files_from_page(page: dict) -> list[dict]:
    """Extract one page's file entries, tolerating the "files"/"items" pair.

    The live payload carries both names for the same array (the same
    tolerance ``ca_client._confirm_async`` already applies); anything else
    is a shape this module does not understand and must fold to unreachable
    rather than be misread as an empty project.
    """
    entries = page.get("files")
    if entries is None:
        entries = page.get("items")
    if not isinstance(entries, list):
        raise _CAUnavailable("list_project_files data missing 'files'/'items' list")
    return [entry for entry in entries if isinstance(entry, dict)]


async def _probe_async(
    base_url: str,
    project_id: uuid.UUID,
    timeout: float,
    cert: str | None,
    key: str | None,
    ca: str | None,
) -> ExternalFilesProbe:
    """Read every page of ``project_id``'s file listing into one probe."""
    client = _client_from_url(base_url, timeout=timeout, cert=cert, key=key, ca=ca)
    try:
        collected: set[str] = set()
        total: int | None = None
        for block_position in range(1, _MAX_FILE_PAGES + 1):
            page = await _call_ca_command(
                client,
                "list_project_files",
                {
                    "project_id": str(project_id),
                    "page_size": _PAGE_SIZE,
                    "block_position": block_position,
                },
                timeout,
            )
            if total is None:
                candidate_total = page.get("total")
                total = candidate_total if isinstance(candidate_total, int) else None
                if total is not None and total > _MAX_FILE_PAGES * _PAGE_SIZE:
                    # Refuse a knowingly partial inventory (module docstring).
                    raise _CAUnavailable(
                        f"project file listing of {total} rows exceeds the "
                        f"{_MAX_FILE_PAGES * _PAGE_SIZE}-row probe cap"
                    )
            entries = _files_from_page(page)
            for entry in entries:
                relative_path = entry.get("relative_path")
                if isinstance(relative_path, str) and relative_path.strip():
                    collected.add(relative_path.strip())
            if len(entries) < _PAGE_SIZE:
                break
            if total is not None and len(collected) >= total:
                break
        if total is not None and len(collected) < total:
            raise _CAUnavailable(
                f"read {len(collected)} of {total} project files before the page cap"
            )
        return ExternalFilesProbe(
            available=True, reason=None, files=frozenset(collected)
        )
    finally:
        try:
            await client.rpc.close()
        except Exception:
            pass


def list_project_files_probe(
    *,
    ca_url: str | None,
    project_id: uuid.UUID,
    timeout: float,
    cert: str | None = None,
    key: str | None = None,
    ca: str | None = None,
) -> ExternalFilesProbe:
    """Read ``project_id``'s full project-relative file inventory from the live CA.

    Never raises. Returns ``ExternalFilesProbe(available=False,
    reason="ca_unreachable", files=frozenset())`` when ``ca_url`` is
    ``None``/unconfigured and on every transport or shape failure
    (connection refused, timeout, TLS/certificate error, unrecognized
    envelope, a listing larger than the probe's page cap, or an incomplete
    read) -- the same never-raise, bounded-budget contract
    ``ca_client.confirm_project_anchor`` carries, so a slow or unreachable
    CA degrades the gate instead of failing a plan_validate call.

    ``timeout`` is the PER-CA-CALL budget, exactly as in
    ``confirm_project_anchor``; the overall guard is sized from it times the
    page cap, since a full inventory makes one sequential queued call per
    page.
    """
    if not ca_url:
        return ExternalFilesProbe(available=False, reason="ca_unreachable")
    try:
        overall_budget = timeout * (_MAX_FILE_PAGES + 1) + 5.0
        return _run_blocking(
            _probe_async(ca_url, project_id, timeout, cert, key, ca),
            timeout=overall_budget,
        )
    except Exception:
        return ExternalFilesProbe(available=False, reason="ca_unreachable")
