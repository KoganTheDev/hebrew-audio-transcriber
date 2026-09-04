"""
Tests for the opt-in "powerset" diarization engine.

This module only runs when config.DIARIZATION_ENGINE is flipped, so nothing
in the default path exercises it - which is exactly how a pipeline rots into
dead code that still imports cleanly. Everything below runs without
onnxruntime, sherpa-onnx or a model file: the decode arithmetic is already
pure (core/segmentation.py), and the two library boundaries - an ONNX session
and the sherpa embedding/clustering objects - are narrow enough to stand in
for with fakes, so the parts that carry the measured behaviour (the majority
vote in _reconstruct, the duration floors in _tracks_to_spans, which audio an
embedding is computed over) can be asserted directly.

The stubs are planted in sys.modules rather than patched onto the module,
because diarize_powerset imports onnxruntime and sherpa_onnx *locally* inside
the function - the same trap tests/test_diarization.py documents.
"""

import sys
import types

import numpy as np
import pytest

from speech_to_text import config
from speech_to_text.core import diarization_powerset as dp
from speech_to_text.core import segmentation as seg
from speech_to_text.core.diarization import DiarizationUnavailable, SpeakerSpan


class TestProviders:
    def test_known_provider_names_map_to_onnxruntime_names(self):
        assert dp._providers("cpu") == ["CPUExecutionProvider"]
        assert dp._providers("cuda") == ["CUDAExecutionProvider"]

    def test_provider_name_is_case_insensitive(self):
        assert dp._providers("CUDA") == ["CUDAExecutionProvider"]

    def test_unknown_provider_falls_back_to_cpu_rather_than_raising(self):
        """A bad DIARIZATION_PROVIDER must not be fatal - CPU always exists."""
        assert dp._providers("tpu") == ["CPUExecutionProvider"]


class TestFrameSamples:
    def test_frame_zero_starts_at_the_window_start(self):
        assert dp._frame_samples(1000, 0) == (1000, 1000 + seg.RECEPTIVE_FIELD_SAMPLES)

    def test_each_frame_advances_by_exactly_one_frame_shift(self):
        first, _ = dp._frame_samples(0, 3)
        second, _ = dp._frame_samples(0, 4)
        assert second - first == seg.FRAME_SHIFT_SAMPLES

    def test_receptive_fields_of_adjacent_frames_overlap(self):
        """The receptive field is far wider than the hop, so frames overlap
        heavily - that is why _gather concatenates runs rather than frames."""
        _, first_end = dp._frame_samples(0, 0)
        second_begin, _ = dp._frame_samples(0, 1)
        assert second_begin < first_end


class TestMaskRuns:
    def test_returns_half_open_index_ranges(self):
        mask = np.array([False, True, True, False])
        assert dp._mask_runs(mask) == [(1, 3)]

    def test_finds_several_separated_runs(self):
        mask = np.array([True, False, True, True, False, True])
        assert dp._mask_runs(mask) == [(0, 1), (2, 4), (5, 6)]

    def test_a_run_touching_the_end_is_closed_off(self):
        assert dp._mask_runs(np.array([False, True, True])) == [(1, 3)]

    def test_an_all_false_mask_has_no_runs(self):
        assert dp._mask_runs(np.zeros(5, dtype=bool)) == []


class TestGather:
    def test_concatenates_only_the_audio_under_the_active_frames(self):
        samples = np.arange(20000, dtype=np.float32)
        mask = np.zeros(4, dtype=bool)
        mask[1] = True
        gathered = dp._gather(samples, 0, mask)

        begin, end = dp._frame_samples(0, 1)
        assert np.array_equal(gathered, samples[begin:end])

    def test_two_separated_runs_are_spliced_into_one_array(self):
        samples = np.arange(30000, dtype=np.float32)
        mask = np.zeros(6, dtype=bool)
        mask[0] = True
        mask[4] = True
        gathered = dp._gather(samples, 0, mask)

        first = dp._frame_samples(0, 0)
        second = dp._frame_samples(0, 4)
        expected = np.concatenate([samples[first[0] : first[1]], samples[second[0] : second[1]]])
        assert np.array_equal(gathered, expected)

    def test_a_run_running_past_the_end_of_the_audio_is_clipped(self):
        samples = np.arange(500, dtype=np.float32)
        mask = np.array([True])
        assert len(dp._gather(samples, 0, mask)) == 500

    def test_an_empty_mask_gathers_nothing_rather_than_raising(self):
        gathered = dp._gather(np.zeros(1000, dtype=np.float32), 0, np.zeros(3, dtype=bool))
        assert gathered.shape == (0,)
        assert gathered.dtype == np.float32

    def test_a_run_entirely_past_the_end_of_the_audio_contributes_nothing(self):
        samples = np.zeros(100, dtype=np.float32)
        mask = np.zeros(5, dtype=bool)
        mask[4] = True
        assert len(dp._gather(samples, 0, mask)) == 0


