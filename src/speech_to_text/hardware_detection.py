"""Hardware Detection Module
Detects CPU/GPU specs and calculates estimated transcription time.
"""

import logging
import platform
import subprocess
from typing import Dict, Optional, Tuple

from speech_to_text import config
from speech_to_text.core.calibration import RELATIVE_COMPUTE_COST, load_cached_tiny_rtf

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    logger.debug("psutil not available - using default hardware specs")
    psutil = None


def _format_duration(seconds: int, elide_zero: bool) -> str:
    """Render a whole-second duration as "Xs" / "Xm Ys" / "Xh Ym", the
    <60s / <1h / else ladder used by both estimate_transcription_time's
    reason string and get_time_estimate_display.

    The two callers genuinely differ on one thing: the reason string always
    shows both components once past the 60s mark ("5m 0s"), while the
    display shown directly to the user drops a zero trailing component
    ("5m") because a bare minute count reads cleaner in the UI than a
    "0s"/"0m" that adds nothing. elide_zero picks which behaviour a caller
    wants rather than forcing one on both.
    """
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins, secs = divmod(seconds, 60)
        if elide_zero and secs == 0:
            return f"{mins}m"
        return f"{mins}m {secs}s"
    else:
        hours, remainder = divmod(seconds, 3600)
        mins = remainder // 60
        if elide_zero and mins == 0:
            return f"{hours}h"
        return f"{hours}h {mins}m"


