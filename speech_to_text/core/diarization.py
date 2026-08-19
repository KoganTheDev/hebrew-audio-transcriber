"""
Speaker diarization: working out who spoke when, for single-microphone
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
from typing import Callable, List, Optional, Sequence

import numpy as np

from speech_to_text.core.segments import Segment

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
_EMBEDDING_MODEL = os.path.join(
    MODELS_DIR, "3dspeaker_speech_campplus_sv_en_voxceleb_16k.onnx"
)


class DiarizationUnavailable(Exception):
    """Raised when diarization cannot run. Never fatal to a transcription."""


def models_present() -> bool:
    return os.path.exists(_SEGMENTATION_MODEL) and os.path.exists(_EMBEDDING_MODEL)


def ensure_models(progress: Optional[Callable[[int, int], None]] = None) -> None:
    """
    Download the ONNX models on first use.

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
) -> List["SpeakerSpan"]:
    """
    Label who is speaking across a mono recording.

    Args:
        samples: float32 mono audio.
        num_speakers: Exact speaker count if known, or -1 to infer it.
        progress: Called with (processed_chunks, total_chunks).

    Returns speaker-labelled time spans, sorted by start time.
    Raises DiarizationUnavailable if the engine or models are missing.
    """
    try:
        import sherpa_onnx
    except ImportError as e:
        raise DiarizationUnavailable("sherpa-onnx is not installed") from e

    ensure_models(progress=None)

    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=_SEGMENTATION_MODEL
            ),
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=_EMBEDDING_MODEL),
        clustering=sherpa_onnx.FastClusteringConfig(
            # num_clusters wins when set; threshold is only consulted when the
            # count is unknown (-1).
            num_clusters=num_speakers if num_speakers and num_speakers > 0 else -1,
            threshold=0.5,
        ),
    )
    if not config.validate():
        raise DiarizationUnavailable("Invalid diarization configuration")

    engine = sherpa_onnx.OfflineSpeakerDiarization(config)

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
    logger.info(
        f"Diarization found {result.num_speakers} speaker(s) across {len(spans)} spans"
    )
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


def assign_speakers(segments: Sequence[Segment], spans: Sequence[SpeakerSpan]) -> None:
    """
    Attach a speaker to each transcript segment, in place.

    Works at word level, not segment level. Whisper's segment boundaries are
    decided by its decoder and have no relationship to who is talking, so a
    speaker change lands mid-segment routinely. Attributing whole segments by
    their overall time span would smear every such change across an entire
    turn. Instead each word is matched to the span it overlaps most, and the
    segment takes the majority vote of its words - which puts the boundary at
    the nearest word rather than the nearest segment.

    Segments with no word timings (or no overlapping span at all) fall back to
    matching on the segment's own span, and stay None if even that fails.
    Leaving a segment unattributed is better than guessing: the renderer simply
    omits the label.
    """
    if not spans:
        return

    for segment in segments:
        votes = {}
        for word in segment.words:
            speaker = _best_speaker(spans, word.start, word.end)
            if speaker is not None:
                votes[speaker] = votes.get(speaker, 0) + 1

        if votes:
            segment.speaker = max(votes.items(), key=lambda kv: kv[1])[0]
        else:
            segment.speaker = _best_speaker(spans, segment.start, segment.end)


def _best_speaker(spans: Sequence[SpeakerSpan], start: float, end: float) -> Optional[int]:
    """The speaker whose spans overlap [start, end] the most, if any."""
    totals = {}
    for span in spans:
        overlap = span.overlap(start, end)
        if overlap > 0:
            totals[span.speaker] = totals.get(span.speaker, 0.0) + overlap
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: kv[1])[0]
