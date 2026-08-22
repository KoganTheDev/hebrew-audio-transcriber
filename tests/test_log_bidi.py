"""
Tests for core/log_bidi.py - the mode resolution and the formatter that
applies to_visual_order() to the console stream only. See the module
comment in core/hebrew_text.py above to_visual_order() and the docstring on
visual_order_mode() for why this exists.
"""

import logging
from unittest.mock import patch

import pytest

from speech_to_text.core.hebrew_text import isolate_rtl
from speech_to_text.core.log_bidi import VisualOrderFormatter, visual_order_mode


class TestVisualOrderMode:
    def test_explicit_visual_wins_regardless_of_platform_or_tty(self, monkeypatch):
        monkeypatch.setenv("STT_LOG_BIDI", "visual")
        with patch("os.name", "posix"), patch("sys.stdout.isatty", return_value=False):
            assert visual_order_mode() == "visual"

    def test_explicit_logical_wins_regardless_of_platform_or_tty(self, monkeypatch):
        monkeypatch.setenv("STT_LOG_BIDI", "logical")
        with patch("os.name", "nt"), patch("sys.stdout.isatty", return_value=True):
            assert visual_order_mode() == "logical"

    def test_auto_is_visual_on_windows_tty(self, monkeypatch):
        monkeypatch.delenv("STT_LOG_BIDI", raising=False)
        with patch("os.name", "nt"), patch("sys.stdout.isatty", return_value=True):
            assert visual_order_mode() == "visual"

    def test_auto_is_logical_when_redirected(self, monkeypatch):
        monkeypatch.delenv("STT_LOG_BIDI", raising=False)
        with patch("os.name", "nt"), patch("sys.stdout.isatty", return_value=False):
            assert visual_order_mode() == "logical"

    def test_auto_is_logical_off_windows(self, monkeypatch):
        monkeypatch.delenv("STT_LOG_BIDI", raising=False)
        with patch("os.name", "posix"), patch("sys.stdout.isatty", return_value=True):
            assert visual_order_mode() == "logical"

    def test_unrecognised_value_falls_back_to_auto(self, monkeypatch):
        monkeypatch.setenv("STT_LOG_BIDI", "sideways")
        with patch("os.name", "nt"), patch("sys.stdout.isatty", return_value=True):
            assert visual_order_mode() == "visual"


class TestVisualOrderFormatter:
    def _record(self, message: str) -> logging.LogRecord:
        return logging.LogRecord(
            name="speech_to_text.core.transcriber",
            level=logging.DEBUG,
            pathname="transcriber.py",
            lineno=169,
            msg=message,
            args=None,
            exc_info=None,
        )

    def test_reorders_hebrew_in_visual_mode(self, monkeypatch):
        monkeypatch.setenv("STT_LOG_BIDI", "visual")
        formatter = VisualOrderFormatter("%(message)s")
        result = formatter.format(self._record(isolate_rtl("שלום")))
        assert result == "םולש"

    def test_leaves_message_untouched_in_logical_mode(self, monkeypatch):
        monkeypatch.setenv("STT_LOG_BIDI", "logical")
        formatter = VisualOrderFormatter("%(message)s")
        isolated = isolate_rtl("שלום")
        result = formatter.format(self._record(isolated))
        assert result == isolated

    def test_reorders_each_line_of_a_multiline_message_separately(self, monkeypatch):
        monkeypatch.setenv("STT_LOG_BIDI", "visual")
        formatter = VisualOrderFormatter("%(message)s")
        message = f"{isolate_rtl('שלום')}\n{isolate_rtl('בוקר')}"
        result = formatter.format(self._record(message))
        assert result == "םולש\nרקוב"
