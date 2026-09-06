"""Diarization built on our own powerset decode, for the "powerset" engine.

sherpa runs the whole pipeline behind one call with a fixed argmax decode, so
the two things measurement says matter here are both out of reach through it:
where to threshold, and what audio the speaker embeddings are computed over.
This module owns exactly that middle. The embedding extractor and the
clustering are still sherpa's (SpeakerEmbeddingExtractor, FastClustering, both
usable standalone) - hand-writing an 80-dim Kaldi filterbank or an
agglomerative clustering would be delicate code with no measurement behind it.

The pipeline, and why it is this shape:

    1. Decode each 10s window into per-speaker marginals (core/segmentation).
    2. Binarise each window ON ITS OWN. Window-local speaker indices are not
       comparable across windows, and aligning neighbours would let one bad
       alignment early in a file propagate through everything after it.
    3. Embed each (window, local speaker) with enough speech.
    4. Cluster those embeddings into the requested number of speakers.
       Alignment falls out of it: two windows' local speakers land in the same
       cluster precisely when they sound like the same person.
    5. Reconstruct one global track per cluster and cut it into spans.

Overlapping spans are a normal output, not an error - the same as sherpa
returns, and what SpeakerSpan and the DER metric both already handle.

MEASURED, including one result that went the wrong way. On 300s of AMI at
num_speakers=4, against sherpa's DER 0.4646 (missed 16.29, false alarm 9.40,
confusion 46.51):

    embeddings from clean frames only   DER 0.4085  miss 14.36  FA 13.43  conf 35.68
    embeddings from all active frames   DER 0.4011  miss 14.83  FA 13.21  conf 34.29

Confusion - the error that dominates here, and what a user sees as "one
speaker got all the sentences" - falls by about a quarter. But masking overlap
out of the embeddings, the stated reason to expect that fall, is very slightly
WORSE than not masking: the gain comes from owning the decode and its
threshold, so mask_overlap defaults to False. Recorded rather than deleted so
nobody re-derives the idea from first principles and re-adds it.

Both runs returned 3 speakers for a requested 4, which is not a merge bug: the
first 300s of ES2004a has only THREE speakers (MEE014 does not talk until
later), so those runs were forcing a fourth cluster onto audio with no fourth
speaker. Worth stating because _reconstruct DOES have a rule that can erase a
real speaker, and it would be easy to misread one as evidence of the other.
"""

import logging
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

import numpy as np

from speech_to_text import config
from speech_to_text.core import segmentation as seg

if TYPE_CHECKING:
    from speech_to_text.core.diarization import SpeakerSpan

logger = logging.getLogger(__name__)


def diarize_powerset(
    samples: np.ndarray,
    sample_rate: int = 16000,
    num_speakers: int = 2,
    progress: Callable[[int, int], None] | None = None,
    onset: float | None = None,
    mask_overlap: bool = False,
) -> list["SpeakerSpan"]:
    """Label who is speaking, decoding the segmentation model directly.

    Same contract as core.diarization.diarize: float32 mono audio in,
    speaker-labelled spans sorted by start time out.

    mask_overlap: True computes each speaker's embedding only from frames
    where they are the sole active speaker, False from every frame they are
    active in. It defaults to False because the measurement went against it
    (see the module docstring), and stays switchable so that A/B remains
    reproducible - not because it is worth turning in production.
    """
    # Imported here, not at module scope: core/ is imported by the GUI process
    # too, and sherpa-onnx must not be a hard import for paths that never
    # diarize.
    from speech_to_text.core.diarization import (
        _EMBEDDING_MODEL,
        _SEGMENTATION_MODEL,
        DiarizationUnavailable,
        SpeakerSpan,
        ensure_models,
    )

    try:
        import onnxruntime as ort
        import sherpa_onnx
    except ImportError as e:
        raise DiarizationUnavailable("onnxruntime/sherpa-onnx is not installed") from e

    if sample_rate != seg.SAMPLE_RATE:
        raise DiarizationUnavailable(
            f"Diarization needs {seg.SAMPLE_RATE} Hz audio, got {sample_rate}"
        )

    ensure_models(progress=None)
    if onset is None:
        onset = config.DIARIZATION_ONSET

    session = ort.InferenceSession(
        _SEGMENTATION_MODEL,
        providers=_providers(config.DIARIZATION_PROVIDER),
    )
    marginals, starts = _infer_with_progress(session, samples, progress)

    active = marginals >= onset  # (W, F, K)
    embeddings, owners = _embed_windows(
        sherpa_onnx, _EMBEDDING_MODEL, samples, active, starts, mask_overlap
    )

    if not embeddings:
        logger.warning("Diarization found no speech confident enough to embed")
        return []

    labels = _cluster(sherpa_onnx, embeddings, num_speakers)
    tracks = _reconstruct(active, starts, owners, labels, len(samples))
    spans = _tracks_to_spans(SpeakerSpan, tracks)

    logger.info(
        f"Diarization (powerset) found {len({s.speaker for s in spans})} speaker(s) "
        f"across {len(spans)} spans"
    )
    return spans


