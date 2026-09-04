"""Bidi control characters and time formatting.

Split out first because it is the part of the old core/formatting with no
dependency on segments, turns or HTML at all - just characters and pure
string formatting, shared by both the plain-text and HTML renderers (see
split_sentences() below) and by the live-progress UI (format_mmss(), used
outside this package entirely).
"""

import logging
import re
from typing import List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bidi control characters
# ---------------------------------------------------------------------------
# Writing "[00:01:23]" into a Hebrew line does not render as typed. Under the
# Unicode Bidirectional Algorithm, "[" and "]" are *neutral* characters with
# the Bidi_Mirrored property: in an RTL paragraph they resolve to RTL and the
# renderer substitutes the mirrored glyph, so the text displays as
# "]00:01:23[" - and the whole bracketed group can land on the wrong side of
# the line, because the digits inside it form an LTR run embedded in RTL text.
#
# The brackets are gone now - timestamps render as a range, "0:32 - 1:05" -
# but the isolate mechanism below is not optional decoration left over from
# them. The hyphen separating the two times is itself a neutral character,
# exactly like "[" and "]" were: sitting between two LTR digit runs inside an
# RTL paragraph, it can resolve either direction, and the two ends of the
# range can swap sides the same way the brackets used to. Wrapping the whole
# "M:SS - M:SS" span in one LRI/PDI pair - not each half separately - is what
# keeps "start - end" reading as start-then-end regardless of the Hebrew
# around it.
#
# Typing the brackets (or the hyphen's operands) in the opposite order "fixes"
# this in whichever program you happen to test, and breaks it in the next one,
# because it treats a rendering rule as if it were a character-order rule. It
# also corrupts the file for anything that parses timestamps. The actual fix
# is to tell the bidi algorithm what this run is:
#
#   LRI ... PDI  (U+2066 / U+2069) - Left-to-Right Isolate. Forces the enclosed
#       run to lay out LTR *and* isolates it, so it neither inherits direction
#       from the Hebrew around it nor leaks direction into it. Isolates are the
#       modern replacement for the older embedding controls precisely because
#       they don't leak.
#   RLM (U+200F) - Right-to-Left Mark. A zero-width strong RTL character. Placed
#       at the start of a line it pins the paragraph direction to RTL, so a line
#       that happens to begin with a digit or bracket doesn't flip its whole
#       layout. gui/i18n.py already uses this same trick for path lines.
LRI = "⁦"
PDI = "⁩"
# Retained deliberately even though the HTML renderer no longer emits it: the
# document declares dir="rtl", which settles paragraph direction outright, so
# there is nothing left for a strong-character hint to steer. It stays as the
# documented counterpart to the explanation above - and gui/i18n.py still uses
# the same character to anchor path lines inside the Qt UI, where there is no
# document direction to declare.
RLM = "‏"


def split_sentences(text: str) -> List[str]:
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

    This is the original pre-timestamps output format, kept so the app can
    still produce exactly what it produced before (see render_html(), which
    falls back to bare, unlabelled <p> sentences when there is nothing
    structural to show).
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


def format_instant(seconds: float) -> str:
    """Format one moment as "M:SS", isolated for RTL embedding.

    format_range() below argues that a turn needs a range rather than a
    single instant, because an instant does not say where playback stops.
    That reasoning does not carry to a sentence bubble, for two reasons.
    A bubble already carries data-start/data-end, so clicking it plays
    exactly that sentence whatever the label says - the ambiguity the range
    was introduced to remove cannot occur here. And at whole-second
    resolution a range is actively worse: sentences are routinely under a
    second apart, so "0:00 - 0:00" is what a real short sentence renders as.
    A repeated degenerate range on every bubble is noise that also looks
    broken.

    The hour promotion is kept, though, because that half of format_range's
    reasoning does still apply: "72:15" reads as a wrong number rather than
    as an hour boundary.
    """
    fmt = format_hhmmss if _total_seconds(seconds) >= 3600 else format_mmss
    return f"{LRI}{fmt(seconds)}{PDI}"


def format_range(start: float, end: float) -> str:
    """Format a turn's timing as "M:SS - M:SS", isolated for RTL embedding.

    A single instant told the reader *when* a turn began; it did not tell them
    where it ended, so playing it ran on past the turn into whatever came
    next. A range says exactly what will play.

    Both ends promote to H:MM:SS together, never just one, once either passes
    an hour - "0:05:00 - 1:12:15" is legible, but the unpromoted
    "5:00 - 72:15" reads as a wrong number, not as an hour boundary. See the
    module docstring for why the whole range, not just each half, sits inside
    one LRI/PDI pair: the hyphen between the two LTR digit runs is a neutral
    character and can reorder the same way the old mirrored brackets did.
    """
    promote = _total_seconds(start) >= 3600 or _total_seconds(end) >= 3600
    fmt = format_hhmmss if promote else format_mmss
    return f"{LRI}{fmt(start)} - {fmt(end)}{PDI}"
