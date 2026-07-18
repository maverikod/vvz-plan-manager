"""Regression tests for bug 5926d536: planmgr did not verify analysis-server
project existence, silently accepting a typo'd project UUID (or nonexistent
file) as a live-looking bug/todo anchor.

Covers, at the two layers introduced by the fix:

- ``plan_manager.runtime.ca_client.confirm_project_anchor``: the CA transport
  primitive. Never raises; folds every transport failure (unconfigured,
  unreachable, malformed response, bounded-timeout) into
  ``AnchorConfirmation(confirmed=False, reason="ca_unreachable")``, and only a
  clean CA response that omits the project/file into
  ``AnchorConfirmation(confirmed=False, reason="not_found")``.
- ``plan_manager.commands.anchor_confirmation.confirm_anchor``: the shared
  command-layer helper reused by bug_create, bug_reanchor, todo_create, and
  todo_reanchor -- a no-op pass-through for every anchor kind other than
  "project"/"file", delegating to the CA transport otherwise.

Command-level wiring (confirmed -> anchored; not confirmed -> unanchored +
reason surfaced in the response; bug_list/todo_list's unanchored_only finds
the resulting records) is covered by test_anchor_confirmation_commands.py and
test_list_sql_pushdown.py.
"""
from __future__ import annotations

import uuid

from plan_manager.commands import anchor_confirmation as ac_module
from plan_manager.commands.anchor_confirmation import confirm_anchor
from plan_manager.runtime import ca_client
from plan_manager.runtime.ca_client import AnchorConfirmation, confirm_project_anchor
from plan_manager.runtime.context import AppConfig


def _app_config(**overrides) -> AppConfig:
    base = dict(
        embedding_url=None,
        embedding_timeout=30.0,
        code_analysis_url="mtls://casmgr:15010",
        code_analysis_timeout=1.0,
        code_analysis_cert="/etc/planmgr/secrets/client.crt",
        code_analysis_key="/etc/planmgr/secrets/client.key",
        code_analysis_ca="/etc/planmgr/secrets/ca.crt",
        export_root="/tmp/export",
        scoring_threshold=85.0,
        scoring_aggregation="minimum",
        trust_floor=0.2,
        concept_weight=1.0,
    )
    base.update(overrides)
    return AppConfig(**base)


# --- plan_manager.runtime.ca_client: the CA transport primitive -------------------


def _immediate_envelope(data: dict) -> dict:
    """Build a real execute_command_unified "immediate" envelope.

    Matches mcp_proxy_adapter's actual shape: the raw JSON-RPC ``result`` of a
    SuccessResult-backed command is ``{"success": true, "data": {...}}``, and
    ``execute_command_unified`` wraps that UNCHANGED as the immediate
    envelope's own ``result`` -- one nesting layer deeper than the queued
    case below (see execute_command_unified's immediate branch).
    """
    return {"mode": "immediate", "command": "x", "result": {"success": True, "data": data}, "queued": False}


def _queued_envelope(data: dict) -> dict:
    """Build a real execute_command_unified "queued" envelope.

    Captured live (2026-07-18, casmgr 1.6.53) from inside the deployed
    container: the queued branch DOUBLE-wraps -- the mode-envelope's
    ``result`` is itself a job envelope whose OWN ``result`` is the
    ``{"success", "data"}`` layer, which is NOT unwrapped server-side:
    ``{"mode": "queued", ..., "result": {"job_id", "command",
    "result": {"success": True, "data": {...}}}}``. A single peel of
    ``result`` lands on ``{"job_id", "command", "result": ...}`` (no
    "success"/"projects" key), which is exactly the shape that made the
    first cut mis-read every live response as ca_unreachable.
    """
    return {
        "mode": "queued",
        "command": "x",
        "job_id": "job-1",
        "status": "completed",
        "result": {"job_id": "job-1", "command": "x", "result": {"success": True, "data": data}},
        "queued": True,
        "raw_status": {},
    }


