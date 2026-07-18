"""Live Code Analysis server (CA) project/file existence confirmation (bug 5926d536).

planmgr previously accepted a bug/todo project or file anchor on UUID/path-shape
validation alone (``plan_manager.domain.primary_anchor.validate_anchor``,
``plan_manager.domain.runtime_validation.validate_file_reference``) with no
check that the analysis-server project (or file) actually exists -- a typo'd
project UUID was accepted silently, creating an invisible phantom-anchored
record. This module adds the missing LIVE check against the CA server's
``list_projects`` / ``list_project_files`` commands, reusing the
``code-analysis-client`` package already declared as a plan_manager dependency
(the same JSON-RPC transport pattern ``plan_manager.scoring.embedding`` uses
for the embedding service, adapted here for CA's mTLS transport).

CA commands are QUEUED (mcp-proxy-adapter's job/WS contract), not plain
request/response: a raw ``execute_command`` call returns only the JSON-RPC
``result`` field unchanged, which -- for a queued command -- is a queue
envelope (``job_id``/``status``), never the flattened ``{"projects": [...]}``
payload a naive caller would expect. This module therefore drives
``execute_command_unified`` (``auto_poll=True``), which transparently waits
out an actual queued job and normalizes both the immediate and queued cases
into one ``{"mode": ..., "result": ...}`` envelope; :func:`_unwrap_command_data`
then defensively peels that envelope (and the ``{"success", "data"}`` shape a
plain ``SuccessResult``-backed immediate response carries) down to the
command's own data dict, tolerating either nesting so a shape this module
hasn't seen folds to "ca_unreachable" instead of silently misreading absence
of the field as "not_found".

This module never raises to its caller: any transport failure (CA
unconfigured, connection refused, timeout, TLS/certificate error, malformed
or unrecognized envelope shape) folds into a ``"ca_unreachable"``
:class:`AnchorConfirmation`; only a clean, successfully-unwrapped CA response
that omits the requested project/file yields ``"not_found"``. Callers
(``plan_manager.commands.anchor_confirmation``) never persist an anchor that
is not ``confirmed``.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass
from typing import Any, Coroutine
from urllib.parse import urlparse

from code_analysis_client import CodeAnalysisAsyncClient


@dataclass(frozen=True)
class AnchorConfirmation:
    """Outcome of one live CA confirmation attempt.

    ``reason`` is ``None`` when ``confirmed`` is True, else exactly one of
    ``"ca_unreachable"`` (CA unconfigured, unreachable, or malformed
    response) or ``"not_found"`` (CA answered cleanly but the project, or
    the file within an existing project, is not listed).
    """

    confirmed: bool
    reason: str | None


class _CAUnavailable(Exception):
    """Internal signal that the CA transport failed; always folds to ca_unreachable."""


def _run_blocking(coro: Coroutine[Any, Any, AnchorConfirmation], timeout: float) -> AnchorConfirmation:
    """Run *coro* from synchronous command code, even inside a running event loop.

    Mirrors the bridging shape of ``plan_manager.scoring.embedding._run_async_blocking``
    (this module's callers are synchronous command code, same as the scoring
    path); kept as a local, CA-specific copy rather than a cross-package import
    of that private helper.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(asyncio.wait_for(coro, timeout=timeout))

    result: list[AnchorConfirmation] = []
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(asyncio.wait_for(coro, timeout=timeout)))
        except BaseException as exc:
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join(timeout + 1.0)
    if thread.is_alive():
        raise TimeoutError(f"CA confirmation timed out after {timeout} seconds")
    if error:
        raise error[0]
    return result[0]


def _client_from_url(
    base_url: str,
    *,
    timeout: float,
    cert: str | None,
    key: str | None,
    ca: str | None,
) -> CodeAnalysisAsyncClient:
    """Build a CA client from a "scheme://host:port" URL and mTLS material."""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https", "mtls"):
        raise _CAUnavailable(f"unsupported CA URL scheme: {parsed.scheme!r}")
    if not parsed.hostname:
        raise _CAUnavailable("CA URL must include a host")
    default_port = 443 if parsed.scheme in ("https", "mtls") else 80
    return CodeAnalysisAsyncClient(
        protocol=parsed.scheme,
        host=parsed.hostname,
        port=parsed.port or default_port,
        cert=cert,
        key=key,
        ca=ca,
        check_hostname=False,
        timeout=timeout,
    )


