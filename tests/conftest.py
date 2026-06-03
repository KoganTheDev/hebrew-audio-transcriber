"""
Pytest configuration and shared fixtures for testing.
"""

import pytest
import tempfile
import os
from unittest.mock import MagicMock, patch


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
    open(audio_path, 'a').close()
    return audio_path


@pytest.fixture
def mock_hardware():
    """Create a mocked hardware detector."""
    with patch('speech_to_text.hardware_detection.psutil') as mock_psutil:
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
        yield mock_psutil


@pytest.fixture
def mock_whisper_model():
    """Create a mocked WhisperModel."""
    with patch('speech_to_text.core.transcriber.WhisperModel') as mock_model:
        yield mock_model
