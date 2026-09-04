"""
Tests for mapping diarization spans onto transcript segments, plus a
config-building smoke test for diarize() itself.

Most of this file needs no sherpa-onnx: assign_speakers is where the
subtlety lives. Whisper decides segment boundaries by its own decoder state,
so speaker changes land mid-segment routinely and the naive "attribute the
whole segment by its overall time span" approach smears them - and even
majority-voting the whole segment to one label throws away the minority
words' speaker. assign_speakers instead splits a straddling segment at the
word boundary where the speaker actually changed.

TestDiarizeBuildsSherpaConfig is the exception: diarize() itself had zero
coverage before this, and that let a real bug through - a local variable
named `config` inside diarize() shadowed the module-level `from
speech_to_text import config` import for the entire function body, including
the right-hand side of its own assignment, so every call raised
UnboundLocalError. worker.py's deliberately non-fatal except around speaker
identification swallowed that into a silent "no speaker labels", and nothing
caught it except an actual run against real audio and real models - which
this project's unit tests, by design, never do. That test stubs sherpa_onnx
with a fake module standing in for the real package, so diarize()'s own
config-building code runs for real in pytest without needing the real
sherpa-onnx package, the real models, or real audio - a renamed/shadowed
variable or a bad kwarg fails loudly here instead of only in production.

Trap worth noting for the stub: diarize() does `import sherpa_onnx` as a
*local* import inside the function body, not a module-level one, so the fix
is to plant the fake under sys.modules["sherpa_onnx"] (monkeypatch.setitem)
so that local import resolves to it - patching an attribute on some other
module that merely re-exports sherpa_onnx would not reach this import at
all, since it re-imports the name itself rather than reading a shared
reference.
"""

import sys
import types

import numpy as np

from speech_to_text.core import diarization
from speech_to_text.core.diarization import (
    MIN_SPEAKER_RUN_WORDS,
    SpeakerSpan,
    _best_speaker,
    assign_speakers,
)
from speech_to_text.core.segments import Segment, Word


def word(start, end, text="x", probability=0.9):
    return Word(start=start, end=end, text=text, probability=probability)


class TestSpeakerSpan:
    def test_overlap_of_contained_range(self):
        assert SpeakerSpan(0, 10, 0).overlap(2, 5) == 3

    def test_partial_overlap(self):
        assert SpeakerSpan(0, 10, 0).overlap(8, 15) == 2

    def test_disjoint_ranges_do_not_overlap(self):
        assert SpeakerSpan(0, 5, 0).overlap(6, 9) == 0

    def test_touching_ranges_do_not_overlap(self):
        assert SpeakerSpan(0, 5, 0).overlap(5, 9) == 0


class TestBestSpeaker:
    def test_picks_the_largest_overlap(self):
        spans = [SpeakerSpan(0, 4, 0), SpeakerSpan(4, 10, 1)]
        assert _best_speaker(spans, 3, 10) == 1

    def test_sums_multiple_spans_from_the_same_speaker(self):
        """Speaker 0 talks twice for 2s total; speaker 1 once for 1.5s."""
        spans = [SpeakerSpan(0, 2, 0), SpeakerSpan(2, 3.5, 1), SpeakerSpan(3.5, 5.5, 0)]
        assert _best_speaker(spans, 0, 5.5) == 0

    def test_returns_none_when_nothing_overlaps(self):
        assert _best_speaker([SpeakerSpan(0, 1, 0)], 50, 60) is None


