"""
Tests for transcriber module.
"""

from unittest.mock import MagicMock, call, patch

import pytest

from speech_to_text.core.hebrew_text import PDI, RLI
from speech_to_text.core.segments import plain_text
from speech_to_text.core.transcriber import Transcriber


def fake_segment(text, start=0.0, end=1.0, words=None):
    """
    Build a stand-in for a faster-whisper segment.

    MagicMock(text=...) alone is not enough any more: Transcriber now reads
    start/end/words off each segment, and a bare MagicMock returns child
    mocks for those, not numbers. Setting them explicitly keeps these tests
    testing our conversion logic rather than mock behaviour.
    """
    segment = MagicMock()
    segment.text = text
    segment.start = start
    segment.end = end
    segment.words = words
    return segment


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
    
    def test_model_repo_resolves_config_key_to_upstream_id(self):
        """A config.MODELS key is our name for a model, not its address."""
        assert Transcriber(model_size="ivrit-turbo").model_repo == \
            "ivrit-ai/whisper-large-v3-turbo-ct2"
        assert Transcriber(model_size="large").model_repo == "large-v3"

    def test_model_repo_passes_through_unknown_names(self):
        """
        Lets the evaluation harness benchmark models that have no GUI card by
        naming a raw Whisper size or repo id directly.
        """
        assert Transcriber(model_size="distil-large-v3").model_repo == "distil-large-v3"

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_load_model_uses_repo_not_key(self, mock_whisper_model_class):
        """
        The repo id, not our key, must reach faster-whisper - passing
        "ivrit-turbo" would just 404.
        """
        transcriber = Transcriber(model_size="ivrit-turbo")
        transcriber.load_model()

        assert mock_whisper_model_class.call_args.args[0] == \
            "ivrit-ai/whisper-large-v3-turbo-ct2"

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

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_load_model_defaults_to_cpu_compute_type_unset(self, mock_whisper_model_class):
        """
        No cpu_threads/num_workers override given -> neither kwarg reaches
        WhisperModel at all, so ctranslate2 picks its own thread count
        exactly as it always did (see _load_on's docstring for why
        production leaves these alone).
        """
        Transcriber(device="cpu").load_model()

        kwargs = mock_whisper_model_class.call_args.kwargs
        assert kwargs["compute_type"] == "int8"
        assert "cpu_threads" not in kwargs
        assert "num_workers" not in kwargs

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_load_model_forwards_explicit_axes_to_whispermodel(self, mock_whisper_model_class):
        """
        The knobs tests/eval/compare_models.py sweeps (Phase B) must actually
        reach WhisperModel, not just live on the Transcriber instance.
        """
        Transcriber(
            compute_type="float32", beam_size=1, cpu_threads=4, num_workers=2,
        ).load_model()

        kwargs = mock_whisper_model_class.call_args.kwargs
        assert kwargs["compute_type"] == "float32"
        assert kwargs["cpu_threads"] == 4
        assert kwargs["num_workers"] == 2

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_load_model_uses_cuda_compute_type_on_cuda(self, mock_whisper_model_class):
        """
        config.compute_type_for_device is device-conditional (float16 on
        CUDA, int8 on CPU) - a single global COMPUTE_TYPE used to apply
        regardless of device. Untested on real GPU hardware; see
        load_model()'s docstring.
        """
        Transcriber(device="cuda").load_model()

        assert mock_whisper_model_class.call_args.kwargs["compute_type"] == "float16"
        assert mock_whisper_model_class.call_args.kwargs["device"] == "cuda"

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_load_model_falls_back_to_cpu_when_cuda_init_fails(self, mock_whisper_model_class):
        """
        A CUDA device_recommendation is only a guess from nvidia-smi output -
        it does not prove the ctranslate2/CUDA runtime actually initialises.
        A driver/CUDA-version mismatch is a real, live failure mode (see
        load_model()'s docstring) and must not fail the whole transcription
        when CPU would have worked fine. Simulated here since this
        development machine has no NVIDIA GPU to fail on for real.
        """
        mock_model = MagicMock()
        mock_whisper_model_class.side_effect = [RuntimeError("simulated CUDA init failure"), mock_model]

        transcriber = Transcriber(device="cuda")
        result = transcriber.load_model()

        assert result is True
        assert transcriber.device == "cpu"
        assert transcriber.model is mock_model
        assert mock_whisper_model_class.call_count == 2
        first_call, second_call = mock_whisper_model_class.call_args_list
        assert first_call.kwargs["device"] == "cuda"
        assert second_call.kwargs["device"] == "cpu"
        assert second_call.kwargs["compute_type"] == "int8"

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_load_model_reports_failure_when_both_cuda_and_the_cpu_fallback_fail(
        self, mock_whisper_model_class
    ):
        """A machine with no working backend at all must still fail cleanly."""
        mock_whisper_model_class.side_effect = RuntimeError("nothing works")

        transcriber = Transcriber(device="cuda")
        result = transcriber.load_model()

        assert result is False
        assert transcriber.model is None
    
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
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("Hello "), fake_segment("World")],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert result is not None
        text = plain_text(result)
        assert "Hello" in text
        assert "World" in text

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_uses_config_beam_size_by_default(self, mock_whisper_model_class):
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("Hello")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        transcriber.transcribe("dummy_audio.mp3")

        assert mock_model.transcribe.call_args.kwargs["beam_size"] == 5

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_forwards_explicit_beam_size(self, mock_whisper_model_class):
        """The Phase B sweep axis - must actually reach model.transcribe()."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("Hello")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber(beam_size=1)
        transcriber.load_model()
        transcriber.transcribe("dummy_audio.mp3")

        assert mock_model.transcribe.call_args.kwargs["beam_size"] == 1

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_requests_word_timestamps(self, mock_whisper_model_class):
        """
        Word timings must be requested, or segment.words comes back None and
        both diarization and confidence-gated correction silently lose the
        data they depend on.
        """
        mock_model = MagicMock()
        mock_model.transcribe.return_value = ([fake_segment("Hello")], MagicMock())
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        transcriber.transcribe("dummy_audio.mp3")

        assert mock_model.transcribe.call_args.kwargs["word_timestamps"] is True

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_captures_timings_and_words(self, mock_whisper_model_class):
        """Timings and per-word confidences survive into our Segment type."""
        word = MagicMock()
        word.word = "שלום"
        word.start = 1.5
        word.end = 2.0
        word.probability = 0.42

        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("שלום", start=1.5, end=2.0, words=[word])],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert len(result) == 1
        assert result[0].start == 1.5
        assert result[0].end == 2.0
        assert result[0].speaker is None
        assert len(result[0].words) == 1
        assert result[0].words[0].text == "שלום"
        assert result[0].words[0].probability == 0.42

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_tolerates_missing_word_data(self, mock_whisper_model_class):
        """words=None (word_timestamps off, or an older faster-whisper) must not raise."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("Hello", words=None)],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert len(result) == 1
        assert result[0].words == []

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_adds_spaces_between_segments(self, mock_whisper_model_class):
        """Test that spaces are added between segments."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("Hello"), fake_segment("World")],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        assert plain_text(result) == "Hello World"

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_transcribe_empty_segments(self, mock_whisper_model_class):
        """Test transcription with empty segments."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("Hello"), fake_segment(""), fake_segment("World")],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        result = transcriber.transcribe("dummy_audio.mp3")

        # Should skip empty segment
        assert len(result) == 2
        assert plain_text(result) == "Hello World"

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_segment_debug_log_isolates_hebrew_preview(self, mock_whisper_model_class, caplog):
        """
        The reported bug: a Hebrew segment preview logged into the
        otherwise-LTR DEBUG line must be wrapped in an RTL isolate so a
        trailing neutral character (here, the comma) can't reorder to the
        wrong side. See core/hebrew_text.isolate_rtl.
        """
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment(" סניף כשר למהדרין,")],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        with caplog.at_level("DEBUG", logger="speech_to_text.core.transcriber"):
            transcriber.transcribe("dummy_audio.mp3")

        debug_lines = [r.message for r in caplog.records if r.message.startswith("Segment ")]
        assert len(debug_lines) == 1
        assert debug_lines[0] == f"Segment 1: {RLI} סניף כשר למהדרין,{PDI}"

    @patch('speech_to_text.core.transcriber.WhisperModel')
    def test_segment_debug_log_does_not_isolate_ascii_preview(self, mock_whisper_model_class, caplog):
        """An ASCII-only preview has no bidi problem, so no isolate noise."""
        mock_model = MagicMock()
        mock_model.transcribe.return_value = (
            [fake_segment("Hello World")],
            MagicMock()
        )
        mock_whisper_model_class.return_value = mock_model

        transcriber = Transcriber()
        transcriber.load_model()
        with caplog.at_level("DEBUG", logger="speech_to_text.core.transcriber"):
            transcriber.transcribe("dummy_audio.mp3")

        debug_lines = [r.message for r in caplog.records if r.message.startswith("Segment ")]
        assert debug_lines == ["Segment 1: Hello World"]


# Transcript rendering is covered in tests/test_formatting.py - it grew its own
# module once timestamps, turn merging and bidi control characters arrived.
