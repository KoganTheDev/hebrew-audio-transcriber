"""
Speech-to-Text Application - Configuration Module
Centralized configuration for the application.
"""

import os
from typing import List

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
#
# "download_size" is the one-time HuggingFace download for a model faster-
# whisper hasn't cached locally yet (figures from this repo's own README
# table). It exists ONLY as this static, structured number - there is no
# download PROGRESS signal anywhere in this app. core/transcriber.py's
# load_model() emits "w_loading_model" once and then calls WhisperModel(...)
# directly; that call downloads internally (via huggingface_hub) with no
# callback wired back through progress_callback, so the GUI has nothing to
# show while a multi-GB download is actually in flight - "Loading model..."
# covers both "downloading it for the first time" and "reading it off disk",
# indistinguishably. Faking a percentage here would be worse than saying
# nothing: a bar that doesn't move with the real download is a second,
# actively misleading kind of silence. gui/steps/model_select.py uses this
# field to warn about the download BEFORE the model is picked, which is the
# one place in the download's lifecycle this app can currently be honest.
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
        "download_size": "76 MB",
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
        "download_size": "145 MB",
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
        "download_size": "484 MB",
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
        "download_size": "1.5 GB",
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
        "download_size": "3.1 GB",
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
        "download_size": "1.6 GB",
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
        "download_size": "3.1 GB",
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
# Model Download Location
# ============================================================================
#
# WhisperModel's download_root controls both where faster-whisper looks for
# an already-cached model AND where it writes a new download. This used to
# be the literal "./whisper_models" passed straight into the WhisperModel(...)
# call in core/transcriber.py - relative to the process's CURRENT WORKING
# DIRECTORY, not to this package or the repo. That was invisible for as long
# as the app was only ever launched from the repo root, but pyproject.toml
# installs a `speech-to-text` console script (see [project.scripts]) that can
# be run from anywhere, and a relative download_root resolves against
# wherever the process happened to start - so a launch from a different
# working directory couldn't find the existing cache and silently
# re-downloaded the whole thing from scratch. There is no download-progress
# signal anywhere in this app (see MODELS' "download_size" comment above), so
# the only symptom was "Loading model..." taking twenty unexplained minutes -
# and on this machine that re-download is 5.9 GB.
#
# gui/steps/model_select.py used to hand-mirror the same literal in
# _WHISPER_DOWNLOAD_ROOT (with a comment admitting there was no shared
# constant to import instead) just to decide whether a model card should
# warn about a pending download. Two independent copies of the same path
# meant they could only be changed in lockstep by hand, and a mismatch would
# make the card's download note lie about what the downloader will actually
# do. MODEL_DOWNLOAD_ROOT is that shared constant - both call sites read it.
#
# Resolved once, at import time, to an ABSOLUTE path - so the value cannot
# change with the working directory - in this order:
#
#   1. SPEECH_TO_TEXT_MODEL_DIR, if set. An explicit escape hatch for anyone
#      who wants models on a different drive (they run multiple GB each).
#   2. An existing "whisper_models" directory already sitting next to this
#      package (one level up from speech_to_text/ - the repo root in a
#      source checkout, or the directory the package was installed beside).
#      Checked before the per-user fallback below, on purpose: this is the
#      branch that finds the 5.9 GB already on disk, and it has to win over
#      inventing a new, empty location that would look - from
#      gui/steps/model_select.py's _model_is_downloaded's point of view -
#      exactly like nothing had ever been downloaded.
#   3. Otherwise, a per-user data directory: %LOCALAPPDATA% on Windows, or
#      $XDG_DATA_HOME / ~/.local/share elsewhere. A fresh install still needs
#      somewhere sensible to put models rather than writing into whatever
#      directory the process happened to start in.
#
# core/ must never import PyQt5 (see core/__init__.py's module docstring for
# why - faster-whisper/ctranslate2 and PyQt5 bundle conflicting DLLs on
# Windows), which rules out QStandardPaths for step 3 even though
# gui/theme.py's glyph cache uses exactly that API for the same kind of
# per-user-directory question. This has to stay plain os / os.path so
# core/transcriber.py can import it too.
def _default_model_download_root() -> str:
    """Where to put models when SPEECH_TO_TEXT_MODEL_DIR isn't set - see above."""
    package_dir = os.path.dirname(os.path.abspath(__file__))
    beside_package = os.path.join(os.path.dirname(package_dir), "whisper_models")
    if os.path.isdir(beside_package):
        return beside_package

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "speech-to-text", "whisper_models")


