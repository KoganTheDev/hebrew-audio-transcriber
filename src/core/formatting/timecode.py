"""Bidi control characters and pure time/string formatting.

Depends on nothing else in the package, so both renderers and the
live-progress UI outside it can use these.
"""

import logging
import re

logger = logging.getLogger(__name__)

# In Hebrew text the hyphen of "0:32 - 1:05" is bidi-neutral, so the two times
# can swap sides ("1:05 - 0:32"). Reordering the characters only fixes it in
# whichever viewer you test, and corrupts the timestamps. LRI ... PDI (U+2066
# / U+2069) isolates the whole range as one LTR run - one pair around both
# halves, so the hyphen stays inside it.
LRI = "⁦"
PDI = "⁩"
# Right-to-Left Mark: pins a line's paragraph direction to RTL. The HTML
# renderer declares dir="rtl" instead; gui/i18n.py uses this for Qt path lines.
RLM = "‏"


def split_sentences(text: str) -> list[str]:
    """Split a transcript blob into sentences. Shared by format_plain and
    render_html, so the two cannot disagree on a sentence boundary.
    """
    if not text:
        return []
    try:
        sentences = re.split(r"(?<=[.!?])\s+", text)
        return [s.strip() for s in sentences if s.strip()]
    except Exception as e:
        logger.warning(f"Could not split sentences: {e}")
        return [text]


def format_plain(text: str) -> str:
    """One sentence per line - the plain-text counterpart of render_html()'s
    bare <p> fallback.
    """
    return "\n".join(split_sentences(text))


def _total_seconds(seconds: float) -> int:
    """Coerce to a non-negative whole second count, tolerating junk input."""
    try:
        return max(int(seconds), 0)
    except (TypeError, ValueError):
        return 0


def format_mmss(seconds: float) -> str:
    """Format as m:ss - used for live progress, where hours would be noise."""
    minutes, secs = divmod(_total_seconds(seconds), 60)
    return f"{minutes}:{secs:02d}"


def format_hhmmss(seconds: float) -> str:
    """Format as H:MM:SS - transcript timestamps, where "1:12:15" is easier to
    scrub to than "72:15".
    """
    hours, remainder = divmod(_total_seconds(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_range(start: float, end: float) -> str:
    """A turn's timing as "M:SS - M:SS" inside one LRI/PDI isolate.

    Past an hour both ends switch to H:MM:SS together - "5:00 - 72:15" reads
    as a wrong number, "0:05:00 - 1:12:15" does not.
    """
    promote = _total_seconds(start) >= 3600 or _total_seconds(end) >= 3600
    fmt = format_hhmmss if promote else format_mmss
    return f"{LRI}{fmt(start)} - {fmt(end)}{PDI}"
