"""
Tests for GUI components (limited GUI testing due to PyQt5 complexity).
"""

import pytest
from unittest.mock import MagicMock, patch, call


class TestGUI:
    """Test GUI components."""
    
    @pytest.mark.skipif(True, reason="PyQt5 GUI testing requires X11 or mocking display")
    def test_main_window_creation(self):
        """Test main window creation."""
        pass
    
    @patch('speech_to_text.gui.main_window.QMainWindow')
    def test_transcription_thread_initialization(self, mock_main_window):
        """Test transcription thread initialization."""
        from speech_to_text.gui.main_window import TranscriptionThread
        
        thread = TranscriptionThread(
            audio_file="test.mp3",
            model_size="small",
            device="cpu"
        )
        
        assert thread.audio_file == "test.mp3"
        assert thread.model_size == "small"
        assert thread.device == "cpu"
