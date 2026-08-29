"""
Decode math for core/segmentation.py.

Every test here runs on synthetic logits and a fake ONNX session, so the whole
file passes with no model downloaded and no audio - which is the point. The
decode is arithmetic with several off-by-one traps in it (class ordering,
frame-centre timing, the window-to-global-grid identity), and those are
exactly the mistakes that produce a plausible-looking but silently shifted
result against real audio. Catching them here is much cheaper than catching
them in a DER number.
"""

import itertools

import numpy as np
import pytest

from speech_to_text.core import segmentation as seg


class FakeSession:
    """
    Stands in for an onnxruntime InferenceSession.

    Returns logits shaped exactly as the real model does, (1, 589, 7), taken
    from a per-window queue so a test can dictate what each window "hears".
    """

    def __init__(self, per_window_logits):
        self._queue = list(per_window_logits)
        self.calls = []

    def run(self, _outputs, feeds):
        self.calls.append(feeds["x"].shape)
        return [self._queue.pop(0)[None, :, :]]


def logits_for(class_index, frames=seg.FRAMES_PER_WINDOW, confidence=20.0):
    """Logits whose softmax is ~1.0 on one powerset class for every frame."""
    out = np.zeros((frames, seg.NUM_CLASSES), dtype=np.float32)
    out[:, class_index] = confidence
    return out


class TestPowersetOrdering:

    def test_matches_pyannote_combinations_construction(self):
        """
        The class order is a wire format shared with a model file we do not
        build. Deriving it independently here means a future pyannote change
        fails loudly instead of silently permuting speakers.
        """
        expected = []
        for size in range(0, 3):
            expected.extend(itertools.combinations(range(seg.NUM_LOCAL_SPEAKERS), size))
        assert seg.powerset_classes() == expected

    def test_matrix_marks_exactly_the_speakers_each_class_means(self):
        matrix = seg.powerset_matrix()
        assert matrix.shape == (seg.NUM_CLASSES, seg.NUM_LOCAL_SPEAKERS)
        assert matrix[0].tolist() == [0, 0, 0]      # silence
        assert matrix[1].tolist() == [1, 0, 0]      # {0}
        assert matrix[3].tolist() == [0, 0, 1]      # {2}
        assert matrix[4].tolist() == [1, 1, 0]      # {0,1}
        assert matrix[6].tolist() == [0, 1, 1]      # {1,2}

    def test_overlap_classes_mark_two_speakers_each(self):
        matrix = seg.powerset_matrix()
        assert matrix[4:].sum(axis=1).tolist() == [2.0, 2.0, 2.0]


class TestSoftmax:

    def test_rows_sum_to_one(self):
        rng = np.random.default_rng(0)
        out = seg.softmax(rng.normal(size=(5, seg.NUM_CLASSES)).astype(np.float32))
        assert np.allclose(out.sum(axis=-1), 1.0)

    def test_handles_the_models_actual_scale_without_overflow(self):
        """
        Real output is logits summing to about -105 for one frame. A naive
        exp() without the max-shift would underflow to all zeros here and
        produce nan on the divide.
        """
        out = seg.softmax(np.full((1, seg.NUM_CLASSES), -700.0, dtype=np.float32))
        assert np.isfinite(out).all()
        assert np.allclose(out.sum(), 1.0)


class TestWindowStarts:

    def test_audio_shorter_than_one_window_is_a_single_window(self):
        assert seg.window_starts(1000) == [0]
        assert seg.window_starts(seg.WINDOW_SAMPLES) == [0]

    def test_windows_step_by_a_whole_number_of_frames(self):
        starts = seg.window_starts(seg.WINDOW_SAMPLES * 3)
        steps = {b - a for a, b in zip(starts, starts[1:])}
        # Every step except possibly the final catch-up one is exactly the hop.
        assert seg.WINDOW_HOP_SAMPLES in steps
        for step in steps:
            assert step <= seg.WINDOW_HOP_SAMPLES

    def test_last_window_reaches_the_end_of_the_audio(self):
        n = seg.WINDOW_SAMPLES * 3 + 12345
        starts = seg.window_starts(n)
        assert starts[-1] + seg.WINDOW_SAMPLES == n

    def test_hop_is_a_whole_number_of_frame_shifts(self):
        """The property the exact grid identity depends on."""
        assert seg.WINDOW_HOP_SAMPLES % seg.FRAME_SHIFT_SAMPLES == 0
        assert seg.WINDOW_HOP_SAMPLES // seg.FRAME_SHIFT_SAMPLES == seg.WINDOW_HOP_FRAMES