def resolve_model_download_root() -> str:
    """
    Compute MODEL_DOWNLOAD_ROOT's value. A function, not just a module-level
    expression, so tests can re-run the resolution under monkeypatched
    environment variables / cwd without reimporting the module.
    """
    override = os.environ.get("SPEECH_TO_TEXT_MODEL_DIR")
    root = override if override else _default_model_download_root()
    # abspath, not just relying on the pieces above already being absolute:
    # a user-supplied SPEECH_TO_TEXT_MODEL_DIR could itself be relative, and
    # this is the one place that guarantee has to hold no matter the input.
    root = os.path.abspath(root)
    os.makedirs(root, exist_ok=True)
    return root


MODEL_DOWNLOAD_ROOT = resolve_model_download_root()

# ============================================================================
# Transcription Settings
# ============================================================================

LANGUAGE = "he"  # Hebrew
BEAM_SIZE = 5
COMPUTE_TYPE = "int8"  # CPU default - see compute_type_for_device() below
VAD_FILTER = True
FORMAT_OUTPUT = True
SENTENCE_ENDINGS = r"[.!?]"

# ctranslate2's get_supported_compute_types("cpu") on this development
# machine (no NVIDIA GPU, Intel Iris Xe only) is {int8, int8_float32, int16,
# float32} - float16 is not in that set on CPU, only on CUDA. COMPUTE_TYPE
# used to be a single global regardless of device, which meant a CUDA run
# would still load in int8 - correct, but throwing away the accuracy a GPU
# can afford at no speed cost, since float16 is CUDA's native throughput
# type. This has not been measured on a GPU (this machine has none - see
# Transcriber.load_model()'s docstring); "float16 on CUDA" here reflects
# ctranslate2's own documented recommendation, not a benchmark run here.
def compute_type_for_device(device: str) -> str:
    """The right ctranslate2 compute_type for a given faster-whisper device."""
    return "float16" if device == "cuda" else COMPUTE_TYPE

# ============================================================================
# File Configuration
# ============================================================================

SUPPORTED_FORMATS = ("*.mp3", "*.wav", "*.m4a", "*.flac", "*.ogg", "*.mp4", "*.mkv")

# HTML replaced .txt as the output format entirely (see core/formatting's
# module docstring for why: only a declared, not guessed, paragraph
# direction gets Hebrew to align correctly). One input file is named after
# itself; a batch is named after the folder it came from, since there is no
# single source filename to hang the output name on. See output_path_for().
OUTPUT_FILENAME_TEMPLATE = "{stem}_transcription.html"


def output_path_for(audio_files: List[str]) -> str:
    """
    Decide the output path for a transcription run.

    One file -> named after it (so two different recordings never collide).
    Several files -> named after their shared folder. Always written beside
    the first input file, so the output lands next to the audio regardless
    of which directory the app itself runs from.

    This only overwrites a previous run over the *same* input(s) - re-running
    a batch from the same folder replaces its own output, which is no worse
    than the old fixed transcription.txt and strictly better everywhere else.
    """
    first_dir = os.path.dirname(audio_files[0])
    if len(audio_files) == 1:
        # splitext splits on the LAST dot, so "a.b.wav" -> stem "a.b" - a
        # filename with a dot in it doesn't lose part of its name.
        stem, _ext = os.path.splitext(os.path.basename(audio_files[0]))
    else:
        stem = os.path.basename(os.path.normpath(first_dir)) or "batch"

    filename = OUTPUT_FILENAME_TEMPLATE.format(stem=stem)
    return os.path.join(first_dir, filename)


