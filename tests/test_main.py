"""
Tests for main module and entry points.
"""

import logging
import os
import subprocess
import sys
from pathlib import Path

import pytest
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


class TestHighDpiEntryPointOrdering:
    """
    The high-DPI attributes live at module scope in gui/main_window.py, which
    only works because speech_to_text/main.py imports that module BEFORE it
    constructs its QApplication. Qt ignores AA_EnableHighDpiScaling once an
    application object exists, so reordering that import would not raise
    anything - it would silently drop the app back to blurry bitmap scaling,
    which is the kind of regression nobody notices until they look at a
    screenshot months later.

    TestHighDpiRendering above proves the attributes are set when the module
    is imported first. This proves the real entry point actually imports it
    first.
    """

    def test_main_imports_the_gui_module_before_constructing_qapplication(self):
        import ast
        import inspect

        import speech_to_text.main as main_module

        source = inspect.getsource(main_module)
        tree = ast.parse(source)

        import_line = None
        construct_line = None
        for node in ast.walk(tree):
            if (
                import_line is None
                and isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("speech_to_text.gui.main_window")
            ):
                import_line = node.lineno
            if (
                construct_line is None
                and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "QApplication"
            ):
                construct_line = node.lineno

        assert import_line is not None, "main.py no longer imports gui.main_window"
        assert construct_line is not None, "main.py no longer constructs QApplication directly"
        assert import_line < construct_line, (
            "speech_to_text/main.py constructs QApplication on line "
            f"{construct_line} before importing gui.main_window on line {import_line}. "
            "The high-DPI attributes are set at that module's import time and Qt "
            "ignores them once a QApplication exists, so this ordering is load-bearing."
        )


class TestHighDpiRendering:
    """
    Pin that speech_to_text.gui.main_window enables Qt's high-DPI
    rendering path - AA_EnableHighDpiScaling, AA_UseHighDpiPixmaps, and the
    PassThrough rounding policy (see the comment above that module's
    `_is_text_entry_widget` for why these three, and why they live at
    module scope there rather than duplicated in speech_to_text/main.py
    and this module's own main()). Without them Windows falls back to
    bitmap-stretching the whole window at 125%/150% scale - it still
    renders, just visibly soft, which is easy to miss in a screenshot-free
    CI run and exactly the kind of regression this test exists to catch.

    Qt requires these set BEFORE the QApplication instance is constructed,
    and once set they are process-global, not per-instance - so a plain
    in-process assertion here would depend on which test module happens to
    construct pytest's one shared QApplication first (several other GUI
    tests in this suite do too), which is exactly the kind of import-order
    fragility the codebase's own comments warn about elsewhere (see e.g.
    test_gui.py's qapp fixture). A subprocess sidesteps that: a fresh
    interpreter imports main_window (which sets the attributes as an
    import-time side effect - see that module), THEN constructs
    QApplication, and reports back what it actually saw.
    """

    def test_high_dpi_attributes_set_before_qapplication(self):
        repo_root = Path(__file__).resolve().parent.parent
        script = (
            "from PyQt5.QtCore import Qt\n"
            "from speech_to_text.gui.main_window import MainWindow\n"
            "from PyQt5.QtWidgets import QApplication\n"
            "app = QApplication([])\n"
            "print('scaling=%s pixmaps=%s policy=%s' % (\n"
            "    app.testAttribute(Qt.AA_EnableHighDpiScaling),\n"
            "    app.testAttribute(Qt.AA_UseHighDpiPixmaps),\n"
            "    int(QApplication.highDpiScaleFactorRoundingPolicy()),\n"
            "))\n"
        )
        env = dict(os.environ)
        # Headless platform plugin - no real display needed just to
        # construct a QApplication and read its attributes back.
        env["QT_QPA_PLATFORM"] = "offscreen"
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.returncode == 0, (
            f"subprocess failed (exit {result.returncode}):\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        assert "scaling=True pixmaps=True" in result.stdout, result.stdout
        # 5 == Qt.HighDpiScaleFactorRoundingPolicy.PassThrough - asserted
        # as the literal int since the subprocess can only hand back text
        # over stdout, not the enum object itself.
        assert "policy=5" in result.stdout, result.stdout
