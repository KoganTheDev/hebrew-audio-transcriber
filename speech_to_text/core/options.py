"""
Settings for one transcription run.

Bundled into a dataclass rather than passed as a growing list of positional
arguments to run_transcription_process, which has to be forwarded verbatim
through TranscriptionThread and multiprocessing.Process args and was already
seven items long.

Stdlib only and trivially picklable, since instances cross a process boundary.
Like everything in core/, this must not import PyQt5 or gui.i18n.
"""

from dataclasses import dataclass
from typing import Optional

from speech_to_text import config


@dataclass
class TranscriptionOptions:
    """What to transcribe, with which model, and how to render the result."""

    model_size: str = config.DEFAULT_MODEL
    device: str = "cpu"
    language: str = config.LANGUAGE

    # Real audio length, probed by the GUI before the run starts
    # (gui.audio_utils). Drives accurate progress percentages.
    audio_duration_seconds: float = 0.0

    # --- Output rendering -------------------------------------------------
    timestamps: bool = True

    # Format string for a speaker name, e.g. "דובר {n}" / "Speaker {n}".
    # Rendered text cannot be produced in this process - it has no access to
    # gui.i18n and does not know the UI language - so the GUI passes the
    # already-translated template down as data. None disables speaker labels.
    speaker_label: Optional[str] = None

    # --- Speaker identification -------------------------------------------
    identify_speakers: bool = True

    # How many people are in the recording. Knowing this exactly is the single
    # biggest accuracy lever in diarization: clustering into a fixed number of
    # speakers is far more robust than inferring the count from a similarity
    # threshold. -1 means "unknown, infer it".
    num_speakers: int = 2
