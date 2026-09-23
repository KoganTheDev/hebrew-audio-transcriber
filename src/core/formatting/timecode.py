"""Bidi control characters and pure time/string formatting.

Depends on nothing else in the package, so both renderers and the
live-progress UI outside it can use these.
"""

import logging
import re

logger = logging.getLogger(__name__)

# A timestamp range, "0:32 - 1:05", sits inside otherwise-Hebrew text. Under
# the Unicode Bidirectional Algorithm the hyphen separating the two times is a
# *neutral* character: between two LTR digit runs in an RTL paragraph it can
# resolve either direction, and the two ends of the range can swap sides, so
# the line displays as "1:05 - 0:32".
#
# Typing the operands in the opposite order "fixes" this in whichever program
# you happen to test and breaks it in the next one, because it treats a
# rendering rule as if it were a character-order rule. It also corrupts the
# file for anything that parses timestamps. The actual fix is to tell the bidi
# algorithm what this run is:
#
#   LRI ... PDI  (U+2066 / U+2069) - Left-to-Right Isolate. Forces the enclosed
#       run to lay out LTR *and* isolates it, so it neither inherits direction
#       from the Hebrew around it nor leaks direction into it. Isolates are the
#       modern replacement for the older embedding controls precisely because
#       they don't leak. One pair around the whole "M:SS - M:SS" span, not one
#       per half, is what keeps the hyphen inside a single LTR run.
#   RLM (U+200F) - Right-to-Left Mark. A zero-width strong RTL character. Placed
#       at the start of a line it pins the paragraph direction to RTL, so a line
#       that happens to begin with a digit doesn't flip its whole layout. It
#       cannot fix a range on its own: it steers the paragraph, not the neutral
#       hyphen between two LTR runs inside it.
LRI = "⁦"
PDI = "⁩"
# Unused by the HTML renderer, whose document declares dir="rtl" and so settles
# paragraph direction outright. Kept as the counterpart to the note above, and
# gui/i18n.py uses the same character to anchor path lines in the Qt UI, where
# there is no document direction to declare.
RLM = "‏"


def split_sentences(text: str) -> list[str]:
    """Split a transcript blob into one entry per sentence.

    Shared by format_plain (one sentence per text line) and render_html (one
    sentence per <p>) so the two output formats can't quietly drift apart on
    what counts as a sentence boundary.
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
    """Format a transcript blob with one sentence per line.

    The unstructured output format, for when there is nothing to label: the
    plain-text counterpart of render_html()'s bare <p> fallback.
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
    """Format as H:MM:SS - used for transcript timestamps.

    Always includes the hour, unlike format_mmss: a transcript timestamp is a
    position someone will scrub to, and "72:15" is harder to act on than
    "1:12:15".
    """
    hours, remainder = divmod(_total_seconds(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_range(start: float, end: float) -> str:
    """Format a turn's timing as "M:SS - M:SS", isolated for RTL embedding.

    Both ends promote to H:MM:SS together, never just one, once either passes
    an hour - "0:05:00 - 1:12:15" is legible, but the unpromoted
    "5:00 - 72:15" reads as a wrong number, not as an hour boundary. The whole
    range sits inside one LRI/PDI pair rather than each half separately; see
    the LRI comment above for why.
    """
    promote = _total_seconds(start) >= 3600 or _total_seconds(end) >= 3600
    fmt = format_hhmmss if promote else format_mmss
    return f"{LRI}{fmt(start)} - {fmt(end)}{PDI}"