def _providers(name: str) -> list[str]:
    """onnxruntime provider list, falling back to CPU if the name is unknown."""
    available = {"cpu": "CPUExecutionProvider", "cuda": "CUDAExecutionProvider"}
    return [available.get(name.lower(), "CPUExecutionProvider")]


def _infer_with_progress(
    session: Any,
    samples: np.ndarray,
    progress: Callable[[int, int], None] | None,
) -> tuple[np.ndarray, list[int]]:
    """infer_marginals, reporting progress per window.

    Duplicated rather than adding a callback to segmentation.py, so that
    module stays free of anything but arithmetic.
    """
    starts = seg.window_starts(len(samples))
    matrix = seg.powerset_matrix()
    out = np.empty((len(starts), seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=np.float32)
    for index, start in enumerate(starts):
        window = samples[start : start + seg.WINDOW_SAMPLES]
        if len(window) < seg.WINDOW_SAMPLES:
            window = np.pad(window, (0, seg.WINDOW_SAMPLES - len(window)))
        logits = session.run(None, {"x": window.reshape(1, 1, -1).astype(np.float32)})[0]
        out[index] = seg.softmax(logits[0]) @ matrix
        if progress:
            progress(index + 1, len(starts))
    return out, starts


def _frame_samples(window_start: int, frame_index: int) -> tuple[int, int]:
    """Sample range one frame's receptive field covers."""
    begin = window_start + frame_index * seg.FRAME_SHIFT_SAMPLES
    return begin, begin + seg.RECEPTIVE_FIELD_SAMPLES


def _embed_windows(
    sherpa_onnx: Any,
    model_path: str,
    samples: np.ndarray,
    active: np.ndarray,
    starts: Sequence[int],
    mask_overlap: bool,
) -> tuple[list[np.ndarray], list[tuple[int, int]]]:
    """One embedding per (window, local speaker) that has enough usable speech.

    Returns the embeddings and the (window, speaker) each came from; `owners`
    is what maps cluster labels back onto the right slice of the activity
    tensor afterwards.

    The audio fed to the extractor is the CONCATENATION of that speaker's
    frames, not a full window with everything else zeroed. Both give the
    extractor only that speaker's voice, but concatenating gives it 1-3s
    instead of a 10s window that is mostly silence, which is where this
    pipeline's speed comes from. The cost is a splice discontinuity at each
    joint, which the filterbank sees as a transient.
    """
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=model_path,
            num_threads=config.DIARIZATION_NUM_THREADS,
            provider=config.DIARIZATION_PROVIDER,
        )
    )
    minimum = int(config.DIARIZATION_EMBED_MIN_CLEAN_SECONDS * seg.SAMPLE_RATE)

    embeddings: list[np.ndarray] = []
    owners: list[tuple[int, int]] = []
    for window_index, start in enumerate(starts):
        window_active = active[window_index]  # (F, K)
        alone = window_active.sum(axis=1) == 1  # (F,)
        for speaker in range(seg.NUM_LOCAL_SPEAKERS):
            usable = window_active[:, speaker]
            if mask_overlap:
                usable = usable & alone
            if not usable.any():
                continue

            audio = _gather(samples, start, usable)
            if len(audio) < minimum:
                # Not enough evidence to say who this is. Not the same as
                # dropping the speech: about ten windows cover every moment,
                # so a frame skipped here is almost always claimed by a
                # neighbour that did have a confident view of it.
                continue

            stream = extractor.create_stream()
            stream.accept_waveform(sample_rate=seg.SAMPLE_RATE, waveform=audio)
            stream.input_finished()
            embeddings.append(np.asarray(extractor.compute(stream), dtype=np.float32))
            owners.append((window_index, speaker))

    return embeddings, owners


