"""
Speech-to-Text Application - Configuration Module
Centralized configuration for the application.
"""

import os

# ============================================================================
# Model Configuration with detailed pros/cons
# ============================================================================
#
# The dict key is this app's identifier for a model (used by the GUI cards,
# i18n.MODEL_STRINGS, RELATIVE_COMPUTE_COST and the settings we persist).
# "repo" is what actually gets handed to faster-whisper's WhisperModel - either
# a bare Whisper size or a HuggingFace repo id holding CTranslate2 weights.
#
# Those were the same string until Hebrew-specific models were added, which
# forced them apart: "ivrit-turbo" is a stable local identifier, while
# "ivrit-ai/whisper-large-v3-turbo-ct2" is an upstream address that can change.
#
# Entries are ordered by ascending accuracy_score - the GUI renders the cards in
# this order, and tests assert the ordering holds.

MODELS = {
    "tiny": {
        "repo": "tiny",
        "name": "Tiny",
        "description": "Ultra-fast, lowest quality",
        "pros": [
            "✓ Fastest option (~30 min for 60-min audio)",
            "✓ Minimal RAM (1 GB)",
            "✓ Good for: Quick rough drafts, testing",
        ],
        "cons": [
            "✗ Lowest accuracy",
            "✗ Many errors and misheard words",
            "✗ Poor Hebrew support",
        ],
        "time_estimate": "~30 minutes",
        "ram_required": "1 GB",
        "accuracy_score": 2,
        "best_for": "Quick testing only",
        "recommended": False,
    },
    "base": {
        "repo": "base",
        "name": "Base",
        "description": "Good balance of speed and quality",
        "pros": [
            "✓ Reasonable speed (3-5 hours)",
            "✓ Moderate RAM (2 GB)",
            "✓ Better than tiny, acceptable for casual use",
        ],
        "cons": [
            "✗ Moderate accuracy (some errors)",
            "✗ Not ideal for Hebrew",
            "✗ Professional users may notice mistakes",
        ],
        "time_estimate": "~3-5 hours",
        "ram_required": "2 GB",
        "accuracy_score": 3,
        "best_for": "Casual transcription",
        "recommended": False,
    },
    "small": {
        "repo": "small",
        "name": "Small",
        "description": "Better accuracy for Hebrew",
        "pros": [
            "✓ Good accuracy for Hebrew",
            "✓ Reasonable time (8-10 hours)",
            "✓ 3 GB RAM, manageable",
        ],
        "cons": [
            "✗ Slower than base",
            "✗ Still not perfect accuracy",
            "✗ Not recommended for critical content",
        ],
        "time_estimate": "~8-10 hours",
        "ram_required": "3 GB",
        "accuracy_score": 3.5,
        "best_for": "Good quality transcription",
        "recommended": False,
    },
    "medium": {
        "repo": "medium",
        "name": "Medium",
        "description": "High accuracy general-purpose model",
        "pros": [
            "✓ Good accuracy across languages",
            "✓ Professional quality results",
            "✓ Good balance of quality/time",
        ],
        "cons": [
            "✗ Longer processing (~20-24 hours)",
            "✗ Requires 5 GB RAM",
            "✗ Slower and less accurate on Hebrew than Ivrit Turbo",
        ],
        "time_estimate": "~20-24 hours",
        "ram_required": "5 GB",
        "accuracy_score": 4,
        "best_for": "General-purpose transcription",
        "recommended": False,
    },
    "large": {
        # Pinned explicitly. "large" is an alias whose target has moved between
        # faster-whisper releases, so the bare name silently changed which model
        # actually ran depending on the installed version.
        "repo": "large-v3",
        "name": "Large",
        "description": "Best general-purpose model, very slow",
        "pros": [
            "✓ Highest accuracy of the general-purpose models",
            "✓ Handles mixed-language audio well",
            "✓ Fewest errors outside Hebrew",
        ],
        "cons": [
            "✗ Very slow (40+ hours)",
            "✗ High RAM requirement (8 GB)",
            "✗ May run out of memory on limited systems",
            "✗ Still trained mostly on non-Hebrew speech",
        ],
        "time_estimate": "~40+ hours",
        "ram_required": "8 GB",
        "accuracy_score": 4.5,
        "best_for": "Mixed-language or non-Hebrew content",
        "recommended": False,
    },
    # ------------------------------------------------------------------
    # Hebrew-specialised models (ivrit.ai).
    #
    # Everything above is stock OpenAI Whisper, trained overwhelmingly on
    # English; Hebrew is a small slice of its training data, which is the root
    # cause of the misheard-word problem this app exists to solve. ivrit.ai
    # fine-tunes Whisper on hundreds of hours of transcribed Hebrew speech and
    # publishes the result already converted to CTranslate2 - the exact format
    # faster-whisper loads - so using them costs nothing but the download.
    # ------------------------------------------------------------------
    "ivrit-turbo": {
        "repo": "ivrit-ai/whisper-large-v3-turbo-ct2",
        "name": "Ivrit Turbo",
        "description": "Hebrew-tuned, fast and accurate (recommended)",
        "pros": [
            "✓ Trained specifically on Hebrew speech",
            "✓ Far fewer misheard Hebrew words than any model above",
            "✓ Turbo decoder: faster than Medium despite being larger",
            "✓ Best choice for Hebrew content",
        ],
        "cons": [
            "✗ One-time 1.6 GB download on first use",
            "✗ Requires 3 GB RAM",
            "✗ Hebrew only - weaker on other languages than Large",
        ],
        "time_estimate": "~8-12 hours",
        "ram_required": "3 GB",
        "accuracy_score": 5,
        "best_for": "Hebrew transcription (RECOMMENDED)",
        "recommended": True,
    },
    "ivrit-large": {
        "repo": "ivrit-ai/whisper-large-v3-ct2",
        "name": "Ivrit Large",
        "description": "Hebrew-tuned, highest accuracy, slow",
        "pros": [
            "✓ Most accurate Hebrew option available",
            "✓ Best for critical or hard-to-hear recordings",
        ],
        "cons": [
            "✗ One-time 3.1 GB download on first use",
            "✗ Very slow (40+ hours)",
            "✗ High RAM requirement (8 GB)",
            "✗ Rarely worth it over Ivrit Turbo",
        ],
        "time_estimate": "~40+ hours",
        "ram_required": "8 GB",
        "accuracy_score": 5.5,
        "best_for": "Critical Hebrew content",
        "recommended": False,
    },
}

