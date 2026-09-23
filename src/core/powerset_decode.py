"""Powerset decoding of the pyannote segmentation-3.0 ONNX model.

Why own the decode when core/diarization.py already runs this model through
sherpa-onnx: sherpa's decode is sealed in C++ and takes an argmax over the 7
powerset classes, which is a fixed operating point. On 300s of AMI, argmax
finds 138.7s of the 150.0s of reference speech and 1.6s of its 5.4s of
overlap; thresholding the per-speaker MARGINAL at 0.40 instead finds 148.0s
of speech and 4.5s of overlap, from the same forward pass and the same model.
That threshold is the entire reason this file exists - a from-scratch decode
reproducing argmax was measured within 0.4s of sherpa's spans over 60s.

Numpy and onnxruntime only: no sherpa_onnx, no application state, no
clustering. Every function is pure, so the decode is testable on synthetic
logits with no model file - which matters because it is arithmetic with
several off-by-one traps in it (window_starts, and the grid identity in
aggregate_invariants).

What it deliberately does NOT do is decide global speaker identity. The model
emits at most 3 speakers per 10s window and those indices are LOCAL - one
window's "speaker 1" has no relationship to the next window's. Aligning them
is a clustering problem, and pyannote 3.1 does not try to solve it by
comparing neighbouring windows either (skip_aggregation=True, identity left
to clustering). So marginals are returned per window, unaggregated, and the
only quantities aggregated across windows here are the two that survive an
unknown permutation: "is anyone speaking" and "how many".
"""

from collections.abc import Sequence
from typing import Any

import numpy as np

# All six constants are read from the shipped model's own ONNX metadata
# rather than hardcoded from the pyannote paper - verified against
# diarization_models/sherpa-onnx-pyannote-segmentation-3-0/model.onnx, whose
# metadata map declares sample_rate 16000, window_size 160000, num_speakers 3,
# num_classes 7, powerset_max_classes 2, receptive_field_shift 270 and
# receptive_field_size 991.
SAMPLE_RATE = 16000
WINDOW_SAMPLES = 160000  # 10.0s
FRAME_SHIFT_SAMPLES = 270  # 0.016875s
RECEPTIVE_FIELD_SAMPLES = 991
FRAMES_PER_WINDOW = 589  # confirmed live: y.shape == (N, 589, 7)
NUM_LOCAL_SPEAKERS = 3
NUM_CLASSES = 7

# The hop between windows, expressed in FRAMES rather than seconds, and this
# is load-bearing. pyannote's pipeline steps by 10% of the window, i.e. 1.0s,
# but 16000 is not a multiple of 270: a 1.0s hop puts each window's frames on
# a slightly different sub-grid, so mapping them onto one global timeline
# needs rounding, and the rounding error accumulates over a long file. Making
# the hop an exact multiple of the frame shift removes the problem entirely -
# window j's frame i lands on global grid index exactly 59*j + i, integer
# arithmetic, no drift, and directly assertable in a test.
#
# 59 frames = 15930 samples = 0.995625s, within half a percent of pyannote's
# own 1.0s step, so each grid point is still covered by about ten windows.
WINDOW_HOP_FRAMES = 59
WINDOW_HOP_SAMPLES = WINDOW_HOP_FRAMES * FRAME_SHIFT_SAMPLES  # 15930


def powerset_matrix() -> np.ndarray:
    """The (7, 3) indicator mapping each powerset class to the speakers it means."""
    matrix = np.zeros((NUM_CLASSES, NUM_LOCAL_SPEAKERS), dtype=np.float32)
    for class_index, speakers in enumerate(powerset_classes()):
        for speaker in speakers:
            matrix[class_index, speaker] = 1.0
    return matrix


def powerset_classes() -> list[tuple[int, ...]]:
    """The speaker set each of the 7 classes stands for, in model order.

    Silence, the singletons in speaker order, then the pairs lexicographically:

        0 -> {}       1 -> {0}     2 -> {1}     3 -> {2}
        4 -> {0,1}    5 -> {0,2}   6 -> {1,2}

    A literal rather than the itertools.combinations construction pyannote
    uses, because the ordering is a wire format shared with a model file we do
    not build: silently regenerating a changed order would mislabel every
    speaker while still "working". A test asserts the two agree.
    """
    return [(), (0,), (1,), (2,), (0, 1), (0, 2), (1, 2)]


def softmax(logits: np.ndarray) -> np.ndarray:
    """Row-wise softmax over the last axis.

    The model emits LOGITS, not probabilities - a single frame's 7 values were
    measured summing to -105.77 on a live run - so thresholding without this
    would be meaningless.
    """
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    normalised: np.ndarray = exp / exp.sum(axis=-1, keepdims=True)
    return normalised


def window_starts(num_samples: int) -> list[int]:
    """Start sample of every analysis window covering num_samples of audio.

    Always at least one window. Short audio, and the tail after the last whole
    hop, are both handled by the caller zero-padding to WINDOW_SAMPLES rather
    than feeding the model a short input: the ONNX graph accepts a dynamic
    length, but the model was trained on 10s windows and anything shorter is
    off-distribution. Frames whose receptive field falls entirely past the real
    end of the audio are dropped later (see _grid_size), so padding cannot
    invent speech.
    """
    if num_samples <= WINDOW_SAMPLES:
        return [0]
    last_full = num_samples - WINDOW_SAMPLES
    starts = list(range(0, last_full + 1, WINDOW_HOP_SAMPLES))
    # The final hop rarely lands exactly on the end. One extra window, pinned
    # to the last full window's worth of audio, covers the remainder without
    # a short input.
    if starts[-1] != last_full:
        starts.append(last_full)
    return starts


