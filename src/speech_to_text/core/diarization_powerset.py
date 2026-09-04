"""
Diarization built on our own powerset decode, for the "powerset" engine.

Why this exists rather than just calling sherpa-onnx: see
config.DIARIZATION_ENGINE. In short, sherpa runs the whole pipeline behind
one call and its decode is a fixed argmax operating point, so the two things
that measurement said actually matter here are both out of reach through it -
choosing where to threshold, and choosing what audio the speaker embeddings
are computed over.

What is NOT rewritten: the embedding extractor and the clustering are still
sherpa's (SpeakerEmbeddingExtractor and FastClustering, both usable
standalone from Python). Hand-writing an 80-dim Kaldi filterbank with the
right normalisation, or an agglomerative clustering, would be a lot of
delicate code with no measurement saying it would be any better. What this
module owns is the middle: which frames belong to whom, and which audio each
speaker's embedding is computed from.

The shape of the pipeline, and why it is this shape:

    1. Decode each 10s window into per-speaker marginals (core/segmentation).
    2. Binarise each window ON ITS OWN. Window-local speaker indices are not
       comparable across windows, and pyannote 3.1 does not try to make them
       comparable by aligning neighbours - a single bad alignment early in a
       file would propagate through everything after it.
    3. Embed each (window, local speaker) that has enough CLEAN speech.
    4. Cluster those embeddings into the requested number of speakers.
       Alignment falls out of this: two windows' local speakers end up in the
       same cluster precisely when they sound like the same person.
    5. Reconstruct one global track per cluster and cut it into spans.

Overlapping spans are a normal output, not an error - the same as sherpa
already returns, and what SpeakerSpan and the DER metric both already handle.

MEASURED, including one result that went the wrong way. On 300s of AMI at
num_speakers=4, against sherpa's DER 0.4646 (missed 16.29, false alarm 9.40,
confusion 46.51):

    embeddings from clean frames only   DER 0.4085  miss 14.36  FA 13.43  conf 35.68
    embeddings from all active frames   DER 0.4011  miss 14.83  FA 13.21  conf 34.29

Confusion - the error that dominates this pipeline and the one a user sees as
"one speaker got all the sentences" - falls by about a quarter. But masking
overlap out of the embeddings, which was the stated reason to expect that
fall, is very slightly WORSE than not masking. So the improvement comes from
owning the decode and its threshold, not from clean embeddings, and
mask_overlap defaults to False accordingly. The idea is recorded here rather
than deleted so nobody re-derives it from first principles and re-adds it.

Both runs above returned 3 speakers for a requested 4, which looked like a
merge bug and is not one: the first 300s of ES2004a has only THREE speakers
in it (MEE014 does not talk until later in the file), so 3 was the right
answer and those runs were forcing a fourth cluster onto audio with no fourth
speaker. Worth stating because the reconstruction below DOES have a rule that
can erase a real speaker - see _reconstruct - and it would be easy to misread
one as evidence of the other.
"""

import logging
from typing import Callable, List, Optional, Sequence, Tuple

import numpy as np

from speech_to_text import config
from speech_to_text.core import segmentation as seg

logger = logging.getLogger(__name__)


