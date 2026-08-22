"""
Tests for the RTL isolate helper in core/hebrew_text.py.

isolate_rtl() exists to stop Hebrew text logged into an otherwise-LTR line
(see core/transcriber.py's per-segment DEBUG line) from having a trailing
neutral character - like the comma faster-whisper leaves on a truncated
segment - reorder to the wrong side under the Unicode Bidirectional
Algorithm. See the long comment in hebrew_text.py for the full reasoning;
these tests just pin the observable behaviour.
"""

from speech_to_text.core.hebrew_text import PDI, RLI, isolate_rtl


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
