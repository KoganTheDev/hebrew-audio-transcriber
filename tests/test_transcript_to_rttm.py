"""
Tests for the parsing/merging logic behind tests/eval/transcript_to_rttm.py.

Same mocking discipline as tests/test_diarization_metrics.py and
tests/test_hebrew_metrics.py: this exercises the pure parsing and turn-merge
functions against small inline HTML, never the real 1.23 MB hand-corrected
fixture (that fixture is exercised, once, by tests/eval/compare_diarization.py
directly - a dev harness, not this suite).
"""

from tests.eval.transcript_to_rttm import (
    build_rttm,
    merge_turns,
    parse_transcript,
)


def _bubble(start: str, end: str, speaker: str, turn: str = "0-0") -> str:
    return (
        f'<div class="bubble" data-line="0-0-0" data-turn="{turn}" '
        f'data-start="{start}" data-end="{end}" data-speaker="{speaker}" data-palette="0">'
        f"text</div>"
    )


def _roster(rows: dict[str, str]) -> str:
    """rows: speaker id -> human name, rendered as the app's own .speaker-row markup."""
    parts = []
    for speaker_id, name in rows.items():
        parts.append(
            f'<div class="speaker-row" data-speaker="{speaker_id}" data-palette="0">'
            f'<button type="button" class="swatch-trigger"></button>'
            f'<input class="speaker-name" type="text" value="{name}" '
            f'placeholder="Speaker {speaker_id}"></div>'
        )
    return "".join(parts)


class TestParseTranscript:
    def test_reads_bubbles_and_skips_unattributed_ones(self):
        html = (
            _bubble("0.00", "1.00", "0")
            + '<div class="bubble" data-start="1.00" data-end="2.00">no speaker</div>'
        )
        bubbles, _ = parse_transcript(html)
        assert len(bubbles) == 1
        assert bubbles[0].speaker == "0"

    def test_reads_speaker_names_from_roster_rows(self):
        html = _roster({"0": "Yair", "1": "Naor"})
        _, names = parse_transcript(html)
        assert names == {"0": "Yair", "1": "Naor"}

    def test_bare_speaker_name_input_with_no_enclosing_row_is_ignored(self):
        """A stray .speaker-name with no id-bearing .speaker-row around it
        (e.g. inside a menu template) must not silently claim some other
        speaker's id - it has none to claim."""
        html = '<input class="speaker-name" type="text" value="Ghost">'
        _, names = parse_transcript(html)
        assert names == {}

    def test_ignores_the_read_only_bubble_spk_chip_data_speaker(self):
        """The regression this whole script exists to avoid: a bubble's
        nested .bubble-spk button repeats data-speaker as a decorative copy,
        and a naive parse must not let its id override the bubble's own."""
        html = (
            '<div class="bubble" data-start="0.00" data-end="1.00" data-speaker="0">'
            '<button class="bubble-spk" data-speaker="1">Yair</button>'
            "</div>"
        )
        bubbles, _ = parse_transcript(html)
        assert len(bubbles) == 1
        assert bubbles[0].speaker == "0"


class TestMergeTurns:
    def test_consecutive_same_speaker_bubbles_merge_into_one_turn(self):
        html = _bubble("0.00", "5.00", "0") + _bubble("5.00", "9.00", "0")
        bubbles, names = parse_transcript(html)
        turns = merge_turns(bubbles, names)
        assert len(turns) == 1
        assert turns[0].start == 0.00
        assert turns[0].end == 9.00
        assert turns[0].speaker == "0"

    def test_speaker_change_produces_two_turns(self):
        html = _bubble("0.00", "5.00", "0") + _bubble("5.00", "9.00", "1")
        bubbles, names = parse_transcript(html)
        turns = merge_turns(bubbles, names)
        assert len(turns) == 2
        assert [t.speaker for t in turns] == ["0", "1"]
        assert turns[0].end == 5.00
        assert turns[1].start == 5.00

    def test_speaker_names_are_used_as_labels_when_available(self):
        html = (
            _roster({"0": "Yair", "1": "Naor"})
            + _bubble("0.00", "5.00", "0")
            + _bubble("5.00", "9.00", "1")
        )
        bubbles, names = parse_transcript(html)
        turns = merge_turns(bubbles, names)
        assert [t.speaker for t in turns] == ["Yair", "Naor"]

    def test_falls_back_to_numeric_id_when_name_is_missing(self):
        html = _bubble("0.00", "5.00", "0")
        bubbles, names = parse_transcript(html)
        turns = merge_turns(bubbles, names)
        assert turns[0].speaker == "0"

    def test_name_containing_a_space_is_underscore_joined_for_rttm_safety(self):
        """RTTM's speaker field is one positional column - a name with a
        space would shift every column after it (see read_rttm)."""
        html = _roster({"0": "Yair Shizaf"}) + _bubble("0.00", "5.00", "0")
        bubbles, names = parse_transcript(html)
        turns = merge_turns(bubbles, names)
        assert turns[0].speaker == "Yair_Shizaf"


class TestBuildRttm:
    def test_round_trips_through_read_rttm(self):
        import os
        import tempfile

        from tests.eval.diarization_metrics import read_rttm

        html = (
            _roster({"0": "Yair", "1": "Naor"})
            + _bubble("0.00", "5.00", "0")
            + _bubble("5.00", "9.00", "0")
            + _bubble("9.00", "12.00", "1")
        )
        rttm_text = build_rttm(html, file_id="test", source="test.html")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test.rttm")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(rttm_text)
            turns = read_rttm(path)

        assert turns == [(0.0, 9.0, "Yair"), (9.0, 12.0, "Naor")]

    def test_header_lines_are_not_speaker_rows(self):
        """Provenance header lines must not be mistaken for SPEAKER rows by
        read_rttm - they don't start with the literal token "SPEAKER"."""
        html = _bubble("0.00", "1.00", "0")
        rttm_text = build_rttm(html, file_id="test", source="test.html")
        header_lines = [line for line in rttm_text.splitlines() if not line.startswith("SPEAKER")]
        assert header_lines  # the provenance header is present
        assert all(line.startswith("#") for line in header_lines)

    def test_raises_on_transcript_with_no_labelled_bubbles(self):
        import pytest

        with pytest.raises(ValueError):
            build_rttm("<html><body>no bubbles here</body></html>", file_id="x", source="x.html")