class _FakeRpc:
    def __init__(self, *, projects_envelope=None, files_envelope=None, project_exc=None, files_exc=None):
        self._projects_envelope = projects_envelope
        self._files_envelope = files_envelope
        self._project_exc = project_exc
        self._files_exc = files_exc
        self.calls: list[tuple[str, dict]] = []
        self.closed = False

    async def execute_command_unified(self, command, params, *, auto_poll, timeout):
        self.calls.append((command, dict(params)))
        assert auto_poll is True
        if command == "list_projects":
            if self._project_exc is not None:
                raise self._project_exc
            return self._projects_envelope
        if command == "list_project_files":
            if self._files_exc is not None:
                raise self._files_exc
            return self._files_envelope
        raise AssertionError(f"unexpected CA command: {command}")

    async def close(self):
        self.closed = True


class _FakeClient:
    def __init__(self, rpc: _FakeRpc):
        self.rpc = rpc


def _patch_client(monkeypatch, rpc: _FakeRpc):
    def _fake_client_from_url(base_url, *, timeout, cert, key, ca):
        return _FakeClient(rpc)

    monkeypatch.setattr(ca_client, "_client_from_url", _fake_client_from_url)


def test_confirm_project_anchor_unconfigured_is_ca_unreachable(monkeypatch) -> None:
    def _boom(*a, **kw):
        raise AssertionError("CA transport must not be contacted when ca_url is unconfigured")

    monkeypatch.setattr(ca_client, "_client_from_url", _boom)
    result = confirm_project_anchor(ca_url=None, project_id=uuid.uuid4(), file_path=None, timeout=1.0)
    assert result == AnchorConfirmation(confirmed=False, reason="ca_unreachable")


def test_confirm_project_anchor_project_found_confirms_immediate_envelope(monkeypatch) -> None:
    """The immediate {"mode":"immediate","result":{"success":true,"data":{...}}} shape."""
    project_id = uuid.uuid4()
    rpc = _FakeRpc(projects_envelope=_immediate_envelope({"projects": [{"id": str(project_id)}], "count": 1}))
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=project_id, file_path=None, timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=True, reason=None)
    assert [c[0] for c in rpc.calls] == ["list_projects"]
    assert rpc.closed is True


def test_confirm_project_anchor_project_found_confirms_queued_envelope(monkeypatch) -> None:
    """The queued {"mode":"queued","result":{...data...},"job_id":...} shape (the one the
    original flat-fake implementation would have misread as ca_unreachable, per L1's finding)."""
    project_id = uuid.uuid4()
    rpc = _FakeRpc(projects_envelope=_queued_envelope({"projects": [{"id": str(project_id)}], "count": 1}))
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=project_id, file_path=None, timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=True, reason=None)
    assert [c[0] for c in rpc.calls] == ["list_projects"]


def test_confirm_project_anchor_project_not_in_list_is_not_found(monkeypatch) -> None:
    rpc = _FakeRpc(projects_envelope=_immediate_envelope({"projects": [{"id": str(uuid.uuid4())}], "count": 1}))
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=uuid.uuid4(), file_path="src/x.py", timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=False, reason="not_found")
    # File-path validation requires the project to exist first: since the project
    # was not found, list_project_files must never be attempted.
    assert [c[0] for c in rpc.calls] == ["list_projects"]


def test_confirm_project_anchor_file_found_confirms_via_files_key(monkeypatch) -> None:
    project_id = uuid.uuid4()
    rpc = _FakeRpc(
        projects_envelope=_immediate_envelope({"projects": [{"id": str(project_id)}]}),
        files_envelope=_immediate_envelope(
            {"files": [{"relative_path": "src/save.py"}, {"relative_path": "src/other.py"}]}
        ),
    )
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=project_id, file_path="src/save.py", timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=True, reason=None)
    assert [c[0] for c in rpc.calls] == ["list_projects", "list_project_files"]


def test_confirm_project_anchor_file_found_confirms_via_items_key_queued(monkeypatch) -> None:
    """The live list_project_files data payload carries both "files" and "items"; this
    exercises the "items" fallback through the queued envelope shape."""
    project_id = uuid.uuid4()
    rpc = _FakeRpc(
        projects_envelope=_queued_envelope({"projects": [{"id": str(project_id)}]}),
        files_envelope=_queued_envelope({"items": [{"relative_path": "src/save.py"}]}),
    )
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=project_id, file_path="src/save.py", timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=True, reason=None)


