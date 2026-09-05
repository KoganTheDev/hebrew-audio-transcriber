"""Transcription decoding settings and the speed / time-estimate constants."""

LANGUAGE = "he"  # Hebrew
BEAM_SIZE = 5
COMPUTE_TYPE = "int8"  # CPU default - see compute_type_for_device() below
VAD_FILTER = True
FORMAT_OUTPUT = True
SENTENCE_ENDINGS = r"[.!?]"


# ctranslate2's get_supported_compute_types("cpu") on this development
# machine (no NVIDIA GPU, Intel Iris Xe only) is {int8, int8_float32, int16,
# float32} - float16 is not in that set on CPU, only on CUDA. A single global
# compute type would load CUDA in int8 too: correct, but throwing away the
# accuracy a GPU can afford at no speed cost, since float16 is CUDA's native
# throughput type. This has not been measured on a GPU (this machine has none
# - see Transcriber.load_model()'s docstring); "float16 on CUDA" here reflects
# ctranslate2's own documented recommendation, not a benchmark run here.
def compute_type_for_device(device: str) -> str:
    """The right ctranslate2 compute_type for a given faster-whisper device."""
    return "float16" if device == "cuda" else COMPUTE_TYPE


# Placeholder speed factors, used only until the real per-machine
# calibration benchmark (speech_to_text.core.calibration) finishes on first
# run - see HardwareDetector.estimate_transcription_time. Not used once a
# real measurement is available.
SPEED_FACTORS = {
    "tiny": 2.5,  # 2.5x real-time (10 min audio = ~4 min processing)
    "small": 1.8,  # 1.8x real-time
    "base": 1.0,  # 1x real-time (baseline)
    "medium": 0.65,  # 0.65x real-time (slower than real-time)
    "large": 0.35,  # 0.35x real-time (very slow)
}

# Used to scale time estimates across different CPU core counts.
BASELINE_CPU_CORES = 4

# Audio duration estimate when file info is not available:
# file_size_mb * 60 * AUDIO_MINUTES_PER_100MB = estimated_seconds
AUDIO_MINUTES_PER_100MB = 12.5

# Model loading, i.e. the time before transcription itself begins.
TRANSCRIPTION_OVERHEAD_SECONDS = 20
