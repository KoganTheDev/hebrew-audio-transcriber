"""Structured transcript data.

Until this module existed, the transcript was a bare `str`: Transcriber
concatenated every segment's text and threw the rest away. faster-whisper
actually hands back far more per segment - start/end times, per-word
timings, per-word confidence - and all of it was discarded one line after
being received.

Timestamps, speaker attribution and confidence-driven correction each need
that discarded structure, so the pipeline now carries `Segment` objects from
transcription all the way to the renderer, and only flattens to text in
core.formatting as the very last step.

Deliberately dependency-free (stdlib only): this is imported by the worker
process (see core/__init__.py for why core/ must never pull in PyQt5) and by
the GUI process, which must never pull in faster-whisper for the same
MSVCP140.dll reason from the other direction. A shared vocabulary type can't
belong to either side.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Word:
    """A single word with its timing and the model's confidence in it.

    `probability` is what makes targeted correction possible: it lets the
    Hebrew correction pass look only at words Whisper itself was unsure
    about, instead of second-guessing the entire transcript (see
    core/hebrew_correct.py for why that distinction matters so much in
    Hebrew).
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
    """One source file's transcript, as a unit the renderer can place under its
    own heading.

    Exists so a batch run has a shared vocabulary type for "one file's
    output" the same way Segment is the shared vocabulary type for "one
    chunk of transcript" - see the module docstring for why that type has to
    live here rather than in core.worker or core.formatting: both the worker
    process and the GUI process need it, and it must stay stdlib-only either
    way.
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
