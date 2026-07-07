"""Bridge the queue job progress tracker to a scoring progress callback.

Queue-bound commands receive ``context["progress_tracker"]`` (injected by the
adapter's CommandExecutionJob) whose ``set_progress``/``set_description`` writes
are persisted synchronously via queuemgr and become visible to
``queue_get_job_status``. This module adapts that tracker into the uniform
``progress(pct=None, message=None)`` callback consumed by the scoring layer, so
a long semantic scoring job reports live progress instead of sitting at 0.
"""

from typing import Any, Callable, Optional


def progress_from_context(
    context: Any,
) -> Optional[Callable[..., None]]:
    """Return a ``progress(pct=None, message=None)`` callback, or None.

    Returns None when there is no progress tracker in ``context`` (a direct,
    non-queued call), so callers can pass the result straight through.
    """
    tracker = None
    if isinstance(context, dict):
        tracker = context.get("progress_tracker")
    if tracker is None:
        return None

    def report(pct: Optional[int] = None, message: Optional[str] = None) -> None:
        try:
            if pct is not None:
                tracker.set_progress(int(pct))
            if message is not None:
                tracker.set_description(message)
        except Exception:
            # Progress reporting is best-effort and never fails the command.
            pass

    return report
