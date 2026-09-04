"""
Tests for core/segments.py.

The vocabulary types the whole pipeline is written in. What is worth pinning
here is the small amount of behaviour they carry beyond being data: the
duration property's floor, plain_text's spacing rule (the regression
baseline other tests compare transcripts against), and the defaults that let
a caller build a Segment without knowing about words or speakers.
"""

import pickle

from speech_to_text.core.segments import Segment, TranscriptDocument, Word, plain_text


class TestDefaults:
    def test_a_word_is_assumed_confident_unless_told_otherwise(self):
        """
        1.0 means the Hebrew correction pass leaves the word alone. Absent
        confidence data must not be read as "the model was unsure", which
        would have it rewriting words on the strength of nothing.
        """
        assert Word(start=0.0, end=1.0, text="שלום").probability == 1.0

    def test_a_segment_without_speaker_identification_carries_no_speaker(self):
        segment = Segment(start=0.0, end=1.0, text="hello")
        assert segment.speaker is None
        assert segment.words == []

    def test_two_segments_do_not_share_one_words_list(self):
        first = Segment(start=0.0, end=1.0, text="a")
        second = Segment(start=1.0, end=2.0, text="b")
        first.words.append(Word(start=0.0, end=0.5, text="a"))
        assert second.words == []

    def test_a_document_starts_empty_and_unfailed(self):
        document = TranscriptDocument(source_name="a.wav")
        assert document.segments == []
        assert document.failed is False


class TestDuration:
    def test_duration_is_the_span_between_the_two_timestamps(self):
        assert Segment(start=1.5, end=4.0, text="x").duration == 2.5

    def test_a_backwards_segment_reports_zero_rather_than_a_negative_length(self):
        """
        faster-whisper timings are not guaranteed monotonic across a decode
        retry. A negative duration would propagate into every downstream
        average and width calculation as a silently wrong number.
        """
        assert Segment(start=4.0, end=1.0, text="x").duration == 0.0


class TestPlainText:
    def test_segments_are_joined_with_a_single_space(self):
        segments = [
            Segment(start=0.0, end=1.0, text="Hello"),
            Segment(start=1.0, end=2.0, text="World"),
        ]
        assert plain_text(segments) == "Hello World"

    def test_a_segment_that_already_ends_in_a_space_does_not_gain_a_second(self):
        segments = [
            Segment(start=0.0, end=1.0, text="Hello "),
            Segment(start=1.0, end=2.0, text="World"),
        ]
        assert plain_text(segments) == "Hello World"

    def test_empty_segments_are_skipped_rather_than_leaving_gaps(self):
        segments = [
            Segment(start=0.0, end=1.0, text=""),
            Segment(start=1.0, end=2.0, text="Hello"),
            Segment(start=2.0, end=3.0, text=""),
            Segment(start=3.0, end=4.0, text="World"),
        ]
        assert plain_text(segments) == "Hello World"

    def test_no_segments_flattens_to_the_empty_string(self):
        assert plain_text([]) == ""


def test_the_types_survive_the_trip_between_the_two_processes():
    """
    Segments are built in the worker process and read in the GUI process, so
    they are pickled on the way. The module is stdlib-only partly to keep
    that true - see its docstring for the MSVCP140.dll reason neither
    process can import the other's dependencies.
    """
    document = TranscriptDocument(
        source_name="a.wav",
        segments=[
            Segment(
                start=0.0,
                end=1.0,
                text="שלום",
                words=[Word(start=0.0, end=1.0, text="שלום", probability=0.4)],
                speaker=1,
            )
        ],
    )

    # Test-authored bytes only, round-tripped to prove the shape survives
    # exactly the mechanism multiprocessing uses for it.
    restored = pickle.loads(pickle.dumps(document))

    assert restored == document
    assert restored.segments[0].words[0].probability == 0.4