class TestBridge:
    def test_intervals_closer_than_the_gap_are_joined(self):
        assert dp._bridge([(0.0, 1.0), (1.2, 2.0)], 0.5) == [(0.0, 2.0)]

    def test_intervals_further_apart_than_the_gap_are_left_alone(self):
        intervals = [(0.0, 1.0), (3.0, 4.0)]
        assert dp._bridge(intervals, 0.5) == intervals

    def test_a_gap_exactly_at_the_limit_is_not_bridged(self):
        assert dp._bridge([(0.0, 1.0), (1.5, 2.0)], 0.5) == [(0.0, 1.0), (1.5, 2.0)]

    def test_a_contained_interval_does_not_shorten_the_one_it_joins(self):
        """max() on the end, not the later end: an interval swallowed whole by
        its predecessor must not pull the joined end backwards."""
        assert dp._bridge([(0.0, 5.0), (1.0, 2.0)], 0.5) == [(0.0, 5.0)]

    def test_no_intervals_bridge_to_no_intervals(self):
        assert dp._bridge([], 0.5) == []


class TestTracksToSpans:
    """
    The duration floors, and the order they are applied in. min_duration_off
    runs first on purpose - a turn interrupted by a breath is judged on its
    whole length rather than as two fragments that each look too short.
    """

    def _track(self, frames, active_ranges):
        track = np.zeros((frames, 1), dtype=bool)
        for begin, end in active_ranges:
            track[begin:end, 0] = True
        return track

    def _frames_for(self, seconds):
        return int(np.ceil(seconds * seg.SAMPLE_RATE / seg.FRAME_SHIFT_SAMPLES)) + 1

    def test_a_long_run_becomes_one_span_with_the_right_speaker(self):
        frames = self._frames_for(3.0)
        spans = dp._tracks_to_spans(SpeakerSpan, self._track(frames, [(0, frames)]))

        assert len(spans) == 1
        assert spans[0].speaker == 0
        assert spans[0].end - spans[0].start >= config.DIARIZATION_MIN_DURATION_ON

    def test_a_run_shorter_than_min_duration_on_is_dropped(self):
        spans = dp._tracks_to_spans(SpeakerSpan, self._track(40, [(0, 2)]))
        assert spans == []

    def test_a_brief_pause_is_bridged_before_the_length_floor_is_applied(self):
        """Two halves that are each too short survive as one span, which is
        the whole reason min_duration_off is applied first."""
        half = self._frames_for(config.DIARIZATION_MIN_DURATION_ON * 0.75)
        gap = 1  # well inside min_duration_off
        frames = half * 2 + gap
        track = self._track(frames, [(0, half), (half + gap, frames)])

        spans = dp._tracks_to_spans(SpeakerSpan, track)
        assert len(spans) == 1

    def test_spans_come_back_sorted_across_speakers(self):
        frames = self._frames_for(3.0)
        tracks = np.zeros((frames * 2, 2), dtype=bool)
        tracks[frames:, 0] = True  # speaker 0 talks second
        tracks[:frames, 1] = True  # speaker 1 talks first

        spans = dp._tracks_to_spans(SpeakerSpan, tracks)
        assert [s.speaker for s in spans] == [1, 0]
        assert spans[0].start < spans[1].start

    def test_a_silent_track_yields_no_spans(self):
        assert dp._tracks_to_spans(SpeakerSpan, np.zeros((100, 2), dtype=bool)) == []


