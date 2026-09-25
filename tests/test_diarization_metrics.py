"""
Tests for the DER computation behind tests/eval/compare_diarization.py.

Two of these (test_confusion_only and test_missed_and_false_alarm) are cases
small enough to compute by hand - see the arithmetic in each docstring - so a
future change to compute_der's per-interval formula has something exact to
be checked against, not just "the number changed, is that good or bad".
"""

import pytest

from tests.eval.diarization_metrics import (
    DERResult,
    compute_der,
    read_rttm,
    read_uem,
    speaker_count_error,
    speaker_recall,
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


class TestSpeakerRecall:
    def test_one_of_two_speakers_never_found_but_der_looks_unremarkable(self):
        """
        The case this whole stage exists for: a hypothesis that covers
        speaker A perfectly but never mentions speaker B at all. DER, being
        time-weighted over the whole file, reports this as "half the speech
        is missed" - a mediocre number, not an alarming one - because B's
        lost speech is indistinguishable in the DER formula from any other
        missed_speech. speaker_recall must show it as 1 of 2 speakers found,
        with B's own coverage at 0.0.
        """
        reference = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
        hypothesis = [(0.0, 5.0, "spk0")]

        der = compute_der(reference, hypothesis)
        assert 0.4 < der.der < 0.6  # unremarkable-looking DER

        result = speaker_recall(reference, hypothesis)
        assert result.found_count == 1
        assert result.total_count == 2
        assert result.per_speaker["A"] == 1.0
        assert result.per_speaker["B"] == 0.0

    def test_perfect_coverage_finds_every_speaker(self):
        reference = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
        hypothesis = [(0.0, 5.0, "spk0"), (5.0, 10.0, "spk1")]
        result = speaker_recall(reference, hypothesis)
        assert result.found_count == 2
        assert result.total_count == 2
        assert result.per_speaker["A"] == 1.0
        assert result.per_speaker["B"] == 1.0

    def test_zero_coverage_speaker_is_not_found(self):
        reference = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
        hypothesis = [(20.0, 25.0, "spk0")]  # entirely outside both speakers
        result = speaker_recall(reference, hypothesis)
        assert result.found_count == 0
        assert result.per_speaker["A"] == 0.0
        assert result.per_speaker["B"] == 0.0

    def test_partial_coverage_is_a_fraction_not_a_boolean(self):
        reference = [(0.0, 10.0, "A")]
        hypothesis = [(0.0, 3.0, "spk0")]  # covers 3 of A's 10 seconds
        result = speaker_recall(reference, hypothesis)
        assert result.per_speaker["A"] == 0.3
        assert result.found_count == 1  # 0.3 is well above the "found" floor


class TestSpeakerCountError:
    def test_matching_counts_is_zero_error(self):
        reference = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
        hypothesis = [(0.0, 5.0, "spk0"), (5.0, 10.0, "spk1")]
        result = speaker_count_error(reference, hypothesis)
        assert result.error == 0

    def test_under_clustering_two_people_collapsed_into_one_is_negative(self):
        """Two reference speakers, one hypothesis label - the "second speaker
        isn't recognised at all" failure mode reported at
        src/config/diarization.py's AMI finding."""
        reference = [(0.0, 5.0, "A"), (5.0, 10.0, "B")]
        hypothesis = [(0.0, 10.0, "spk0")]
        result = speaker_count_error(reference, hypothesis)
        assert result.error == -1

    def test_over_clustering_one_person_split_into_several_is_positive(self):
        reference = [(0.0, 10.0, "A")]
        hypothesis = [(0.0, 5.0, "spk0"), (5.0, 10.0, "spk1")]
        result = speaker_count_error(reference, hypothesis)
        assert result.error == 1


class TestScoredRegions:
    """
    compute_der's `scored` mask, and read_uem.

    A reference built by aligning a human transcript onto machine timings has
    HOLES: a line the aligner could not confidently match is dropped rather
    than guessed at, leaving a gap the reference cannot tell apart from
    silence. Speech correctly detected in a hole was being counted as
    invented - measured at 218s of one real fixture's span, which was also the
    fixture with by far the highest false alarm.
    """

    def test_a_hole_in_the_reference_inflates_false_alarm_when_scored(self):
        """The bug, stated as a test: the hypothesis is RIGHT about 0-10, and
        the reference simply does not cover 5-10."""
        reference = [(0.0, 5.0, "A")]
        hypothesis = [(0.0, 10.0, "spk0")]

        unmasked = compute_der(reference, hypothesis)
        assert unmasked.false_alarm == pytest.approx(5.0)

        # Withhold the hole, and the same hypothesis scores clean.
        masked = compute_der(reference, hypothesis, scored=[(0.0, 5.0)])
        assert masked.false_alarm == pytest.approx(0.0)
        assert masked.der == pytest.approx(0.0)

    def test_the_mask_clips_both_sides_not_just_the_hypothesis(self):
        """Reference speech outside a scored region must not count toward
        missed speech either - otherwise the denominator includes time the
        run was never asked about."""
        reference = [(0.0, 10.0, "A")]
        hypothesis = [(0.0, 5.0, "spk0")]

        masked = compute_der(reference, hypothesis, scored=[(0.0, 5.0)])
        assert masked.total_ref_speech == pytest.approx(5.0)
        assert masked.missed_speech == pytest.approx(0.0)

    def test_no_mask_scores_the_whole_timeline(self):
        """AMI's reference is hand-drawn, so a gap there really is silence -
        passing no mask has to keep counting it."""
        reference = [(0.0, 5.0, "A")]
        hypothesis = [(0.0, 10.0, "spk0")]
        assert compute_der(reference, hypothesis, scored=None).false_alarm == pytest.approx(5.0)

    def test_a_mask_that_excludes_all_reference_speech_is_an_error(self):
        """Not silently a DER of 0: scoring nothing is a misconfigured run,
        and the existing empty-reference guard is the right place to land."""
        with pytest.raises(ValueError):
            compute_der([(0.0, 5.0, "A")], [(0.0, 5.0, "spk0")], scored=[(90.0, 95.0)])

    def test_read_uem_parses_regions_and_skips_comments(self, tmp_path):
        path = tmp_path / "f.uem"
        path.write_text(
            "# a comment line, the same shape read_rttm tolerates\n"
            "\n"
            "myfile 1 0.00 12.50\n"
            "myfile 1 20.00 33.25\n",
            encoding="utf-8",
        )
        assert read_uem(str(path)) == [(0.0, 12.5), (20.0, 33.25)]
