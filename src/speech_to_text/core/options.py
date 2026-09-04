"""Settings for one transcription run.

Stdlib only and trivially picklable: instances cross a process boundary as a
multiprocessing.Process argument, so anything unpicklable added here fails
only in the child, as an error nobody can trace back to this file.
"""

from dataclasses import dataclass, field
from typing import Optional

from speech_to_text import config


@dataclass
class TranscriptionOptions:
    """What to transcribe, with which model, and how to render the result."""

    model_size: str = config.DEFAULT_MODEL
    device: str = "cpu"
    language: str = config.LANGUAGE

    # Real audio length per input file, probed by the GUI before the run
    # starts (gui.audio_utils), one entry per audio_files entry in the same
    # order. Drives the duration-weighted progress percentages in
    # core/worker.py.
    audio_durations: list[float] = field(default_factory=list)

    timestamps: bool = True

    # The next three are already-translated text, passed down as data because
    # this process has no access to gui.i18n and does not know the UI
    # language. speaker_label is a format string, e.g. "דובר {n}"; None
    # disables speaker labels. failed_label (e.g. "Transcription failed") is
    # only safe as None when no file in the batch fails. ui_strings holds the
    # transcript page's own chrome, and missing keys fall back to English
    # inside the page rather than rendering blank.
    speaker_label: Optional[str] = None
    failed_label: Optional[str] = None
    ui_strings: dict[str, str] = field(default_factory=dict)

    identify_speakers: bool = True

    # How many people are in the recording. Knowing this exactly is the single
    # biggest accuracy lever in diarization: clustering into a fixed number of
    # speakers is far more robust than inferring the count from a similarity
    # threshold. -1 means "unknown, infer it".
    num_speakers: int = 2

    # Path to a user-maintained list of domain terms (names, places, jargon).
    # Absent or empty means the correction pass does nothing, which is the
    # intended default - see core/hebrew_correct.py for why a general
    # dictionary would make Hebrew transcripts worse rather than better.
    terms_file: Optional[str] = None

    @property
    def total_duration(self) -> float:
        return sum(self.audio_durations)