class TestFrameTiming:

    def test_first_frame_centres_half_a_receptive_field_in(self):
        expected = ((seg.RECEPTIVE_FIELD_SAMPLES - 1) / 2.0) / seg.SAMPLE_RATE
        assert seg.frame_center_time(0, 0) == pytest.approx(expected)

    def test_successive_frames_are_one_shift_apart(self):
        step = seg.frame_center_time(0, 1) - seg.frame_center_time(0, 0)
        assert step == pytest.approx(seg.FRAME_SHIFT_SAMPLES / seg.SAMPLE_RATE)

    def test_window_of_589_frames_spans_about_ten_seconds(self):
        last = seg.frame_center_time(0, seg.FRAMES_PER_WINDOW - 1)
        assert 9.8 < last < 10.0

    def test_grid_identity_window_j_frame_i_is_59j_plus_i(self):
        """
        The reason the hop is expressed in frames. Window j's frame i must
        land on global index 59*j + i exactly, with no rounding - a drifting
        grid would smear every span by a growing amount over a long file.
        """
        for j in range(0, 12):
            start = j * seg.WINDOW_HOP_SAMPLES
            for i in (0, 1, 300, seg.FRAMES_PER_WINDOW - 1):
                grid = seg._grid_base(start) + i
                assert grid == seg.WINDOW_HOP_FRAMES * j + i
                assert seg.frame_center_time(start, i) == pytest.approx(
                    seg.grid_times(grid + 1)[grid]
                )


class TestInferMarginals:

    def test_silence_class_yields_no_active_speakers(self):
        session = FakeSession([logits_for(0)])
        marginals, starts = seg.infer_marginals(session, np.zeros(seg.WINDOW_SAMPLES, np.float32))
        assert starts == [0]
        assert marginals.shape == (1, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS)
        assert marginals.max() < 1e-3

    def test_single_speaker_class_activates_exactly_that_speaker(self):
        session = FakeSession([logits_for(2)])          # class 2 == {1}
        marginals, _ = seg.infer_marginals(session, np.zeros(seg.WINDOW_SAMPLES, np.float32))
        assert marginals[0, 0, 1] == pytest.approx(1.0, abs=1e-3)
        assert marginals[0, 0, 0] < 1e-3
        assert marginals[0, 0, 2] < 1e-3

    def test_overlap_class_activates_both_of_its_speakers(self):
        session = FakeSession([logits_for(4)])          # class 4 == {0,1}
        marginals, _ = seg.infer_marginals(session, np.zeros(seg.WINDOW_SAMPLES, np.float32))
        assert marginals[0, 0, 0] == pytest.approx(1.0, abs=1e-3)
        assert marginals[0, 0, 1] == pytest.approx(1.0, abs=1e-3)
        assert marginals[0, 0, 2] < 1e-3

    def test_marginal_sums_probability_across_every_class_containing_a_speaker(self):
        """
        The property that makes a marginal threshold different from an argmax:
        probability split across two classes that both contain speaker 0 still
        adds up for speaker 0, even when neither class wins the argmax.
        """
        raw = np.zeros((seg.FRAMES_PER_WINDOW, seg.NUM_CLASSES), dtype=np.float32)
        raw[:, 1] = 1.0      # {0}
        raw[:, 4] = 1.0      # {0,1}
        raw[:, 0] = 1.3      # silence wins the argmax
        session = FakeSession([raw])
        marginals, _ = seg.infer_marginals(session, np.zeros(seg.WINDOW_SAMPLES, np.float32))

        probs = seg.softmax(raw)
        assert probs[0].argmax() == 0                       # argmax says silence
        # Every class containing speaker 0 counts: {0}, {0,1} AND {0,2} - the
        # last one has a zero logit, not zero probability.
        expected = probs[0, 1] + probs[0, 4] + probs[0, 5]
        assert marginals[0, 0, 0] == pytest.approx(expected)
        assert marginals[0, 0, 0] > 0.4                     # marginal says speaker 0

    def test_short_audio_is_padded_to_a_full_window(self):
        session = FakeSession([logits_for(0)])
        seg.infer_marginals(session, np.zeros(1000, dtype=np.float32))
        assert session.calls == [(1, 1, seg.WINDOW_SAMPLES)]


