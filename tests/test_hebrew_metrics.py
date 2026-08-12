"""
Tests for the Hebrew normalisation behind WER/CER.

These matter because a normalisation bug does not crash - it silently produces
a plausible-looking error rate that is wrong, which is worse than no number at
all.
"""

import math

from tests.eval.hebrew_metrics import (
    character_error_rate, edit_distance, normalize, tokens, word_error_rate,
)


class TestNormalize:

    def test_nikud_is_not_a_recognition_error(self):
        assert normalize("שָׁלוֹם עוֹלָם") == normalize("שלום עולם")

    def test_final_forms_collapse_to_their_base_letter(self):
        """Positional variants of one letter, not different letters."""
        assert normalize("שלום") == normalize("שלומ")
        assert normalize("ארץ") == normalize("ארצ")

    def test_punctuation_is_dropped(self):
        assert tokens("שלום, מה שלומך?") == tokens("שלום מה שלומך")

    def test_our_own_bidi_controls_are_dropped(self):
        # Trailing מ, not ם - final-form collapsing applies here too.
        assert normalize("‏⁦שלום⁩") == "שלומ"

    def test_rendered_timestamps_are_dropped(self):
        """
        A reference transcript is usually a corrected copy of a saved run, so
        it arrives with timestamps. Leaving the digits in would count them as
        words and inflate the error rate.
        """
        rendered = "‏⁦[0:01:23]⁩ שלום עולם"
        assert normalize(rendered) == "שלומ עולמ"

    def test_speaker_labels_are_dropped(self):
        assert normalize("דובר 1: שלום") == "שלומ"
        assert normalize("Speaker 2: שלום") == "שלומ"

    def test_whitespace_is_collapsed(self):
        assert normalize("  שלום    עולם  ") == "שלומ עולמ"


class TestEditDistance:

    def test_identical_sequences(self):
        assert edit_distance(["a", "b"], ["a", "b"]) == 0

    def test_substitution_insertion_deletion(self):
        assert edit_distance(["a", "b"], ["a", "c"]) == 1
        assert edit_distance(["a"], ["a", "b"]) == 1
        assert edit_distance(["a", "b"], ["a"]) == 1

    def test_empty_reference(self):
        assert edit_distance([], ["a", "b"]) == 2


class TestErrorRates:

    def test_identical_text_scores_zero(self):
        text = "שלום מה שלומך היום"
        assert word_error_rate(text, text) == 0.0
        assert character_error_rate(text, text) == 0.0

    def test_one_wrong_word_in_four(self):
        assert word_error_rate("שלום מה שלומך היום", "שלום מה שלומך אתמול") == 0.25

    def test_formatting_only_differences_score_zero(self):
        """The whole point of normalising: this is not a recognition error."""
        assert word_error_rate("שלום מה שלומך", "שָׁלוֹם, מה שלומך!") == 0.0

    def test_empty_reference_is_undefined_not_zero(self):
        """Returning 0.0 here would read as a perfect score."""
        assert math.isnan(word_error_rate("", "שלום"))
        assert math.isnan(character_error_rate("", "שלום"))
