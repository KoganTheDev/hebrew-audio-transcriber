"""
Tests for the Hebrew correction pass.

The safety properties matter more than the corrections here. A pass like this
fails silently and plausibly: a bad replacement produces a real Hebrew word in
a real sentence, so nobody notices until they compare against the audio. Most
of these tests therefore assert that it does *nothing*.
"""

import pytest

from core.hebrew_corrections import (
    TermList,
    correct,
    strip_clitics,
    weighted_distance,
)
from core.hebrew_text import normalize_word
from core.segments import Segment, Word


def word(text, probability=0.9, start=0.0, end=1.0):
    return Word(start=start, end=end, text=text, probability=probability)


def segment_of(*words):
    return Segment(
        start=0.0,
        end=1.0,
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


class TestMultiWordTerms:
    """
    Terms with a space in them, which never matched before.

    faster-whisper emits one word at a time, and every word was compared to
    the whole term - so "יובל קוגן" or "באר שבע" in a term list did nothing
    unless the model happened to run the two words together.
    """

    def test_a_misheard_surname_is_fixed_inside_the_full_name(self):
        seg = segment_of(word("יובל "), word("כוגן", probability=0.2))
        changes = correct([seg], TermList(["יובל קוגן"]))

        assert seg.text == "יובל קוגן"
        assert changes == [("יובל כוגן", "יובל קוגן", pytest.approx(0.2))]

    def test_each_word_keeps_its_own_timing(self):
        """Word i of the term goes onto word i of the window, so playback and
        sentence splitting see the same timeline as before."""
        first = word("באר ", start=1.0, end=1.4)
        second = word("שבה", probability=0.3, start=1.4, end=1.9)
        seg = segment_of(first, second)
        correct([seg], TermList(["באר שבע"]))

        assert [(w.text, w.start, w.end) for w in seg.words] == [
            ("באר ", 1.0, 1.4),
            ("שבע", 1.4, 1.9),
        ]

    def test_a_prefix_on_the_first_word_is_kept(self):
        seg = segment_of(word("במכללת "), word("ברודה", probability=0.3))
        correct([seg], TermList(["מכללת בראודה"]))
        assert seg.text == "במכללת בראודה"

    def test_a_confident_word_is_never_rewritten_to_fit_a_term(self):
        """
        The confident word is evidence, not a candidate. Scored as one string,
        "דנה לא" is close enough to "דנה לוי"; but here the doubted word is
        the common לא, and the confident one would have had to change for
        the term to fit.
        """
        seg = segment_of(word("דנה ", probability=0.3), word("לא"))
        assert correct([seg], TermList(["דנה לוי"])) == []
        assert seg.text == "דנה לא"

    def test_a_doubted_common_word_too_far_from_the_term_is_left_alone(self):
        seg = segment_of(word("דנה "), word("לא", probability=0.3))
        assert correct([seg], TermList(["דנה לוי"])) == []

    def test_no_doubted_word_means_no_change(self):
        seg = segment_of(word("יובל "), word("כוגן"))
        assert correct([seg], TermList(["יובל קוגן"])) == []

    def test_an_already_correct_phrase_is_not_reported(self):
        seg = segment_of(word("יובל "), word("קוגן", probability=0.2))
        assert correct([seg], TermList(["יובל קוגן"])) == []

    def test_two_equally_close_phrases_are_refused(self):
        # Control: either term alone is close enough to be applied, so the
        # refusal below is the tie and not some other limit.
        alone = segment_of(word("דנה "), word("חתך", probability=0.2))
        assert correct([alone], TermList(["דנה חתם"])) != []

        tied = segment_of(word("דנה "), word("חתך", probability=0.2))
        assert correct([tied], TermList(["דנה חתם", "דנה חתן"])) == []
        assert tied.text == "דנה חתך"

    def test_a_word_a_phrase_claimed_is_not_corrected_again_alone(self):
        """The phrase pass runs first; its words are off-limits to the
        single-word pass, which could otherwise undo or double the fix."""
        seg = segment_of(word("יובל ", probability=0.2), word("כוגן", probability=0.2))
        changes = correct([seg], TermList(["יובל קוגן", "יובלים"]))

        assert seg.text == "יובל קוגן"
        assert len(changes) == 1

    def test_the_window_slides_across_the_segment(self):
        seg = segment_of(
            word("נפגשנו "),
            word("עם "),
            word("יובל "),
            word("כוגן", probability=0.2),
            word(" היום"),
        )
        correct([seg], TermList(["יובל קוגן"]))
        assert seg.text == "נפגשנו עם יובל קוגן היום"

    def test_a_three_word_term(self):
        seg = segment_of(word("תל "), word("אביב "), word("יבו", probability=0.3))
        correct([seg], TermList(["תל אביב יפו"]))
        assert seg.text == "תל אביב יפו"

    def test_single_word_terms_still_work_alongside_phrases(self):
        seg = segment_of(
            word("כיסריה ", probability=0.2), word("יובל "), word("כוגן", probability=0.2)
        )
        correct([seg], TermList(["קיסריה", "יובל קוגן"]))
        assert seg.text == "קיסריה יובל קוגן"

    def test_extra_spaces_inside_a_term_do_not_break_matching(self):
        seg = segment_of(word("יובל "), word("כוגן", probability=0.2))
        correct([seg], TermList(["יובל   קוגן"]))
        assert seg.text == "יובל קוגן"


class TestPunctuationAttachedToWords:
    """
    faster-whisper attaches punctuation to the word before it, so every name
    at the end of a sentence or before a comma used to fail the plain-Hebrew
    check and was never even considered.
    """

    def test_a_word_before_a_full_stop_is_corrected_and_keeps_it(self):
        seg = segment_of(word("נסענו "), word("לכיסריה.", probability=0.2))
        changes = correct([seg], TermList(["קיסריה"]))

        assert seg.text == "נסענו לקיסריה."
        assert changes[0][:2] == ("לכיסריה.", "לקיסריה.")

    @pytest.mark.parametrize("mark", [",", "?", "!", "...", ":", ";", "?!"])
    def test_trailing_marks_survive(self, mark):
        seg = segment_of(word("כיסריה" + mark, probability=0.2))
        correct([seg], TermList(["קיסריה"]))
        assert seg.text == "קיסריה" + mark

    def test_quotes_and_brackets_on_both_sides_survive(self):
        seg = segment_of(word('"כיסריה",', probability=0.2))
        correct([seg], TermList(["קיסריה"]))
        assert seg.text == '"קיסריה",'

    def test_a_word_ending_in_geresh_is_not_cut_short(self):
        """ג'ורג' ends in a geresh that is part of the word; stripping it as
        punctuation would hand the matcher a different, shorter word."""
        seg = segment_of(word("ג'ורג'", probability=0.2))
        assert correct([seg], TermList(["ג'ורג"])) == []
        assert seg.text == "ג'ורג'"

    def test_punctuation_alone_is_not_a_word(self):
        seg = segment_of(word("...", probability=0.1))
        assert correct([seg], TermList(["קיסריה"])) == []

    def test_a_phrase_at_the_end_of_a_sentence(self):
        seg = segment_of(word("עם "), word("יובל "), word("כוגן.", probability=0.2))
        correct([seg], TermList(["יובל קוגן"]))
        assert seg.text == "עם יובל קוגן."

    def test_a_phrase_in_quotes_keeps_both_quotes(self):
        seg = segment_of(word('"יובל '), word('כוגן"', probability=0.2))
        correct([seg], TermList(["יובל קוגן"]))
        assert seg.text == '"יובל קוגן"'

    def test_a_comma_inside_the_window_means_it_is_not_one_name(self):
        """ "יובל, כוגן" is two things said in a row, not a misheard name."""
        seg = segment_of(word("יובל, "), word("כוגן", probability=0.2))
        assert correct([seg], TermList(["יובל קוגן"])) == []
        assert seg.text == "יובל, כוגן"


class TestWordsTheRecordingShowsTheModelKnows:
    """
    Found on a real call (tests/eval/compare_term_correction): the term ענבל
    kept rewriting אבל ("but") - 1.25 apart, inside the 1.36 limit - although
    the same recording held אבל 29 times at confidence 1.0. A word the model
    has written confidently and repeatedly is a word it knows, not a
    misheard name, whatever term it happens to be close to.
    """

    def test_a_common_word_seen_confidently_elsewhere_is_left_alone(self):
        known = segment_of(word("אבל ", 1.0), word("טוב ", 1.0), word("אבל", 0.98))
        doubted = segment_of(word("אבל", probability=0.13))
        assert correct([known, doubted], TermList(["ענבל"])) == []
        assert doubted.text == "אבל"

    def test_the_same_word_with_no_confident_sightings_is_still_corrected(self):
        """Control: the guard, not the matcher, is what refused above."""
        doubted = segment_of(word("אבל", probability=0.13))
        assert correct([doubted], TermList(["ענבל"])) != []

    def test_one_confident_sighting_is_not_enough(self):
        """A misheard name can itself come out confident once - ציל for צליל
        at 0.96 on the same call - and must not then shield its other
        occurrences from correction."""
        once = segment_of(word("ציל", probability=0.96))
        doubted = segment_of(word("ציל", probability=0.3))
        correct([once, doubted], TermList(["צליל"]))
        assert doubted.text == "צליל"

    def test_punctuation_does_not_hide_a_known_word(self):
        known = segment_of(word("אבל, ", 1.0), word("אבל.", 1.0))
        doubted = segment_of(word("אבל...", probability=0.45))
        assert correct([known, doubted], TermList(["ענבל"])) == []

    def test_a_known_doubted_word_blocks_a_phrase_too(self):
        known = segment_of(word("נדבר ", 1.0), word("נדבר", 1.0))
        doubted = segment_of(word("יוסי "), word("נדבר", probability=0.3))
        assert correct([known, doubted], TermList(["יוסי נאור"])) == []
