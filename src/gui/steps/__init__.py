"""The three wizard step widgets, one module each; MainWindow wires them
together through the Step enum.
"""

from enum import Enum

from gui.steps.file_select import FileSelectStep
from gui.steps.model_select import ModelSelectStep
from gui.steps.transcription import TranscriptionStep


class Step(Enum):
    """Application steps."""

    FILE_SELECT = 0
    MODEL_SELECT = 1
    TRANSCRIPTION = 2


__all__ = ["Step", "FileSelectStep", "ModelSelectStep", "TranscriptionStep"]