class TestAssignSpeakers:
    def test_boundary_slip_word_does_not_split_and_takes_the_majority_label(self):
        """
        A stray word that is only CLIPPED by the next span - the diarizer put
        its boundary a fraction early - is not a turn. The run is shorter than
        MIN_SPEAKER_RUN_WORDS and speaker 1 covers only a sliver of the word,
        so it folds back into the majority run instead of fracturing the
        segment.

        Contrast test_fully_covered_long_word_survives_as_an_interjection
        below, which is the case this guard must NOT swallow.
        """
        segment = Segment(
            start=0,
            end=10,
            text="a b c d e",
            words=[word(0, 1), word(1, 2), word(2, 3), word(3, 4), word(4, 5)],
        )
        # Speaker 1 starts 0.1s before the last word ends, clipping it only.
        spans = [SpeakerSpan(0, 4.9, 0), SpeakerSpan(4.9, 10, 1)]

        result = assign_speakers([segment], spans)
        assert len(result) == 1
        assert result[0] is segment  # identity preserved: no split happened
        assert result[0].speaker == 0

    def test_fully_covered_long_word_survives_as_an_interjection(self):
        """
        The behaviour the run-length floor used to erase: a genuine one-word
        turn ("כן", "לא") spoken entirely inside the other speaker's span.

        Length alone cannot tell this apart from a boundary slip, which is why
        coverage decides it - here speaker 1 covers the whole word, and the
        word is long enough to carry a real utterance, so it keeps its own run
        and the segment splits three ways.
        """
        words = [
            word(0.0, 1.0, text="a"),
            word(1.0, 2.0, text=" b"),
            word(2.0, 3.0, text=" c"),
            word(3.0, 4.0, text=" d"),
            word(4.0, 5.0, text=" e"),
        ]
        segment = Segment(start=0.0, end=5.0, text="a b c d e", words=words)
        spans = [
            SpeakerSpan(0.0, 2.0, 0),
            SpeakerSpan(2.0, 3.0, 1),
            SpeakerSpan(3.0, 5.0, 0),
        ]

        result = assign_speakers([segment], spans)
        assert [s.speaker for s in result] == [0, 1, 0]
        assert [s.text for s in result] == ["a b", "c", "d e"]

    def test_short_run_folds_toward_the_better_supported_neighbour(self):
        """
        The left-fold bias, directly. A too-short run sits between two
        different speakers; the audio supports the RIGHT one, so that is where
        it goes. Folding left unconditionally - which is what this code did -
        is how the earlier speaker accumulated the other's words.
        """
        words = [
            word(0.0, 1.0, text="a"),
            word(1.0, 2.0, text=" b"),
            word(2.0, 2.2, text=" c"),
            word(2.2, 3.2, text=" d"),
            word(3.2, 4.2, text=" e"),
        ]
        segment = Segment(start=0.0, end=4.2, text="a b c d e", words=words)
        # "c" is a 0.2s boundary slip (too short to be an interjection), and
        # the split is deliberately lopsided: speaker 0 covers only 0.05s of
        # it against speaker 2's 0.15s. An even split would land on the
        # tie-break instead and prove nothing about the scoring.
        spans = [
            SpeakerSpan(0.0, 2.05, 0),
            SpeakerSpan(2.05, 4.2, 2),
        ]

        result = assign_speakers([segment], spans)
        assert [s.speaker for s in result] == [0, 2]
        assert [s.text for s in result] == ["a b", "c d e"]

    def test_falls_back_to_segment_span_without_word_timings(self):
        segment = Segment(start=0, end=5, text="a", words=[])
        result = assign_speakers([segment], [SpeakerSpan(0, 5, 1)])
        assert result == [segment]
        assert result[0] is segment
        assert result[0].speaker == 1

    def test_segment_outside_every_span_stays_unattributed(self):
        """Better to omit the label than to invent one - render() drops it."""
        segment = Segment(start=100, end=105, text="a", words=[word(100, 101)])
        result = assign_speakers([segment], [SpeakerSpan(0, 5, 0)])
        assert result == [segment]
        assert result[0].speaker is None

    def test_no_spans_leaves_everything_untouched(self):
        segment = Segment(start=0, end=5, text="a", words=[word(0, 1)])
        result = assign_speakers([segment], [])
        assert result == [segment]
        assert result[0] is segment
        assert result[0].speaker is None

    def test_conversation_alternates_correctly(self):
        segments = [
            Segment(start=0, end=3, text="one", words=[word(0, 3)]),
            Segment(start=3.2, end=6, text="two", words=[word(3.2, 6)]),
            Segment(start=6.5, end=9, text="three", words=[word(6.5, 9)]),
        ]
        spans = [
            SpeakerSpan(0, 3.1, 0),
            SpeakerSpan(3.1, 6.2, 1),
            SpeakerSpan(6.2, 9, 0),
        ]
        result = assign_speakers(segments, spans)
        assert [s.speaker for s in result] == [0, 1, 0]
        # None of these needed splitting - every one is the same object back.
        assert [s is orig for s, orig in zip(result, segments)] == [True, True, True]

    def test_no_split_needed_returns_the_input_object_unchanged(self):
        """A single-speaker segment is handed back by identity, not rebuilt."""
        segment = Segment(
            start=0,
            end=2,
            text="a b",
            words=[word(0, 1, text="a"), word(1, 2, text=" b")],
        )
        result = assign_speakers([segment], [SpeakerSpan(0, 2, 0)])
        assert result[0] is segment
        assert result[0].speaker == 0

    def test_segment_straddling_two_speakers_splits_at_the_right_word(self):
        """
        Three words each for speaker 0 then speaker 1 - both runs meet
        MIN_SPEAKER_RUN_WORDS, so the segment is cut into two sub-segments at
        the word boundary where the speaker actually changes, not smeared
        into one majority label.
        """
        # Pins that the module-level name and the config knob cannot drift
        # apart, rather than pinning the value itself - the value is a tuning
        # decision that lives in config.py and is allowed to change; the two
        # names being the same thing is the invariant this file depends on.
        from speech_to_text import config as app_config

        assert MIN_SPEAKER_RUN_WORDS == app_config.DIARIZATION_MIN_SPEAKER_RUN_WORDS
        assert MIN_SPEAKER_RUN_WORDS == 2  # the value this fixture is built for
        words = [
            word(0.0, 1.0, text="a"),
            word(1.0, 2.0, text=" b"),
            word(2.0, 3.0, text=" c"),
            word(3.0, 4.0, text=" d"),
            word(4.0, 5.0, text=" e"),
            word(5.0, 6.0, text=" f"),
        ]
        segment = Segment(start=0.0, end=6.0, text="a b c d e f", words=words)
        spans = [SpeakerSpan(0.0, 3.0, 0), SpeakerSpan(3.0, 6.0, 1)]

        result = assign_speakers([segment], spans)

        assert len(result) == 2
        first, second = result
        assert first.speaker == 0
        assert second.speaker == 1
        # The segment's own outer bounds are preserved at the outer edges...
        assert first.start == 0.0
        assert second.end == 6.0
        # ...and the split lands exactly at the word boundary between the
        # last speaker-0 word and the first speaker-1 word.
        assert first.end == 3.0
        assert second.start == 3.0
        assert first.text == "a b c"
        assert second.text == "d e f"
        assert [w.text for w in first.words] == ["a", " b", " c"]
        assert [w.text for w in second.words] == [" d", " e", " f"]

    def test_split_preserves_word_spacing_exactly(self):
        """
        Word.text carries leading spaces from faster-whisper. Rejoining a
        run's word texts and stripping the ends must reproduce clean text
        with neither doubled nor missing spaces between words.
        """
        words = [
            word(0.0, 0.4, text="Hello"),
            word(0.4, 0.8, text=" there"),
            word(0.8, 1.2, text=" my"),
            word(1.2, 1.6, text=" friend"),
        ]
        segment = Segment(start=0.0, end=1.6, text="Hello there my friend", words=words)
        spans = [SpeakerSpan(0.0, 0.8, 0), SpeakerSpan(0.8, 1.6, 1)]

        result = assign_speakers([segment], spans)

        assert [s.text for s in result] == ["Hello there", "my friend"]
        for piece in result:
            assert "  " not in piece.text
            assert not piece.text.startswith(" ")
            assert not piece.text.endswith(" ")

    def test_lone_brief_flip_between_two_runs_of_the_other_speaker_does_not_split(self):
        """
        A middle word flips to speaker 1 too briefly to be a turn - surrounded
        by speaker 0 on both sides and only fractionally covered - so it is
        folded back and the whole segment stays speaker 0.

        The same shape with a fully-covered, long enough word is a real
        interjection and DOES split; see
        test_fully_covered_long_word_survives_as_an_interjection.
        """
        words = [
            word(0.0, 1.0, text="a"),
            word(1.0, 2.0, text=" b"),
            word(2.0, 2.2, text=" c"),
            word(2.2, 3.2, text=" d"),
            word(3.2, 4.2, text=" e"),
        ]
        segment = Segment(start=0.0, end=4.2, text="a b c d e", words=words)
        # Speaker 1 holds a 0.1s sliver inside word "c" only.
        spans = [
            SpeakerSpan(0.0, 2.05, 0),
            SpeakerSpan(2.05, 2.15, 1),
            SpeakerSpan(2.15, 4.2, 0),
        ]

        result = assign_speakers([segment], spans)
        assert len(result) == 1
        assert result[0] is segment
        assert result[0].speaker == 0

    def test_gap_word_takes_the_nearer_neighbour_in_time_not_the_earlier_one(self):
        """
        The forward-fill bias, directly. The middle word overlaps no span at
        all; it sits 0.8s after speaker 0 stopped and 0.05s before speaker 1
        starts, so it belongs with speaker 1. Forward-fill gave it to speaker
        0 purely because speaker 0 came first.
        """
        words = [
            word(0.0, 1.0, text="a"),
            word(1.0, 2.0, text=" b"),
            word(2.8, 2.95, text=" c"),
            word(3.0, 4.0, text=" d"),
            word(4.0, 5.0, text=" e"),
        ]
        segment = Segment(start=0.0, end=5.0, text="a b c d e", words=words)
        # Nothing covers 2.8-2.95: it falls in the gap between the two spans.
        spans = [SpeakerSpan(0.0, 2.0, 0), SpeakerSpan(3.0, 5.0, 1)]

        result = assign_speakers([segment], spans)
        assert [s.speaker for s in result] == [0, 1]
        assert [s.text for s in result] == ["a b", "c d e"]

    def test_gap_word_beyond_the_fill_ceiling_stays_unattributed(self):
        """
        A word marooned in a long silence keeps no label at all. Guessing one
        across several seconds is how a single speaker's label used to run on
        over everything that followed; rendering it with no speaker is the
        honest outcome.
        """
        words = [
            word(0.0, 1.0, text="a"),
            word(1.0, 2.0, text=" b"),
            word(20.0, 21.0, text=" c"),
        ]
        segment = Segment(start=0.0, end=21.0, text="a b c", words=words)
        spans = [SpeakerSpan(0.0, 2.0, 0)]

        result = assign_speakers([segment], spans)
        assert [s.speaker for s in result] == [0, None]
        assert [s.text for s in result] == ["a b", "c"]

    def test_multiple_segments_are_flattened_into_one_list(self):
        """assign_speakers returns a flat list, splits included, in order."""
        straddling = Segment(
            start=0.0,
            end=4.0,
            text="a b c d",
            words=[
                word(0.0, 1.0, text="a"),
                word(1.0, 2.0, text=" b"),
                word(2.0, 3.0, text=" c"),
                word(3.0, 4.0, text=" d"),
            ],
        )
        clean = Segment(start=4.5, end=5.5, text="e", words=[word(4.5, 5.5, text="e")])
        spans = [SpeakerSpan(0.0, 2.0, 0), SpeakerSpan(2.0, 5.5, 1)]

        result = assign_speakers([straddling, clean], spans)

        assert len(result) == 3
        assert [s.speaker for s in result] == [0, 1, 1]
        assert result[2] is clean