def test_confirm_project_anchor_file_not_found(monkeypatch) -> None:
    project_id = uuid.uuid4()
    rpc = _FakeRpc(
        projects_envelope=_immediate_envelope({"projects": [{"id": str(project_id)}]}),
        files_envelope=_immediate_envelope({"files": [{"relative_path": "src/other.py"}]}),
    )
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=project_id, file_path="src/missing.py", timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=False, reason="not_found")


def test_confirm_project_anchor_transport_exception_is_ca_unreachable(monkeypatch) -> None:
    rpc = _FakeRpc(project_exc=RuntimeError("connection refused"))
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=uuid.uuid4(), file_path=None, timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=False, reason="ca_unreachable")


def test_confirm_project_anchor_file_check_transport_exception_is_ca_unreachable(monkeypatch) -> None:
    project_id = uuid.uuid4()
    rpc = _FakeRpc(
        projects_envelope=_immediate_envelope({"projects": [{"id": str(project_id)}]}),
        files_exc=RuntimeError("timed out"),
    )
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=project_id, file_path="src/save.py", timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=False, reason="ca_unreachable")


def test_confirm_project_anchor_malformed_response_is_ca_unreachable(monkeypatch) -> None:
    """A response that unwraps to a dict but lacks the expected 'projects' key."""
    rpc = _FakeRpc(projects_envelope=_immediate_envelope({"not_projects": []}))
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=uuid.uuid4(), file_path=None, timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=False, reason="ca_unreachable")


def test_confirm_project_anchor_bare_queue_envelope_without_data_is_ca_unreachable(monkeypatch) -> None:
    """Regression for the exact defect L1 found: a raw queue envelope (job_id/status,
    no data reachable at all) must fold to ca_unreachable, never silently read as
    'no projects' -> not_found."""
    rpc = _FakeRpc(
        projects_envelope={"mode": "queued", "job_id": "job-1", "status": "pending", "result": "not-a-dict"}
    )
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=uuid.uuid4(), file_path=None, timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=False, reason="ca_unreachable")


def test_confirm_project_anchor_explicit_failure_response_is_ca_unreachable(monkeypatch) -> None:
    rpc = _FakeRpc(
        projects_envelope={
            "mode": "immediate",
            "result": {"success": False, "message": "boom"},
            "queued": False,
        }
    )
    _patch_client(monkeypatch, rpc)
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=uuid.uuid4(), file_path=None, timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=False, reason="ca_unreachable")


def test_confirm_project_anchor_unsupported_scheme_is_ca_unreachable() -> None:
    # No monkeypatch: _client_from_url itself rejects the scheme before any I/O.
    result = confirm_project_anchor(
        ca_url="ftp://casmgr:15010", project_id=uuid.uuid4(), file_path=None, timeout=1.0
    )
    assert result == AnchorConfirmation(confirmed=False, reason="ca_unreachable")


def test_confirm_project_anchor_bounded_timeout_does_not_hang(monkeypatch) -> None:
    """A slow/unreachable CA must fall to the unreachable path quickly, not hang."""
    import asyncio

    class _HangingRpc(_FakeRpc):
        async def execute_command_unified(self, command, params, *, auto_poll, timeout):
            await asyncio.sleep(5.0)
            raise AssertionError("must never complete within the bounded timeout")

    _patch_client(monkeypatch, _HangingRpc())
    import time

    start = time.monotonic()
    result = confirm_project_anchor(
        ca_url="mtls://casmgr:15010", project_id=uuid.uuid4(), file_path=None, timeout=0.2
    )
    elapsed = time.monotonic() - start
    assert result == AnchorConfirmation(confirmed=False, reason="ca_unreachable")
    assert elapsed < 3.0, f"CA confirmation did not honor the bounded timeout: took {elapsed}s"


