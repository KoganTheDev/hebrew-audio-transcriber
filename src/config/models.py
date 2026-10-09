"""The model catalogue: what the GUI offers and what faster-whisper loads."""

# Keyed by the app's own model id (also used by i18n.MODEL_STRINGS and the
# speed tables). "repo" is what faster-whisper loads - a HuggingFace repo of
# CTranslate2 weights, kept separate because upstream addresses can move.
# Ordered by ascending accuracy_score: the GUI renders cards in this order.
#
# Only Hebrew-tuned models: decoding is always language="he", and every stock
# Whisper size was less accurate on Hebrew than Ivrit Turbo. Stock sizes still
# load by raw name (calibration benchmarks "tiny" that way).
#
# "download_size" is shown before a model is picked because there is no
# download progress to show during it: WhisperModel downloads internally with
# no callback, so "Loading model..." covers both download and disk load.
MODELS = {
    # ivrit.ai: Whisper fine-tuned on hundreds of hours of Hebrew, published
    # in the CTranslate2 format faster-whisper loads.
    "ivrit-turbo": {
        "repo": "ivrit-ai/whisper-large-v3-turbo-ct2",
        "ram_required": "3 GB",
        "download_size": "1.6 GB",
        "accuracy_score": 5,
    },
    "ivrit-large": {
        "repo": "ivrit-ai/whisper-large-v3-ct2",
        "ram_required": "8 GB",
        "download_size": "3.1 GB",
        "accuracy_score": 5.5,
    },
}

# Default model. Nearly Ivrit Large's accuracy at about a fifth of its runtime.
DEFAULT_MODEL = "ivrit-turbo"


def hf_repo_id(repo: str) -> str:
    """The HuggingFace repo id for a MODELS "repo" value.

    Bare Whisper sizes ("tiny") resolve to Systran's CTranslate2 conversions,
    as faster-whisper does; owner/repo ids pass through. Shared by the loader
    and the model step's download warning so the two cannot drift apart.
    """
    return repo if "/" in repo else f"Systran/faster-whisper-{repo}"
