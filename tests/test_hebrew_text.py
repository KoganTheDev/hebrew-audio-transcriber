"""
Tests for the RTL isolate helper in core/hebrew_text.py.

isolate_rtl() exists to stop Hebrew text logged into an otherwise-LTR line
(see core/transcriber.py's per-segment DEBUG line) from having a trailing
neutral character - like the comma faster-whisper leaves on a truncated
segment - reorder to the wrong side under the Unicode Bidirectional
Algorithm. See the long comment in hebrew_text.py for the full reasoning;
these tests just pin the observable behaviour.
"""

from speech_to_text.core.hebrew_text import PDI, RLI, isolate_rtl, to_visual_order


def test_wraps_hebrew_text_in_rtl_isolate():
    result = isolate_rtl("סניף כשר למהדרין,")
    assert result == f"{RLI}סניף כשר למהדרין,{PDI}"
    assert result.startswith(RLI)
    assert result.endswith(PDI)


def test_does_not_wrap_pure_ascii_text():
    """
    An all-ASCII preview has no bidi problem to fix - wrapping it would only
    add invisible control characters that anyone grepping the log file (or
    speech_to_text.log) would have to know to ignore.
    """
    assert isolate_rtl("Hello World") == "Hello World"


def test_does_not_wrap_empty_or_placeholder_text():
    assert isolate_rtl("") == ""
    assert isolate_rtl("(empty)") == "(empty)"


def test_wraps_mixed_hebrew_and_latin_text():
    """Even one Hebrew character means the run needs isolating."""
    result = isolate_rtl("abc שלום")
    assert result == f"{RLI}abc שלום{PDI}"


class TestToVisualOrder:
    """
    to_visual_order() turns a logical-order line into the visual order a
    non-bidi console needs - see the module comment above the function for
    why. These pin the observable behaviour of the scoped UBA subset it
    implements, not the algorithm's internals.
    """

    def test_pure_hebrew_run_reverses(self):
        assert to_visual_order("שלום") == "םולש"

    def test_isolated_run_keeps_trailing_comma_inside(self):
        """
        isolate_rtl() already records that the trailing comma
        faster-whisper leaves on a truncated segment belongs inside the
        Hebrew run - to_visual_order must honour that rather than treating
        the comma as a separate neutral character.
        """
        isolated = isolate_rtl("סניף כשר למהדרין,")
        assert to_visual_order(isolated) == ",ןירדהמל רשכ ףינס"

    def test_ascii_line_is_returned_identical(self):
        """
        No strong-RTL character and no isolate span means nothing to
        reorder - the common case (every non-Hebrew log line) must not pay
        for a reorder it doesn't need, so this asserts object identity, not
        just equal content.
        """
        text = "Starting Hebrew Audio Transcriber v1.0"
        assert to_visual_order(text) is text

    def test_mixed_line_reverses_only_the_hebrew(self):
        assert to_visual_order("abc שלום def") == "abc םולש def"

    def test_digits_inside_a_hebrew_run_stay_left_to_right(self):
        """
        "42" sits inside one continuous RTL run here (flanked by Hebrew
        letters on both sides), so without the digit-preserving step it
        would come back as "24" - reversed along with everything else.
        """
        assert to_visual_order("אב 42 גד") == "דג 42 בא"

    def test_parens_keep_visually_enclosing_the_word(self):
        """
        The parens themselves sit outside the RTL run (each is flanked by
        a line boundary on one side, not Hebrew on both), so they are left
        in place while the word inside is reversed - the net effect is
        that they still visually enclose it.
        """
        assert to_visual_order("(שלום)") == "(םולש)"

    def test_parens_swallowed_into_an_isolate_span_are_mirrored(self):
        """
        Here the whole isolate span - parens included - is one RTL run, so
        a plain reversal alone would flip "(" and ")" to the wrong sides.
        MIRROR_PAIRS is what puts them back the right way round.
        """
        isolated = isolate_rtl("(סניף)")
        assert to_visual_order(isolated) == "(ףינס)"