def _unwrap_command_data(envelope: Any) -> dict[str, Any]:
    """Peel an ``execute_command_unified`` envelope down to the command's own data dict.

    Tolerates every shape actually observed for a CA command response:

    - queued: ``{"mode": "queued", "result": <data-dict>, "job_id": ..., "status": ...}``
      -- the queued path already unwraps its own ``{"success", "data"}`` layer
      server-side (see ``execute_command_unified``'s queued branch), so
      ``result`` here IS the command's data dict directly.
    - immediate: ``{"mode": "immediate", "result": {"success": true, "data": <data-dict>}}``
      -- the raw JSON-RPC ``result`` field of a ``SuccessResult``-backed
      command, one more layer than the queued case.
    - a bare ``{"success": true, "data": <data-dict>}`` or a flat data dict
      passed directly (e.g. from a lower-level/legacy caller).

    Peels "result" if present, then peels "data" if the remaining dict also
    carries a "success" key (so a queued dict that happens to have a "data"
    key of its own is not double-unwrapped), then falls back to the
    remaining dict as the payload itself.

    Raises :class:`_CAUnavailable` when ``success`` is explicitly False, or
    when no dict payload can be recovered at all -- both cases must fold to
    "ca_unreachable", never be misread as a clean "not_found".
    """
    value: Any = envelope
    # The queued path DOUBLE-wraps: the unified mode-envelope's "result" is
    # itself a job envelope whose OWN "result" is the {success, data} layer,
    # observed live as {mode, command, job_id, status,
    #   result: {job_id, command, result: {success, data: {...}}}, ...}.
    # Peel "result" repeatedly (bounded) until we reach the {success, data}
    # layer; a single peel lands on {job_id, command, result: ...}, which has
    # no "success" key and would wrongly be returned as the payload.
    for _ in range(6):
        if not isinstance(value, dict):
            break
        if "success" in value:
            if value.get("success") is False:
                raise _CAUnavailable(
                    f"CA command failed: {value.get('message') or value.get('error') or value!r}"
                )
            data = value.get("data")
            if isinstance(data, dict):
                value = data
            break
        if "result" in value:
            value = value["result"]
            continue
        break
    if not isinstance(value, dict):
        raise _CAUnavailable(f"CA response did not resolve to a data dict: {envelope!r}")
    return value


async def _call_ca_command(client: CodeAnalysisAsyncClient, command: str, params: dict[str, Any], timeout: float) -> dict[str, Any]:
    """Invoke a CA command through the queued-aware unified path and unwrap its data.

    Uses ``execute_command_unified(..., auto_poll=True, timeout=timeout)`` (not
    the raw ``execute_command``) so a queued CA command -- ``list_projects``
    and ``list_project_files`` are queued commands on the live server -- is
    transparently waited out via its job/WS contract instead of returning a
    bare queue envelope (``job_id``/``status``) that a naive caller would
    misread as "no projects"/"no files".
    """
    try:
        envelope = await client.rpc.execute_command_unified(
            command, params, auto_poll=True, timeout=timeout
        )
    except Exception as exc:
        raise _CAUnavailable(str(exc)) from exc
    return _unwrap_command_data(envelope)


async def _confirm_async(
    base_url: str,
    project_id: uuid.UUID,
    file_path: str | None,
    timeout: float,
    cert: str | None,
    key: str | None,
    ca: str | None,
) -> AnchorConfirmation:
    """Confirm ``project_id`` (and ``file_path`` when given) against a live CA server."""
    client = _client_from_url(base_url, timeout=timeout, cert=cert, key=key, ca=ca)
    try:
        projects_data = await _call_ca_command(client, "list_projects", {}, timeout)
        projects = projects_data.get("projects")
        if not isinstance(projects, list):
            raise _CAUnavailable("list_projects data missing 'projects' list")
        known_project_ids = {
            str(item["id"]) for item in projects if isinstance(item, dict) and item.get("id")
        }
        if str(project_id) not in known_project_ids:
            return AnchorConfirmation(confirmed=False, reason="not_found")

        if file_path is None:
            return AnchorConfirmation(confirmed=True, reason=None)

        files_data = await _call_ca_command(
            client,
            "list_project_files",
            {"project_id": str(project_id), "file_pattern": file_path},
            timeout,
        )
        # The live list_project_files data payload carries both "files" and
        # "items" arrays of the same entries; accept either name.
        files = files_data.get("files")
        if files is None:
            files = files_data.get("items")
        if not isinstance(files, list):
            raise _CAUnavailable("list_project_files data missing 'files'/'items' list")
        matched = any(
            isinstance(entry, dict) and entry.get("relative_path") == file_path
            for entry in files
        )
        return AnchorConfirmation(confirmed=matched, reason=None if matched else "not_found")
    finally:
        try:
            await client.rpc.close()
        except Exception:
            pass


def confirm_project_anchor(
    *,
    ca_url: str | None,
    project_id: uuid.UUID,
    file_path: str | None,
    timeout: float,
    cert: str | None = None,
    key: str | None = None,
    ca: str | None = None,
) -> AnchorConfirmation:
    """Confirm a project (and optional file) anchor against the live CA server.

    Returns ``confirmed=False, reason="ca_unreachable"`` when ``ca_url`` is
    ``None``/unconfigured, or on any transport failure (connection refused,
    timeout, TLS/certificate error, malformed response, or the bounded
    ``timeout`` elapsing). Returns ``confirmed=False, reason="not_found"``
    only for a clean CA response that does not list the requested project
    (or, when ``file_path`` is given, does not list that file under the
    confirmed project). Never raises -- every failure mode is folded into
    the returned :class:`AnchorConfirmation` so a slow/unreachable CA can
    never hang or fail a bug/todo create.
    """
    if not ca_url:
        return AnchorConfirmation(confirmed=False, reason="ca_unreachable")
    try:
        return _run_blocking(
            _confirm_async(ca_url, project_id, file_path, timeout, cert, key, ca),
            timeout=timeout,
        )
    except Exception:
        return AnchorConfirmation(confirmed=False, reason="ca_unreachable")
