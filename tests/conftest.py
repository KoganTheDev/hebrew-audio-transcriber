"""
Pytest configuration and shared fixtures for testing.
"""

import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def sample_audio_path(temp_dir):
    """Create a sample audio file path for testing."""
    audio_path = os.path.join(temp_dir, "sample_audio.mp3")
    # Create an empty file for testing
    open(audio_path, "a").close()
    return audio_path


@pytest.fixture
def mock_hardware():
    """Create a mocked hardware detector."""
    with patch("speech_to_text.hardware_detection.psutil") as mock_psutil:
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
        yield mock_psutil


@pytest.fixture
def mock_whisper_model():
    """Create a mocked WhisperModel."""
    with patch("speech_to_text.core.transcriber.WhisperModel") as mock_model:
        yield mock_model


@pytest.fixture(autouse=True)
def never_download_model_weights(monkeypatch):
    """No unit test may fetch model weights over the network.

    Transcriber.load_model() calls _fetch_weights() to run the download itself
    rather than leaving it to WhisperModel, so that it can report progress -
    see that method's docstring. Tests mock WhisperModel, which used to be
    enough to keep the suite offline; it no longer is, and without this fixture
    a single load_model() in a unit test pulls 1.6 GB and takes the suite from
    50 seconds to three and a half minutes.

    Returning None is exactly the documented fallback, so the code under test
    takes the same path it did before _fetch_weights existed: WhisperModel
    receives the repo id. A test that wants to exercise the download itself
    should undo this with its own monkeypatch.
    """
    monkeypatch.setattr(
        "speech_to_text.core.transcriber.Transcriber._fetch_weights",
        lambda self: None,
    )
