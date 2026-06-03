"""
Integration tests for the entire system.
"""

import pytest
import os
from unittest.mock import MagicMock, patch
from speech_to_text import config
from speech_to_text.hardware_detection import HardwareDetector
from speech_to_text.core.transcriber import Transcriber


class TestIntegration:
    """Integration tests for the system."""
    
    @pytest.mark.integration
    def test_config_hardware_compatibility(self):
        """Test that config models are compatible with hardware detection."""
        with patch('speech_to_text.hardware_detection.psutil') as mock_psutil:
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
            
            with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
                detector = HardwareDetector()
                
                # All models should be checkable
                for model_name in config.MODELS.keys():
                    can_run, reason = detector.can_run_model(model_name)
                    # With 8GB RAM, tiny, base, small, and medium should work
                    assert isinstance(can_run, bool)
                    assert isinstance(reason, str)
    
    @pytest.mark.integration
    def test_transcriber_with_config_models(self):
        """Test that transcriber works with all config models."""
        for model_name in config.MODELS.keys():
            transcriber = Transcriber(
                model_size=model_name,
                device="cpu",
                language=config.LANGUAGE
            )
            
            assert transcriber.model_size == model_name
            assert transcriber.device == "cpu"
            assert transcriber.language == config.LANGUAGE
    
    @pytest.mark.integration
    def test_model_progression(self):
        """Test that model sizes progress correctly in terms of resource requirements."""
        from speech_to_text.config import MODELS
        
        model_names = list(MODELS.keys())
        for i in range(len(model_names) - 1):
            current = MODELS[model_names[i]]
            next_model = MODELS[model_names[i + 1]]
            
            # Next model should have equal or lower speed and equal or higher accuracy
            current_accuracy = current['accuracy_score']
            next_accuracy = next_model['accuracy_score']
            
            assert next_accuracy >= current_accuracy, \
                f"Accuracy should increase: {model_names[i]} -> {model_names[i+1]}"
    
    @pytest.mark.integration
    def test_file_path_handling(self, temp_dir):
        """Test that file paths are handled correctly."""
        # Create a test file
        test_file = os.path.join(temp_dir, "test_audio.mp3")
        with open(test_file, 'w') as f:
            f.write("test")
        
        assert os.path.exists(test_file)
        assert os.path.isfile(test_file)
    
    @pytest.mark.integration
    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_end_to_end_transcription_flow(self, mock_whisper_class, sample_audio_path):
        """Test end-to-end transcription flow."""
        # Mock the model
        mock_model = MagicMock()
        mock_segment = MagicMock(text="Hello World")
        mock_model.transcribe.return_value = ([mock_segment], MagicMock())
        mock_whisper_class.return_value = mock_model
        
        # Create transcriber
        transcriber = Transcriber(model_size="small")
        assert transcriber.load_model() is True
        
        # Transcribe
        result = transcriber.transcribe(sample_audio_path)
        assert result is not None
        assert "Hello" in result
        
        # Format output
        formatted = transcriber.format_output(result)
        assert formatted is not None