def frame_center_time(window_start: int, frame_index: int) -> float:
    """Time in seconds at the centre of one frame's receptive field.

    Frame i of a window starting at sample a sees [a + i*SHIFT, +SIZE). The
    centre, not the left edge: the model's opinion at frame i is about the
    middle of what it can see, and anchoring to the edge would shift every span
    about 31ms early.
    """
    center_sample = window_start + frame_index * FRAME_SHIFT_SAMPLES
    return (center_sample + (RECEPTIVE_FIELD_SAMPLES - 1) / 2.0) / SAMPLE_RATE


def infer_marginals(session: Any, samples: np.ndarray) -> tuple[np.ndarray, list[int]]:
    """Run the model over every window and return per-speaker marginals.

    Returns (marginals, starts), marginals shaped
    (num_windows, FRAMES_PER_WINDOW, NUM_LOCAL_SPEAKERS): the probability that
    a local speaker is talking in a frame, summed over every powerset class
    containing them.

    Stops before stitching windows together, so the part that needs clustering
    to be correct is not buried inside the part that is just arithmetic.
    """
    starts = window_starts(len(samples))
    matrix = powerset_matrix()

    out = np.empty((len(starts), FRAMES_PER_WINDOW, NUM_LOCAL_SPEAKERS), dtype=np.float32)
    for index, start in enumerate(starts):
        window = samples[start : start + WINDOW_SAMPLES]
        if len(window) < WINDOW_SAMPLES:
            window = np.pad(window, (0, WINDOW_SAMPLES - len(window)))
        logits = session.run(None, {"x": window.reshape(1, 1, -1).astype(np.float32)})[0]
        out[index] = softmax(logits[0]) @ matrix
    return out, starts


def aggregate_invariants(
    marginals: np.ndarray,
    starts: Sequence[int],
    onset: float,
    num_samples: int | None = None,
) -> tuple[np.ndarray, np.ndarray]:
    """Fold overlapping windows into two global tracks that survive permutation.

    Returns (speech, count) over a global frame grid: speech[g] is the
    fraction of windows covering g that saw ANY speaker active, count[g] the
    mean number they saw, both from each window's own binarised opinion at
    `onset`.

    Only these two, and the name says why: speaker indices are local to a
    window, so summing marginals[..., k] across windows would add one window's
    "speaker 1" to another's unrelated one. "Someone is talking" and "two
    people are talking" mean the same thing under any permutation of the local
    speakers, so they pool without knowing it.

    The grid identity is exact - window j's frame i is global index
    WINDOW_HOP_FRAMES*j + i, no rounding, because the hop is a whole number of
    frame shifts. That holds for the evenly spaced windows only; the catch-up
    window window_starts may append is placed from its own sample offset.
    """
    active = marginals >= onset  # (W, F, K)
    any_active = np.asarray(active.any(axis=2))  # (W, F)
    how_many = active.sum(axis=2)  # (W, F)

    grid_size = _grid_size(starts, num_samples)
    speech_sum = np.zeros(grid_size, dtype=np.float64)
    count_sum = np.zeros(grid_size, dtype=np.float64)
    votes = np.zeros(grid_size, dtype=np.float64)

    for index, start in enumerate(starts):
        base = _grid_base(start)
        stop = min(base + FRAMES_PER_WINDOW, grid_size)
        width = stop - base
        if width <= 0:
            continue
        speech_sum[base:stop] += any_active[index, :width]
        count_sum[base:stop] += how_many[index, :width]
        votes[base:stop] += 1.0

    seen = votes > 0
    speech = np.zeros(grid_size, dtype=np.float64)
    count = np.zeros(grid_size, dtype=np.float64)
    speech[seen] = speech_sum[seen] / votes[seen]
    count[seen] = count_sum[seen] / votes[seen]
    return speech, count


def _grid_base(window_start: int) -> int:
    """Global grid index of a window's first frame.

    Exact for every evenly spaced window. The catch-up window window_starts
    appends is off that lattice, so it rounds to the nearest frame - a sub-17ms
    placement error on one window at the very end of the file.
    """
    return int(round(window_start / FRAME_SHIFT_SAMPLES))


def _grid_size(starts: Sequence[int], num_samples: int | None) -> int:
    by_windows = _grid_base(starts[-1]) + FRAMES_PER_WINDOW
    if num_samples is None:
        return by_windows
    # Never report frames whose centre lies past the real end of the audio:
    # those exist only because the last window was zero-padded.
    by_audio = int(np.ceil(num_samples / FRAME_SHIFT_SAMPLES))
    return max(1, min(by_windows, by_audio))


def grid_times(grid_size: int) -> np.ndarray:
    """Centre time of every global grid frame, in seconds."""
    index = np.arange(grid_size, dtype=np.float64)
    center = index * FRAME_SHIFT_SAMPLES + (RECEPTIVE_FIELD_SAMPLES - 1) / 2.0
    return center / SAMPLE_RATE


def runs_to_intervals(mask: np.ndarray, min_duration: float = 0.0) -> list[tuple[float, float]]:
    """Contiguous True stretches of a per-frame mask, as (start, end) seconds.

    Edges are frame centres, so a single-frame run would have zero width; it
    is returned as [t, t + frame_shift) instead, so a lone frame carries the
    duration it represents rather than vanishing.
    """
    if mask.size == 0:
        return []
    frame = FRAME_SHIFT_SAMPLES / SAMPLE_RATE
    times = grid_times(len(mask))

    intervals: list[tuple[float, float]] = []
    padded = np.concatenate(([False], mask.astype(bool), [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    for begin, finish in zip(edges[0::2], edges[1::2]):
        start = float(times[begin])
        end = float(times[finish - 1]) + frame
        if end - start >= min_duration:
            intervals.append((start, end))
    return intervals