class TestReconstruct:
    """
    The majority vote that turns window-local speakers into global tracks.
    The half-of-the-votes bar is a measured trade-off (AMI 300s: share 0.50
    gives DER 0.4011 at false alarm 13.21, share 0.25 gives DER 0.5412 at
    false alarm 51.85), so these tests pin the direction it errs in rather
    than just that it runs.
    """

    def test_a_single_window_agreeing_with_itself_becomes_an_active_track(self):
        frames = seg.FRAMES_PER_WINDOW
        active = np.zeros((1, frames, seg.NUM_LOCAL_SPEAKERS), dtype=bool)
        active[0, :100, 0] = True

        tracks = dp._reconstruct(active, [0], [(0, 0)], [0], seg.WINDOW_SAMPLES)
        assert tracks[:100, 0].all()
        assert not tracks[100:, 0].any()

    def test_an_evenly_split_vote_still_counts_as_active(self):
        """The bar is >= 0.5, not > 0.5, so one window in two is enough. Worth
        pinning: which way the tie falls decides whether a briefly-seen
        speaker survives at all."""
        active = np.zeros((2, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=bool)
        active[0, :, 0] = True  # window 0 says "talking throughout"
        active[1, :, 0] = False  # window 1 disagrees

        starts = [0, seg.WINDOW_HOP_SAMPLES]
        tracks = dp._reconstruct(active, starts, [(0, 0), (1, 0)], [0, 0], 2 * seg.WINDOW_SAMPLES)

        assert tracks[0, 0]  # only window 0 covers this frame
        assert tracks[seg.WINDOW_HOP_FRAMES + 1, 0]  # both cover it, split 1-1

    def test_a_speaker_only_one_window_in_three_resolves_is_erased(self):
        """The measured cost of the majority rule, in the direction it errs:
        a speaker too few windows ever resolve as their own local speaker can
        never reach half the votes and disappears entirely rather than merely
        being under-detected. Lowering the bar recovers them and cuts
        confusion, but on AMI 300s share 0.25 gives DER 0.5412 at false alarm
        51.85 against 0.4011 at 13.21 for share 0.50 - so half stays."""
        active = np.zeros((3, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=bool)
        active[1, :, 0] = True  # only the middle window ever sees them

        starts = [0, seg.WINDOW_HOP_SAMPLES, 2 * seg.WINDOW_HOP_SAMPLES]
        owners = [(0, 0), (1, 0), (2, 0)]
        tracks = dp._reconstruct(active, starts, owners, [0, 0, 0], 3 * seg.WINDOW_SAMPLES)

        overlap_of_all_three = 2 * seg.WINDOW_HOP_FRAMES + 1
        assert not tracks[overlap_of_all_three, 0]

    def test_local_speakers_clustered_together_land_on_one_global_track(self):
        """Local speaker indices are not comparable across windows; the
        cluster labels are what aligns them, and that is the only thing that
        does."""
        active = np.zeros((2, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=bool)
        active[0, :, 0] = True
        active[1, :, 2] = True  # a different LOCAL index, same person

        starts = [0, seg.WINDOW_HOP_SAMPLES]
        tracks = dp._reconstruct(active, starts, [(0, 0), (1, 2)], [0, 0], 2 * seg.WINDOW_SAMPLES)

        assert tracks.shape[1] == 1
        assert tracks[:, 0].any()

    def test_windows_with_no_embedding_cast_no_votes_at_all(self):
        """A window whose speakers were all too quiet to embed must not count
        toward the denominator, or it would silently veto its neighbours."""
        active = np.zeros((2, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=bool)
        active[0, :, 0] = True

        starts = [0, seg.WINDOW_HOP_SAMPLES]
        # Only window 0 produced an embedding.
        tracks = dp._reconstruct(active, starts, [(0, 0)], [0], 2 * seg.WINDOW_SAMPLES)
        assert tracks[:100, 0].all()


class FakeStream:
    def __init__(self):
        self.waveform = None

    def accept_waveform(self, sample_rate, waveform):
        self.waveform = waveform

    def input_finished(self):
        pass


class FakeExtractor:
    """Returns an embedding derived from the audio length, so a test can tell
    which frames were actually handed over."""

    def __init__(self, config):
        self.config = config
        self.seen = []

    def create_stream(self):
        return FakeStream()

    def compute(self, stream):
        self.seen.append(len(stream.waveform))
        return [float(len(stream.waveform)), 0.0]


def _fake_sherpa(monkeypatch, cluster_labels=None):
    """Plant a sherpa_onnx stub and return it, so tests can read what it saw."""
    module = types.ModuleType("sherpa_onnx")

    class Config:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    extractors = []

    def make_extractor(config):
        extractor = FakeExtractor(config)
        extractors.append(extractor)
        return extractor

    class FakeClustering:
        def __init__(self, config):
            self.config = config

        def __call__(self, matrix):
            if cluster_labels is not None:
                return cluster_labels
            return [0] * len(matrix)

    module.SpeakerEmbeddingExtractor = make_extractor
    module.SpeakerEmbeddingExtractorConfig = Config
    module.FastClustering = FakeClustering
    module.FastClusteringConfig = Config
    module.extractors = extractors
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    return module


class TestEmbedWindows:
    def test_embeds_only_speakers_with_enough_audio(self, monkeypatch):
        """Skipping a speaker is not the same as dropping their speech: about
        ten windows cover every moment, so a neighbouring window with a
        confident view almost always claims it."""
        sherpa = _fake_sherpa(monkeypatch)
        samples = np.zeros(seg.WINDOW_SAMPLES, dtype=np.float32)

        active = np.zeros((1, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=bool)
        active[0, :, 0] = True  # speaker 0 talks the whole window
        active[0, :2, 1] = True  # speaker 1 says almost nothing

        embeddings, owners = dp._embed_windows(
            sherpa, "model.onnx", samples, active, [0], mask_overlap=False
        )
        assert owners == [(0, 0)]
        assert len(embeddings) == 1

    def test_masking_overlap_shortens_the_audio_a_speaker_is_embedded_from(self, monkeypatch):
        """mask_overlap defaults to False because the AMI measurement went
        against it, but the switch has to still do what it claims."""
        sherpa = _fake_sherpa(monkeypatch)
        samples = np.zeros(seg.WINDOW_SAMPLES, dtype=np.float32)

        active = np.zeros((1, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=bool)
        active[0, :, 0] = True
        active[0, :300, 1] = True  # 300 frames of genuine overlap

        _, unmasked_owners = dp._embed_windows(
            sherpa, "model.onnx", samples, active, [0], mask_overlap=False
        )
        unmasked_lengths = list(sherpa.extractors[-1].seen)

        _, masked_owners = dp._embed_windows(
            sherpa, "model.onnx", samples, active, [0], mask_overlap=True
        )
        masked_lengths = list(sherpa.extractors[-1].seen)

        assert (0, 0) in unmasked_owners and (0, 0) in masked_owners
        assert masked_lengths[0] < unmasked_lengths[0]

    def test_a_silent_window_produces_no_embeddings(self, monkeypatch):
        sherpa = _fake_sherpa(monkeypatch)
        active = np.zeros((1, seg.FRAMES_PER_WINDOW, seg.NUM_LOCAL_SPEAKERS), dtype=bool)

        embeddings, owners = dp._embed_windows(
            sherpa,
            "model.onnx",
            np.zeros(seg.WINDOW_SAMPLES, dtype=np.float32),
            active,
            [0],
            mask_overlap=False,
        )
        assert embeddings == [] and owners == []


class TestCluster:
    def test_an_exact_speaker_count_is_passed_through_as_num_clusters(self, monkeypatch):
        sherpa = _fake_sherpa(monkeypatch, cluster_labels=[0, 1])
        labels = dp._cluster(sherpa, [np.zeros(2, dtype=np.float32)] * 2, num_speakers=2)
        assert labels == [0, 1]

    def test_a_non_positive_speaker_count_asks_the_threshold_to_decide(self, monkeypatch):
        """num_speakers <= 0 means "infer" - it must become -1 rather than
        being passed through as 0, which sherpa would read as "no clusters"."""
        seen = {}
        sherpa = _fake_sherpa(monkeypatch)

        class Recording:
            def __init__(self, config):
                seen["config"] = config

            def __call__(self, matrix):
                return [0] * len(matrix)

        sherpa.FastClustering = Recording
        dp._cluster(sherpa, [np.zeros(2, dtype=np.float32)], num_speakers=-1)
        assert seen["config"].num_clusters == -1


class FakeSession:
    """Stands in for an onnxruntime InferenceSession over the segmentation
    model, emitting logits that make local speaker 0 active throughout."""

    def __init__(self, *args, **kwargs):
        self.calls = 0

    def run(self, outputs, feed):
        self.calls += 1
        logits = np.full((1, seg.FRAMES_PER_WINDOW, seg.NUM_CLASSES), -20.0, dtype=np.float32)
        logits[0, :, 1] = 20.0  # class 1 is the singleton {0}
        return [logits]


class TestInferWithProgress:
    def test_reports_one_progress_step_per_window(self, monkeypatch):
        seen = []
        samples = np.zeros(3 * seg.WINDOW_SAMPLES, dtype=np.float32)
        marginals, starts = dp._infer_with_progress(
            FakeSession(), samples, lambda done, total: seen.append((done, total))
        )

        assert len(seen) == len(starts)
        assert seen[-1] == (len(starts), len(starts))
        assert marginals.shape == (
            len(starts),
            seg.FRAMES_PER_WINDOW,
            seg.NUM_LOCAL_SPEAKERS,
        )

    def test_works_without_a_progress_callback(self):
        marginals, starts = dp._infer_with_progress(
            FakeSession(), np.zeros(seg.WINDOW_SAMPLES, dtype=np.float32), None
        )
        assert starts == [0]
        assert marginals[0, 0, 0] > 0.9

    def test_short_audio_is_padded_up_to_a_full_window(self):
        """The ONNX graph would accept a short input, but the model was
        trained on 10s windows and a shorter one is off-distribution."""
        session = FakeSession()
        dp._infer_with_progress(session, np.zeros(1600, dtype=np.float32), None)
        assert session.calls == 1


class TestDiarizePowerset:
    def _install(self, monkeypatch, cluster_labels=None):
        _fake_sherpa(monkeypatch, cluster_labels=cluster_labels)
        ort = types.ModuleType("onnxruntime")
        ort.InferenceSession = FakeSession
        monkeypatch.setitem(sys.modules, "onnxruntime", ort)
        monkeypatch.setattr(
            "speech_to_text.core.diarization.ensure_models", lambda progress=None: None
        )

    def test_rejects_audio_at_the_wrong_sample_rate(self, monkeypatch):
        self._install(monkeypatch)
        with pytest.raises(DiarizationUnavailable):
            dp.diarize_powerset(np.zeros(1600, dtype=np.float32), sample_rate=8000)

    def test_end_to_end_returns_sorted_speaker_spans(self, monkeypatch):
        self._install(monkeypatch)
        samples = np.zeros(3 * seg.WINDOW_SAMPLES, dtype=np.float32)

        spans = dp.diarize_powerset(samples, sample_rate=16000, num_speakers=1)

        assert spans
        assert all(isinstance(span, SpeakerSpan) for span in spans)
        assert spans == sorted(spans, key=lambda s: (s.start, s.end, s.speaker))

    def test_returns_nothing_when_no_speech_is_confident_enough_to_embed(self, monkeypatch):
        """Silence must come back as "no spans", not as an exception - an
        empty span list is a valid answer that assign_speakers handles."""
        self._install(monkeypatch)

        class SilentSession(FakeSession):
            def run(self, outputs, feed):
                logits = np.full(
                    (1, seg.FRAMES_PER_WINDOW, seg.NUM_CLASSES), -20.0, dtype=np.float32
                )
                logits[0, :, 0] = 20.0  # class 0 is the empty set
                return [logits]

        sys.modules["onnxruntime"].InferenceSession = lambda *a, **k: SilentSession()

        assert dp.diarize_powerset(np.zeros(seg.WINDOW_SAMPLES, dtype=np.float32)) == []

    def test_the_onset_argument_overrides_the_configured_threshold(self, monkeypatch):
        """The threshold is the entire reason this engine exists (AMI 300s:
        argmax finds 138.7s of 150.0s of reference speech, a 0.40 marginal
        threshold finds 148.0s), so it has to be reachable per call for the
        measurement to stay reproducible."""
        self._install(monkeypatch)
        samples = np.zeros(seg.WINDOW_SAMPLES, dtype=np.float32)

        # An onset above 1.0 can never be met, so nothing is ever active.
        assert dp.diarize_powerset(samples, onset=1.5) == []
