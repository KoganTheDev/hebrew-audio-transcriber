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
# Only Hebrew-tuned models are offered. The app always decodes with
# language="he" (config.LANGUAGE), so the stock Whisper sizes this list used to
# carry had no job left: each was less accurate on Hebrew than Ivrit Turbo, and
# Medium and Large were slower as well. Stock sizes can still be passed by raw
# name - calibration benchmarks "tiny" that way, and so can the eval harness
# (see Transcriber.model_repo).
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
    # Hebrew-specialised models (ivrit.ai).
    #
    # Stock OpenAI Whisper is trained overwhelmingly on English; Hebrew is a
    # small slice of its training data, which is the root
    # cause of the misheard-word problem this app exists to solve. ivrit.ai
    # fine-tunes Whisper on hundreds of hours of transcribed Hebrew speech and
    # publishes the result already converted to CTranslate2 - the exact format
    # faster-whisper loads - so using them costs nothing but the download.
    "ivrit-turbo": {
        "repo": "ivrit-ai/whisper-large-v3-turbo-ct2",
        "name": "Ivrit Turbo",
        "description": "Hebrew-tuned, fast and accurate",
        "purpose": (
            "The right choice for almost every recording: Hebrew-tuned, "
            "and about 5x faster than Ivrit Large."
        ),
        "accuracy": "High",
        "pros": [
            "✓ Trained specifically on Hebrew speech",
            "✓ Far fewer misheard Hebrew words than stock Whisper",
            "✓ Turbo decoder: about 5x faster than Ivrit Large",
            "✓ Best choice for Hebrew content",
        ],
        "cons": [
            "✗ One-time 1.6 GB download on first use",
            "✗ Requires 3 GB RAM",
            "✗ Slightly less accurate than Ivrit Large on hard audio",
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
        "purpose": (
            "For hard-to-hear or critical recordings, when you can wait. "
            "Slightly more accurate, much slower."
        ),
        "accuracy": "Highest",
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

# Default model. Nearly Ivrit Large's accuracy at about a fifth of its runtime.
DEFAULT_MODEL = "ivrit-turbo"


def hf_repo_id(repo: str) -> str:
    """The HuggingFace repo id for a MODELS "repo" value.

    The stock Whisper sizes are stored bare ("tiny", "large-v3") because that
    is what faster-whisper accepts, but it resolves them to Systran's
    CTranslate2 conversions before anything touches the download cache. The
    ivrit.ai entries are already full owner/repo addresses and pass through.

    One definition, because two call sites need the same answer for different
    reasons - core/transcriber.py to fetch the weights, and
    gui/steps/model_select.py to decide whether a card should warn about a
    download - and a pair of hand-mirrored literals is exactly how those two
    drift apart.
    """
    return repo if "/" in repo else f"Systran/faster-whisper-{repo}"
