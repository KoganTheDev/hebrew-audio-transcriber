"""Qt-free decision logic sitting behind the GUI's widgets.

Everything under this package is plain Python: no PyQt5 import, and no
import of any `gui` module that itself pulls PyQt5 in (which rules out
`gui.i18n`, whose QSettings-backed language state needs Qt). That is the
whole point of the package - the decisions a step takes when the user
clicks Next become unit-testable with no QApplication, instead of only
through a live MainWindow.

Anything a presenter needs from the Qt world - translation, hardware
probing - arrives as an injected argument, so a test can hand it a stub.
"""

from speech_to_text.gui.presenters.transcription import (
    DeviceRecommender,
    TranscriptionRequest,
    build_file_summary,
    build_transcription_request,
)

__all__ = [
    "DeviceRecommender",
    "TranscriptionRequest",
    "build_file_summary",
    "build_transcription_request",
]