# User-maintained list of domain terms (names, places, jargon) that a general
# model reliably mishears. One term per line, UTF-8, "#" for comments. Looked
# for in the working directory; absent means the correction pass does nothing,
# which is the intended default - see core/hebrew_correct.py.
TERMS_FILENAME = "hebrew_terms.txt"
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
#
# The window used to be setFixedSize'd at 650x600, with the maximize hint
# stripped - no resize logic anywhere had to cope with a size other than
# exactly this one. That hid a real shortfall rather than avoiding it:
# measured with minsize.py, the chrome (header 50 + step indicator 20 + nav
# bar 83) is 153px, and the worst step - transcription, once show_result()
# has populated the completion panel - needs 475px on its own. 153 + 475 =
# 628px, 28px more than the 600px the fixed window ever gave it, which is
# exactly the "result panel clipped on completion" bug. Step 1 fares only
# slightly better (440 + 153 = 593px, 7px of slack) - both are the same
# underlying problem, a window too short for its own content, not two
# separate bugs.
#
# GUI_WINDOW_MIN_HEIGHT is the floor this drives: it has to sit at or above
# 628px or the same clipping comes back the moment the window is resized
# down to it. 550 (the old, never-enforced value - the window was fixed-size
# so nothing ever read it) is below that floor and would be a lie. 640 gives
# a small, deliberate margin above the measured 628px minimum rather than
# pinning the floor exactly on it, so the completion panel doesn't start
# touching the window edge the instant someone drags to the smallest allowed
# size.
#
# GUI_WINDOW_HEIGHT (the default, initial size) stays clearly above the
# minimum rather than sitting on it, for the same reason step 3's own
# comments give for widening its margins: a size that exactly matches the
# content floor reads as cramped even when nothing is technically clipped.
# 720 leaves the completion panel - the tallest state of any step - about
# 90px of breathing room by default, while remaining well short of forcing
# a scroll on a 1080p display.
#
# GUI_WINDOW_MIN_WIDTH is unchanged at 600: the model card caption (the
# tightest element width-wise) has 57px of slack at 600px and only starts
# clipping below roughly 545px, so 600 was already a safe floor and this
# step's overflow was purely a height problem.
#
# Deliberately NOT addressed here: the app never calls
# AA_EnableHighDpiScaling / AA_UseHighDpiPixmaps or sets a high-DPI rounding
# policy, so it is DPI-unaware and Windows bitmap-scales the whole window at
# 125%/150% instead of Qt resolving fonts and layouts at the real DPI. That
# is precisely why fixed pixel budgets like the ones above have held up
# this long, and why every number measured for this step was measured
# against that same unaware rendering path. Turning high-DPI scaling on
# would make every font metric resolve differently (generally larger) and
# re-tighten every budget this revamp just balanced - a real quality
# improvement (sharper text, correct scaling on high-DPI displays) but a
# separate change that needs its own re-measurement pass across all three
# steps, not something to fold into a resize fix with no time left to
# re-verify.

GUI_WINDOW_WIDTH = 650          # Main window default width (px)
GUI_WINDOW_HEIGHT = 720         # Main window default height (px) - see note above
GUI_WINDOW_MIN_WIDTH = 600      # Minimum resizable width (px)
GUI_WINDOW_MIN_HEIGHT = 640     # Minimum resizable height (px) - measured content floor is 628px

# ============================================================================
# GUI Configuration - Drag-Drop Zone
# ============================================================================
# File selection zone styling and spacing

GUI_DROP_ZONE_HEIGHT = 170      # Drop zone MINIMUM height (px). Its own content (icon +
                                # three lines) floors at ~172px, so a larger value here is a
                                # floor the layout cannot compress below, not a target it can
                                # give back - which is what overflowed the fixed window. The
                                # zone grows well past this via its layout stretch factor
                                # whenever the step has slack; see file_select.py.
