"""Structured transcript data, carried from transcription to the renderer.

Timestamps, speaker attribution and confidence-driven correction all need the
per-word timings and confidence faster-whisper returns, so text is flattened
only at the very end, in core.formatting. Stdlib only: both the worker and the
GUI process import it (see core/__init__.py for why they must stay apart).
"""

from dataclasses import dataclass, field


@dataclass
class Word:
    """A word, its timing, and the model's confidence - which lets the Hebrew
    pass look only at words Whisper doubted (core/hebrew_corrections.py).
    """

    start: float
    end: float
    text: str
    probability: float = 1.0
    # What the model wrote, when the Hebrew pass replaced it - so the
    # transcript page can offer "restore original" on an auto-correction.
    original: str | None = None
    # Terms from the user's list this word may have been meant to be, for
    # the page's click-to-fix menu. Only ever filled for doubted words.
    suggestions: list[str] = field(default_factory=list)


@dataclass
class Segment:
    """A decoder-sized chunk (a few seconds); core.formatting merges them into
    speaker turns, since one line per segment reads as choppy.
    """

    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    # 0-based speaker index. None means speaker identification did not run,
    # or ran and could not attribute this segment - both render without a
    # speaker label rather than guessing.
    speaker: int | None = None

    @property
    def duration(self) -> float:
        return max(self.end - self.start, 0.0)


@dataclass
class TranscriptDocument:
    """One source file's transcript, as a unit the renderer places under its
    own heading.
    """

    source_name: str  # basename of the audio file
    segments: list[Segment] = field(default_factory=list)
    failed: bool = False  # transcription of this one file did not complete
    error_detail: str | None = None  # str(exception) when failed is True


def plain_text(segments: list[Segment]) -> str:
    """Flatten segments to one blob - the regression baseline tests/eval and
    the integration test compare transcripts against (no production caller).
    """
    text = ""
    for segment in segments:
        if not segment.text:
            continue
        if text and not text.endswith(" "):
            text += " "
        text += segment.text
    return text
