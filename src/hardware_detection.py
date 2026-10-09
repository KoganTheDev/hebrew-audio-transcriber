"""Hardware Detection Module
Detects CPU/GPU specs and calculates estimated transcription time.
"""

import logging
import platform
import subprocess
from typing import cast

import config
from core.calibration import RELATIVE_COMPUTE_COST, load_cached_tiny_rtf

logger = logging.getLogger(__name__)

try:
    import psutil
except ImportError:
    logger.debug("psutil not available - using default hardware specs")
    psutil = None


def _format_duration(seconds: int) -> str:
    """Render a whole-second duration as "Xs" / "Xm Ys" / "Xh Ym" for
    estimate_transcription_time's log line. English on purpose: the log does
    not follow the UI language. What the user sees is i18n.format_duration.
    """
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins, secs = divmod(seconds, 60)
        return f"{mins}m {secs}s"
    else:
        hours, remainder = divmod(seconds, 3600)
        return f"{hours}h {remainder // 60}m"


def _required_ram_gb(model_size: str, default: int = 5) -> int:
    """A model's RAM requirement from config.MODELS ("3 GB" -> 3); unparseable
    means the mid-range default - a wrong estimate beats a crashed probe.
    """
    entry = config.MODELS.get(model_size)
    if not entry:
        return default
    digits = "".join(c for c in str(entry.get("ram_required", "")) if c.isdigit())
    return int(digits) if digits else default


class HardwareDetector:
    """Detects hardware specs and estimates processing time."""

    def __init__(self) -> None:
        logger.debug("Initializing HardwareDetector...")

        if psutil:
            self.cpu_count = psutil.cpu_count(logical=False)
            # Decimal GB (1000**3), not GiB (1024**3): RAM sticks, OS "About"
            # panels, and the model RAM requirements in config/models.py are
            # all specified in decimal GB, so a 64 GB machine should read
            # "64.8 GB" here, not the binary "60.4 GiB" mislabeled as GB.
            self.ram_gb = psutil.virtual_memory().total / (1000**3)
            logger.debug(f"Detected: {self.cpu_count} CPU cores, {self.ram_gb:.2f} GB RAM")
        else:
            self.cpu_count = 4  # Default
            self.ram_gb = 8  # Default
            logger.debug("Using default specs: 4 CPU cores, 8 GB RAM")

        self.has_gpu = self._detect_gpu()
        self.gpu_name = self._get_gpu_name()
        self.os_name = platform.system()

        # Measured tiny-model seconds per audio second (core.calibration), or
        # None until calibrated. Cached per device and core count.
        self.tiny_seconds_per_audio_second: float | None = load_cached_tiny_rtf(
            self.cpu_count, self.get_device_recommendation()[0]
        )

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

    def _get_gpu_name(self) -> str | None:
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

    def get_device_recommendation(self) -> tuple[str, str]:
        """("cuda" | "cpu", reason): an NVIDIA GPU if present, else the CPU."""
        if self.has_gpu and self.gpu_name and "NVIDIA" in self.gpu_name:
            return ("cuda", f"NVIDIA GPU detected: {self.gpu_name}")
        return ("cpu", f"Using CPU ({self.cpu_count} cores, {self.ram_gb:.1f}GB RAM)")

    def get_hardware_info(self) -> dict:
        """Get formatted hardware information."""
        return {
            "cpu_cores": self.cpu_count,
            "ram_gb": f"{self.ram_gb:.1f}",
            "has_gpu": self.has_gpu,
            "gpu_name": self.gpu_name or "No NVIDIA GPU",
            "os": self.os_name,
        }

    def can_run_model(self, model_size: str) -> tuple[bool, str]:
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

    # A fixed ceiling, not a multiple of the audio length, so long files are
    # pushed toward faster models while short ones get the most accurate.
    RECOMMENDED_TIME_BUDGET_SECONDS = 2 * 3600  # 2 hours

    def recommend_model(self, audio_duration_seconds: int = 0) -> tuple[str, str]:
        """The most accurate model that fits in RAM and, once a duration and a
        calibrated speed are known, finishes within RECOMMENDED_TIME_BUDGET_SECONDS.
        Returns (model_size, reason).
        """
        have_real_timing = (
            audio_duration_seconds > 0 and self.tiny_seconds_per_audio_second is not None
        )

        ordered = sorted(
            config.MODELS.items(),
            # cast, not float(): config.MODELS is typed dict[str, dict[str, object]],
            # so the score reads as object and is not comparable. This is a typing
            # assertion with no runtime effect, rather than a conversion.
            key=lambda kv: cast(float, kv[1]["accuracy_score"]),
            reverse=True,
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

        # Nothing fit (less RAM than even Ivrit Turbo asks for) - fall back to
        # the default anyway, since some result is better than none. It must
        # be a config.MODELS key: the model step looks the recommendation up
        # among its cards, and a model with no card there raises KeyError.
        return config.DEFAULT_MODEL, "Below the recommended RAM for any model"

    def estimate_transcription_time(
        self,
        audio_duration_seconds: int,
        model_size: str,
        identify_speakers: bool = False,
    ) -> tuple[int, str]:
        """(seconds, reason) for a file: the calibrated benchmark scaled by the
        model's relative cost. model_size is a config.MODELS key or a raw
        Whisper size.
        """
        if self.tiny_seconds_per_audio_second is not None:
            # Unknown models are costed as the slowest card, so an estimate
            # errs long rather than promising a time it can't meet.
            relative_cost = RELATIVE_COMPUTE_COST.get(
                model_size, RELATIVE_COMPUTE_COST["ivrit-large"]
            )
            seconds_per_audio_second = self.tiny_seconds_per_audio_second * relative_cost
            device_desc = (
                f"GPU ({self.gpu_name})"
                if self.get_device_recommendation()[0] == "cuda"
                else f"{self.cpu_count} CPU cores"
            )
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
        time_str = _format_duration(estimated_seconds)

        reason = f"Model: {model_size.title()} | Device: {device_desc} | Audio: {audio_min:.1f}m → ~{time_str}"

        logger.debug(f"Time estimation: {reason}")

        return estimated_seconds, reason