class TestAggregateInvariants:

    def test_single_window_reports_speech_and_count(self):
        marginals = np.zeros((1, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), np.float32)
        marginals[0, :100, 0] = 0.9                       # one speaker
        marginals[0, 100:200, :2] = 0.9                   # two speakers
        speech, count = seg.aggregate_invariants(marginals, [0], onset=0.5)

        assert speech[50] == pytest.approx(1.0)
        assert count[50] == pytest.approx(1.0)
        assert count[150] == pytest.approx(2.0)
        assert speech[300] == pytest.approx(0.0)

    def test_onset_controls_what_counts_as_active(self):
        marginals = np.full((1, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), 0.0, np.float32)
        marginals[0, :, 0] = 0.45
        high, _ = seg.aggregate_invariants(marginals, [0], onset=0.5)
        low, _ = seg.aggregate_invariants(marginals, [0], onset=0.4)
        assert high[10] == pytest.approx(0.0)
        assert low[10] == pytest.approx(1.0)

    def test_is_invariant_to_permuting_local_speaker_indices(self):
        """
        The property the whole function is built around. Two windows may order
        their local speakers differently; pooling must not care.
        """
        rng = np.random.default_rng(3)
        marginals = rng.random((4, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS)).astype(np.float32)
        starts = [j * seg.WINDOW_HOP_SAMPLES for j in range(4)]

        shuffled = marginals.copy()
        shuffled[1] = shuffled[1][:, [2, 0, 1]]
        shuffled[3] = shuffled[3][:, [1, 2, 0]]

        a = seg.aggregate_invariants(marginals, starts, onset=0.5)
        b = seg.aggregate_invariants(shuffled, starts, onset=0.5)
        assert np.allclose(a[0], b[0])
        assert np.allclose(a[1], b[1])

    def test_overlapping_windows_average_their_votes(self):
        marginals = np.zeros((2, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), np.float32)
        marginals[0, :, 0] = 0.9        # window 0 hears speech everywhere
        marginals[1, :, 0] = 0.0        # window 1 hears nothing
        starts = [0, seg.WINDOW_HOP_SAMPLES]
        speech, _ = seg.aggregate_invariants(marginals, starts, onset=0.5)

        # Frames only window 0 covers, then frames both cover.
        assert speech[10] == pytest.approx(1.0)
        assert speech[seg.WINDOW_HOP_FRAMES + 10] == pytest.approx(0.5)

    def test_grid_is_truncated_to_the_real_audio_length(self):
        """Padding at the tail must not invent frames past the end."""
        marginals = np.ones((1, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), np.float32)
        speech, _ = seg.aggregate_invariants(
            marginals, [0], onset=0.5, num_samples=seg.FRAME_SHIFT_SAMPLES * 100
        )
        assert len(speech) == 100


class TestRunsToIntervals:

    def test_empty_mask_gives_no_intervals(self):
        assert seg.runs_to_intervals(np.zeros(10, dtype=bool)) == []

    def test_contiguous_run_becomes_one_interval(self):
        mask = np.zeros(100, dtype=bool)
        mask[10:20] = True
        intervals = seg.runs_to_intervals(mask)
        assert len(intervals) == 1
        start, end = intervals[0]
        assert start == pytest.approx(seg.grid_times(100)[10])
        assert end > start

    def test_two_runs_stay_separate(self):
        mask = np.zeros(100, dtype=bool)
        mask[10:20] = True
        mask[40:50] = True
        assert len(seg.runs_to_intervals(mask)) == 2

    def test_single_frame_run_carries_one_frame_of_duration(self):
        mask = np.zeros(10, dtype=bool)
        mask[5] = True
        (start, end), = seg.runs_to_intervals(mask)
        assert end - start == pytest.approx(seg.FRAME_SHIFT_SAMPLES / seg.SAMPLE_RATE)

    def test_min_duration_drops_short_runs(self):
        mask = np.zeros(200, dtype=bool)
        mask[10] = True            # one frame, ~17ms
        mask[100:150] = True       # ~840ms
        assert len(seg.runs_to_intervals(mask, min_duration=0.5)) == 1
