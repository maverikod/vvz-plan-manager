"""Label assignment for HRS binding paragraphs.

Normative label-assignment algorithm (MRS concept C-002): draws unique
four-character base36 labels for unlabeled binding paragraphs of an HRS
document, in document order, and inserts them into the document text
without disturbing any other content. Existing labels are never
rewritten, reused, or reordered.
"""
import random

from plan_manager.domain.paragraph import Paragraph, parse_paragraphs

BASE36_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _draw_label(existing_labels: set[str]) -> str:
    """Draw a new four-character base36 label not present in existing_labels.

    Args:
        existing_labels: The set of labels (four-character strings) that
            are already in use and must not be produced. Not mutated by
            this function.

    Returns:
        A four-character string drawn from BASE36_ALPHABET that is not a
        member of existing_labels.
    """
    while True:
        candidate = "".join(random.choice(BASE36_ALPHABET) for _ in range(4))
        if candidate not in existing_labels:
            return candidate


def _binding_block_start_lines(document_text: str) -> list[int]:
    """Find the starting line index of each binding paragraph block.

    Args:
        document_text: The full HRS document text.

    Returns:
        A list of 0-based line indices into document_text.splitlines(),
        one per binding paragraph block, in document order: each entry
        is the index of that block's first line. The order and count of
        this list corresponds exactly, element for element, to the
        order and count of the list returned by
        plan_manager.domain.paragraph.parse_paragraphs(document_text),
        because both functions classify lines using the identical
        boundary rules.
    """
    lines = document_text.splitlines()
    in_non_binding = False
    in_fence = False
    block_open = False
    start_lines: list[int] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == "<!-- non-binding -->":
            if not in_non_binding:
                in_non_binding = True
            block_open = False
            continue
        if stripped == "<!-- /non-binding -->":
            if in_non_binding:
                in_non_binding = False
            block_open = False
            continue
        if stripped.startswith("```"):
            in_fence = not in_fence
            block_open = False
            continue
        if in_fence:
            block_open = False
            continue
        if stripped.startswith("#"):
            block_open = False
            continue
        if stripped == "":
            block_open = False
            continue
        if not block_open:
            block_open = True
            if not in_non_binding:
                start_lines.append(i)

    return start_lines


def assign_labels(document_text: str) -> tuple[str, list[Paragraph]]:
    """Assign stable labels to unlabeled binding paragraphs in document order.

    Args:
        document_text: The full HRS document text.

    Returns:
        A two-element tuple ``(new_document_text, paragraphs)``.

    The first element is the document with inserted ``"{xxxx} "`` labels on the
    first line of each previously-unlabeled binding paragraph start, preserving all
    other content and whitespace except for the insertion point. Labels are
    assigned in the order returned by `parse_paragraphs`, and heading lines,
    fenced code blocks, non-binding regions, blank lines, and previously labeled
    paragraphs are not modified.

    The second element is the list of Paragraph objects in the same order as
    `parse_paragraphs(document_text)`, with `label=None` paragraphs replaced by new
    Paragraphs carrying their assigned labels and existing labels preserved.
    """
    paragraphs = parse_paragraphs(document_text)
    start_lines = _binding_block_start_lines(document_text)
    existing_labels = {label for para in paragraphs if (label := para.label) is not None}
    lines = document_text.splitlines()
    result: list[Paragraph] = []

    for i, para in enumerate(paragraphs):
        if para.label is not None:
            result.append(para)
            continue

        new_label = _draw_label(existing_labels)
        existing_labels.add(new_label)

        line = lines[start_lines[i]]
        indent_len = len(line) - len(line.lstrip())
        prefix = line[:indent_len]
        rest = line[indent_len:]
        lines[start_lines[i]] = prefix + "{" + new_label + "} " + rest

        result.append(Paragraph(label=new_label, text=para.text, position=para.position))

    return "\n".join(lines), result


def assign_missing_labels(paragraphs):
    """Assign labels to unlabeled paragraph-like objects, preserving order.

    Accepts Paragraph or StoredParagraph-like values with label, text, and
    position attributes. If uuid and plan_uuid attributes are present they are
    preserved on the returned objects by reconstructing through the input
    object's class.
    """
    existing_labels = {
        label for para in paragraphs if (label := para.label) is not None
    }
    labeled = []
    new_labels: list[str] = []
    for para in paragraphs:
        if para.label is not None:
            labeled.append(para)
            continue
        new_label = _draw_label(existing_labels)
        existing_labels.add(new_label)
        new_labels.append(new_label)
        if hasattr(para, "uuid") and hasattr(para, "plan_uuid"):
            labeled.append(
                para.__class__(
                    uuid=para.uuid,
                    plan_uuid=para.plan_uuid,
                    label=new_label,
                    text=para.text,
                    position=para.position,
                )
            )
        else:
            labeled.append(
                para.__class__(
                    label=new_label,
                    text=para.text,
                    position=para.position,
                )
            )
    return labeled, new_labels
