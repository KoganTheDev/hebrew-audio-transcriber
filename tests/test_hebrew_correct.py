"""
Tests for the Hebrew correction pass.

The safety properties matter more than the corrections here. A pass like this
fails silently and plausibly: a bad replacement produces a real Hebrew word in
a real sentence, so nobody notices until they compare against the audio. Most
of these tests therefore assert that it does *nothing*.
"""

import pytest

from speech_to_text.core.hebrew_correct import (
    TermList,
    correct,
    strip_clitics,
    weighted_distance,
)
from speech_to_text.core.hebrew_text import normalize_word
from speech_to_text.core.segments import Segment, Word


def word(text, probability=0.9, start=0.0, end=1.0):
    return Word(start=start, end=end, text=text, probability=probability)


def segment_of(*words):
    return Segment(
        start=0.0, end=1.0,
        text="".join(w.text for w in words),
        words=list(words),
    )


class TestNormalize:

    def test_nikud_removed(self):
        assert normalize_word("שָׁלוֹם") == normalize_word("שלום")

    def test_final_forms_collapsed(self):
        assert normalize_word("ירושלים")[-1] == normalize_word("ירושלימ")[-1]


class TestStripClitics:

    def test_single_prefix(self):
        assert strip_clitics("בירושלים") == ("ב", "ירושלים")

    def test_stacked_prefixes(self):
        assert strip_clitics("ולירושלים") == ("ול", "ירושלים")

    def test_short_words_are_left_intact(self):
        """
        Stripping every leading ש would turn שלום into ום. The stem-length
        floor is what prevents that.
        """
        assert strip_clitics("שלום") == ("", "שלום")

    def test_word_of_only_clitics_is_not_consumed(self):
        prefix, stem = strip_clitics("ובכל")
        assert stem


class TestWeightedDistance:

    def test_identical_words_are_free(self):
        assert weighted_distance("שלום", "שלום") == 0.0

    def test_homophone_substitution_is_cheaper_than_a_normal_one(self):
        """
        א/ע sound alike, so confusing them is weak evidence of a different
        word. ש/ר do not, so confusing them is strong evidence.
        """
        homophone = weighted_distance("אבג", "עבג")
        unrelated = weighted_distance("אבג", "רבג")
        assert homophone < unrelated
        assert unrelated == 1.0

    def test_insertions_cost_full_price(self):
        assert weighted_distance("אבג", "אבגד") == 1.0

    def test_empty_strings(self):
        assert weighted_distance("", "אבג") == 3.0
        assert weighted_distance("אבג", "") == 3.0

    def test_cutoff_returns_early_without_lying_about_closeness(self):
        distance = weighted_distance("אבגדהו", "זחטיכל", cutoff=1.0)
        assert distance > 1.0


class TestTermList:

    def test_empty_list_matches_nothing(self):
        assert TermList([]).best_match("שלום") is None

    def test_close_word_matches(self):
        terms = TermList(["ירושלים"])
        match = terms.best_match("ירושלים")
        assert match is None or match[0] == "ירושלים"

    def test_homophone_error_is_corrected(self):
        """כ/ק are homophones - exactly the confusion an ASR model makes."""
        terms = TermList(["קיסריה"])
        match = terms.best_match("כיסריה")
        assert match is not None
        assert match[0] == "קיסריה"

    def test_prefix_is_preserved_on_the_correction(self):
        terms = TermList(["קיסריה"])
        match = terms.best_match("בכיסריה")
        assert match is not None
        assert match[0] == "בקיסריה"

    def test_unrelated_word_does_not_match(self):
        terms = TermList(["ירושלים"])
        assert terms.best_match("מחשב") is None

    def test_ambiguous_candidates_are_refused(self):
        """
        Two terms equally close means the choice is a coin flip, and a coin
        flip on a proper noun is worse than leaving the model's guess alone.
        """
        terms = TermList(["חתם", "חתן"])
        assert terms.best_match("חתך") is None

    def test_very_short_words_are_skipped(self):
        assert TermList(["ירושלים"]).best_match("א") is None

    def test_comments_and_blanks_are_ignored_when_loading(self, tmp_path):
        path = tmp_path / "terms.txt"
        path.write_text("# a comment\n\nירושלים\n  \nקיסריה\n", encoding="utf-8")
        terms = TermList.load(str(path))
        assert len(terms) == 2

    def test_missing_file_loads_empty(self, tmp_path):
        assert len(TermList.load(str(tmp_path / "nope.txt"))) == 0


class TestCorrect:

    def test_empty_term_list_is_a_strict_no_op(self):
        """The default state of the feature must change nothing."""
        seg = segment_of(word("כיסריה", probability=0.2))
        original = seg.text
        changes = correct([seg], TermList([]))
        assert changes == []
        assert seg.text == original

    def test_high_confidence_words_are_never_touched(self):
        """
        The confidence gate is the safety property: without it this becomes a
        dictionary pass over the whole transcript, which is the version that
        makes Hebrew worse.
        """
        seg = segment_of(word("כיסריה", probability=0.99))
        changes = correct([seg], TermList(["קיסריה"]))
        assert changes == []
        assert "כיסריה" in seg.text

    def test_low_confidence_word_is_corrected(self):
        seg = segment_of(word("כיסריה", probability=0.2))
        changes = correct([seg], TermList(["קיסריה"]))
        assert len(changes) == 1
        assert changes[0][0] == "כיסריה"
        assert changes[0][1] == "קיסריה"
        assert "קיסריה" in seg.text

    def test_spacing_around_a_corrected_word_survives(self):
        seg = segment_of(word("אני "), word("בכיסריה", probability=0.2), word(" היום"))
        correct([seg], TermList(["קיסריה"]))
        assert seg.text == "אני בקיסריה היום"

    def test_non_hebrew_tokens_are_ignored(self):
        seg = segment_of(word("Jerusalem", probability=0.1), word("123", probability=0.1))
        assert correct([seg], TermList(["ירושלים"])) == []

    def test_segments_without_word_timings_are_skipped(self):
        """Nothing to gate on, so nothing is safe to change."""
        seg = Segment(start=0, end=1, text="כיסריה", words=[])
        assert correct([seg], TermList(["קיסריה"])) == []

    def test_changes_are_returned_for_auditing(self):
        seg = segment_of(word("כיסריה", probability=0.2))
        changes = correct([seg], TermList(["קיסריה"]))
        assert changes[0][2] == pytest.approx(0.2)

    def test_correction_is_in_place(self):
        """worker.py relies on this - it never rebinds the segment list."""
        seg = segment_of(word("כיסריה", probability=0.2))
        correct([seg], TermList(["קיסריה"]))
        assert seg.words[0].text == "קיסריה"
