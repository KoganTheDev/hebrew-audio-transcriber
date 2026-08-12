"""
Tests for transcript rendering.

The bidi assertions here are deliberately at the codepoint level. Bracketed
timestamps inside Hebrew text are exactly the kind of thing that looks fine in
whichever editor you happen to open and silently regresses everywhere else, so
"it rendered correctly on my machine" is not a test.
"""

import pytest

from speech_to_text.core.formatting import (
    LRI, PDI, RLM,
    format_hhmmss, format_plain, merge_turns, render, timestamp_prefix,
)
from speech_to_text.core.segments import Segment

HE = "שלום עולם"


def seg(start, end, text=HE, speaker=None):
    return Segment(start=start, end=end, text=text, speaker=speaker)


class TestTimeFormatting:

    @pytest.mark.parametrize("seconds,expected", [
        (0, "0:00:00"),
        (5, "0:00:05"),
        (83, "0:01:23"),
        (3600, "1:00:00"),
        (3725, "1:02:05"),
        (36000, "10:00:00"),
    ])
    def test_hhmmss(self, seconds, expected):
        assert format_hhmmss(seconds) == expected

    def test_negative_and_junk_do_not_raise(self):
        assert format_hhmmss(-5) == "0:00:00"
        assert format_hhmmss(None) == "0:00:00"
        assert format_hhmmss("abc") == "0:00:00"


class TestBidi:
    """The RTL bracket problem - see the module docstring in core/formatting."""

    def test_timestamp_is_wrapped_in_an_ltr_isolate(self):
        """
        Without LRI/PDI the mirrored brackets resolve RTL inside a Hebrew
        paragraph and display as ]00:01:23[ .
        """
        assert timestamp_prefix(83) == "⁦[0:01:23]⁩"

    def test_bracket_characters_are_stored_in_logical_order(self):
        """
        The fix must be bidi control characters, not reordered brackets.
        Swapping the ASCII would 'fix' one renderer, break others, and corrupt
        the file for anything parsing timestamps.
        """
        prefix = timestamp_prefix(83)
        assert prefix.index("[") < prefix.index("]")

    def test_line_starts_with_rtl_mark(self):
        """Pins paragraph direction to RTL so a line opening with a digit doesn't flip."""
        line = render([seg(0, 1)]).split("\n")[0]
        assert line[0] == RLM

    def test_exact_codepoint_sequence_of_a_rendered_line(self):
        """
        Full-line pin. If any of these control characters is dropped or
        reordered, Hebrew transcripts render wrong in some viewers and right in
        others - which is far harder to notice than an outright failure.
        """
        line = render([seg(83, 90, speaker=0)], speaker_label="דובר {n}").split("\n")[0]
        assert line == f"{RLM}{LRI}[0:01:23]{PDI} דובר 1: {HE}"
        assert [hex(ord(c)) for c in line[:2]] == ["0x200f", "0x2066"]

    def test_control_characters_are_the_isolating_variants(self):
        """
        U+2066/U+2069, not the older U+202A/U+202C embeddings, which leak
        direction into surrounding text instead of isolating from it.
        """
        assert ord(LRI) == 0x2066
        assert ord(PDI) == 0x2069
        assert ord(RLM) == 0x200F


class TestTurnMerging:

    def test_consecutive_close_segments_merge(self):
        turns = merge_turns([seg(0, 3, "אחד"), seg(3.5, 6, "שתיים")])
        assert len(turns) == 1
        assert turns[0].text == "אחד שתיים"
        assert turns[0].start == 0
        assert turns[0].end == 6

    def test_long_pause_splits_a_turn(self):
        turns = merge_turns([seg(0, 3, "אחד"), seg(10, 12, "שתיים")])
        assert len(turns) == 2

    def test_speaker_change_splits_a_turn(self):
        turns = merge_turns([
            seg(0, 3, "אחד", speaker=0),
            seg(3.2, 6, "שתיים", speaker=1),
        ])
        assert len(turns) == 2
        assert [t.speaker for t in turns] == [0, 1]

    def test_turn_is_capped_so_it_stays_scannable(self):
        segments = [seg(i * 5, i * 5 + 5, f"חלק{i}") for i in range(30)]
        turns = merge_turns(segments)
        assert len(turns) > 1
        assert all(t.end - t.start <= 60 for t in turns)

    def test_blank_segments_are_skipped(self):
        turns = merge_turns([seg(0, 1, "אחד"), seg(1, 2, "   "), seg(2, 3, "שתיים")])
        assert len(turns) == 1
        assert turns[0].text == "אחד שתיים"


class TestRender:

    def test_empty_input(self):
        assert render([]) == ""

    def test_timestamps_only(self):
        out = render([seg(0, 2, "אחד"), seg(30, 32, "שתיים")])
        assert out == f"{RLM}{LRI}[0:00:00]{PDI} אחד\n{RLM}{LRI}[0:00:30]{PDI} שתיים"

    def test_speaker_numbering_is_one_based(self):
        """'Speaker 0' reads like a bug to anyone who isn't a programmer."""
        out = render([seg(0, 2, "אחד", speaker=0)], speaker_label="Speaker {n}")
        assert "Speaker 1:" in out
        assert "Speaker 0:" not in out

    def test_unattributed_segments_get_no_label(self):
        """Better to omit the speaker than to guess one."""
        out = render([seg(0, 2, "אחד", speaker=None)], speaker_label="דובר {n}")
        assert "דובר" not in out

    def test_no_timestamps_no_speakers_falls_back_to_plain(self):
        """The pre-existing output path has to stay genuinely unchanged."""
        segments = [Segment(start=0, end=1, text="שלום עולם. מה שלומך?")]
        assert render(segments, timestamps=False) == "שלום עולם.\nמה שלומך?"

    def test_plain_format_still_splits_sentences(self):
        assert format_plain("One. Two. Three!") == "One.\nTwo.\nThree!"
