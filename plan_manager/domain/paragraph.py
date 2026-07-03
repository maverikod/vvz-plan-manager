"""Paragraph domain model and normative HRS text parsing.

Defines the Paragraph dataclass, the addressable binding unit of the HRS
(MRS concept C-002), and the normative pure-text parsing algorithm that
splits an HRS markdown document into its binding paragraphs, excluding
non-binding regions, heading lines, and fenced code blocks.
"""
import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class Paragraph:
    """A binding paragraph of an HRS document (MRS concept C-002).

    Attributes:
        label: Four-character base36 label (without surrounding curly
            braces) already present on this paragraph, or None if the
            paragraph has not yet been assigned a label.
        text: The paragraph's prose text. If the paragraph already carried
            a label, the "{xxxx} " label prefix has been stripped off; if
            it did not, text is the paragraph's block text unchanged.
        position: Zero-based integer document order among binding
            paragraphs only (non-binding paragraphs, heading lines, and
            fenced code block lines are not counted).
    """
    label: Optional[str]
    text: str
    position: int


_LABEL_PATTERN = re.compile(r"^\{[0-9a-z]{4}\} ")


def parse_paragraphs(document_text: str) -> list[Paragraph]:
    """Parse an HRS markdown document into its ordered binding paragraphs.

    Args:
        document_text: The full HRS document text.

    Returns:
        A list of Paragraph objects, one per binding paragraph, in
        document order, with position 0, 1, 2, ... assigned in that
        order. Paragraphs inside non-binding regions, heading lines, and
        fenced code blocks are excluded entirely (they are not
        returned); this exclusion is the non_binding_exclusion_set
        classification.

    The parsing algorithm is normative: lines are grouped into blocks on
    blank-line boundaries; markers "<!-- non-binding -->" and
    "<!-- /non-binding -->" delimit non-nesting excluded regions; lines
    starting with "#" (headings) and lines inside fenced code blocks
    delimited by lines starting with "```" are excluded from binding
    paragraphs; a block already starting with "{xxxx} " (four base36
    characters) keeps that label, otherwise label is None.
    """
    lines = document_text.splitlines()
    in_non_binding = False
    in_fence = False
    block_open = False
    block_lines: list[str] = []
    block_start_non_binding = False
    binding_block_texts: list[str] = []

    def close_block() -> None:
        nonlocal block_lines
        if block_open and not block_start_non_binding:
            binding_block_texts.append("\n".join(block_lines))
        block_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped == "<!-- non-binding -->":
            if not in_non_binding:
                in_non_binding = True
            close_block()
            block_open = False
            continue
        if stripped == "<!-- /non-binding -->":
            if in_non_binding:
                in_non_binding = False
            close_block()
            block_open = False
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            close_block()
            block_open = False
            continue
        if in_fence:
            close_block()
            block_open = False
            continue
        if stripped.startswith("#"):
            close_block()
            block_open = False
            continue
        if stripped == "":
            close_block()
            block_open = False
            continue
        if not block_open:
            block_open = True
            block_lines = []
            block_start_non_binding = in_non_binding
        block_lines.append(line)

    close_block()

    result: list[Paragraph] = []
    for position, block_text in enumerate(binding_block_texts):
        lstripped = block_text.lstrip()
        match = _LABEL_PATTERN.match(lstripped)
        if match is not None:
            label = lstripped[1:5]
            text = lstripped[7:]
        else:
            label = None
            text = block_text
        result.append(Paragraph(label=label, text=text, position=position))
    return result
