"""Targeted HRS text editing: paragraph-granular insert, update, and delete.

Orchestrates the para_insert / para_update / para_delete commands over the
stored-paragraph primitives in plan_manager.domain.paragraph_store, recording
each mutation's revision attribution through
plan_manager.storage.version_store (direct mode) or
plan_manager.cascade.write.cascade_write_many (cascade mode). Kept separate
from plan_manager.hrs.paragraphs (which this module reuses for snapshot
building) so that file stays within the legacy plan's mechanical size cap.

Position-space invariant: the stored position column is ONE sequence over ALL
rows — binding and wrapped non-binding alike (a wrap keeps the row and its
position). Position shifts on insert/delete therefore move non-binding rows
too, and label uniqueness is enforced against labels held by wrapped rows
(an unwrap restores them into the binding set).
"""

import dataclasses
import re
import uuid

from plan_manager.cascade.record import CascadeRecord
from plan_manager.cascade.write import cascade_write_many
from plan_manager.commands.errors import DomainCommandError
from plan_manager.domain import paragraph_store
from plan_manager.domain.labeling import _draw_label
from plan_manager.domain.paragraph import Paragraph, parse_paragraphs
from plan_manager.domain.plan import get_plan
from plan_manager.hrs.paragraphs import _paragraph_snapshot
from plan_manager.storage.version_store import record_revision


_LABEL_RE = re.compile(r"^[0-9a-z]{4}$")


def _record_changes(
    conn,
    plan_uuid: uuid.UUID,
    author: str,
    message: str,
    changes: list[tuple[uuid.UUID, dict]],
    cascade: CascadeRecord | None,
) -> None:
    """Record a multi-row paragraph mutation as ONE revision (direct or cascade mode).

    Position shifts change sibling rows alongside the directly-edited one;
    all of them must land in a single revision so a cascade abort restores
    the whole position sequence atomically (same discipline as the C-008
    recursive subtree delete's cascade_write_many usage).
    """
    if cascade is None:
        plan = get_plan(conn, plan_uuid)
        record_revision(
            conn,
            plan_uuid,
            author,
            message,
            changes,
            plan.head_revision_uuid,
            ref_name=None,
        )
    else:
        cascade_write_many(conn, plan_uuid, cascade, changes, [], author, message)


def _parse_single_paragraph(text: str) -> Paragraph:
    """Parse ``text`` through the normative HRS parser, requiring exactly one binding paragraph.

    Raises:
        DomainCommandError: code IMPORT_INVALID when the text parses to
            zero or more than one binding paragraph.
    """
    paragraphs = parse_paragraphs(text)
    if len(paragraphs) != 1:
        raise DomainCommandError(
            "IMPORT_INVALID",
            f"text must parse to exactly one binding paragraph, got {len(paragraphs)}",
        )
    return paragraphs[0]


def _shifted_snapshots(
    plan_uuid: uuid.UUID,
    rows: list,
    delta: int,
) -> list[tuple[uuid.UUID, dict]]:
    """Post-shift snapshots for every row whose position moved by ``delta``."""
    return [
        (
            row.uuid,
            _paragraph_snapshot(
                row.uuid,
                plan_uuid,
                dataclasses.replace(row, position=row.position + delta),
                binding=row.binding,
            ),
        )
        for row in rows
    ]


def _find_binding_row(conn, plan_uuid: uuid.UUID, label: str):
    """Resolve one BINDING stored row by its bare label, or raise PARAGRAPH_NOT_FOUND.

    Label addressing deliberately covers binding rows only (the same scope
    as list_paragraphs/para_get): a wrapped (non-binding) row keeps its
    label but is not addressable here — unwrap it first.
    """
    for row in paragraph_store.list_paragraphs(conn, plan_uuid):
        if row.label == label:
            return row
    raise DomainCommandError("PARAGRAPH_NOT_FOUND", f"label not found: {label}")


