"""
The transcription path across module boundaries: Transcriber's segments
rendered by core.formatting into the HTML document the app saves.

Each module has its own unit tests; this one checks that what one produces is
what the next consumes. Whisper itself is mocked - no model is loaded.
"""

from unittest.mock import MagicMock, patch

import pytest

from core.formatting import render_html
from core.segments import TranscriptDocument, plain_text
from core.transcriber import Transcriber


@pytest.mark.integration
@patch("core.transcriber.WhisperModel")
def test_a_transcribed_file_renders_into_the_saved_document(mock_whisper_class, tmp_path):
    audio = tmp_path / "sample_audio.mp3"
    audio.touch()
    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([MagicMock(text="Hello World")], MagicMock())
    mock_whisper_class.return_value = mock_model

    transcriber = Transcriber(model_size="ivrit-turbo")
    assert transcriber.load_model() is True
    segments = transcriber.transcribe(str(audio))
    assert "Hello" in plain_text(segments)

    rendered = render_html([TranscriptDocument(source_name=audio.name, segments=segments)])
    assert "<html" in rendered
    assert "Hello World" in rendered
