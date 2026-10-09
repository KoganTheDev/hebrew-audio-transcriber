"""Absolute paths for the model caches, the log and the term list, and the
name of a run's output file.

Every path here is absolute on purpose. Each of them was once relative and
resolved against the working directory, so launching from anywhere but the
project folder re-downloaded gigabytes of models, scattered logs, or split
the term list in two. Plain os.path only: core/ imports this, and core/ must
never import PyQt5 (see core/__init__.py).
"""

import os


def _repo_root() -> str:
    """The checkout this code runs from (config/ -> src/ -> repo root)."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _in_checkout() -> bool:
    """A full checkout, as opposed to a src/ tree copied somewhere on its own."""
    return os.path.isfile(os.path.join(_repo_root(), "pyproject.toml"))


def _user_dir(kind: str) -> str:
    """Per-user "data" (worth keeping) or "state" (reproducible) directory."""
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    elif kind == "state":
        base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "speech-to-text")


def _cache_root(dir_name: str) -> str:
    """An existing cache of that name at the repo root, else a per-user one.

    The existing cache wins: it is where gigabytes of models already sit, and
    a fresh empty location would look exactly like nothing was downloaded.
    """
    beside = os.path.join(_repo_root(), dir_name)
    if os.path.isdir(beside):
        return beside
    return os.path.join(_user_dir("data"), dir_name)


def resolve_model_download_root() -> str:
    """Where faster-whisper looks for, and downloads, models.

    SPEECH_TO_TEXT_MODEL_DIR overrides (models run to several GB each). A
    function so tests can re-resolve under patched environment variables.
    """
    override = os.environ.get("SPEECH_TO_TEXT_MODEL_DIR")
    root = os.path.abspath(override or _cache_root("whisper_models"))
    os.makedirs(root, exist_ok=True)
    return root


MODEL_DOWNLOAD_ROOT = resolve_model_download_root()


def resolve_diarization_models_root() -> str:
    """Where the sherpa-onnx speaker models live.

    Not created here: diarization is optional, and ensure_models() makes the
    directory when it first downloads.
    """
    override = os.environ.get("SPEECH_TO_TEXT_DIARIZATION_DIR")
    return os.path.abspath(override or _cache_root("diarization_models"))


DIARIZATION_MODELS_ROOT = resolve_diarization_models_root()


LOG_FILENAME = "speech_to_text.log"

# Generous, because the per-phase timings that make a slow run diagnosable are
# DEBUG lines: bound the bytes, not the detail.
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_BACKUP_COUNT = 3


def resolve_log_path() -> str:
    """The log: at the repo root in a checkout (where people already find it),
    else the per-user state directory. SPEECH_TO_TEXT_LOG_DIR overrides.
    """
    override = os.environ.get("SPEECH_TO_TEXT_LOG_DIR")
    if override:
        directory = os.path.abspath(override)
    elif _in_checkout():
        directory = _repo_root()
    else:
        directory = os.path.join(_user_dir("state"), "logs")
    os.makedirs(directory, exist_ok=True)
    return os.path.join(directory, LOG_FILENAME)


SUPPORTED_FORMATS = ("*.mp3", "*.wav", "*.m4a", "*.flac", "*.ogg", "*.mp4", "*.mkv")

# HTML, not .txt: only a declared paragraph direction aligns Hebrew correctly
# (see core/formatting).
OUTPUT_FILENAME_TEMPLATE = "{stem}_transcription.html"


def output_path_for(audio_files: list[str]) -> str:
    """Beside the first input: named after the file, or for a batch after its
    folder. Re-running the same input(s) replaces that run's own output.
    """
    first_dir = os.path.dirname(audio_files[0])
    if len(audio_files) == 1:
        stem, _ext = os.path.splitext(os.path.basename(audio_files[0]))
    else:
        stem = os.path.basename(os.path.normpath(first_dir)) or "batch"
    return os.path.join(first_dir, OUTPUT_FILENAME_TEMPLATE.format(stem=stem))


# Domain terms (names, places, jargon) a general model mishears: one per line,
# UTF-8, "#" comments. Absent means the correction pass does nothing.
TERMS_FILENAME = "hebrew_terms.txt"
CHECKPOINT_FILENAME = "transcription_checkpoint.txt"


def resolve_terms_path() -> str:
    """The term list both the terms dialog writes and the worker reads - one
    path, so they can never edit and read different copies. At the repo root
    in a checkout, else per-user data. SPEECH_TO_TEXT_TERMS_FILE overrides.
    """
    override = os.environ.get("SPEECH_TO_TEXT_TERMS_FILE")
    if override:
        return os.path.abspath(override)
    if _in_checkout():
        return os.path.join(_repo_root(), TERMS_FILENAME)
    return os.path.join(_user_dir("data"), TERMS_FILENAME)
