"""Transcription decoding settings and the speed / time-estimate constants."""

LANGUAGE = "he"  # Hebrew
BEAM_SIZE = 5
COMPUTE_TYPE = "int8"  # CPU default - see compute_type_for_device() below
VAD_FILTER = True
FORMAT_OUTPUT = True
SENTENCE_ENDINGS = r"[.!?]"


# float16 is CUDA-only in ctranslate2 (not offered on CPU), and CUDA's native
# throughput type - ctranslate2's documented recommendation, not measured
# here (no GPU on the development machine).
def compute_type_for_device(device: str) -> str:
    """The right ctranslate2 compute_type for a given faster-whisper device."""
    return "float16" if device == "cuda" else COMPUTE_TYPE


# Placeholders until the first-run calibration benchmark (core.calibration)
# lands; a missing key falls back to 1.0.
SPEED_FACTORS = {
    "ivrit-large": 0.35,  # x real-time
    # Same ~5.5x turbo speedup core.calibration.RELATIVE_COMPUTE_COST uses.
    "ivrit-turbo": 0.35 * 5.5,
}

# Used to scale time estimates across different CPU core counts.
BASELINE_CPU_CORES = 4

# Audio duration estimate when file info is not available:
# file_size_mb * 60 * AUDIO_MINUTES_PER_100MB = estimated_seconds
AUDIO_MINUTES_PER_100MB = 12.5

# Model loading, i.e. the time before transcription itself begins.
TRANSCRIPTION_OVERHEAD_SECONDS = 20
