"""
Tests for transcriber module.
"""

import pytest
from unittest.mock import MagicMock, patch, call
from speech_to_text.core.transcriber import Transcriber


class TestTranscriber:
    """Test transcriber functionality."""
    
    def test_transcriber_initialization(self):
        """Test transcriber initialization."""
        transcriber = Transcriber(
            model_size="small",
            device="cpu",
            language="he"
        )
        
        assert transcriber.model_size == "small"
        assert transcriber.device == "cpu"
        assert transcriber.language == "he"
        assert transcriber.model is None
    
    def test_transcriber_default_callback(self):
        """Test default progress callback."""
        transcriber = Transcriber()
        # Should not raise
        transcriber.progress_callback("Test message", 50)
    
    def test_transcriber_custom_callback(self):
        """Test custom progress callback."""
        callback = MagicMock()
        transcriber = Transcriber(progress_callback=callback)
        
        transcriber.progress_callback("Test message", 50)
        callback.assert_called_once_with("Test message", 50)
    
    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_load_model_success(self, mock_whisper_model_class):
        """Test successful model loading."""
        mock_model = MagicMock()
        mock_whisper_model_class.return_value = mock_model
        
        transcriber = Transcriber()
        result = transcriber.load_model()
        
        assert result is True
        assert transcriber.model is not None
        mock_whisper_model_class.assert_called_once()
    
    def test_load_model_whisper_not_installed(self):
        """Test model loading when WhisperModel is not available."""
        with patch('speech_to_text.core.transcriber.WhisperModel', None):
            transcriber = Transcriber()
            result = transcriber.load_model()
            assert result is False
    
    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_load_model_failure(self, mock_whisper_model_class):
        """Test model loading failure."""
        mock_whisper_model_class.side_effect = Exception("Model loading failed")
        
        transcriber = Transcriber()
        result = transcriber.load_model()
        
        assert result is False
        assert transcriber.model is None
    
    def test_transcribe_without_model(self):
        """Test transcription without loading model."""
        transcriber = Transcriber()
        result = transcriber.transcribe("dummy_audio.mp3")
        
        assert result is None
    
    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_success(self, mock_whisper_model_class):
        """Test successful transcription."""
        # Create mock segments
        mock_segment1 = MagicMock(text="Hello ")
        mock_segment2 = MagicMock(text="World")
        
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [mock_segment1, mock_segment2],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model
        
        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")
        
        assert result is not None
        assert "Hello" in result
        assert "World" in result
    
    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_adds_spaces_between_segments(self, mock_whisper_model_class):
        """Test that spaces are added between segments."""
        mock_segment1 = MagicMock(text="Hello")
        mock_segment2 = MagicMock(text="World")
        
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [mock_segment1, mock_segment2],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model
        
        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")
        
        # Should have space between Hello and World
        assert "Hello World" in result or result == "Hello World"
    
    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_empty_segments(self, mock_whisper_model_class):
        """Test transcription with empty segments."""
        mock_segment1 = MagicMock(text="Hello")
        mock_segment2 = MagicMock(text="")
        mock_segment3 = MagicMock(text="World")
        
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [mock_segment1, mock_segment2, mock_segment3],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model
        
        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")
        
        # Should skip empty segment
        assert "Hello World" in result
    
    def test_format_output_empty_text(self):
        """Test formatting empty text."""
        transcriber = Transcriber()
        result = transcriber.format_output("")
        assert result == ""
    
    def test_format_output_single_sentence(self):
        """Test formatting single sentence."""
        transcriber = Transcriber()
        result = transcriber.format_output("Hello world.")
        assert "Hello world." in result
    
    def test_format_output_multiple_sentences(self):
        """Test formatting multiple sentences."""
        transcriber = Transcriber()
        text = "Hello world. This is a test. Great!"
        result = transcriber.format_output(text)
        
        lines = result.split("\n")
        assert len(lines) == 3
        assert "Hello world." in lines[0]
        assert "This is a test." in lines[1]
        assert "Great!" in lines[2]
    
    def test_format_output_with_different_endings(self):
        """Test formatting with different sentence endings."""
        transcriber = Transcriber()
        text = "Is this right? Yes! Maybe."
        result = transcriber.format_output(text)
        
        lines = result.split("\n")
        assert len(lines) == 3
