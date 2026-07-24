"""Shared free-text field merge helper for bug 32755092 (history-preserving append mode).

``bug_update`` and ``bug_fix_update`` (and any future command with the same
shape) accept an ``append`` boolean on their free-text, history-bearing
fields. The default (``append=False``) is the pre-existing REPLACE semantics
(API compatibility). ``append=True`` preserves history: the incoming text is
appended to the currently stored value, separated by a blank line
(``"\\n\\n"``); appending to a currently empty/null field just sets it (no
leading separator).
"""

from __future__ import annotations


def merge_text_field(existing: str | None, incoming: str | None, append: bool) -> str | None:
    """Combine a stored free-text field with an incoming value.

    Callers only invoke this for a field whose incoming value is not None
    (an omitted field is left untouched by the caller, exactly as before this
    change) -- this helper does not special-case ``incoming is None``.

    Args:
        existing: The field's currently stored value (None/empty if unset).
        incoming: The new text supplied by the caller for this update.
        append: False (default) -- REPLACE semantics: return `incoming` unchanged.
            True -- history-preserving semantics: return `existing` and `incoming`
            joined by a blank line ("\\n\\n"); if `existing` is None/empty, there is
            nothing to append to, so `incoming` alone becomes the field's new value.

    Returns:
        The value to persist for this field.
    """
    if not append or not existing:
        return incoming
    return f"{existing}\n\n{incoming}"
