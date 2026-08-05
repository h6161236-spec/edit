from __future__ import annotations


class BackgroundTaskCancelled(RuntimeError):
    """Raised when the user stops the current background task.

    Lives in its own module so that both the worker layer (`ui/workers.py`)
    and the process-running layers (`exporting.py`, `providers/tts.py`) can
    raise and catch it without circular imports. Subprocess-based tasks check
    for a cancellation request after a process dies and re-raise this error so
    a user-initiated cancel is reported as "cancelled" instead of "failed".
    """
