"""Where models are downloaded to and where transcripts are written.

The only real logic in the config package: resolving an absolute model
download root, and naming a transcription run's output file.
"""

import os


# WhisperModel's download_root controls both where faster-whisper looks for
# an already-cached model AND where it writes a new download, so it must be
# ABSOLUTE. A relative root resolves against the process's current working
# directory, and pyproject.toml installs a `speech-to-text` console script
# (see [project.scripts]) that can be run from anywhere - so a launch from a
# different directory would miss the existing cache and silently re-download
# from scratch. There is no download-progress signal anywhere in this app (see
# MODELS' "download_size" comment), so the only symptom is "Loading model..."
# taking twenty unexplained minutes - and on this machine that re-download is
# 5.9 GB.
#
# MODEL_DOWNLOAD_ROOT is also the single shared constant behind the model
# card's pending-download warning in gui/steps/model_select.py: two copies of
# this path could drift, and the card's note would then lie about what the
# downloader will actually do.
#
# Resolved once, at import time, in this order:
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
def _cache_root(dir_name: str) -> str:
    """An existing model cache of that name beside the package, or a per-user path.

    Shared by both caches. They are separate downloads with separate
    environment overrides, but "where does a model cache live" has one answer
    and it should not be written twice - the diarization cache spent a long
    time as a bare relative "./diarization_models" precisely because this
    reasoning lived only in the Whisper half.
    """
    # dirname twice: this module lives in the config/ subpackage, so the
    # package root - speech_to_text/, the directory the ancestor walk below is
    # written in terms of - is one further up than this file's own directory.
    package_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # Two levels, not one. Under the src-layout the package sits at
    # <repo>/src/speech_to_text/, so its immediate parent is src/ - while the
    # already-downloaded models live at <repo>/<dir_name>, one level further
    # up. Checking only the immediate parent would silently miss them and
    # re-download everything into src/.
    for ancestor in (os.path.dirname(package_dir), os.path.dirname(os.path.dirname(package_dir))):
        beside = os.path.join(ancestor, dir_name)
        if os.path.isdir(beside):
            return beside

    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~\\AppData\\Local")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "speech-to-text", dir_name)


def _default_model_download_root() -> str:
    """Where to put Whisper models when SPEECH_TO_TEXT_MODEL_DIR isn't set."""
    return _cache_root("whisper_models")


def resolve_model_download_root() -> str:
    """Compute MODEL_DOWNLOAD_ROOT's value. A function, not just a module-level
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


def resolve_diarization_models_root() -> str:
    """Absolute path for the sherpa-onnx speaker models.

    This was a bare relative "./diarization_models" in core/diarization.py, so
    it resolved against the process working directory. The launchers cd to the
    project first, which hid it - but the console-script entry point declared
    in pyproject.toml does not, so running `speech-to-text` from anywhere else
    re-downloaded 36 MB into whatever directory the user happened to be in, or
    failed outright on a read-only one. Exactly the bug the Whisper cache had,
    and the reasoning for that fix is directly above.

    No makedirs here, unlike the Whisper root: diarization is optional, and
    ensure_models() creates the directory when it actually fetches something.
    Creating an empty folder on import for every user who never turns speaker
    identification on would be litter.
    """
    override = os.environ.get("SPEECH_TO_TEXT_DIARIZATION_DIR")
    root = override if override else _cache_root("diarization_models")
    # abspath for the same reason MODEL_DOWNLOAD_ROOT does it: a user-supplied
    # override could itself be relative, and this is the one place that
    # guarantee has to hold whatever the input.
    return os.path.abspath(root)


DIARIZATION_MODELS_ROOT = resolve_diarization_models_root()


SUPPORTED_FORMATS = ("*.mp3", "*.wav", "*.m4a", "*.flac", "*.ogg", "*.mp4", "*.mkv")

# HTML, not .txt: only a declared, not guessed, paragraph direction gets Hebrew
# to align correctly (see core/formatting's module docstring). One input file is
# named after itself; a batch is named after the folder it came from, since
# there is no single source filename to hang the output name on. See
# output_path_for().
OUTPUT_FILENAME_TEMPLATE = "{stem}_transcription.html"


def output_path_for(audio_files: list[str]) -> str:
    """Decide the output path for a transcription run.

    One file -> named after it (so two different recordings never collide).
    Several files -> named after their shared folder. Always written beside
    the first input file, so the output lands next to the audio regardless
    of which directory the app itself runs from.

    This only overwrites a previous run over the *same* input(s) - re-running
    a batch from the same folder replaces its own output.
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