# --- plan_manager.commands.anchor_confirmation.confirm_anchor: shared helper -----


def test_confirm_anchor_not_applicable_for_non_project_file_types(monkeypatch) -> None:
    def _boom(*a, **kw):
        raise AssertionError("CA must not be consulted for a non-project/file anchor type")

    monkeypatch.setattr(ac_module, "confirm_project_anchor", _boom)
    for requested_type in ("plan", "step", "command", "runtime_service", "execution_attempt", "unidentified", "none", "todo", "bug", "bug_fix"):
        result = confirm_anchor(
            lambda: _app_config(), requested_type=requested_type, project_id=uuid.uuid4(), file_path=None
        )
        assert result.applicable is False
        assert result.confirmed is True
        assert result.reason is None


def test_confirm_anchor_not_applicable_when_project_id_missing(monkeypatch) -> None:
    def _boom(*a, **kw):
        raise AssertionError("CA must not be consulted without a project_id")

    monkeypatch.setattr(ac_module, "confirm_project_anchor", _boom)
    result = confirm_anchor(lambda: _app_config(), requested_type="project", project_id=None, file_path=None)
    assert result.applicable is False
    assert result.confirmed is True


def test_confirm_anchor_project_type_never_forwards_file_path(monkeypatch) -> None:
    captured = {}

    def _fake_confirm(*, ca_url, project_id, file_path, timeout, cert, key, ca):
        captured["file_path"] = file_path
        return AnchorConfirmation(confirmed=True, reason=None)

    monkeypatch.setattr(ac_module, "confirm_project_anchor", _fake_confirm)
    confirm_anchor(
        lambda: _app_config(), requested_type="project", project_id=uuid.uuid4(), file_path="src/stray.py"
    )
    assert captured["file_path"] is None


def test_confirm_anchor_file_type_forwards_file_path(monkeypatch) -> None:
    captured = {}

    def _fake_confirm(*, ca_url, project_id, file_path, timeout, cert, key, ca):
        captured["file_path"] = file_path
        captured["ca_url"] = ca_url
        captured["timeout"] = timeout
        return AnchorConfirmation(confirmed=True, reason=None)

    monkeypatch.setattr(ac_module, "confirm_project_anchor", _fake_confirm)
    cfg = _app_config(code_analysis_url="mtls://casmgr:15010", code_analysis_timeout=7.0)
    result = confirm_anchor(lambda: cfg, requested_type="file", project_id=uuid.uuid4(), file_path="src/save.py")
    assert captured["file_path"] == "src/save.py"
    assert captured["ca_url"] == "mtls://casmgr:15010"
    assert captured["timeout"] == 7.0
    assert result.applicable is True
    assert result.confirmed is True
    assert result.reason is None


def test_confirm_anchor_propagates_not_found(monkeypatch) -> None:
    monkeypatch.setattr(
        ac_module, "confirm_project_anchor", lambda **kw: AnchorConfirmation(confirmed=False, reason="not_found")
    )
    result = confirm_anchor(lambda: _app_config(), requested_type="project", project_id=uuid.uuid4(), file_path=None)
    assert result.applicable is True
    assert result.confirmed is False
    assert result.reason == "not_found"


def test_confirm_anchor_propagates_ca_unreachable(monkeypatch) -> None:
    monkeypatch.setattr(
        ac_module,
        "confirm_project_anchor",
        lambda **kw: AnchorConfirmation(confirmed=False, reason="ca_unreachable"),
    )
    result = confirm_anchor(lambda: _app_config(), requested_type="file", project_id=uuid.uuid4(), file_path="x.py")
    assert result.applicable is True
    assert result.confirmed is False
    assert result.reason == "ca_unreachable"


def test_anchor_confirmation_to_payload() -> None:
    from plan_manager.commands.anchor_confirmation import AnchorConfirmation as CmdAnchorConfirmation

    outcome = CmdAnchorConfirmation(applicable=True, confirmed=False, reason="not_found")
    assert outcome.to_payload("project") == {
        "requested_type": "project",
        "confirmed": False,
        "reason": "not_found",
    }
