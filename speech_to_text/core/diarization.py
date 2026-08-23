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

from speech_to_text import config
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
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=_EMBEDDING_MODEL),
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


# A run of words attributed to one speaker has to be at least this long
# before assign_speakers will cut the segment there. A single stray word
# voting for the other speaker is far more likely to be a boundary-rounding
# error in the diarizer than a genuine one-word interjection, so a run this
# short is folded back into its neighbour instead of fracturing the segment.
MIN_SPEAKER_RUN_WORDS = 2


def assign_speakers(segments: Sequence[Segment], spans: Sequence[SpeakerSpan]) -> List[Segment]:
    """
    Attach a speaker to each transcript segment, splitting where the speaker
    changes mid-segment.

    Works at word level, not segment level. Whisper's segment boundaries are
    decided by its decoder and have no relationship to who is talking, so a
    speaker change lands mid-segment routinely. Attributing whole segments by
    their overall time span would smear every such change across an entire
    turn, and even majority-voting the whole segment to one label throws the
    minority words' speaker away. Instead each word is matched to the span it
    overlaps most, and consecutive words that agree become one sub-segment -
    so a straddling segment is cut into two (or more) at the word boundary
    where the speaker actually changed, rather than losing that boundary.

    Segment(start, end, text, speaker, words) is fully reconstructible (see
    core/segments.py), so a split rebuilds new Segment objects rather than
    mutating the input. A segment that does not need splitting is returned
    unchanged - same object, not a copy - so callers that compare identity
    (or just want the common case to be cheap) see that.

    Segments with no word timings (or no overlapping span at all) fall back to
    matching on the segment's own span, and stay None if even that fails.
    Leaving a segment unattributed is better than guessing: the renderer
    simply omits the label.

    The returned list is new: `segments` itself is never reordered, extended
    or shortened, and a split segment's pieces are new Segment objects. But a
    segment that is not split IS mutated - its `.speaker` is set in place
    (in the no-split and fallback branches above) and that same object,
    not a copy, is what comes back in the result. So `segments is not
    assign_speakers(segments, spans)` always holds, but
    `segments[i] is result[j]` can still be true for an unsplit segment.
    """
    if not spans:
        return list(segments)

    result: List[Segment] = []
    for segment in segments:
        result.extend(_split_segment(segment, spans))
    return result


def _split_segment(segment: Segment, spans: Sequence[SpeakerSpan]) -> List[Segment]:
    """Attribute one segment, splitting it if a real speaker change is found."""
    if not segment.words:
        # No word timings at all - the per-channel stereo path never carries
        # them, and neither does a segment faster-whisper emitted without
        # word_timestamps. Only the segment's own span is available.
        segment.speaker = _best_speaker(spans, segment.start, segment.end)
        return [segment]

    labels = [_best_speaker(spans, word.start, word.end) for word in segment.words]

    if all(label is None for label in labels):
        # Every word missed every span - e.g. the whole segment falls in a
        # gap min_duration_on/off dropped. Leave it unattributed rather than
        # inventing a label from nothing.
        segment.speaker = None
        return [segment]

    # A word with no overlap of its own (a rounding gap at a span boundary,
    # or a span dropped by min_duration_on) does not get to start a run or a
    # None-labelled sub-segment - it is filled in from its neighbours, the
    # same way it would have simply not voted under the old majority scheme.
    filled = _fill_unmatched(labels)
    runs = _coalesce_adjacent(_merge_short_runs(_runs(filled), MIN_SPEAKER_RUN_WORDS))

    if len(runs) == 1:
        segment.speaker = runs[0][2]
        return [segment]

    pieces: List[Segment] = []
    last_index = len(runs) - 1
    for i, (start_idx, end_idx, label) in enumerate(runs):
        run_words = segment.words[start_idx:end_idx]
        # Rejoining word texts and stripping mirrors exactly how the original
        # segment text itself was produced: faster-whisper decodes the whole
        # token run and strips it once, and each word's own decoded text
        # already carries whatever leading space separates it from its
        # neighbour (verified against the installed faster-whisper: word
        # text comes from tokenizer.decode() on that word's token slice, so
        # concatenating word texts reproduces the segment text exactly).
        # Stripping only the ends - not collapsing internal whitespace -
        # keeps inter-word spacing exactly as the model produced it.
        text = "".join(word.text for word in run_words).strip()
        # Endpoints: the first piece keeps the segment's own start (which can
        # lead the first word, e.g. VAD padding) and the last piece keeps its
        # own end, for the same reason. Interior boundaries use the word
        # timings themselves, since that word boundary is the split point.
        start = segment.start if i == 0 else run_words[0].start
        end = segment.end if i == last_index else run_words[-1].end
        pieces.append(Segment(start=start, end=end, text=text, words=list(run_words), speaker=label))
    return pieces


def _fill_unmatched(labels: Sequence[Optional[int]]) -> List[Optional[int]]:
    """
    Carry the nearest real label over words with no span overlap of their own.

    Forward-fill first (a gap word takes on the speaker who was just
    talking), then back-fill any still-None prefix from the first real label
    found. This only runs after the all-None case has already been handled,
    so a real label always exists to fill from.
    """
    filled: List[Optional[int]] = list(labels)
    last: Optional[int] = None
    for i, label in enumerate(filled):
        if label is None:
            filled[i] = last
        else:
            last = label

    if filled[0] is None:
        first_real = next(label for label in filled if label is not None)
        for i, label in enumerate(filled):
            if label is None:
                filled[i] = first_real
            else:
                break

    return filled


def _runs(labels: Sequence[Optional[int]]) -> List[List]:
    """Consecutive equal-label stretches, as mutable [start, end, label]."""
    runs: List[List] = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            runs.append([start, i, labels[start]])
            start = i
    return runs


def _merge_short_runs(runs: List[List], min_words: int) -> List[List]:
    """
    Fold any run shorter than min_words into a neighbour so it cannot, on its
    own, split the segment (see MIN_SPEAKER_RUN_WORDS).

    Restarts the scan after each merge rather than trying to merge in one
    pass, because folding a short run into its neighbour can make that
    neighbour's other side newly eligible to merge too. The number of runs in
    one Whisper segment is small (a handful of words at most), so the
    restart's extra cost is negligible.
    """
    if len(runs) <= 1:
        return runs

    merged = [list(run) for run in runs]
    changed = True
    while changed and len(merged) > 1:
        changed = False
        for i, (start, end, _label) in enumerate(merged):
            if end - start >= min_words:
                continue
            if i > 0:
                merged[i - 1][1] = end
            else:
                merged[1][0] = start
            del merged[i]
            changed = True
            break

    return merged


def _coalesce_adjacent(runs: List[List]) -> List[List]:
    """Merge neighbouring runs that ended up with the same label after merging short ones."""
    if not runs:
        return runs
    out = [list(runs[0])]
    for start, end, label in runs[1:]:
        if label == out[-1][2]:
            out[-1][1] = end
        else:
            out.append([start, end, label])
    return out


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
