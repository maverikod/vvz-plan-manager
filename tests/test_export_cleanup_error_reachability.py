"""Tests for error-code reachability in export_cleanup command (CR-2 phase 2, A-002).

Preserves error-code reachability discipline for export_cleanup without touching
the adjudicated allowlist in tests/test_error_code_reachability_cr1.py. Proves
that every error case documented in ExportCleanupCommand.metadata() is actually
reachable via its command surface.
"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from mcp_proxy_adapter.commands.result import ErrorResult

from plan_manager.commands import export_cleanup_command
from plan_manager.commands.export_cleanup_command import ExportCleanupCommand
import plan_manager.exchange.export_cleanup as export_cleanup


# --- fixtures ----------------------------------------------------------------

@contextmanager
def _fake_db():
    """Provide a fake database connection object (bare object with no SQL capability)."""
    yield object()


def _wire(monkeypatch, tmp_path: Path) -> None:
    """Wire up command-surface dependencies using monkeypatch."""
    monkeypatch.setattr(export_cleanup_command, "db_connection", _fake_db)
    monkeypatch.setattr(
        export_cleanup_command, "app_config",
        lambda: SimpleNamespace(export_root=str(tmp_path)),
    )
    # MANDATORY: list_plans is called before boundary check in classify_export_directories,
    # so stub it to avoid SQL errors on the fake connection.
    monkeypatch.setattr(
        export_cleanup, "list_plans",
        lambda conn, show_deleted=True: []
    )


def _run(**kwargs) -> SuccessResult | ErrorResult:
    """Execute ExportCleanupCommand.execute() and return its result object directly."""
    return asyncio.run(ExportCleanupCommand().execute(**kwargs))


# --- test suite --------------------------------------------------------------

def test_export_cleanup_documents_at_least_one_error_case() -> None:
    """Assert ExportCleanupCommand.metadata() defines at least one error case."""
    metadata = ExportCleanupCommand.metadata()
    assert "error_cases" in metadata
    error_cases = metadata["error_cases"]
    assert isinstance(error_cases, dict)
    assert len(error_cases) > 0, "error_cases must be non-empty for reachability tests to be meaningful"


def test_every_documented_error_case_is_reachable(monkeypatch, tmp_path: Path) -> None:
    """Verify every documented error case is actually reachable via command invocation.

    Derives the documented code set from live metadata (not hard-coded), builds a
    mapping from each code to its concrete negative invocation based on metadata
    description, drives each invocation, collects observed codes, and asserts
    observed == documented.
    """
    _wire(monkeypatch, tmp_path)

    # Read documented error cases from live metadata
    metadata = ExportCleanupCommand.metadata()
    documented = set(metadata["error_cases"].keys())

    # Build invocation mapping from documented codes
    # Each code maps to the kwargs needed to trigger it
    invocation_map: dict[str, dict] = {}

    for code in documented:
        case_spec = metadata["error_cases"][code]
        description = case_spec.get("description", "")

        if code == "EXPORT_PATH_INVALID":
            # From metadata: "A caller-supplied plan filter resolves to a directory
            # name that fails export-root boundary validation (an unsafe or
            # traversal-shaped name)."
            invocation_map[code] = {"plan": "../outside", "changed_by": "agent-1"}
        else:
            raise AssertionError(
                f"No invocation mapping defined for documented code '{code}'. "
                f"Extend the invocation_map with a concrete negative case based on "
                f"the code's metadata description: {description}"
            )

    # Drive each documented code and collect observed codes
    observed: set[str] = set()
    for code, kwargs in invocation_map.items():
        result = _run(**kwargs)
        assert isinstance(result, ErrorResult), (
            f"Invocation for code '{code}' with kwargs {kwargs} "
            f"should return ErrorResult, not {type(result).__name__}"
        )
        returned_code = result.details["domain_code"]
        observed.add(returned_code)

    # Verify every documented code was observed
    assert observed == documented, (
        f"Mismatch between documented and observed error codes. "
        f"Documented: {documented}, Observed: {observed}"
    )


def test_boundary_refusal_message_matches_its_documented_template(monkeypatch, tmp_path: Path) -> None:
    """Verify EXPORT_PATH_INVALID error message is consistent with documented template.

    Checks the invariant: the message names the offending plan filter and
    describes an export-root escape. Does NOT pin the exact full-string snapshot
    so harmless rewording does not fail the suite, but DOES fail if the message
    stops naming the offender or describing the escape.
    """
    _wire(monkeypatch, tmp_path)

    # Invoke the boundary-refusal case
    result = _run(plan="../outside", changed_by="agent-1")
    assert isinstance(result, ErrorResult)

    # Verify the code is correct
    assert result.details["domain_code"] == "EXPORT_PATH_INVALID"

    # Verify the message matches the documented template invariants:
    # - The template is: "export directory name escapes the export root: {plan}"
    # - Invariant 1: message names the offending plan filter ("../outside")
    # - Invariant 2: message describes an export-root escape
    message = result.message
    assert "../outside" in message, (
        f"Message should name the offending plan filter '../outside', "
        f"but got: {message}"
    )
    # Check for keywords indicating an export-root escape
    assert any(phrase in message.lower() for phrase in ["escapes", "escape", "export root", "export-root"]), (
        f"Message should describe an export-root escape, "
        f"but got: {message}"
    )
