"""Structured transcript data.

faster-whisper hands back start/end times, per-word timings and per-word
confidence alongside the text. Timestamps, speaker attribution and
confidence-driven correction each need that structure, so the pipeline
carries Segment objects from transcription all the way to the renderer and
only flattens to text in core.formatting, as the last step.

Deliberately stdlib-only: it is imported by the worker process (which must
never pull in PyQt5) and by the GUI process (which must never pull in
faster-whisper), because PyQt5 and ctranslate2 bundle conflicting copies of
MSVCP140.dll on Windows and loading both crashes intermittently. A shared
vocabulary type cannot belong to either side.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Word:
    """A single word with its timing and the model's confidence in it.

    `probability` is what makes targeted correction possible: the Hebrew pass
    looks only at words Whisper itself was unsure about instead of
    second-guessing the whole transcript (see core/hebrew_correct.py for why
    that distinction matters so much in Hebrew).
    """

    start: float
    end: float
    text: str
    probability: float = 1.0


@dataclass
class Segment:
    """One chunk of transcript as emitted by the ASR model.

    A segment is a decoder-sized unit, not a human-sized one - typically a
    few seconds. Rendering one line per segment produces an unreadably choppy
    transcript, so core.formatting merges runs of segments into speaker
    "turns" before writing them out.
    """

    start: float
    end: float
    text: str
    words: list[Word] = field(default_factory=list)
    # 0-based speaker index. None means speaker identification did not run,
    # or ran and could not attribute this segment - both render without a
    # speaker label rather than guessing.
    speaker: Optional[int] = None

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


def plain_text(segments: list[Segment]) -> str:
    """Flatten segments back into one unpunctuated-by-us blob.

    No production caller: it is the regression baseline that tests/eval's
    model sweep and the integration test both compare transcripts against,
    and it has to produce the exact string the pipeline did before segments
    carried structure, so it belongs beside the type it flattens.
    """
    text = ""
    for segment in segments:
        if not segment.text:
            continue
        if text and not text.endswith(" "):
            text += " "
        text += segment.text
    return text