def _install_fake_sherpa_onnx(monkeypatch):  # noqa: C901 - test fixture builder, not shipped code
    """
    Plant a minimal stand-in for the sherpa_onnx package under
    sys.modules["sherpa_onnx"], so diarize()'s local `import sherpa_onnx`
    resolves to this instead of the real package. See this file's module
    docstring for why sys.modules is the right thing to patch here.

    Each fake config class mirrors only the constructor shape diarize()
    actually calls it with - just enough that a renamed keyword argument, a
    variable shadowed into UnboundLocalError, or any other mistake in how
    diarize() assembles its config raises here, in pytest, instead of only
    surfacing against real models and real audio.
    """

    class FakeDiarizationConfig:
        # Class-level so the test can inspect what diarize() actually built
        # after the call returns, without diarize() needing to hand
        # anything back for the purpose.
        last_instance = None

        def __init__(
            self, segmentation, embedding, clustering, min_duration_on=0.3, min_duration_off=0.5
        ):
            self.segmentation = segmentation
            self.embedding = embedding
            self.clustering = clustering
            self.min_duration_on = min_duration_on
            self.min_duration_off = min_duration_off
            FakeDiarizationConfig.last_instance = self

        def validate(self):
            return True

    class FakeSegmentationModelConfig:
        def __init__(self, pyannote, num_threads=1, provider="cpu"):
            self.pyannote = pyannote
            self.num_threads = num_threads
            self.provider = provider

    class FakePyannoteModelConfig:
        def __init__(self, model):
            self.model = model

    class FakeEmbeddingConfig:
        def __init__(self, model, num_threads=1, provider="cpu"):
            self.model = model
            self.num_threads = num_threads
            self.provider = provider

    class FakeClusteringConfig:
        def __init__(self, num_clusters, threshold):
            self.num_clusters = num_clusters
            self.threshold = threshold

    class FakeSpan:
        def __init__(self, start, end, speaker):
            self.start = start
            self.end = end
            self.speaker = speaker

    class FakeResult:
        def __init__(self, spans):
            self._spans = spans
            self.num_speakers = len({s.speaker for s in spans})

        def sort_by_start_time(self):
            return sorted(self._spans, key=lambda s: s.start)

    class FakeEngine:
        sample_rate = 16000

        def __init__(self, config):
            self.config = config

        def process(self, samples, callback=None):
            if callback:
                callback(1, 1)
            return FakeResult([FakeSpan(0.0, 1.0, 0), FakeSpan(1.0, 2.0, 1)])

    fake_module = types.ModuleType("sherpa_onnx")
    fake_module.OfflineSpeakerDiarizationConfig = FakeDiarizationConfig
    fake_module.OfflineSpeakerSegmentationModelConfig = FakeSegmentationModelConfig
    fake_module.OfflineSpeakerSegmentationPyannoteModelConfig = FakePyannoteModelConfig
    fake_module.SpeakerEmbeddingExtractorConfig = FakeEmbeddingConfig
    fake_module.FastClusteringConfig = FakeClusteringConfig
    fake_module.OfflineSpeakerDiarization = FakeEngine

    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake_module)
    return FakeDiarizationConfig