def _gather(samples: np.ndarray, window_start: int, mask: np.ndarray) -> np.ndarray:
    """Concatenate the audio under every True frame of one window's mask."""
    pieces = []
    for begin, end in _mask_runs(mask):
        first, _ = _frame_samples(window_start, begin)
        _, last = _frame_samples(window_start, end - 1)
        first = max(0, first)
        last = min(len(samples), last)
        if last > first:
            pieces.append(samples[first:last])
    if not pieces:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(pieces).astype(np.float32)


def _mask_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous True stretches of a boolean array, as [begin, end) indices."""
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


def _cluster(sherpa_onnx: Any, embeddings: list[np.ndarray], num_speakers: int) -> list[int]:
    """Group (window, speaker) embeddings into speakers.

    num_speakers <= 0 means "infer", handing the decision to the threshold.
    The GUI's spin box is 2-10, so in practice this is an exact count.
    """
    matrix = np.ascontiguousarray(np.vstack(embeddings).astype(np.float32))
    clustering = sherpa_onnx.FastClustering(
        sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers if num_speakers and num_speakers > 0 else -1,
            threshold=0.5,
        )
    )
    return list(clustering(matrix))


def _reconstruct(
    active: np.ndarray,
    starts: Sequence[int],
    owners: Sequence[tuple[int, int]],
    labels: Sequence[int],
    num_samples: int,
) -> np.ndarray:
    """Fold every window's local speakers into global per-cluster activity.

    Cross-window alignment happens here, by cluster membership rather than by
    comparing neighbouring windows to each other. Each covering window votes on
    "is cluster c talking here", and a moment is active for c when at least
    half say so - one window's mistake is outvoted rather than propagated.

    The majority rule has a measured cost: a speaker few windows ever resolve
    as their own local speaker can never reach half the votes, so they are
    erased entirely rather than merely under-detected. Lowering the bar
    recovers them and cuts confusion, but on 300s of AMI share 0.50 gives DER
    0.4011 at false alarm 13.21 while share 0.25 gives DER 0.5412 at false
    alarm 51.85. Half stays; the direction the trade-off runs is written down
    so nobody has to rediscover it.
    """
    num_clusters = max(labels) + 1
    grid = seg._grid_size(starts, num_samples)

    votes_for = np.zeros((grid, num_clusters), dtype=np.float64)
    votes = np.zeros(grid, dtype=np.float64)

    covered_windows = set()
    for (window_index, speaker), label in zip(owners, labels):
        base = seg._grid_base(starts[window_index])
        stop = min(base + seg.FRAMES_PER_WINDOW, grid)
        width = stop - base
        if width <= 0:
            continue
        votes_for[base:stop, label] += active[window_index, :width, speaker]
        covered_windows.add(window_index)

    for window_index in covered_windows:
        base = seg._grid_base(starts[window_index])
        stop = min(base + seg.FRAMES_PER_WINDOW, grid)
        if stop > base:
            votes[base:stop] += 1.0

    seen = votes > 0
    share = np.zeros_like(votes_for)
    share[seen] = votes_for[seen] / votes[seen][:, None]
    return share >= 0.5


def _tracks_to_spans(span_type: type["SpeakerSpan"], tracks: np.ndarray) -> list["SpeakerSpan"]:
    """Cut each cluster's boolean track into spans, applying the duration floors.

    min_duration_off is applied first deliberately: bridging a short pause
    means a turn interrupted by a breath is judged on its whole length rather
    than as two fragments that each look too short to keep.
    """
    spans: list[SpeakerSpan] = []
    for speaker in range(tracks.shape[1]):
        intervals = seg.runs_to_intervals(tracks[:, speaker])
        intervals = _bridge(intervals, config.DIARIZATION_MIN_DURATION_OFF)
        for start, end in intervals:
            if end - start >= config.DIARIZATION_MIN_DURATION_ON:
                spans.append(span_type(start=start, end=end, speaker=speaker))
    spans.sort(key=lambda s: (s.start, s.end, s.speaker))
    return spans


def _bridge(intervals: list[tuple[float, float]], max_gap: float) -> list[tuple[float, float]]:
    """Join intervals separated by less than max_gap seconds."""
    if not intervals:
        return intervals
    out = [intervals[0]]
    for start, end in intervals[1:]:
        previous_start, previous_end = out[-1]
        if start - previous_end < max_gap:
            out[-1] = (previous_start, max(previous_end, end))
        else:
            out.append((start, end))
    return out