def _required_ram_gb(model_size: str, default: int = 5) -> int:
    """Parse a model's RAM requirement out of config.MODELS ("3 GB" -> 3).

    config stores it as display text because that's what the model cards show.
    Parsing it here keeps a single source of truth; an unparseable or unknown
    entry falls back to the mid-range default rather than raising, since a
    wrong estimate is much better than a crashed hardware probe.
    """
    entry = config.MODELS.get(model_size)
    if not entry:
        return default
    digits = "".join(c for c in str(entry.get("ram_required", "")) if c.isdigit())
    return int(digits) if digits else default


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

        # Real measured transcription speed on this machine (seconds of tiny-
        # model processing per second of audio), used by
        # estimate_transcription_time instead of guessed constants. None
        # until a calibration benchmark has run - see set_calibration() and
        # speech_to_text.core.calibration.
        self.tiny_seconds_per_audio_second: Optional[float] = load_cached_tiny_rtf(self.cpu_count)

        logger.info(f"Hardware: OS={self.os_name}, GPU={'Yes' if self.has_gpu else 'No'}")
        if self.has_gpu:
            logger.info(f"GPU Model: {self.gpu_name}")
        if self.tiny_seconds_per_audio_second is not None:
            logger.debug(
                f"Loaded cached calibration: {self.tiny_seconds_per_audio_second:.4f}s/audio-s"
            )

    def set_calibration(self, tiny_seconds_per_audio_second: float) -> None:
        """Record a fresh calibration result (see CalibrationThread)."""
        self.tiny_seconds_per_audio_second = tiny_seconds_per_audio_second
        logger.debug(f"Calibration applied: {tiny_seconds_per_audio_second:.4f}s/audio-s")

    def _detect_gpu(self) -> bool:
        """Check if NVIDIA GPU is available."""
        try:
            result = subprocess.run(
                ["nvidia-smi", "--list-gpus"], capture_output=True, text=True, timeout=5
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
                timeout=5,
            )
            if result.returncode == 0:
                gpu_name = result.stdout.strip().split("\n")[0]
                logger.debug(f"GPU name retrieved: {gpu_name}")
                return gpu_name
            logger.warning("Failed to get GPU name from nvidia-smi")
            return "Unknown GPU"
        except Exception as e:
            logger.debug(f"Could not retrieve GPU name: {e}")
            return None

    def get_device_recommendation(self) -> Tuple[str, str]:
        """Recommend optimal device (CPU or GPU) based on available hardware.

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
        """Check if system can run given model size.
        Returns: (can_run, reason)
        """
        # Read from config.MODELS rather than a parallel table. A hardcoded
        # copy here would silently report the wrong requirement for any model
        # added later - and since recommend_model gates on this, an under-stated
        # requirement means recommending a model the machine cannot actually
        # load.
        required = _required_ram_gb(model_size)

        if self.ram_gb < required:
            return False, f"Insufficient RAM: {self.ram_gb:.1f}GB available, {required}GB required"

        return True, f"✓ System has enough RAM ({self.ram_gb:.1f}GB)"

    # Absolute wall-clock ceiling we're willing to let the recommended model
    # take, once a real audio duration + calibrated speed are known. Fixed
    # (not a multiplier of the audio's own length) so the recommendation
    # actually depends on file length: short files can afford the most
    # accurate model since it'll still finish quickly in absolute terms,
    # while long files get pushed toward faster models to stay under the
    # same ceiling.
    RECOMMENDED_TIME_BUDGET_SECONDS = 2 * 3600  # 2 hours

    def recommend_model(self, audio_duration_seconds: int = 0) -> Tuple[str, str]:
        """Recommend the highest-accuracy model this machine (and, once known,
        this specific file) can realistically handle.

        Walks models from highest to lowest accuracy_score and returns the
        first one that (a) fits in available RAM (can_run_model) and, once
        we have a real audio duration and a calibrated per-machine speed
        (see core.calibration), (b) is estimated to finish within
        RECOMMENDED_TIME_BUDGET_SECONDS. Device (GPU) is not considered -
        transcription always runs on CPU in this app (see
        TranscriptionThread).

        Before a file is picked or before calibration finishes, real timing
        can't be evaluated yet, so the choice falls back to RAM fit only.

        Returns: (model_size, reason)
        """
        have_real_timing = (
            audio_duration_seconds > 0 and self.tiny_seconds_per_audio_second is not None
        )

        ordered = sorted(
            config.MODELS.items(), key=lambda kv: kv[1]["accuracy_score"], reverse=True
        )

        for model_name, _ in ordered:
            can_run, _ = self.can_run_model(model_name)
            if not can_run:
                continue

            if have_real_timing:
                estimated_seconds, _ = self.estimate_transcription_time(
                    audio_duration_seconds, model_name
                )
                if estimated_seconds > self.RECOMMENDED_TIME_BUDGET_SECONDS:
                    continue
                budget_min = self.RECOMMENDED_TIME_BUDGET_SECONDS / 60
                return model_name, f"Highest accuracy estimated to finish within ~{budget_min:.0f}m"

            return (
                model_name,
                f"Highest accuracy this machine's RAM can support ({self.ram_gb:.1f}GB)",
            )

        # Nothing fit (e.g. not even enough RAM for 'tiny') - fall back to
        # the cheapest model anyway, since some result is better than none.
        return "tiny", "Minimum viable option for this hardware"

    def estimate_transcription_time(
        self,
        audio_duration_seconds: int,
        model_size: str,
        identify_speakers: bool = False,
    ) -> Tuple[int, str]:
        """Estimate transcription time based on audio duration, model, and hardware.

        Uses a real measured benchmark (self.tiny_seconds_per_audio_second,
        from speech_to_text.core.calibration) scaled to the requested model
        size by relative parameter count, rather than guessed constants.
        Transcription always runs on CPU in this app (see TranscriptionThread
        - device is hardcoded to "cpu"), so this does not factor in GPU speed
        even if a GPU is present.

        Args:
            audio_duration_seconds: Length of audio in seconds
            model_size: Model size (tiny, small, base, medium, large)

        Returns:
            (estimated_seconds, reason_string)

        """
        if self.tiny_seconds_per_audio_second is not None:
            relative_cost = RELATIVE_COMPUTE_COST.get(model_size, RELATIVE_COMPUTE_COST["medium"])
            seconds_per_audio_second = self.tiny_seconds_per_audio_second * relative_cost
            device_desc = f"{self.cpu_count} CPU cores"
        else:
            # Calibration hasn't finished yet (first run only - see
            # CalibrationThread). Use a conservative placeholder so the UI has
            # something to show; it's replaced automatically once the
            # background calibration completes.
            base_speed = config.SPEED_FACTORS.get(model_size, 1.0)
            cpu_factor = self.cpu_count / float(config.BASELINE_CPU_CORES)
            seconds_per_audio_second = 1.0 / (base_speed * cpu_factor)
            device_desc = f"{self.cpu_count} CPU cores (estimating…)"

        processing_time = audio_duration_seconds * seconds_per_audio_second

        if identify_speakers:
            # Diarization is a second full pass over the audio, independent of
            # the Whisper model. Measured at ~0.3x realtime on 4 cores; scaled
            # by core count on the same basis as the placeholder path above.
            cpu_factor = config.BASELINE_CPU_CORES / max(self.cpu_count, 1)
            processing_time += (
                audio_duration_seconds * config.DIARIZATION_REALTIME_FACTOR * cpu_factor
            )

        estimated_seconds = int(processing_time + config.TRANSCRIPTION_OVERHEAD_SECONDS)

        # Generate reason string
        audio_min = audio_duration_seconds / 60
        time_str = _format_duration(estimated_seconds, elide_zero=False)

        reason = f"Model: {model_size.title()} | Device: {device_desc} | Audio: {audio_min:.1f}m → ~{time_str}"

        logger.debug(f"Time estimation: {reason}")

        return estimated_seconds, reason

    def get_time_estimate_display(self, seconds: int) -> str:
        """Format seconds into human-readable time."""
        return _format_duration(seconds, elide_zero=True)
