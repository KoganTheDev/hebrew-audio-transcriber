"""
Integration tests for the entire system.
"""

import os
from unittest.mock import MagicMock, patch

import pytest

from speech_to_text import config
from speech_to_text.core.formatting import render_html
from speech_to_text.core.options import TranscriptionOptions
from speech_to_text.core.segments import TranscriptDocument, plain_text
from speech_to_text.core.transcriber import Transcriber
from speech_to_text.hardware_detection import HardwareDetector


class TestIntegration:
    """Integration tests for the system."""

    @pytest.mark.integration
    def test_config_hardware_compatibility(self):
        """Test that config models are compatible with hardware detection."""
        with patch("speech_to_text.hardware_detection.psutil") as mock_psutil:
            mock_psutil.cpu_count.return_value = 4
            mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)

            with patch.object(HardwareDetector, "_detect_gpu", return_value=False):
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
            transcriber = Transcriber(model_size=model_name, device="cpu", language=config.LANGUAGE)

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
            current_accuracy = current["accuracy_score"]
            next_accuracy = next_model["accuracy_score"]

            assert next_accuracy >= current_accuracy, (
                f"Accuracy should increase: {model_names[i]} -> {model_names[i + 1]}"
            )

    @pytest.mark.integration
    def test_file_path_handling(self, temp_dir):
        """Test that file paths are handled correctly."""
        # Create a test file
        test_file = os.path.join(temp_dir, "test_audio.mp3")
        with open(test_file, "w") as f:
            f.write("test")

        assert os.path.exists(test_file)
        assert os.path.isfile(test_file)

    @pytest.mark.integration
    @patch("speech_to_text.core.transcriber.WhisperModel")
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
        segments = transcriber.transcribe(sample_audio_path)
        assert segments is not None
        assert "Hello" in plain_text(segments)

        # Format output - the worker now always renders a single, self-
        # contained HTML document instead of a .txt file (see
        # core/formatting.py's module docstring for why: direction has to
        # be declared, not guessed, for Hebrew to align correctly).
        document = TranscriptDocument(
            source_name=os.path.basename(sample_audio_path), segments=segments
        )
        rendered = render_html([document])
        assert rendered is not None
        assert "<html" in rendered
        assert "Hello World" in rendered

    @pytest.mark.integration
    def test_transcription_options_survive_pickling(self):
        """
        TranscriptionOptions crosses a real multiprocessing.Process boundary
        (see core/worker.py's module docstring for why transcription runs in
        a separate OS process) - it has to pickle cleanly, batch fields
        included.
        """
        import pickle  # trusted, in-process round-trip only - mirrors multiprocessing's own use

        options = TranscriptionOptions(
            audio_durations=[12.5, 30.0],
            speaker_label="דובר {n}",
            failed_label="נכשל",
        )
        restored = pickle.loads(pickle.dumps(options))
        assert restored.audio_durations == [12.5, 30.0]
        assert restored.total_duration == 42.5
        assert restored.speaker_label == "דובר {n}"
        assert restored.failed_label == "נכשל"
