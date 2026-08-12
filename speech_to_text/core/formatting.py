"""
Rendering structured segments into the output transcript file.

Split out of Transcriber because formatting stopped being a model concern
once segments carried timing and speaker data: the renderer needs to know
about turn merging, bidi control characters and speaker label templates,
none of which have anything to do with running a Whisper model.

Stdlib only, and no PyQt5 - this runs inside the worker process.
"""

import logging
import re
from typing import List, Optional

from speech_to_text.core.segments import Segment, plain_text

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
# Typing the brackets in the opposite order "fixes" this in whichever program
# you happen to test, and breaks it in the next one, because it treats a
# rendering rule as if it were a character-order rule. It also corrupts the
# file for anything that parses timestamps. The actual fix is to tell the bidi
# algorithm what this run is:
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
RLM = "‏"

# ---------------------------------------------------------------------------
# Turn merging
# ---------------------------------------------------------------------------
# Whisper emits a segment every few seconds - a decoder-sized unit, not a
# human-sized one. One timestamped line per segment produces a transcript
# that's technically correct and unreadable, so consecutive segments are merged
# into a "turn" until the speaker changes, the pause gets long enough to read as
# a break, or the turn simply grows too long to stay scannable.
TURN_GAP_SECONDS = 2.0
TURN_MAX_SECONDS = 60.0


def format_plain(text: str) -> str:
    """
    Format a transcript blob with one sentence per line.

    This is the original pre-timestamps output format, kept so the app can
    still produce exactly what it produced before (see render(), which falls
    back to it when there is nothing to timestamp).
    """
    if not text:
        return ""

    try:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        return "\n".join(sentences)
    except Exception as e:
        logger.warning(f"Could not format output: {e}")
        return text


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
    """
    Format as H:MM:SS - used for transcript timestamps.

    Always includes the hour, unlike format_mmss: a transcript timestamp is a
    position someone will scrub to, and "72:15" is harder to act on than
    "1:12:15".
    """
    hours, remainder = divmod(_total_seconds(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def timestamp_prefix(seconds: float) -> str:
    """
    Render "[H:MM:SS]" so it survives being embedded in right-to-left text.

    See the LRI/PDI note above for why the isolate characters are not optional.
    """
    return f"{LRI}[{format_hhmmss(seconds)}]{PDI}"


class Turn:
    """One speaker's uninterrupted stretch of speech."""

    def __init__(self, segment: Segment):
        self.start = segment.start
        self.end = segment.end
        self.speaker = segment.speaker
        self._parts = [segment.text.strip()]

    def append(self, segment: Segment) -> None:
        self.end = segment.end
        text = segment.text.strip()
        if text:
            self._parts.append(text)

    @property
    def text(self) -> str:
        return " ".join(part for part in self._parts if part)


def merge_turns(
    segments: List[Segment],
    gap_seconds: float = TURN_GAP_SECONDS,
    max_seconds: float = TURN_MAX_SECONDS,
) -> List[Turn]:
    """Group consecutive segments into readable speaker turns."""
    turns: List[Turn] = []

    for segment in segments:
        if not segment.text or not segment.text.strip():
            continue

        current = turns[-1] if turns else None
        if (
            current is not None
            and segment.speaker == current.speaker
            and segment.start - current.end <= gap_seconds
            and segment.end - current.start <= max_seconds
        ):
            current.append(segment)
        else:
            turns.append(Turn(segment))

    return turns


def render(
    segments: List[Segment],
    speaker_label: Optional[str] = None,
    timestamps: bool = True,
) -> str:
    """
    Render segments to the finished transcript text.

    Args:
        segments: Transcribed segments, optionally carrying speaker indices.
        speaker_label: Format string for a speaker name, e.g. "דובר {n}" or
            "Speaker {n}". Passed in from the GUI rather than looked up here:
            this module runs in the worker process, which has no access to
            gui.i18n and does not know the UI language (see core/worker.py).
            None means don't label speakers at all.
        timestamps: Whether to prefix each turn with its start time.

    Falls back to the original sentence-per-line format when there is nothing
    structural to show - i.e. no timestamps and no speakers - so the plain
    output path is genuinely unchanged rather than merely similar.
    """
    if not segments:
        return ""

    has_speakers = speaker_label is not None and any(
        segment.speaker is not None for segment in segments
    )

    if not timestamps and not has_speakers:
        return format_plain(plain_text(segments))

    lines = []
    for turn in merge_turns(segments):
        prefix_parts = []
        if timestamps:
            prefix_parts.append(timestamp_prefix(turn.start))
        if has_speakers and turn.speaker is not None:
            # Speakers are 0-based internally and 1-based in the transcript:
            # "Speaker 0" reads like a bug to anyone who isn't a programmer.
            prefix_parts.append(f"{speaker_label.format(n=turn.speaker + 1)}:")

        prefix = " ".join(prefix_parts)
        # Leading RLM pins the line to RTL regardless of what character the
        # prefix happens to start with.
        lines.append(f"{RLM}{prefix} {turn.text}" if prefix else f"{RLM}{turn.text}")

    return "\n".join(lines)
