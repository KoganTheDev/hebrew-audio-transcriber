"""Keep the machine awake for the length of a transcription run.

The symptom: a 15-minute recording taking ~100 minutes (transcribe 6000s,
diarize 818s), then the same file in the same configuration taking 1003s and
214s with byte-identical output. Nothing about the code was slow. This class
of machine enters Modern Standby (S0ix) when it looks idle, and a long
transcription looks extremely idle - no keyboard, no mouse, no window
activity, just a background process burning CPU. Modern Standby does not stop
that process the way real sleep would: the Desktop Activity Moderator
throttles the CPU and suspends background work while time.perf_counter()
keeps counting, so the wall clock detaches from the actual compute. An
overnight run made it plain - ten hours elapsed against 1235 seconds of
process CPU time.

ES_SYSTEM_REQUIRED tells Windows the system is in use; ES_CONTINUOUS makes
that assertion stick until cleared rather than lapsing after one idle-timer
tick. Together they prevent IDLING into sleep or Modern Standby.

They do NOT prevent sleep the user asks for - a lid close, choosing Sleep, a
critically low battery, a policy - and deliberately do not try: an app that
could refuse a lid close would be a worse app. Anyone running a long batch on
a laptop should still leave the lid open.

ES_DISPLAY_REQUIRED is deliberately NOT set: an hour of lit screen to
transcribe a file wastes power for nothing. The display sleeping is fine, the
SYSTEM sleeping is not.

The flags are per-thread state, so this must be held on the thread that stays
alive for the whole run (see core/worker.py's entry point), not on a
short-lived helper.

Everything here degrades to a no-op rather than raising: failing to prevent
sleep must never fail a transcription.
"""

import contextlib
import logging
import sys
from collections.abc import Iterator
from typing import Optional

logger = logging.getLogger(__name__)

# winbase.h. ES_CONTINUOUS makes the assertion persist until cleared;
# without it the flags apply to a single idle-timer reset and then lapse,
# which is useless for a run measured in tens of minutes.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _set_thread_execution_state(flags: int) -> Optional[int]:
    """Call SetThreadExecutionState, or return None where that is impossible.

    Split out so the failure paths are testable without a Windows kernel:
    tests patch this one function to simulate a non-Windows host, a missing
    API and a rejected call.

    Returns the previous execution state, or None if the call was unavailable
    or failed. Windows signals failure with NULL, indistinguishable from a
    legitimate previous state of 0, so 0 counts as failure: being wrong that
    way costs one debug line, while the other way would leave a run
    unprotected while claiming otherwise.
    """
    if not sys.platform.startswith("win"):
        return None
    try:
        import ctypes

        result = ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags))
    except Exception as exc:
        # AttributeError on a ctypes build without windll, OSError from the
        # loader, anything else the platform decides to raise. None of it is
        # worth failing a transcription over.
        logger.debug(f"could not set thread execution state: {exc}")
        return None
    return int(result) or None


def acquire(reason: str = "transcription") -> bool:
    """Assert that the system is in use. Returns whether the request took.

    Paired with release(). Callers should reach for keep_system_awake()
    instead; this pair is what it is built from, and what a caller whose
    hold does not nest inside one block would need.
    """
    acquired = _set_thread_execution_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED) is not None
    if acquired:
        logger.info(f"holding system awake for {reason}")
    else:
        # Not a warning: on any non-Windows host this is the expected path,
        # and on Windows the run still proceeds exactly as it did before.
        logger.debug(f"could not hold system awake for {reason}; continuing anyway")
    return acquired


def release(reason: str = "transcription", acquired: bool = True) -> None:
    """Drop a previous acquire(). Safe to call when acquire() returned False.

    ES_CONTINUOUS alone is the documented way to clear a continuous
    assertion. Callers must run this from a finally: an exception mid-run
    must not leave sleep suppressed for the lifetime of the process.
    """
    if not acquired:
        return
    _set_thread_execution_state(ES_CONTINUOUS)
    logger.debug(f"released system awake hold for {reason}")


@contextlib.contextmanager
def keep_system_awake(reason: str = "transcription") -> Iterator[bool]:
    """Prevent the system idling into sleep for the duration of the block.

    Always yields, whether or not the request was granted, so callers never
    need to branch on it - a run that cannot be protected still runs, just
    with the pre-existing risk of the machine standing by underneath it.
    """
    acquired = acquire(reason)
    try:
        yield acquired
    finally:
        release(reason, acquired)
