"""
Wizard step widgets for the Speech-to-Text Transcriber GUI.
3-step flow: Select File -> Choose Model -> Transcribe

Split into one module per step (file_select.py / model_select.py /
transcription.py) since each is a large, self-contained QFrame widget only
coupled to the others by living in the same wizard — see gui/main_window.py
for how MainWindow wires them together via the Step enum below.
"""

from enum import Enum

from speech_to_text.gui.steps.file_select import FileSelectStep
from speech_to_text.gui.steps.model_select import ModelSelectStep
from speech_to_text.gui.steps.transcription import TranscriptionStep


class Step(Enum):
    """Application steps."""
    FILE_SELECT = 0
    MODEL_SELECT = 1
    TRANSCRIPTION = 2


__all__ = ["Step", "FileSelectStep", "ModelSelectStep", "TranscriptionStep"]
