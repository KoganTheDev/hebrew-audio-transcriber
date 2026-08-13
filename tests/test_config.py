"""
Tests for configuration module.
"""

import os

import pytest

from speech_to_text import config


class TestConfig:
    """Test configuration module."""
    
    def test_models_configuration(self):
        """Test that all models are configured correctly."""
        assert len(config.MODELS) == 7
        for name in ("tiny", "base", "small", "medium", "large",
                     "ivrit-turbo", "ivrit-large"):
            assert name in config.MODELS

    def test_model_has_required_keys(self):
        """Test that all models have required keys."""
        required_keys = {
            "repo", "name", "description", "pros", "cons", "time_estimate",
            "ram_required", "accuracy_score", "best_for", "recommended"
        }

        for model_name, model_info in config.MODELS.items():
            assert set(model_info.keys()) >= required_keys, \
                f"Model {model_name} missing keys"

    def test_large_is_pinned_to_an_explicit_version(self):
        """
        The bare "large" alias has pointed at different Whisper versions across
        faster-whisper releases, which silently changed which model ran.
        """
        assert config.MODELS["large"]["repo"] == "large-v3"

    def test_hebrew_models_point_at_ivrit_repos(self):
        assert config.MODELS["ivrit-turbo"]["repo"] == "ivrit-ai/whisper-large-v3-turbo-ct2"
        assert config.MODELS["ivrit-large"]["repo"] == "ivrit-ai/whisper-large-v3-ct2"

    def test_default_model_is_hebrew_tuned(self):
        """A Hebrew transcription app should not default to a general model."""
        assert config.DEFAULT_MODEL.startswith("ivrit-")
    
    def test_default_model_exists(self):
        """Test that default model is configured."""
        assert config.DEFAULT_MODEL in config.MODELS
    
    def test_only_one_recommended_model(self):
        """Test that exactly one model is marked as recommended."""
        recommended = [m for m in config.MODELS.values() if m['recommended']]
        assert len(recommended) == 1
    
    def test_app_configuration(self):
        """Test application configuration."""
        assert config.APP_NAME == "Hebrew Audio Transcriber"
        assert config.APP_VERSION == "2.0.0"
        assert config.WINDOW_WIDTH > 0
        assert config.WINDOW_HEIGHT > 0
    
    def test_supported_formats(self):
        """Test that supported audio formats are defined."""
        assert isinstance(config.SUPPORTED_FORMATS, tuple)
        assert len(config.SUPPORTED_FORMATS) > 0
        assert all(fmt.startswith("*.") for fmt in config.SUPPORTED_FORMATS)
    
    def test_required_packages(self):
        """Test that required packages are defined."""
        required_packages = config.REQUIRED_PACKAGES
        # faster_whisper is lazy-loaded to avoid torch DLL issues
        # psutil is optional for hardware detection
        assert "PyQt5" in required_packages
        assert "tqdm" in required_packages
        # These should NOT be in required_packages (lazy/optional)
        assert "faster_whisper" not in required_packages
        assert "psutil" not in required_packages
    
    def test_transcription_settings(self):
        """Test transcription configuration."""
        assert config.LANGUAGE == "he"
        assert config.BEAM_SIZE > 0
        assert config.COMPUTE_TYPE in ["int8", "int16", "float16", "float32"]
        assert isinstance(config.VAD_FILTER, bool)
        assert isinstance(config.FORMAT_OUTPUT, bool)
    
    def test_model_accuracy_progression(self):
        """Test that accuracy scores increase with model size."""
        models = list(config.MODELS.keys())
        scores = [config.MODELS[m]["accuracy_score"] for m in models]
        
        # Check that scores are in increasing order
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], \
                f"Accuracy should increase: {models[i]}/{scores[i]} -> {models[i+1]}/{scores[i+1]}"


class TestOutputPathFor:
    """
    output_path_for() replaced the fixed OUTPUT_FILENAME so batches of
    different recordings stop colliding on one transcription.txt - see
    config.OUTPUT_FILENAME_TEMPLATE.
    """

    def test_single_file_is_named_after_its_own_stem(self):
        path = config.output_path_for([os.path.join("dir", "meeting.wav")])
        assert os.path.dirname(path) == "dir"
        assert os.path.basename(path) == "meeting_transcription.html"

    def test_multiple_files_are_named_after_the_shared_folder(self):
        path = config.output_path_for([
            os.path.join("recordings", "a.wav"),
            os.path.join("recordings", "b.wav"),
        ])
        assert os.path.dirname(path) == "recordings"
        assert os.path.basename(path) == "recordings_transcription.html"

    def test_a_dotted_filename_keeps_its_whole_stem(self):
        """splitext splits on the LAST dot - "a.b.wav" must not lose "b"."""
        path = config.output_path_for([os.path.join("dir", "a.b.wav")])
        assert os.path.basename(path) == "a.b_transcription.html"

    def test_different_inputs_give_different_paths(self):
        one = config.output_path_for([os.path.join("dir", "meeting.wav")])
        two = config.output_path_for([os.path.join("dir", "other.wav")])
        assert one != two

        single = config.output_path_for([os.path.join("dir", "a.wav")])
        batch = config.output_path_for([
            os.path.join("dir", "a.wav"), os.path.join("dir", "b.wav"),
        ])
        assert single != batch

    def test_output_is_written_beside_the_first_input(self):
        path = config.output_path_for([
            os.path.join("here", "a.wav"),
            os.path.join("here", "b.wav"),
        ])
        assert os.path.dirname(path) == "here"
