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

    def test_stray_word_does_not_split_and_takes_the_majority_label(self):
        """
        By overall span this segment overlaps speaker 1 more, but four of its
        five words were spoken by speaker 0 and the fifth is a single stray
        word - too short a run (< MIN_SPEAKER_RUN_WORDS) to split on, so it
        folds back into the majority run instead of fracturing the segment.
        """
        segment = Segment(
            start=0, end=10, text="a b c d e",
            words=[word(0, 1), word(1, 2), word(2, 3), word(3, 4), word(9, 10)],
        )
        spans = [SpeakerSpan(0, 4.5, 0), SpeakerSpan(4.5, 10, 1)]

        result = assign_speakers([segment], spans)
        assert len(result) == 1
        assert result[0] is segment  # identity preserved: no split happened
        assert result[0].speaker == 0

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
            start=0, end=2, text="a b",
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
        assert MIN_SPEAKER_RUN_WORDS == 2  # pins the guard this test relies on
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

    def test_lone_flip_between_two_runs_of_the_other_speaker_does_not_split(self):
        """
        A middle word flips to speaker 1 for one word only, surrounded by
        speaker 0 on both sides - too short a run to split on, so it is
        folded into its neighbours and the whole segment stays speaker 0.
        """
        words = [
            word(0.0, 1.0, text="a"),
            word(1.0, 2.0, text=" b"),
            word(2.0, 3.0, text=" c"),
            word(3.0, 4.0, text=" d"),
            word(4.0, 5.0, text=" e"),
        ]
        segment = Segment(start=0.0, end=5.0, text="a b c d e", words=words)
        # Word "c" (2-3s) alone falls in speaker 1's span; everything else is
        # speaker 0's.
        spans = [
            SpeakerSpan(0.0, 2.0, 0),
            SpeakerSpan(2.0, 3.0, 1),
            SpeakerSpan(3.0, 5.0, 0),
        ]

        result = assign_speakers([segment], spans)
        assert len(result) == 1
        assert result[0] is segment
        assert result[0].speaker == 0

    def test_multiple_segments_are_flattened_into_one_list(self):
        """assign_speakers returns a flat list, splits included, in order."""
        straddling = Segment(
            start=0.0, end=4.0, text="a b c d",
            words=[
                word(0.0, 1.0, text="a"), word(1.0, 2.0, text=" b"),
                word(2.0, 3.0, text=" c"), word(3.0, 4.0, text=" d"),
            ],
        )
        clean = Segment(start=4.5, end=5.5, text="e", words=[word(4.5, 5.5, text="e")])
        spans = [SpeakerSpan(0.0, 2.0, 0), SpeakerSpan(2.0, 5.5, 1)]

        result = assign_speakers([straddling, clean], spans)

        assert len(result) == 3
        assert [s.speaker for s in result] == [0, 1, 1]
        assert result[2] is clean


def _install_fake_sherpa_onnx(monkeypatch):
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

        def __init__(self, segmentation, embedding, clustering,
                     min_duration_on=0.3, min_duration_off=0.5):
            self.segmentation = segmentation
            self.embedding = embedding
            self.clustering = clustering
            self.min_duration_on = min_duration_on
            self.min_duration_off = min_duration_off
            FakeDiarizationConfig.last_instance = self

        def validate(self):
            return True

    class FakeSegmentationModelConfig:
        def __init__(self, pyannote):
            self.pyannote = pyannote

    class FakePyannoteModelConfig:
        def __init__(self, model):
            self.model = model

    class FakeEmbeddingConfig:
        def __init__(self, model):
            self.model = model

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

    def test_wrong_sample_rate_raises_diarization_unavailable(self, monkeypatch):
        import pytest

        _install_fake_sherpa_onnx(monkeypatch)
        monkeypatch.setattr(diarization, "models_present", lambda: True)

        samples = np.zeros(800, dtype=np.float32)
        with pytest.raises(diarization.DiarizationUnavailable):
            diarization.diarize(samples, sample_rate=8000, num_speakers=2)
