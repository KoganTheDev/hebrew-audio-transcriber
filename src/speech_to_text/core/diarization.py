"""Speaker diarization: working out who spoke when, for single-microphone
recordings where both parties share one channel.

Engine choice. The obvious candidate is pyannote.audio, which is the accuracy
leader, but it pulls torch and torchaudio (~2.5 GB) and requires a HuggingFace
account plus accepting gated model terms before it will download weights at
runtime. That is a poor fit for an app whose entire premise is that it runs
locally with no account and no network after setup. sherpa-onnx runs the same
family of models through onnxruntime instead: ~36 MB of weights, no login, no
torch, and it exposes the one knob that matters most here - clustering into a
known number of speakers.

Accuracy note: fixing the speaker count is the single largest lever available.
Threshold-based clustering has to infer how many people are present, and it
gets that wrong often enough to fragment one speaker into several. If the user
knows there are two people, saying so removes the hardest part of the problem.
"""

import logging
import os
import shutil
import tarfile
import urllib.request
from typing import Callable, Optional

import numpy as np

from speech_to_text import config

# Word-to-speaker attribution lives in core/speaker_attribution.py; these
# names stay importable from here because worker.py, the eval scripts and the
# tests all reach for them at this path. __all__ below is what keeps ruff from
# reading them as unused.
from speech_to_text.core.speaker_attribution import (
    MIN_SPEAKER_RUN_WORDS,
    _best_speaker,
    assign_speakers,
)

logger = logging.getLogger(__name__)

# Cache next to whisper_models/, which Transcriber already uses as its
# download_root. Both are gitignored.
MODELS_DIR = "./diarization_models"

_SEGMENTATION_ARCHIVE = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
)
_SEGMENTATION_MODEL = os.path.join(
    MODELS_DIR, "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx"
)

# VoxCeleb-trained rather than one of the Chinese-corpus alternatives. Speaker
# embeddings capture voice timbre more than language-specific phonetics, so
# any of them would function on Hebrew, but VoxCeleb is by far the most
# speaker-diverse training set of the options offered, which is the property
# that actually matters for telling two unfamiliar voices apart.
_EMBEDDING_URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
    "speaker-recongition-models/3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
)
_EMBEDDING_MODEL = os.path.join(MODELS_DIR, "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx")


class DiarizationUnavailable(Exception):
    """Raised when diarization cannot run. Never fatal to a transcription."""


def models_present() -> bool:
    return os.path.exists(_SEGMENTATION_MODEL) and os.path.exists(_EMBEDDING_MODEL)


def ensure_models(progress: Optional[Callable[[int, int], None]] = None) -> None:
    """Download the ONNX models on first use.

    sherpa-onnx ships no weights of its own, so this has to happen once. Both
    files are small enough (~36 MB total) that a progress callback is a
    courtesy rather than a necessity, but a silent multi-second stall in a
    desktop app reads as a freeze.
    """
    if models_present():
        return

    os.makedirs(MODELS_DIR, exist_ok=True)

    if not os.path.exists(_EMBEDDING_MODEL):
        _download(_EMBEDDING_URL, _EMBEDDING_MODEL, progress)

    if not os.path.exists(_SEGMENTATION_MODEL):
        archive = os.path.join(MODELS_DIR, "segmentation.tar.bz2")
        _download(_SEGMENTATION_ARCHIVE, archive, progress)
        try:
            with tarfile.open(archive, "r:bz2") as tar:
                # Guard against path traversal in archive members. These come
                # from a trusted release, but extracting archives without
                # checking member paths is the kind of thing that stays wrong
                # forever once copied elsewhere.
                _safe_extract(tar, MODELS_DIR)
        finally:
            if os.path.exists(archive):
                os.remove(archive)

    if not models_present():
        raise DiarizationUnavailable("Diarization models missing after download")


def _safe_extract(tar: tarfile.TarFile, target_dir: str) -> None:
    target_root = os.path.abspath(target_dir)
    for member in tar.getmembers():
        destination = os.path.abspath(os.path.join(target_dir, member.name))
        if not destination.startswith(target_root + os.sep) and destination != target_root:
            raise DiarizationUnavailable(f"Unsafe path in archive: {member.name}")
    tar.extractall(target_dir)


def _download(url: str, destination: str, progress: Optional[Callable[[int, int], None]]) -> None:
    logger.info(f"Downloading {os.path.basename(destination)} ...")
    partial = destination + ".part"
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with open(partial, "wb") as handle:
                while True:
                    chunk = response.read(262144)
                    if not chunk:
                        break
                    handle.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total)
        # Move into place only once complete, so an interrupted download can't
        # leave a truncated file that looks cached on the next run.
        shutil.move(partial, destination)
    except Exception as e:
        if os.path.exists(partial):
            os.remove(partial)
        raise DiarizationUnavailable(f"Could not download {url}: {e}") from e


