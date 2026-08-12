"""
Tests for mapping diarization spans onto transcript segments.

No sherpa-onnx here: these cover the assignment logic, which is where the
subtlety lives. Whisper decides segment boundaries by its own decoder state,
so speaker changes land mid-segment routinely and the naive "attribute the
whole segment by its overall time span" approach smears them.
"""

from speech_to_text.core.diarization import (
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

    def test_words_decide_the_segment_not_its_span(self):
        """
        The core reason for word-level assignment. This segment straddles a
        speaker change: by overall span it overlaps speaker 1 more, but four of
        its five words were spoken by speaker 0.
        """
        segment = Segment(
            start=0, end=10, text="a b c d e",
            words=[word(0, 1), word(1, 2), word(2, 3), word(3, 4), word(9, 10)],
        )
        spans = [SpeakerSpan(0, 4.5, 0), SpeakerSpan(4.5, 10, 1)]

        assign_speakers([segment], spans)
        assert segment.speaker == 0

    def test_falls_back_to_segment_span_without_word_timings(self):
        segment = Segment(start=0, end=5, text="a", words=[])
        assign_speakers([segment], [SpeakerSpan(0, 5, 1)])
        assert segment.speaker == 1

    def test_segment_outside_every_span_stays_unattributed(self):
        """Better to omit the label than to invent one - render() drops it."""
        segment = Segment(start=100, end=105, text="a", words=[word(100, 101)])
        assign_speakers([segment], [SpeakerSpan(0, 5, 0)])
        assert segment.speaker is None

    def test_no_spans_leaves_everything_untouched(self):
        segment = Segment(start=0, end=5, text="a", words=[word(0, 1)])
        assign_speakers([segment], [])
        assert segment.speaker is None

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
        assign_speakers(segments, spans)
        assert [s.speaker for s in segments] == [0, 1, 0]

    def test_assignment_is_in_place(self):
        """worker.py relies on this - it never rebinds the segment list."""
        segments = [Segment(start=0, end=1, text="a", words=[word(0, 1)])]
        original = segments[0]
        assign_speakers(segments, [SpeakerSpan(0, 1, 0)])
        assert segments[0] is original
        assert original.speaker == 0
