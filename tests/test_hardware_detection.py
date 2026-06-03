"""
Tests for hardware detection module.
"""

import pytest
from unittest.mock import MagicMock, patch
from speech_to_text.hardware_detection import HardwareDetector


class TestHardwareDetector:
    """Test hardware detection functionality."""
    
    @patch('speech_to_text.hardware_detection.psutil')
    def test_initialization_with_psutil(self, mock_psutil):
        """Test HardwareDetector initialization with psutil."""
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
        
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            detector = HardwareDetector()
            assert detector.cpu_count == 4
            assert detector.ram_gb == pytest.approx(8.0, rel=0.01)
    
    @patch('speech_to_text.hardware_detection.psutil', None)
    def test_initialization_without_psutil(self):
        """Test HardwareDetector initialization without psutil."""
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            detector = HardwareDetector()
            assert detector.cpu_count == 4
            assert detector.ram_gb == 8
    
    def test_device_recommendation_cpu_only(self):
        """Test device recommendation when only CPU is available."""
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            with patch.object(HardwareDetector, '_get_gpu_name', return_value=None):
                detector = HardwareDetector()
                device, reason = detector.get_device_recommendation()
                assert device == "cpu"
                assert "CPU" in reason
    
    @patch('speech_to_text.hardware_detection.psutil')
    def test_estimate_time_calculation(self, mock_psutil):
        """Test time estimation calculation."""
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
        
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            detector = HardwareDetector()
            
            # Test small model on CPU with 60 minutes of audio
            estimate = detector.estimate_time(60, "tiny", "cpu")
            assert estimate["model"] == "tiny"
            assert estimate["device"] == "cpu"
            assert estimate["audio_length"] == 60
            assert estimate["hours"] >= 0
    
    @patch('speech_to_text.hardware_detection.psutil')
    def test_estimate_time_scales_with_audio_length(self, mock_psutil):
        """Test that time estimation scales with audio length."""
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
        
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            detector = HardwareDetector()
            
            # 30 minutes should take half the time of 60 minutes
            estimate_30 = detector.estimate_time(30, "small", "cpu")
            estimate_60 = detector.estimate_time(60, "small", "cpu")
            
            ratio = estimate_60["minutes"] / estimate_30["minutes"]
            assert ratio == pytest.approx(2.0, rel=0.01)
    
    @patch('speech_to_text.hardware_detection.psutil')
    def test_estimate_time_cuda_faster_than_cpu(self, mock_psutil):
        """Test that CUDA is faster than CPU for estimation."""
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
        
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            detector = HardwareDetector()
            
            estimate_cpu = detector.estimate_time(60, "medium", "cpu")
            estimate_cuda = detector.estimate_time(60, "medium", "cuda")
            
            assert estimate_cuda["minutes"] < estimate_cpu["minutes"]
    
    @patch('speech_to_text.hardware_detection.psutil')
    def test_can_run_model_sufficient_ram(self, mock_psutil):
        """Test model validation with sufficient RAM."""
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
        
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            detector = HardwareDetector()
            can_run, reason = detector.can_run_model("medium")
            assert can_run is True
            assert "enough RAM" in reason
    
    @patch('speech_to_text.hardware_detection.psutil')
    def test_can_run_model_insufficient_ram(self, mock_psutil):
        """Test model validation with insufficient RAM."""
        mock_psutil.cpu_count.return_value = 4
        # Only 2GB RAM
        mock_psutil.virtual_memory.return_value = MagicMock(total=2 * 1024**3)
        
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            detector = HardwareDetector()
            can_run, reason = detector.can_run_model("large")
            assert can_run is False
            assert "Insufficient RAM" in reason
    
    @patch('speech_to_text.hardware_detection.psutil')
    def test_get_hardware_info(self, mock_psutil):
        """Test hardware info retrieval."""
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1024**3)
        
        with patch.object(HardwareDetector, '_detect_gpu', return_value=False):
            with patch.object(HardwareDetector, '_get_gpu_name', return_value=None):
                detector = HardwareDetector()
                info = detector.get_hardware_info()
                
                assert "cpu_cores" in info
                assert "ram_gb" in info
                assert "has_gpu" in info
                assert "gpu_name" in info
                assert "os" in info
