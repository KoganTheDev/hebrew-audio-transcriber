"""
Tests for the DER computation behind tests/eval/compare_diarization.py.

Two of these (test_confusion_only and test_missed_and_false_alarm) are cases
small enough to compute by hand - see the arithmetic in each docstring - so a
future change to compute_der's per-interval formula has something exact to
be checked against, not just "the number changed, is that good or bad".
"""

from tests.eval.diarization_metrics import (
    DERResult,
    compute_der,
    read_rttm,
)


class TestReadRttm:
    def test_parses_speaker_lines(self, tmp_path):
        path = tmp_path / "ref.rttm"
        path.write_text(
            "SPEAKER ES2004a 1 0.000 3.220 <NA> <NA> speaker1 <NA> <NA>\n"
            "SPEAKER ES2004a 1 3.220 1.500 <NA> <NA> speaker2 <NA> <NA>\n",
            encoding="utf-8",
        )
        turns = read_rttm(str(path))
        assert len(turns) == 2
        assert turns[0] == (0.0, 3.22, "speaker1")
        assert turns[1][0] == 3.22 and turns[1][2] == "speaker2"
        assert abs(turns[1][1] - 4.72) < 1e-9

    def test_ignores_non_speaker_rows_and_blank_lines(self, tmp_path):
        path = tmp_path / "ref.rttm"
        path.write_text(
            "\n"
            "SEGMENT ES2004a 1 0.000 3.220 <NA> <NA> <NA> <NA> <NA>\n"
            "SPEAKER ES2004a 1 0.000 3.220 <NA> <NA> speaker1 <NA> <NA>\n",
            encoding="utf-8",
        )
        turns = read_rttm(str(path))
        assert turns == [(0.0, 3.22, "speaker1")]

    def test_sorts_by_start_time(self, tmp_path):
        path = tmp_path / "ref.rttm"
        path.write_text(
            "SPEAKER f 1 5.0 1.0 <NA> <NA> b <NA> <NA>\n"
            "SPEAKER f 1 0.0 1.0 <NA> <NA> a <NA> <NA>\n",
            encoding="utf-8",
        )
        turns = read_rttm(str(path))
        assert [t[2] for t in turns] == ["a", "b"]


class TestComputeDer:
    def test_empty_reference_raises(self):
        import pytest

        with pytest.raises(ValueError):
            compute_der([], [(0.0, 1.0, "x")])

    def test_perfect_match_has_zero_der(self):
        reference = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
        hypothesis = [(0.0, 5.0, "spk0"), (5.0, 10.0, "spk1")]
        result = compute_der(reference, hypothesis)
        assert result.der == 0.0
        assert result.missed_speech == 0.0
        assert result.false_alarm == 0.0
        assert result.confusion == 0.0
        assert result.total_ref_speech == 10.0

    def test_confusion_only(self):
        """
        Hand-computed. Reference: one speaker A talking the whole 10s.
        Hypothesis: speaker X for [0,4) and [6,10) (8s total), speaker Y for
        [4,6) (2s) - a single wrong 2s stretch in the middle of otherwise
        correct output.

        Confusion matrix: (A,X)=8s, (A,Y)=2s -> optimal mapping A->X (the
        larger overlap).

        Per interval:
          [0,4):  ref={A}, hyp={X}, mapping(A)=X active -> correct. 4s.
          [4,6):  ref={A}, hyp={Y}, mapping(A)=X NOT active -> confusion. 2s.
          [6,10): ref={A}, hyp={X}, correct. 4s.

        total_ref = 10s, missed = 0, false_alarm = 0, confusion = 2s.
        DER = 2 / 10 = 0.2.
        """
        reference = [(0.0, 10.0, "A")]
        hypothesis = [(0.0, 4.0, "X"), (4.0, 6.0, "Y"), (6.0, 10.0, "X")]

        result = compute_der(reference, hypothesis)

        assert result.total_ref_speech == 10.0
        assert result.missed_speech == 0.0
        assert result.false_alarm == 0.0
        assert result.confusion == 2.0
        assert result.der == 0.2

    def test_missed_and_false_alarm(self):
        """
        Hand-computed. Reference: speaker A for [0,5). Hypothesis: speaker B
        for [2,7) - overlapping but shifted two seconds late.

        Only one speaker on each side, so the mapping is trivially A->B.

        Per interval:
          [0,2): ref={A}, hyp={}     -> missed, 2s.
          [2,5): ref={A}, hyp={B}    -> correct, 3s.
          [5,7): ref={},  hyp={B}    -> false_alarm, 2s. (n_ref=0, no
                                         contribution to total_ref)

        total_ref = 2 + 3 + 0 = 5s (matches A's own 5s duration).
        missed = 2s, false_alarm = 2s, confusion = 0.
        DER = (2 + 2 + 0) / 5 = 0.8.
        """
        reference = [(0.0, 5.0, "A")]
        hypothesis = [(2.0, 7.0, "B")]

        result = compute_der(reference, hypothesis)

        assert result.total_ref_speech == 5.0
        assert result.missed_speech == 2.0
        assert result.false_alarm == 2.0
        assert result.confusion == 0.0
        assert result.der == 0.8

    def test_no_hypothesis_at_all_is_total_miss(self):
        reference = [(0.0, 5.0, "A")]
        result = compute_der(reference, [])
        assert result.der == 1.0
        assert result.missed_speech == 5.0
        assert result.false_alarm == 0.0

    def test_optimal_mapping_beats_naive_label_order(self):
        """
        Reference speaker labels and hypothesis speaker labels are arbitrary
        strings/indices from unrelated systems - "A" has no reason to mean
        the same person as "spk0". Here the hypothesis's speaker order is
        deliberately reversed relative to the reference; a scorer that
        matched by label order (or first-seen order) instead of by actual
        overlap would wrongly report near-total confusion.
        """
        reference = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
        hypothesis = [(0.0, 5.0, "spk1"), (5.0, 10.0, "spk0")]
        result = compute_der(reference, hypothesis)
        assert result.der == 0.0

    def test_result_str_reports_all_components(self):
        result = DERResult(total_ref_speech=10.0, missed_speech=1.0, false_alarm=2.0, confusion=3.0)
        text = str(result)
        assert "0.6000" in text  # (1+2+3)/10
        assert "missed=1.00s" in text
        assert "false_alarm=2.00s" in text
        assert "confusion=3.00s" in text
