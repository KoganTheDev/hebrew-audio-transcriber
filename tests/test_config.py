"""
Tests for configuration module.
"""

import pytest
from speech_to_text import config


class TestConfig:
    """Test configuration module."""
    
    def test_models_configuration(self):
        """Test that all models are configured correctly."""
        assert len(config.MODELS) == 5
        assert "tiny" in config.MODELS
        assert "base" in config.MODELS
        assert "small" in config.MODELS
        assert "medium" in config.MODELS
        assert "large" in config.MODELS
    
    def test_model_has_required_keys(self):
        """Test that all models have required keys."""
        required_keys = {
            "name", "description", "pros", "cons", "time_estimate",
            "ram_required", "accuracy_score", "best_for", "recommended"
        }
        
        for model_name, model_info in config.MODELS.items():
            assert set(model_info.keys()) >= required_keys, \
                f"Model {model_name} missing keys"
    
    def test_default_model_exists(self):
        """Test that default model is configured."""
        assert config.DEFAULT_MODEL in config.MODELS
    
    def test_only_one_recommended_model(self):
        """Test that exactly one model is marked as recommended."""
        recommended = [m for m in config.MODELS.values() if m['recommended']]
        assert len(recommended) == 1
    
    def test_app_configuration(self):
        """Test application configuration."""
        assert config.APP_NAME == "Speech-to-Text Transcriber"
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
        models = ["tiny", "base", "small", "medium", "large"]
        scores = [config.MODELS[m]["accuracy_score"] for m in models]
        
        # Check that scores are in increasing order
        for i in range(len(scores) - 1):
            assert scores[i] <= scores[i + 1], \
                f"Accuracy should increase: {models[i]}/{scores[i]} -> {models[i+1]}/{scores[i+1]}"
