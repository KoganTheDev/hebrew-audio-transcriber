"""
Hardware Detection Module
Detects CPU/GPU specs and calculates estimated transcription time.
"""

import platform
import subprocess
import logging
from typing import Dict, Tuple, Optional

from speech_to_text import config

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    logger.debug("psutil not available - using default hardware specs")
    psutil = None


class HardwareDetector:
    """Detects hardware specs and estimates processing time."""
    
    def __init__(self):
        logger.debug("Initializing HardwareDetector...")
        
        if psutil:
            self.cpu_count = psutil.cpu_count(logical=False)
            self.ram_gb = psutil.virtual_memory().total / (1024**3)
            logger.debug(f"Detected: {self.cpu_count} CPU cores, {self.ram_gb:.2f} GB RAM")
        else:
            self.cpu_count = 4  # Default
            self.ram_gb = 8  # Default
            logger.debug("Using default specs: 4 CPU cores, 8 GB RAM")
        
        self.has_gpu = self._detect_gpu()
        self.gpu_name = self._get_gpu_name()
        self.os_name = platform.system()
        
        logger.info(f"Hardware: OS={self.os_name}, GPU={'Yes' if self.has_gpu else 'No'}")
        if self.has_gpu:
            logger.info(f"GPU Model: {self.gpu_name}")
        
    def _detect_gpu(self) -> bool:
        """Check if NVIDIA GPU is available."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--list-gpus"],
                capture_output=True,
                text=True,
                timeout=5
            )
            has_gpu = result.returncode == 0
            if has_gpu:
                logger.debug("NVIDIA GPU detected")
            return has_gpu
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.debug(f"No GPU found: {type(e).__name__}")
            return False
        except Exception as e:
            logger.warning(f"Error checking for GPU: {e}")
            return False
    
    def _get_gpu_name(self) -> Optional[str]:
        """Get GPU model name."""
        if not self.has_gpu:
            return None
        try:
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                gpu_name = result.stdout.strip().split('\n')[0]
                logger.debug(f"GPU name retrieved: {gpu_name}")
                return gpu_name
            logger.warning("Failed to get GPU name from nvidia-smi")
            return "Unknown GPU"
        except Exception as e:
            logger.debug(f"Could not retrieve GPU name: {e}")
            return None
    
    def get_device_recommendation(self) -> Tuple[str, str]:
        """
        Recommend optimal device (CPU or GPU) based on available hardware.
        
        Prioritizes NVIDIA GPU if available; falls back to CPU with core count information.
        This recommendation is used to configure faster-whisper's execution backend.
        
        Returns:
            (device_string, reason_string)
            - device_string: "cuda" (for NVIDIA GPU) or "cpu" (for CPU processing)
            - reason_string: Human-readable explanation with hardware details
            
        Example:
            device, reason = hardware.get_device_recommendation()
            # Returns: ("cuda", "NVIDIA GPU detected: NVIDIA A100 40GB")
            # Or: ("cpu", "Using CPU (8 cores, 32.0GB RAM)")
        """
        if self.has_gpu and self.gpu_name and "NVIDIA" in self.gpu_name:
            return ("cuda", f"NVIDIA GPU detected: {self.gpu_name}")
        return ("cpu", f"Using CPU ({self.cpu_count} cores, {self.ram_gb:.1f}GB RAM)")
    
    def estimate_time(self, audio_duration_minutes: int, model_size: str, device: str) -> Dict:
        """
        Estimate transcription time based on hardware and model.
        
        Args:
            audio_duration_minutes: Length of audio in minutes
            model_size: Model size (tiny, base, small, medium, large)
            device: "cpu" or "cuda"
        
        Returns:
            Dict with estimated time and details
        """
        # Base processing speeds (60-min audio on reference hardware)
        speeds = {
            "tiny": {"cpu": 30, "cuda": 5},
            "base": {"cpu": 240, "cuda": 30},
            "small": {"cpu": 540, "cuda": 60},
            "medium": {"cpu": 1200, "cuda": 120},
            "large": {"cpu": 2400, "cuda": 240},
        }
        
        if model_size not in speeds:
            model_size = "medium"
        
        base_time = speeds[model_size].get(device, speeds[model_size]["cpu"])
        
        # Adjust for audio length
        # base_time is the time to process 60 minutes of audio
        estimated_minutes = base_time * (audio_duration_minutes / 60)
        
        # Adjust for hardware
        if device == "cpu":
            # Adjust based on CPU cores (reference: 4 cores)
            adjustment = 4 / max(self.cpu_count, 1)
            estimated_minutes *= adjustment
        
        hours = estimated_minutes / 60
        
        return {
            "minutes": int(estimated_minutes),
            "hours": hours,
            "hours_display": f"{hours:.1f} hours" if hours >= 1 else f"{int(estimated_minutes)} minutes",
            "model": model_size,
            "device": device,
            "audio_length": audio_duration_minutes,
        }
    
    def get_hardware_info(self) -> Dict:
        """Get formatted hardware information."""
        return {
            "cpu_cores": self.cpu_count,
            "ram_gb": f"{self.ram_gb:.1f}",
            "has_gpu": self.has_gpu,
            "gpu_name": self.gpu_name or "No NVIDIA GPU",
            "os": self.os_name,
        }

    def can_run_model(self, model_size: str) -> Tuple[bool, str]:
        """
        Check if system can run given model size.
        Returns: (can_run, reason)
        """
        ram_required = {
            "tiny": 1,
            "base": 2,
            "small": 3,
            "medium": 5,
            "large": 8,
        }
        
        required = ram_required.get(model_size, 5)
        
        if self.ram_gb < required:
            return False, f"Insufficient RAM: {self.ram_gb:.1f}GB available, {required}GB required"
        
        return True, f"✓ System has enough RAM ({self.ram_gb:.1f}GB)"
    
    def recommend_model(self) -> Tuple[str, str]:
        """
        Recommend best model based on hardware.
        Returns: (model_size, reason)
        """
        if self.has_gpu:
            return "small", "GPU available - good speed/accuracy balance"
        elif self.cpu_count >= 8:
            return "base", "8+ CPU cores - balanced model recommended"
        elif self.cpu_count >= 6:
            return "small", "6+ CPU cores - faster model recommended"
        else:
            return "tiny", "Limited CPU cores - fastest model recommended"
    
    def estimate_transcription_time(self, audio_duration_seconds: int, model_size: str) -> Tuple[int, str]:
        """
        Estimate transcription time based on audio duration, model, and hardware.
        
        Args:
            audio_duration_seconds: Length of audio in seconds
            model_size: Model size (tiny, small, base, medium, large)
        
        Returns:
            (estimated_seconds, reason_string)
        """
        # Speed factors: how many seconds of audio processed per second of real time
        # Higher = faster (from config.SPEED_FACTORS)
        base_speed = config.SPEED_FACTORS.get(model_size, 1.0)
        
        # Apply GPU boost if available (from config.GPU_SPEED_MULTIPLIER)
        if self.has_gpu:
            speed = base_speed * config.GPU_SPEED_MULTIPLIER
            device_desc = f"GPU ({self.gpu_name or 'NVIDIA'})"
        else:
            # Scale by CPU cores (normalized to baseline from config.BASELINE_CPU_CORES)
            # This prevents overly optimistic estimates on low-core systems.
            cpu_factor = self.cpu_count / float(config.BASELINE_CPU_CORES)
            speed = base_speed * cpu_factor
            device_desc = f"{self.cpu_count} CPU cores"
        
        # Calculate time with overhead
        processing_time = audio_duration_seconds / speed
        estimated_seconds = int(processing_time + config.TRANSCRIPTION_OVERHEAD_SECONDS)
        
        # Generate reason string
        audio_min = audio_duration_seconds / 60
        if estimated_seconds < 60:
            time_str = f"{estimated_seconds}s"
        elif estimated_seconds < 3600:
            time_str = f"{estimated_seconds // 60}m {estimated_seconds % 60}s"
        else:
            hours = estimated_seconds // 3600
            mins = (estimated_seconds % 3600) // 60
            time_str = f"{hours}h {mins}m"
        
        reason = f"Model: {model_size.title()} • Device: {device_desc} • Audio: {audio_min:.1f}m → ~{time_str}"
        
        logger.debug(f"Time estimation: {reason}")
        
        return estimated_seconds, reason
    
    def get_time_estimate_display(self, seconds: int) -> str:
        """Format seconds into human-readable time."""
        if seconds < 60:
            return f"{seconds}s"
        elif seconds < 3600:
            mins = seconds // 60
            secs = seconds % 60
            return f"{mins}m {secs}s" if secs > 0 else f"{mins}m"
        else:
            hours = seconds // 3600
            mins = (seconds % 3600) // 60
            return f"{hours}h {mins}m" if mins > 0 else f"{hours}h"