GUI_DROP_ZONE_PADDING = 20      # Internal padding in drop zone (px) - reduced to fit the shorter zone
GUI_DROP_ZONE_SPACING = 10      # Space between elements inside drop zone (px) - reduced to fit the shorter zone

# ============================================================================
# Hardware Detection Configuration
# ============================================================================
# Transcription time estimation factors and hardware thresholds

# Placeholder speed factors, used only until the real per-machine
# calibration benchmark (speech_to_text.core.calibration) finishes on first
# run - see HardwareDetector.estimate_transcription_time. Not used once a
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

# sherpa-onnx's OfflineSpeakerDiarizationConfig accepts these two knobs but
# they were never passed, so the library's own defaults applied silently.
# Named here so the app states its diarization behaviour explicitly instead
# of inheriting whatever sherpa-onnx happens to default to next release.
# Kept equal to those defaults for now - this change is about visibility, not
# behaviour; see core/diarization.py:diarize for how they are wired in.
#
# min_duration_on drops any speaker span shorter than this many seconds. It
# is one source of the "no overlap at all" fallback in assign_speakers: a
# genuine but very short utterance can fall entirely below this floor and
# vanish from the span list before word-level attribution ever sees it.
DIARIZATION_MIN_DURATION_ON = 0.3
# min_duration_off is the minimum silence gap required to end a speaker span.
# Shorter gaps are bridged rather than treated as a speaker change.
DIARIZATION_MIN_DURATION_OFF = 0.5

# onnxruntime thread count for both diarization models. Left unset until now,
# so onnxruntime's own default applied - and the default is not the best
# choice here.
#
# Deliberately a small constant rather than os.cpu_count(): the segmentation
# model is run one 10s window at a time, and un-batched inference does not
# scale with threads, it degrades. Measured on this 8-core machine, per
# window: 2 threads 79.5ms, 4 threads 196.3ms, 8 threads 300.5ms. The win
# comes from batching (4 threads at batch 16: 46.9ms/window), not from
# handing onnxruntime every core it can see. 4 is the compromise that helps
# the embedding extractor - which IS given long inputs and does scale - while
# staying well clear of the oversubscription cliff: measured end to end on
# 300s of AMI, diarization went 124.4s -> 96.6s with identical DER.
#
# min() so a 2-core machine is not told to use 4.
DIARIZATION_NUM_THREADS = min(4, os.cpu_count() or 1)

# onnxruntime execution provider. "cpu" is stated rather than left implicit
# because the installed onnxruntime here reports only Azure and CPU providers
# - there is no CUDA provider to fall back from, and naming it keeps a future
# GPU build from silently changing which device diarization runs on.
DIARIZATION_PROVIDER = "cpu"

# --- word-level attribution (core/diarization.py:assign_speakers) ----------
#
# These three govern how a per-word speaker vote is smoothed before it is
# allowed to cut a transcript segment in two. All of them used to be either
# hardcoded or implicit, and all three biased the same direction - toward
# whoever was speaking EARLIER - which is what made one speaker appear to
# absorb the other's turns.

# A run of words attributed to one speaker has to be at least this long
# before assign_speakers will cut the segment there. A single stray word
# voting for the other speaker is more often a boundary-rounding error in the
# diarizer than a real one-word turn.
DIARIZATION_MIN_SPEAKER_RUN_WORDS = 2

# A word that overlaps no span at all borrows a label from its nearest
# labelled neighbour in time - but only across a gap this short. Beyond it
# the word keeps no label. Filling across a long silence is precisely the
# mechanism that lets one speaker's label run on over the other's turn, and
# an unattributed word renders without a speaker rather than under the wrong
# one, which is the honest failure.
DIARIZATION_MAX_FILL_GAP_SECONDS = 1.5

