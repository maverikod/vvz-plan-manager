"""Embedded fenced-code-block parsing check for the mechanical gate (C-008).

Extends the mechanical gate with a check that every fenced code block
inside an atomic-step prompt PARSES for its declared language, closing
the defect class where an over-escaped block passes gate review because
no check inspects fenced source. Python via the standard-library ast
module; SQL via the sqlglot SQL parser (AdditiveMetricsMigrationAndDeps,
C-012), postgres dialect. This module is read-only: it never mutates the
tree or any Step object passed to it.

Fenced blocks are located with a CommonMark-style line-based scanner
(see ``_extract_fenced_blocks``), not a regular expression: a naive
greedy regex over the whole prompt text mis-pairs fences when a block's
content (e.g. a regex or string literal) contains a run of backticks
mid-line. The line scanner only treats a line as a closing fence when,
after stripping surrounding whitespace, the ENTIRE line is a run of
backticks at least as long as the opener's run; a backtick sequence that
merely appears within a content line is never mistaken for a fence
boundary.
"""

from __future__ import annotations

import ast

import sqlglot
from sqlglot.errors import ParseError as SqlglotParseError

from plan_manager.domain.step import Step
from plan_manager.verify.finding import Finding
from plan_manager.verify.gate_data import GateTree, artifact_path_of

_PYTHON_LANGUAGE_TOKENS = frozenset({"python", "py"})
_SQL_LANGUAGE_TOKENS = frozenset({"sql", "postgresql"})


def _path(tree: GateTree, step: Step) -> str:
    try:
        return artifact_path_of(tree.steps, step)
    except ValueError:
        return step.step_id


def _first_line(body: str) -> str:
    """Return the first non-empty line of body, or "" when body has none.

    Args:
        body: The fenced block's body text.

    Returns:
        The first line of body with non-whitespace content, stripped of
        no characters (returned exactly as it appears in body); "" when
        every line of body is empty or whitespace-only.
    """
    for line in body.splitlines():
        if line.strip():
            return line
    return ""


def _is_closing_fence_line(line: str, opener_run: int) -> bool:
    """Return True when line is exactly a backtick run >= opener_run.

    Leading and trailing whitespace is ignored; the remaining content
    must consist solely of backtick characters, and there must be at
    least opener_run of them. A line that merely contains a shorter or
    embedded run of backticks (mid-line, or trailed by other text) is
    not a closer.
    """
    stripped = line.strip()
    if not stripped:
        return False
    if any(ch != "`" for ch in stripped):
        return False
    return len(stripped) >= opener_run


def _extract_fenced_blocks(text: str) -> list[tuple[str, str]]:
    """Scan text line by line and return each fenced block as (language, body).

    A line is an OPENER when, after stripping leading spaces, it starts
    with a run of three or more backticks; everything after that run on
    the same line is the info-string. The language is the info-string's
    first whitespace-delimited token, lowercased ("" when the
    info-string has none).

    A subsequent line is the matching CLOSER when, after stripping
    surrounding whitespace, it consists solely of a backtick run at
    least as long as the opener's run. Lines that merely contain
    backticks (e.g. inside a string literal or regex) do not qualify as
    closers and are treated as ordinary block content.

    Block content is the verbatim sequence of lines strictly between
    opener and closer. When no closer is found before end of text, the
    block runs to the end of text.

    Blocks are returned in document order.
    """
    lines = text.split("\n")
    blocks: list[tuple[str, str]] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        leading_stripped = line.lstrip(" ")
        run = 0
        while run < len(leading_stripped) and leading_stripped[run] == "`":
            run += 1
        if run < 3:
            i += 1
            continue
        info_string = leading_stripped[run:]
        tokens = info_string.strip().lower().split()
        language = tokens[0] if tokens else ""
        body_lines: list[str] = []
        i += 1
        while i < n and not _is_closing_fence_line(lines[i], run):
            body_lines.append(lines[i])
            i += 1
        # Either lines[i] is the closer (skip it) or i == n (unterminated).
        if i < n:
            i += 1
        blocks.append((language, "\n".join(body_lines)))
    return blocks


def check_embedded_code_parses(tree: GateTree, steps: list[Step]) -> list[Finding]:
    """Check that every fenced code block in each atomic step's prompt parses.

    Scans the "prompt" field of every level-5 step in steps for fenced
    code blocks using a CommonMark-style line-based scanner (see
    ``_extract_fenced_blocks``), immune to backticks that appear inside a
    block's content. Blocks are processed in the order they appear in
    the field text, 0-indexed per step.

    For each block, the language is read from the fence's info-string
    (first whitespace-separated token, lowercased):

    - "python" or "py": the block body is parsed with ast.parse. A
      SyntaxError produces one error Finding.
    - "sql" or "postgresql": the block body is parsed with
      sqlglot.parse(body, read="postgres"). A sqlglot.errors.ParseError
      produces one error Finding.
    - any other token, or an empty info-string: the block is not a
      recognized code block. It is not validated and produces no
      Finding.
    - a recognized block that parses without raising produces no
      Finding.

    Args:
        tree: The loaded read-only plan tree, used to resolve each
            step's artifact path for finding attribution.
        steps: The steps in the current gate run's scope. Only level-5
            steps are inspected; other levels are skipped.

    Returns:
        A list of Finding objects, one per invalid recognized-language
        block found, in no particular order. Every Finding has check_id
        "embedded_code.parses" and severity "error".
    """
    findings: list[Finding] = []
    for step in steps:
        if step.level != 5:
            continue
        prompt = step.fields.get("prompt")
        if not isinstance(prompt, str) or not prompt:
            continue
        for index, (language, body) in enumerate(_extract_fenced_blocks(prompt)):
            if language in _PYTHON_LANGUAGE_TOKENS:
                try:
                    ast.parse(body)
                except SyntaxError as exc:
                    findings.append(
                        Finding(
                            check_id="embedded_code.parses",
                            severity="error",
                            artifact_path=_path(tree, step),
                            message=(
                                f"embedded python block {index} "
                                f"(starts {_first_line(body)!r}) failed to "
                                f"parse: {exc}"
                            ),
                        )
                    )
            elif language in _SQL_LANGUAGE_TOKENS:
                try:
                    sqlglot.parse(body, read="postgres")
                except SqlglotParseError as exc:
                    findings.append(
                        Finding(
                            check_id="embedded_code.parses",
                            severity="error",
                            artifact_path=_path(tree, step),
                            message=(
                                f"embedded sql block {index} "
                                f"(starts {_first_line(body)!r}) failed to "
                                f"parse: {exc}"
                            ),
                        )
                    )
            # Any other language token (including "") is not a recognized
            # code block: no finding, per the strict binary contract.
    return findings