class TestDiarizeBuildsSherpaConfig:
    """
    diarize() itself, with sherpa_onnx stubbed - see this file's module
    docstring for the real bug (a shadowed `config` local) this class of
    test exists to catch.
    """

    def test_builds_config_and_returns_spans_without_raising(self, monkeypatch):
        _install_fake_sherpa_onnx(monkeypatch)
        monkeypatch.setattr(diarization, "models_present", lambda: True)

        samples = np.zeros(1600, dtype=np.float32)
        spans = diarization.diarize(samples, sample_rate=16000, num_speakers=2)

        assert [(s.start, s.end, s.speaker) for s in spans] == [(0.0, 1.0, 0), (1.0, 2.0, 1)]

    def test_passes_the_named_min_duration_constants_through(self, monkeypatch):
        """
        The exact bug this class exists for: config.DIARIZATION_MIN_DURATION_ON
        and _OFF must reach the sherpa-onnx config unchanged. A shadowed
        `config` local reading itself instead of the settings module would
        raise before this assertion is ever reached.
        """
        from speech_to_text import config as app_config

        fake_config_cls = _install_fake_sherpa_onnx(monkeypatch)
        monkeypatch.setattr(diarization, "models_present", lambda: True)

        samples = np.zeros(1600, dtype=np.float32)
        diarization.diarize(samples, sample_rate=16000, num_speakers=2)

        built = fake_config_cls.last_instance
        assert built.min_duration_on == app_config.DIARIZATION_MIN_DURATION_ON
        assert built.min_duration_off == app_config.DIARIZATION_MIN_DURATION_OFF

    def test_passes_thread_count_and_provider_to_both_models(self, monkeypatch):
        """
        num_threads/provider have to reach BOTH model configs, not just one.
        They were unset entirely until measured: the embedding extractor is
        where diarization's wall clock actually goes, so a thread count that
        reached only the segmentation model would look wired up while leaving
        the expensive half on onnxruntime's default.
        """
        from speech_to_text import config as app_config

        fake_config_cls = _install_fake_sherpa_onnx(monkeypatch)
        monkeypatch.setattr(diarization, "models_present", lambda: True)

        samples = np.zeros(1600, dtype=np.float32)
        diarization.diarize(samples, sample_rate=16000, num_speakers=2)

        built = fake_config_cls.last_instance
        for model_config in (built.segmentation, built.embedding):
            assert model_config.num_threads == app_config.DIARIZATION_NUM_THREADS
            assert model_config.provider == app_config.DIARIZATION_PROVIDER

    def test_thread_count_stays_below_the_oversubscription_cliff(self):
        """
        Pins the reasoning in config.py, not a magic number: handing
        onnxruntime every core measured SLOWER for this workload (8 threads
        was 3.8x the per-window cost of 2), so the constant must stay a small
        cap rather than drifting to os.cpu_count() in some later tidy-up.
        """
        from speech_to_text import config as app_config

        assert 1 <= app_config.DIARIZATION_NUM_THREADS <= 4

    def test_engine_constant_routes_to_the_powerset_pipeline(self, monkeypatch):
        """
        The whole point of DIARIZATION_ENGINE being one constant is that
        flipping it changes which pipeline runs and nothing else. If this
        dispatch is ever refactored away, the sherpa path would keep working
        and the powerset path would silently become dead code - which is
        exactly the kind of regression that shows up as "the fix stopped
        helping" months later rather than as a failing test.
        """
        from speech_to_text import config as app_config

        called = {}

        def fake_powerset(samples, sample_rate, num_speakers, progress):
            called["args"] = (len(samples), sample_rate, num_speakers)
            return ["sentinel"]

        import speech_to_text.core.diarization_powerset as powerset_module

        monkeypatch.setattr(powerset_module, "diarize_powerset", fake_powerset)
        monkeypatch.setattr(app_config, "DIARIZATION_ENGINE", "powerset")

        result = diarization.diarize(
            np.zeros(1600, dtype=np.float32), sample_rate=16000, num_speakers=3
        )

        assert result == ["sentinel"]
        assert called["args"] == (1600, 16000, 3)

    def test_default_engine_still_runs_sherpa(self, monkeypatch):
        """The powerset engine is opt-in; the shipped default must not move."""
        from speech_to_text import config as app_config

        assert app_config.DIARIZATION_ENGINE == "sherpa"

        _install_fake_sherpa_onnx(monkeypatch)
        monkeypatch.setattr(diarization, "models_present", lambda: True)
        spans = diarization.diarize(
            np.zeros(1600, dtype=np.float32), sample_rate=16000, num_speakers=2
        )
        assert [(s.start, s.end, s.speaker) for s in spans] == [(0.0, 1.0, 0), (1.0, 2.0, 1)]

    def test_wrong_sample_rate_raises_diarization_unavailable(self, monkeypatch):
        import pytest

        _install_fake_sherpa_onnx(monkeypatch)
        monkeypatch.setattr(diarization, "models_present", lambda: True)

        samples = np.zeros(800, dtype=np.float32)
        with pytest.raises(diarization.DiarizationUnavailable):
            diarization.diarize(samples, sample_rate=8000, num_speakers=2)
