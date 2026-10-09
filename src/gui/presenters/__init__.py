"""Qt-free decision logic behind the GUI's widgets, unit-testable without a
QApplication. Nothing here imports PyQt5 or any gui module that does (so not
gui.i18n); Qt-side needs such as translation arrive as arguments.
"""

from gui.presenters.time_estimate import TimeEstimator
from gui.presenters.transcription import (
    DeviceRecommender,
    TranscriptionRequest,
    build_file_summary,
    build_transcription_request,
)

__all__ = [
    "DeviceRecommender",
    "TimeEstimator",
    "TranscriptionRequest",
    "build_file_summary",
    "build_transcription_request",
]