def diarize_powerset(
    samples: np.ndarray,
    sample_rate: int = 16000,
    num_speakers: int = 2,
    progress: Optional[Callable[[int, int], None]] = None,
    onset: Optional[float] = None,
    mask_overlap: bool = False,
) -> List:
    """
    Label who is speaking, decoding the segmentation model directly.

    Same contract as core.diarization.diarize: float32 mono audio in,
    speaker-labelled spans sorted by start time out.

    mask_overlap exists for measurement, and it defaults to False because the
    measurement went against it - see the module docstring. True computes each
    speaker's embedding only from frames where they are the sole active
    speaker; False uses every frame they are active in, overlap included.
    Kept switchable so the A/B stays reproducible, not because it is a knob
    worth turning in production.
    """
    # Imported here, not at module scope: core/ is imported by the GUI
    # process too, and sherpa-onnx must not be a hard import for code paths
    # that never diarize (see core/diarization.py's own local import).
    from speech_to_text.core.diarization import (
        DiarizationUnavailable,
        SpeakerSpan,
        _EMBEDDING_MODEL,
        _SEGMENTATION_MODEL,
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

    active = marginals >= onset                                  # (W, F, K)
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


def _providers(name: str) -> List[str]:
    """onnxruntime provider list, falling back to CPU if the name is unknown."""
    available = {"cpu": "CPUExecutionProvider", "cuda": "CUDAExecutionProvider"}
    return [available.get(name.lower(), "CPUExecutionProvider")]


def _infer_with_progress(session, samples, progress):
    """
    infer_marginals, reporting progress per window.

    Reimplemented here rather than adding a callback to segmentation.py, so
    that module stays free of anything but arithmetic and remains testable
    without a model or a progress sink.
    """
    starts = seg.window_starts(len(samples))
    matrix = seg.powerset_matrix()
    out = np.empty(
        (len(starts), seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=np.float32
    )
    for index, start in enumerate(starts):
        window = samples[start:start + seg.WINDOW_SAMPLES]
        if len(window) < seg.WINDOW_SAMPLES:
            window = np.pad(window, (0, seg.WINDOW_SAMPLES - len(window)))
        logits = session.run(
            None, {"x": window.reshape(1, 1, -1).astype(np.float32)}
        )[0]
        out[index] = seg.softmax(logits[0]) @ matrix
        if progress:
            progress(index + 1, len(starts))
    return out, starts


def _frame_samples(window_start: int, frame_index: int) -> Tuple[int, int]:
    """Sample range one frame's receptive field covers."""
    begin = window_start + frame_index * seg.FRAME_SHIFT_SAMPLES
    return begin, begin + seg.RECEPTIVE_FIELD_SAMPLES


def _embed_windows(
    sherpa_onnx,
    model_path: str,
    samples: np.ndarray,
    active: np.ndarray,
    starts: Sequence[int],
    mask_overlap: bool,
) -> Tuple[List[np.ndarray], List[Tuple[int, int]]]:
    """
    One embedding per (window, local speaker) that has enough usable speech.

    Returns the embeddings and, alongside them, the (window, speaker) each one
    came from - `owners` is what lets the cluster labels be mapped back onto
    the right slice of the activity tensor afterwards.

    The audio fed to the extractor is the CONCATENATION of that speaker's
    frames, not a full window with everything else zeroed out. Both give the
    extractor only that speaker's voice; concatenating gives it 1-3s of audio
    instead of a 10s window that is mostly silence, which is where the speed
    difference in this pipeline comes from. The cost is a splice discontinuity
    at each joint, which the filterbank sees as a transient - one reason
    mask_overlap is switchable rather than assumed.
    """
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(
        sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=model_path,
            num_threads=config.DIARIZATION_NUM_THREADS,
            provider=config.DIARIZATION_PROVIDER,
        )
    )
    minimum = int(config.DIARIZATION_EMBED_MIN_CLEAN_SECONDS * seg.SAMPLE_RATE)

    embeddings: List[np.ndarray] = []
    owners: List[Tuple[int, int]] = []
    for window_index, start in enumerate(starts):
        window_active = active[window_index]                     # (F, K)
        alone = window_active.sum(axis=1) == 1                   # (F,)
        for speaker in range(seg.NUM_LOCAL_SPEAKERS):
            usable = window_active[:, speaker]
            if mask_overlap:
                usable = usable & alone
            if not usable.any():
                continue

            audio = _gather(samples, start, usable)
            if len(audio) < minimum:
                # Not enough evidence to say who this is. Leaving it out is
                # not the same as dropping the speech: roughly ten windows
                # cover every moment, so a frame skipped here is almost
                # always claimed by a neighbouring window that did have a
                # confident view of it.
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


def _mask_runs(mask: np.ndarray) -> List[Tuple[int, int]]:
    """Contiguous True stretches of a boolean array, as [begin, end) indices."""
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2].tolist(), edges[1::2].tolist()))


def _cluster(sherpa_onnx, embeddings: List[np.ndarray], num_speakers: int) -> List[int]:
    """
    Group (window, speaker) embeddings into speakers.

    num_speakers <= 0 means "infer", which hands the decision to the
    threshold. The GUI never sends that today (its spin box is 2-10), so in
    practice this is an exact count.
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
    owners: Sequence[Tuple[int, int]],
    labels: Sequence[int],
    num_samples: int,
) -> np.ndarray:
    """
    Fold every window's local speakers into global per-cluster activity.

    This is where cross-window alignment finally happens, and it happens by
    cluster membership rather than by comparing neighbouring windows to each
    other. Each covering window casts a vote for "is cluster c talking here",
    and a moment is called active for c when more than half of them say so -
    so one window's mistake is outvoted rather than propagated.

    The majority rule has a real cost, measured rather than assumed: a speaker
    that few windows ever resolve as their own local speaker can never reach
    half the votes, so they are erased entirely rather than merely
    under-detected. Lowering the bar does recover them, and cuts confusion
    with it, but at a price not worth paying on this audio - measured on 300s
    of AMI, share 0.50 gives DER 0.4011 at false alarm 13.21, while share 0.25
    gives DER 0.5412 at false alarm 51.85. Half stays, and the trade-off is
    written down here so the next person does not have to rediscover which
    direction it runs.
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


def _tracks_to_spans(span_type, tracks: np.ndarray) -> List:
    """
    Cut each cluster's boolean track into spans, applying the duration floors.

    min_duration_off is applied before min_duration_on deliberately: bridging
    a short pause first means a turn briefly interrupted by a breath is judged
    on its whole length, rather than being split into two fragments that each
    then look too short to keep.
    """
    spans = []
    for speaker in range(tracks.shape[1]):
        intervals = seg.runs_to_intervals(tracks[:, speaker])
        intervals = _bridge(intervals, config.DIARIZATION_MIN_DURATION_OFF)
        for start, end in intervals:
            if end - start >= config.DIARIZATION_MIN_DURATION_ON:
                spans.append(span_type(start=start, end=end, speaker=speaker))
    spans.sort(key=lambda s: (s.start, s.end, s.speaker))
    return spans


def _bridge(
    intervals: List[Tuple[float, float]], max_gap: float
) -> List[Tuple[float, float]]:
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
