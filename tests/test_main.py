"""
Tests for main module and entry points.
"""

import logging

import pytest
import sys
from unittest.mock import MagicMock, patch, call

from speech_to_text.core.log_bidi import VisualOrderFormatter


class TestMain:
    """Test main module."""

    def test_main_imports(self):
        """Test that main module imports are correct."""
        from speech_to_text import main

        assert hasattr(main, 'main')
        assert callable(main.main)

    def test_main_callable(self):
        """Test that main function is callable."""
        from speech_to_text.main import main

        assert callable(main)


class TestLoggingHandlers:
    """
    Regression coverage for the thing that actually matters here: the
    stdout handler and the file handler must end up with *different*
    formatters. main.py used to hand basicConfig(format=...) to both
    handlers at once, which is exactly what made the previous isolate fix
    invisible on screen while still working in speech_to_text.log - nothing
    else in the suite would notice the two streams being unified again.

    Read straight off the module's own stdout_handler/file_handler objects
    rather than enumerating logging.getLogger().handlers: pytest's own
    logging plugin adds handlers of its own to the root logger (also
    StreamHandler/FileHandler subclasses), which would otherwise have to be
    filtered out by guesswork.
    """

    def test_stream_handler_uses_visual_order_formatter(self):
        from speech_to_text import main  # noqa: F401 - import triggers basicConfig

        assert isinstance(main.stdout_handler.formatter, VisualOrderFormatter)

    def test_file_handler_uses_plain_formatter(self):
        from speech_to_text import main  # noqa: F401 - import triggers basicConfig

        assert type(main.file_handler.formatter) is logging.Formatter
        assert not isinstance(main.file_handler.formatter, VisualOrderFormatter)