# A one-word run normally cannot split a segment (see the run-length floor
# above), which erases genuine short interjections - "כן", "לא", "נכון" -
# by folding them into whoever spoke before. It survives as its own run when
# it is at least this long AND the other speaker's span covers essentially
# all of it (see DIARIZATION_INTERJECTION_MIN_COVERAGE), i.e. when the
# diarizer is not merely clipping a boundary but positively asserting a
# different speaker for the whole word.
DIARIZATION_INTERJECTION_MIN_SECONDS = 0.35
DIARIZATION_INTERJECTION_MIN_COVERAGE = 0.8

# --- which diarization pipeline runs (core/diarization.py:diarize) --------
#
# "sherpa"   - sherpa-onnx's OfflineSpeakerDiarization, start to finish.
# "powerset" - our own decode of the same segmentation model
#              (core/segmentation.py), with sherpa's embedding extractor and
#              clustering underneath (core/diarization_powerset.py).
#
# The reason for owning the middle of the pipeline is that sherpa's decode is
# a fixed operating point - an argmax over the 7 powerset classes - and every
# knob it exposes was measured against the AMI reference without moving the
# dominant error. Speaker confusion sat at ~46.5s of 155.4s of reference
# speech across num_clusters=4, count inference at two thresholds, and
# min_duration disabled; and asking for 4 speakers returned 3, i.e. two
# reference speakers merged into one cluster. Thresholding the per-speaker
# marginal instead recovered speech immediately: 143.4s -> 150.5s against a
# 149.9s reference, at onset 0.40.
#
# MEASURED both ways, and the default stays "sherpa" because the result is
# split rather than one-sided.
#
# On AMI ES2004a, first 300s, asking for the 3 speakers that excerpt actually
# contains, "powerset" is clearly better - and note sherpa MERGES two of them:
#
#     sherpa    83s   2 of 3 speakers   DER 0.4700  conf 47.93
#     powerset 119s   3 of 3 speakers   DER 0.4011  conf 34.29
#
# On mp3_test/tesr1.wav, first 300s, a balanced two-person Hebrew
# conversation - the audio this app is actually for - it goes the other way
# on the thing that matters most here:
#
#     sherpa   118s  46 spans  median span 2.06s  overlap 46.9s  66/34 split
#     powerset 151s  28 spans  median span 5.08s  overlap 34.2s  65/35 split
#
# Fewer, longer spans and less detected overlap is the WRONG direction for a
# conversation full of short interjections, which is the complaint this work
# started from. So "powerset" is opt-in until someone measures it against
# Hebrew audio with real speaker labels - which does not exist yet, and is
# the single thing that would most improve confidence here.
#
# One constant reverts everything, which is why it is a constant and not a
# rewrite.
DIARIZATION_ENGINE = "sherpa"

# Marginal probability above which a local speaker counts as talking, for the
# "powerset" engine only. 0.40 rather than the 0.50 that argmax implies:
# measured on 300s of AMI, 0.50 finds 143.4s of the 149.9s of reference
# speech and 0.40 finds 150.5s - essentially exact - at 0.934 recall and
# 0.930 precision. Below 0.35 it starts inventing speech (163.0s at 0.20).
DIARIZATION_ONSET = 0.40

# How many speakers must be judged active, averaged over the windows covering
# a moment, before it is called overlapped speech. Tuned on AMI at f1 0.374
# (recall 0.388, precision 0.361) - which is the best this model does on that
# audio, not a good score. Overlap detection here is a weak signal and is
# treated as one; see core/diarization_powerset.py.
DIARIZATION_OVERLAP_COUNT = 1.10

# A window's speaker needs at least this much clean, non-overlapped speech
# before an embedding is computed for it. Below this the vector is dominated
# by whatever noise happened to be in a handful of frames, and clustering a
# vector like that is worse than leaving those frames to the neighbouring
# windows that do have a confident opinion.
DIARIZATION_EMBED_MIN_CLEAN_SECONDS = 0.5

# ============================================================================
# Dependency Installation Configuration
# ============================================================================
# Timeout for package installation to prevent hanging

INSTALL_TIMEOUT_SECONDS = 120   # 2 minutes per package installation
