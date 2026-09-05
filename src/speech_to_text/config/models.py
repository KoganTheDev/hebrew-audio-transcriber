"""The model catalogue: what the GUI offers and what faster-whisper loads."""

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
    # Hebrew-specialised models (ivrit.ai).
    #
    # Everything above is stock OpenAI Whisper, trained overwhelmingly on
    # English; Hebrew is a small slice of its training data, which is the root
    # cause of the misheard-word problem this app exists to solve. ivrit.ai
    # fine-tunes Whisper on hundreds of hours of transcribed Hebrew speech and
    # publishes the result already converted to CTranslate2 - the exact format
    # faster-whisper loads - so using them costs nothing but the download.
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
