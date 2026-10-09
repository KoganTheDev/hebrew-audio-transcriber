"""Keep the machine awake for the length of a transcription run.

A long run looks idle to Windows, which drops into Modern Standby and
throttles background work while the wall clock keeps counting: one 15-minute
recording took ~100 minutes, and an overnight run logged ten hours against
1235 s of CPU. ES_SYSTEM_REQUIRED | ES_CONTINUOUS prevents idling into sleep.

Deliberately not prevented: sleep the user asks for (lid, Sleep, low battery),
and the display sleeping (no ES_DISPLAY_REQUIRED). The flags are per-thread,
so hold them on the thread that lives for the whole run (core/worker.py).
Everything degrades to a no-op: failing to prevent sleep must never fail a run.
"""

import contextlib
import logging
import sys
from collections.abc import Iterator

logger = logging.getLogger(__name__)

# winbase.h. Without ES_CONTINUOUS the flags lapse after one idle-timer tick.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _set_thread_execution_state(flags: int) -> int | None:
    """SetThreadExecutionState, returning the previous state or None if the
    call was unavailable or failed. A separate function so tests can fake it.

    Windows signals failure with 0, which a real previous state could also be;
    0 counts as failure, since the opposite mistake would claim protection
    that is not there.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes

        result = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
    except Exception as exc:  # no windll, loader errors - never worth failing a run
        logger.debug(f"could not set thread execution state: {exc}")
        return None
    return int(result) or None


def acquire(reason: str = "transcription") -> bool:
    """Assert that the system is in use; returns whether it took. Prefer
    keep_system_awake(), which pairs this with release().
    """
    acquired = _set_thread_execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) is not None
    if acquired:
        logger.info(f"holding system awake for {reason}")
    else:
        # Debug, not a warning: the expected path on any non-Windows host.
        logger.debug(f"could not hold system awake for {reason}; continuing anyway")
    return acquired


def release(reason: str = "transcription", acquired: bool = True) -> None:
    """Drop a previous acquire() (ES_CONTINUOUS alone clears it). Call from a
    finally, so an exception cannot leave sleep suppressed.
    """
    if not acquired:
        return
    _set_thread_execution_state(ES_CONTINUOUS)
    logger.debug(f"released system awake hold for {reason}")


@contextlib.contextmanager
def keep_system_awake(reason: str = "transcription") -> Iterator[bool]:
    """Prevent idling into sleep for the block. Always yields, granted or not,
    so callers never branch on it.
    """
    acquired = acquire(reason)
    try:
        yield acquired
    finally:
        release(reason, acquired)
