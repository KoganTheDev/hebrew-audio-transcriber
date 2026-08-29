"""
Keep the machine awake for the length of a transcription run.

Why this exists
---------------
A 15-minute recording was reported as taking ~100 minutes end to end. The
app's own phase log agreed: transcribe 6000s, diarize 818s. Measured again
later in exactly the same configuration, the same file took 1003s and 214s
and produced byte-identical output (the same 133 speaker spans, the same
214 segments). Nothing about the code was slow.

The Windows event log had the answer. This class of machine enters Modern
Standby (S0ix) when it looks idle, and a long transcription looks extremely
idle: no keyboard, no mouse, no window activity, just a background process
burning CPU. Modern Standby does not stop that process the way real sleep
would. The Desktop Activity Moderator throttles the CPU hard and suspends
background work while time.perf_counter() keeps counting, so every stage
slows down together, the output is unchanged, and the wall clock silently
detaches from the actual compute. An overnight run made the gap obvious:
ten hours of elapsed time against 1235 seconds of process CPU time.

So the honest fix is not a faster decoder setting. It is to tell the OS
that this process is doing real work and the system must not idle out from
under it.

What SetThreadExecutionState does and does not do
------------------------------------------------
ES_SYSTEM_REQUIRED tells Windows the system is in use, and ES_CONTINUOUS
makes that assertion stick until it is explicitly cleared rather than
resetting after one idle-timer tick. Together they prevent the machine from
IDLING into sleep or Modern Standby.

They do NOT prevent sleep the user asks for: closing the lid, choosing
Sleep, a critically low battery, or a policy that forces it. That is
correct behaviour and deliberately not fought here - an app that could
refuse a lid close would be a worse app. Anyone running a long batch on a
laptop should still leave the lid open.

ES_DISPLAY_REQUIRED is deliberately NOT set. Keeping the screen lit for an
hour to transcribe a file would waste power and annoy the user; the display
sleeping is fine, the SYSTEM sleeping is not.

The flags are per-thread state, so this must be entered on the thread that
stays alive for the whole run (see core/worker.py's entry point), not on a
short-lived helper thread.

Everything here degrades to a no-op rather than raising. Failing to prevent
sleep must never fail a transcription: the worst case is the slow run that
was already happening before this module existed.
"""

import contextlib
import logging
import sys
from typing import Optional

logger = logging.getLogger(__name__)

# winbase.h. ES_CONTINUOUS makes the assertion persist until cleared;
# without it the flags apply to a single idle-timer reset and then lapse,
# which is useless for a run measured in tens of minutes.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


def _set_thread_execution_state(flags: int) -> Optional[int]:
    """
    Call SetThreadExecutionState, or return None where that is impossible.

    Split out from the context manager below purely so the failure paths are
    testable without a Windows kernel: tests patch this one function to
    simulate a non-Windows host, a missing API and a rejected call.

    Returns the previous execution state on success, or None if the call is
    unavailable or failed. Windows signals failure by returning NULL, which
    is indistinguishable from a legitimate previous state of 0, so a 0 is
    treated as failure here - the only cost of being wrong is one debug log
    line, whereas treating a real failure as success would leave a run
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
    """
    Assert that the system is in use. Returns whether the request took.

    Paired with release() below. This lower-level pair exists alongside the
    context manager because core/worker.py's entry point is one long
    try/except whose body would have to be reindented wholesale to sit
    inside a `with` - a diff that would bury a four-line behaviour change in
    two hundred lines of whitespace. The context manager is still the right
    choice for any caller that can use it.
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
    """
    Drop a previous acquire(). Safe to call when acquire() returned False.

    Clearing with ES_CONTINUOUS alone is the documented way to drop a
    continuous assertion. Callers must run this from a finally so an
    exception mid-run cannot leave sleep suppressed for the lifetime of the
    process.
    """
    if not acquired:
        return
    _set_thread_execution_state(ES_CONTINUOUS)
    logger.debug(f"released system awake hold for {reason}")


@contextlib.contextmanager
def keep_system_awake(reason: str = "transcription"):
    """
    Prevent the system idling into sleep for the duration of the block.

    Always yields, whether or not the request was granted, so callers never
    need to branch on it - a run that cannot be protected still runs, just
    with the pre-existing risk of the machine standing by underneath it.
    """
    acquired = acquire(reason)
    try:
        yield acquired
    finally:
        release(reason, acquired)
