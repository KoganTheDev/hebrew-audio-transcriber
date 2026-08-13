"""
Settings for one transcription run.

Bundled into a dataclass rather than passed as a growing list of positional
arguments to run_transcription_process, which has to be forwarded verbatim
through TranscriptionThread and multiprocessing.Process args and was already
seven items long.

Stdlib only and trivially picklable, since instances cross a process boundary.
Like everything in core/, this must not import PyQt5 or gui.i18n.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from speech_to_text import config


@dataclass
class TranscriptionOptions:
    """What to transcribe, with which model, and how to render the result."""

    model_size: str = config.DEFAULT_MODEL
    device: str = "cpu"
    language: str = config.LANGUAGE

    # Real audio length per input file, probed by the GUI before the run
    # starts (gui.audio_utils), one entry per audio_files entry in the same
    # order. Drives accurate, duration-weighted progress percentages across
    # a batch - see core/worker.py's per-file progress rescaling.
    audio_durations: List[float] = field(default_factory=list)

    # --- Output rendering -------------------------------------------------
    timestamps: bool = True

    # Format string for a speaker name, e.g. "דובר {n}" / "Speaker {n}".
    # Rendered text cannot be produced in this process - it has no access to
    # gui.i18n and does not know the UI language - so the GUI passes the
    # already-translated template down as data. None disables speaker labels.
    speaker_label: Optional[str] = None

    # Pre-translated text (e.g. "Transcription failed") for a document whose
    # file could not be transcribed. Same reasoning as speaker_label: the
    # worker cannot render UI text itself. None is only safe when no file in
    # the batch actually fails.
    failed_label: Optional[str] = None

    # Already-translated labels for the transcript page's own chrome (search,
    # save, plain text, …). Third instance of the same pattern, and for the
    # same reason: the rendered document is a small application with visible
    # text, and this process cannot translate any of it. Missing keys fall
    # back to English inside the page rather than rendering blank.
    ui_strings: Dict[str, str] = field(default_factory=dict)

    # --- Speaker identification -------------------------------------------
    identify_speakers: bool = True

    # How many people are in the recording. Knowing this exactly is the single
    # biggest accuracy lever in diarization: clustering into a fixed number of
    # speakers is far more robust than inferring the count from a similarity
    # threshold. -1 means "unknown, infer it".
    num_speakers: int = 2

    # --- Hebrew term correction -------------------------------------------
    # Path to a user-maintained list of domain terms (names, places, jargon).
    # Absent or empty file means the correction pass does nothing, which is the
    # intended default - see core/hebrew_correct.py for why a general
    # dictionary would make Hebrew transcripts worse rather than better.
    terms_file: Optional[str] = None

    @property
    def total_duration(self) -> float:
        """
        Sum of every input file's duration - one place for arithmetic that
        used to read a single audio_duration_seconds, now spread across a
        batch (progress rescaling in core/worker.py, the model-time
        recommendation in the GUI).
        """
        return sum(self.audio_durations)
