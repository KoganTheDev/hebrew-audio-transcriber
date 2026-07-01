"""
Speech-to-Text Application - Configuration Module
Centralized configuration for the application.
"""

import os

# ============================================================================
# Model Configuration with detailed pros/cons
# ============================================================================

MODELS = {
    "tiny": {
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
        "name": "Medium",
        "description": "High accuracy, recommended default",
        "pros": [
            "✓ High accuracy for Hebrew (recommended!)",
            "✓ Professional quality results",
            "✓ Good balance of quality/time",
            "✓ Best choice for most users",
        ],
        "cons": [
            "✗ Longer processing (~20-24 hours)",
            "✗ Requires 5 GB RAM",
            "✗ Not for immediate results",
        ],
        "time_estimate": "~20-24 hours",
        "ram_required": "5 GB",
        "accuracy_score": 4,
        "best_for": "Professional quality (RECOMMENDED)",
        "recommended": True,
    },
    "large": {
        "name": "Large",
        "description": "Highest accuracy, very slow",
        "pros": [
            "✓ Highest accuracy possible",
            "✓ Best for critical/important content",
            "✓ Excellent Hebrew support",
            "✓ Fewest errors",
        ],
        "cons": [
            "✗ Very slow (40+ hours)",
            "✗ High RAM requirement (8 GB)",
            "✗ May run out of memory on limited systems",
            "✗ Not practical for most users",
        ],
        "time_estimate": "~40+ hours",
        "ram_required": "8 GB",
        "accuracy_score": 5,
        "best_for": "Highest quality, critical content",
        "recommended": False,
    },
}

# Default model (smart choice)
DEFAULT_MODEL = "medium"

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

# ============================================================================
# Dependency Installation Configuration
# ============================================================================
# Timeout for package installation to prevent hanging

INSTALL_TIMEOUT_SECONDS = 120   # 2 minutes per package installation