# Default model. Hebrew-tuned, and its turbo decoder makes it faster than the
# "medium" it replaced as well as considerably more accurate on Hebrew.
DEFAULT_MODEL = "ivrit-turbo"

# ============================================================================
# Application Configuration
# ============================================================================

APP_NAME = "Hebrew Audio Transcriber"
APP_VERSION = "2.0.0"
APP_ID = "speechtotext.transcriber.2"  # Windows AppUserModelID, for correct taskbar icon grouping
WINDOW_WIDTH = 950
WINDOW_HEIGHT = 800

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.ico")

# ============================================================================
# Transcription Settings
# ============================================================================

LANGUAGE = "he"  # Hebrew
BEAM_SIZE = 5
COMPUTE_TYPE = "int8"
VAD_FILTER = True
FORMAT_OUTPUT = True
SENTENCE_ENDINGS = r"[.!?]"

# ============================================================================
# File Configuration
# ============================================================================

SUPPORTED_FORMATS = ("*.mp3", "*.wav", "*.m4a", "*.flac", "*.ogg", "*.mp4", "*.mkv")
OUTPUT_FILENAME = "transcription.txt"
CHECKPOINT_FILENAME = "transcription_checkpoint.txt"

# ============================================================================
# Dependencies
# ============================================================================

REQUIRED_PACKAGES = {
    "PyQt5": "PyQt5",
    "tqdm": "tqdm",
}

# ============================================================================
# GUI Configuration - Window Dimensions
# ============================================================================
# Window sizing optimized for 1080p displays. Centered on screen.
# Minimal size ensures content is not cramped on smaller displays.

GUI_WINDOW_WIDTH = 650          # Main window width (px)
GUI_WINDOW_HEIGHT = 600         # Main window height (px)
GUI_WINDOW_MIN_WIDTH = 600      # Minimum resizable width (px)
GUI_WINDOW_MIN_HEIGHT = 550     # Minimum resizable height (px)

# ============================================================================
# GUI Configuration - Drag-Drop Zone
# ============================================================================
# File selection zone styling and spacing

GUI_DROP_ZONE_HEIGHT = 210      # Drop zone height (px) — shrunk to make room for the system info table above it
GUI_DROP_ZONE_PADDING = 20      # Internal padding in drop zone (px) — reduced to fit the shorter zone
GUI_DROP_ZONE_SPACING = 10      # Space between elements inside drop zone (px) — reduced to fit the shorter zone

# ============================================================================
# Hardware Detection Configuration
# ============================================================================
# Transcription time estimation factors and hardware thresholds

# Placeholder speed factors, used only until the real per-machine
# calibration benchmark (speech_to_text.core.calibration) finishes on first
# run — see HardwareDetector.estimate_transcription_time. Not used once a
# real measurement is available.
SPEED_FACTORS = {
    "tiny": 2.5,      # 2.5x real-time (10 min audio = ~4 min processing)
    "small": 1.8,     # 1.8x real-time
    "base": 1.0,      # 1x real-time (baseline)
    "medium": 0.65,   # 0.65x real-time (slower than real-time)
    "large": 0.35,    # 0.35x real-time (very slow)
}

# CPU baseline for normalization
# Used to scale time estimates across different CPU core counts
BASELINE_CPU_CORES = 4          # Normalize timing estimates to 4-core baseline

# Audio duration estimation when file info not available
# Fallback formula: file_size_mb * 60 * AUDIO_MINUTES_PER_100MB = estimated_seconds
AUDIO_MINUTES_PER_100MB = 12.5  # Approx 12.5 minutes of audio per 100MB

# Model loading overhead (time before transcription begins)
TRANSCRIPTION_OVERHEAD_SECONDS = 20

# Speaker identification is a second full pass over the audio, on top of
# transcription. Measured at ~0.29x realtime on a 4-core CPU with the
# sherpa-onnx pyannote + campplus models, and scaled by core count where used.
# It is not derived from the Whisper calibration benchmark: different models,
# different compute profile.
DIARIZATION_REALTIME_FACTOR = 0.3

# ============================================================================
# Dependency Installation Configuration
# ============================================================================
# Timeout for package installation to prevent hanging

INSTALL_TIMEOUT_SECONDS = 120   # 2 minutes per package installation
