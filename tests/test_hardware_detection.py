"""
Tests for hardware detection module.
"""

from unittest.mock import MagicMock, patch

import pytest

from hardware_detection import HardwareDetector


class TestHardwareDetector:
    """Test hardware detection functionality."""

    @patch("hardware_detection.psutil")
    def test_initialization_with_psutil(self, mock_psutil):
        """Test HardwareDetector initialization with psutil."""
        mock_psutil.cpu_count.return_value = 4
        # Decimal GB (1000**3), matching how ram_gb is computed - see
        # hardware_detection.py's comment on why it isn't 1024**3 (GiB).
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1000**3)

        with patch.object(HardwareDetector, "_detect_gpu", return_value=False):
            detector = HardwareDetector()
            assert detector.cpu_count == 4
            assert detector.ram_gb == pytest.approx(8.0, rel=0.01)

    @patch("hardware_detection.psutil", None)
    def test_initialization_without_psutil(self):
        """Test HardwareDetector initialization without psutil."""
        with patch.object(HardwareDetector, "_detect_gpu", return_value=False):
            detector = HardwareDetector()
            assert detector.cpu_count == 4
            assert detector.ram_gb == 8

    def test_device_recommendation_cpu_only(self):
        """Test device recommendation when only CPU is available."""
        with patch.object(HardwareDetector, "_detect_gpu", return_value=False):
            with patch.object(HardwareDetector, "_get_gpu_name", return_value=None):
                detector = HardwareDetector()
                device, reason = detector.get_device_recommendation()
                assert device == "cpu"
                assert "CPU" in reason

    @patch("hardware_detection.psutil")
    def test_can_run_model_sufficient_ram(self, mock_psutil):
        """Test model validation with sufficient RAM."""
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1000**3)

        with patch.object(HardwareDetector, "_detect_gpu", return_value=False):
            detector = HardwareDetector()
            can_run, reason = detector.can_run_model("medium")
            assert can_run is True
            assert "enough RAM" in reason

    @patch("hardware_detection.psutil")
    def test_can_run_model_insufficient_ram(self, mock_psutil):
        """Test model validation with insufficient RAM."""
        mock_psutil.cpu_count.return_value = 4
        # Only 2GB RAM
        mock_psutil.virtual_memory.return_value = MagicMock(total=2 * 1000**3)

        with patch.object(HardwareDetector, "_detect_gpu", return_value=False):
            detector = HardwareDetector()
            can_run, reason = detector.can_run_model("large")
            assert can_run is False
            assert "Insufficient RAM" in reason

    @patch("hardware_detection.psutil")
    def test_get_hardware_info(self, mock_psutil):
        """Test hardware info retrieval."""
        mock_psutil.cpu_count.return_value = 4
        mock_psutil.virtual_memory.return_value = MagicMock(total=8 * 1000**3)

        with patch.object(HardwareDetector, "_detect_gpu", return_value=False):
            with patch.object(HardwareDetector, "_get_gpu_name", return_value=None):
                detector = HardwareDetector()
                info = detector.get_hardware_info()

                assert "cpu_cores" in info
                assert "ram_gb" in info
                assert "has_gpu" in info
                assert "gpu_name" in info
                assert "os" in info
