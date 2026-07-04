"""Ephemeral result types for gate and scoring runs (C-017 Finding).

Findings are aggregated into reports and returned to the caller. Nothing in
this module is ever persisted as a plan artifact.
"""

from __future__ import annotations

from dataclasses import dataclass

from plan_manager.storage.canonical import canonical_json

SEVERITIES = frozenset({"error", "warning"})


@dataclass(frozen=True)
class Finding:
    """A single ephemeral result unit of a gate or scoring run.

    Attributes:
        check_id: Identifier of the check that produced this finding.
        severity: One of the values in SEVERITIES ("error" or "warning").
        artifact_path: Branch artifact path the finding is anchored to.
        message: Human-readable description of the finding.
    """

    check_id: str
    severity: str
    artifact_path: str
    message: str


def sort_findings(findings: list[Finding]) -> list[Finding]:
    """Return findings sorted into the total deterministic order.

    Sort key is the tuple (artifact_path, check_id, message).

    Args:
        findings: Findings to sort. Not mutated.

    Returns:
        A new list of the same Finding objects sorted ascending by
        (artifact_path, check_id, message).
    """
    return sorted(findings, key=lambda f: (f.artifact_path, f.check_id, f.message))


@dataclass
class CheckResult:
    """The outcome of one check within a report.

    Attributes:
        check_id: Identifier of the check.
        passed: True iff no finding exists for this check_id.
        findings: Findings for this check_id, in sort_findings order.
    """

    check_id: str
    passed: bool
    findings: list[Finding]


@dataclass
class Report:
    """The aggregated outcome of a full gate or scoring run.

    Attributes:
        checks: One CheckResult per check_id, in the order the check_ids
            were given to build_report.
        green: True iff no finding exists across every CheckResult.
    """

    checks: list[CheckResult]
    green: bool


def build_report(check_ids: list[str], findings: list[Finding]) -> Report:
    """Build a Report with one CheckResult per check_id, in the given order.

    Args:
        check_ids: The ordered list of check identifiers to report on. The
            output has exactly one CheckResult per entry, in this order.
        findings: All findings produced by the run, in any order.

    Returns:
        A Report whose checks list has one CheckResult per entry of
        check_ids (in that order); each CheckResult's findings are the
        subset of `findings` whose check_id equals that CheckResult's
        check_id, sorted via sort_findings; passed is True iff that subset
        is empty; green is True iff `findings` is empty overall.

    Raises:
        ValueError: If any finding's check_id is not present in check_ids.
            The error message names the unknown check_id.
    """
    known = set(check_ids)
    for finding in findings:
        if finding.check_id not in known:
            raise ValueError(f"unknown check_id: {finding.check_id}")
    checks: list[CheckResult] = []
    for check_id in check_ids:
        matched = sort_findings([f for f in findings if f.check_id == check_id])
        checks.append(
            CheckResult(check_id=check_id, passed=len(matched) == 0, findings=matched)
        )
    return Report(checks=checks, green=len(findings) == 0)


def render_text(report: Report) -> str:
    """Render a Report as a per-check PASS/FAIL text report.

    Args:
        report: The Report to render.

    Returns:
        A string with one line per check: "<check_id>: PASS" if
        check.passed else "<check_id>: FAIL", immediately followed by one
        line per finding of that check in the format
        "  <artifact_path> [<severity>] <message>", all lines joined with
        "\n" with no trailing newline.
    """
    lines: list[str] = []
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        lines.append(f"{check.check_id}: {status}")
        for finding in check.findings:
            lines.append(
                f"  {finding.artifact_path} [{finding.severity}] {finding.message}"
            )
    return "\n".join(lines)


def render_json(report: Report) -> str:
    """Render a Report as its canonical JSON form."""
    payload = {
        "green": report.green,
        "checks": [
            {
                "check_id": check.check_id,
                "passed": check.passed,
                "findings": [
                    {
                        "check_id": finding.check_id,
                        "severity": finding.severity,
                        "artifact_path": finding.artifact_path,
                        "message": finding.message,
                    }
                    for finding in check.findings
                ],
            }
            for check in report.checks
        ],
    }
    encoded = canonical_json(payload)
    return encoded.decode("utf-8") if isinstance(encoded, bytes) else encoded