def diarize(
    samples: np.ndarray,
    sample_rate: int = 16000,
    num_speakers: int = 2,
    progress: Optional[Callable[[int, int], None]] = None,
) -> list["SpeakerSpan"]:
    """Label who is speaking across a mono recording.

    Args:
        samples: float32 mono audio.
        num_speakers: Exact speaker count if known, or -1 to infer it.
        progress: Called with (processed_chunks, total_chunks).

    Returns speaker-labelled time spans, sorted by start time. Spans of
    different speakers may overlap - that is simultaneous speech, not an
    error, and both callers (assign_speakers and the DER metric) handle it.

    Raises DiarizationUnavailable if the engine or models are missing.

    Which pipeline runs is config.DIARIZATION_ENGINE; see that constant for
    the measurements behind having two. This function keeps the same contract
    either way, so nothing downstream needs to know which one ran.

    """
    if config.DIARIZATION_ENGINE == "powerset":
        # Imported lazily so the sherpa path does not pay for onnxruntime
        # session setup, and so a broken powerset module cannot stop the
        # default engine from working.
        from speech_to_text.core.diarization_powerset import diarize_powerset

        return diarize_powerset(
            samples,
            sample_rate=sample_rate,
            num_speakers=num_speakers,
            progress=progress,
        )

    try:
        import sherpa_onnx
    except ImportError as e:
        raise DiarizationUnavailable("sherpa-onnx is not installed") from e

    ensure_models(progress=None)

    # Named diar_config, not config: this module imports the application's
    # own settings module as `config` at the top, and a local of that name
    # shadows it for the whole function body - including the right-hand side
    # of this very assignment, where the min_duration_* values below are read.
    # That shadowing turned every diarization run into an UnboundLocalError,
    # which worker.py's deliberately non-fatal except swallowed into
    # "Speaker identification skipped", so the feature failed silently rather
    # than loudly. diarize() has no unit test - it needs real models and real
    # audio - so nothing caught it but an end-to-end run.
    diar_config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=_SEGMENTATION_MODEL
            ),
            # num_threads/provider were never passed here either, so both
            # models ran on onnxruntime's defaults. See the constants in
            # config.py for why the thread count is a small capped number
            # rather than os.cpu_count() - more threads measured SLOWER for
            # this model's one-window-at-a-time inference.
            num_threads=config.DIARIZATION_NUM_THREADS,
            provider=config.DIARIZATION_PROVIDER,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=_EMBEDDING_MODEL,
            num_threads=config.DIARIZATION_NUM_THREADS,
            provider=config.DIARIZATION_PROVIDER,
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            # num_clusters wins when set; threshold is only consulted when the
            # count is unknown (-1).
            num_clusters=num_speakers if num_speakers and num_speakers > 0 else -1,
            threshold=0.5,
        ),
        # Named constants in config.py, kept equal to sherpa-onnx's own
        # defaults - see the comment there for why they are stated explicitly
        # rather than left to the library.
        min_duration_on=config.DIARIZATION_MIN_DURATION_ON,
        min_duration_off=config.DIARIZATION_MIN_DURATION_OFF,
    )
    if not diar_config.validate():
        raise DiarizationUnavailable("Invalid diarization configuration")

    engine = sherpa_onnx.OfflineSpeakerDiarization(diar_config)

    if sample_rate != engine.sample_rate:
        raise DiarizationUnavailable(
            f"Diarization needs {engine.sample_rate} Hz audio, got {sample_rate}"
        )

    def callback(processed: int, total: int) -> int:
        if progress:
            progress(processed, total)
        return 0  # non-zero would ask sherpa-onnx to stop

    result = engine.process(samples, callback=callback)
    spans = [
        SpeakerSpan(start=s.start, end=s.end, speaker=s.speaker)
        for s in result.sort_by_start_time()
    ]
    logger.info(f"Diarization found {result.num_speakers} speaker(s) across {len(spans)} spans")
    return spans


class SpeakerSpan:
    """A stretch of audio attributed to one speaker."""

    __slots__ = ("start", "end", "speaker")

    def __init__(self, start: float, end: float, speaker: int):
        self.start = start
        self.end = end
        self.speaker = speaker

    def overlap(self, start: float, end: float) -> float:
        return max(0.0, min(self.end, end) - max(self.start, start))

    def __repr__(self) -> str:
        return f"SpeakerSpan({self.start:.2f}-{self.end:.2f}, speaker={self.speaker})"


__all__ = [
    "MIN_SPEAKER_RUN_WORDS",
    "DiarizationUnavailable",
    "SpeakerSpan",
    "_best_speaker",
    "assign_speakers",
    "diarize",
    "ensure_models",
    "models_present",
]