def insert_paragraph(
    conn,
    plan_uuid: uuid.UUID,
    text: str,
    position: int | None,
    label: str | None,
    author: str,
    cascade: CascadeRecord | None,
) -> dict:
    """Insert ONE new binding paragraph into a plan's stored HRS.

    ``position`` is a 0-based index in the BINDING paragraph order: the new
    paragraph takes the addressed binding row's physical position and every
    row (binding or not) at or after it shifts +1. ``position`` equal to
    the binding count, or None, appends after ALL stored rows (including
    trailing non-binding ones). ``text`` must parse to exactly one binding
    paragraph; a "{xxxx} " prefix in the text supplies the label unless the
    ``label`` parameter contradicts it. An absent label is drawn fresh with
    the normative generator; uniqueness is enforced against ALL rows
    (non-binding rows keep their labels for unwrap).

    Returns:
        dict with keys "uuid" (uuid.UUID), "label" (str), "position" (int:
        the physical position the row was stored at), and "text" (str).

    Raises:
        DomainCommandError: IMPORT_INVALID (text not exactly one paragraph,
            bad label format, label parameter vs text-prefix conflict,
            position out of range) or DUPLICATE_ID (label already in use).
    """
    parsed = _parse_single_paragraph(text)
    if label is not None and parsed.label is not None and label != parsed.label:
        raise DomainCommandError(
            "IMPORT_INVALID",
            f"label parameter {label!r} conflicts with the text's own "
            f"label prefix {{{parsed.label}}}",
        )
    effective_label = label if label is not None else parsed.label
    if effective_label is not None and not _LABEL_RE.match(effective_label):
        raise DomainCommandError(
            "IMPORT_INVALID",
            f"label must be exactly four base36 characters [0-9a-z]: {effective_label!r}",
        )

    all_rows = paragraph_store.list_all_paragraphs(conn, plan_uuid)
    existing_labels = {row.label for row in all_rows if row.label is not None}
    if effective_label is not None and effective_label in existing_labels:
        raise DomainCommandError(
            "DUPLICATE_ID", f"label already in use: {effective_label}"
        )
    if effective_label is None:
        effective_label = _draw_label(existing_labels)

    binding_rows = [row for row in all_rows if row.binding]
    if position is None or position == len(binding_rows):
        db_position = all_rows[-1].position + 1 if all_rows else 0
        shifted: list = []
    elif 0 <= position < len(binding_rows):
        db_position = binding_rows[position].position
        shifted = [row for row in all_rows if row.position >= db_position]
        paragraph_store.shift_positions(conn, plan_uuid, db_position, 1)
    else:
        raise DomainCommandError(
            "IMPORT_INVALID",
            f"insert position {position} out of range 0..{len(binding_rows)}",
        )

    row_uuid = paragraph_store.insert_paragraph_at(
        conn, plan_uuid, effective_label, parsed.text, db_position
    )

    new_row = paragraph_store.StoredParagraph(
        uuid=row_uuid,
        plan_uuid=plan_uuid,
        label=effective_label,
        text=parsed.text,
        position=db_position,
        binding=True,
    )
    changes = [(row_uuid, _paragraph_snapshot(row_uuid, plan_uuid, new_row))]
    changes.extend(_shifted_snapshots(plan_uuid, shifted, 1))
    _record_changes(
        conn,
        plan_uuid,
        author,
        f"insert paragraph {effective_label}",
        changes,
        cascade,
    )
    return {
        "uuid": row_uuid,
        "label": effective_label,
        "position": db_position,
        "text": parsed.text,
    }


def update_paragraph(
    conn,
    plan_uuid: uuid.UUID,
    label: str,
    text: str,
    author: str,
    cascade: CascadeRecord | None,
) -> dict:
    """Replace the TEXT of one existing binding paragraph addressed by label.

    The row's uuid, label, position, and binding flag are all preserved;
    only text changes. ``text`` must parse to exactly one binding
    paragraph, and a "{xxxx} " prefix is rejected unless it equals the
    addressed label (this command never rewrites labels).

    Returns:
        dict with keys "uuid", "label", "position", and "text" (the new text).

    Raises:
        DomainCommandError: PARAGRAPH_NOT_FOUND (unknown binding label) or
            IMPORT_INVALID (text invalid or label-prefix mismatch).
    """
    row = _find_binding_row(conn, plan_uuid, label)
    parsed = _parse_single_paragraph(text)
    if parsed.label is not None and parsed.label != label:
        raise DomainCommandError(
            "IMPORT_INVALID",
            f"text carries label prefix {{{parsed.label}}} but addresses "
            f"paragraph {label}; label rewrites are not allowed here",
        )

    paragraph_store.update_paragraph_text(conn, row.uuid, parsed.text)

    updated = dataclasses.replace(row, text=parsed.text)
    snapshot = _paragraph_snapshot(row.uuid, plan_uuid, updated)
    _record_changes(
        conn,
        plan_uuid,
        author,
        f"update paragraph {label}",
        [(row.uuid, snapshot)],
        cascade,
    )
    return {
        "uuid": row.uuid,
        "label": label,
        "position": row.position,
        "text": parsed.text,
    }


def delete_paragraph(
    conn,
    plan_uuid: uuid.UUID,
    label: str,
    author: str,
    cascade: CascadeRecord | None,
) -> dict:
    """Delete one binding paragraph addressed by label and close the position gap.

    The row is removed and every row (binding or not) after it shifts -1.
    Recorded as a tombstone snapshot (deleted=True, the convention used
    for true row removals) plus post-shift snapshots of the moved rows in
    the same single revision. Non-binding rows are not addressable (their
    labels are outside the binding label lookup); unwrap first to delete
    a wrapped paragraph.

    Returns:
        dict with keys "uuid", "label", and "position" (the deleted row's).

    Raises:
        DomainCommandError: PARAGRAPH_NOT_FOUND when no binding paragraph
            carries the label.
    """
    row = _find_binding_row(conn, plan_uuid, label)
    all_rows = paragraph_store.list_all_paragraphs(conn, plan_uuid)
    shifted = [r for r in all_rows if r.position > row.position]

    paragraph_store.delete_paragraph(conn, row.uuid)
    paragraph_store.shift_positions(conn, plan_uuid, row.position + 1, -1)

    changes = [
        (row.uuid, _paragraph_snapshot(row.uuid, plan_uuid, row, deleted=True))
    ]
    changes.extend(_shifted_snapshots(plan_uuid, shifted, -1))
    _record_changes(
        conn,
        plan_uuid,
        author,
        f"delete paragraph {label}",
        changes,
        cascade,
    )
    return {"uuid": row.uuid, "label": label, "position": row.position}
