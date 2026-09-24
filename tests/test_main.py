"""
Tests for the app entry point.
"""

import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

import app as app_module
import config
from core.log_bidi import VisualOrderFormatter

# Driven by TestBackgroundWorkStopsBeforeExit. Kept at module level rather than
# inline so the quoting stays readable.
SPY_SCRIPT = """
from PyQt5.QtWidgets import QApplication
import gui.main_window as mw

seen = {}
real_init = mw.MainWindow.__init__


def spy_init(self, *a, **k):
    real_init(self, *a, **k)
    seen['w'] = self


mw.MainWindow.__init__ = spy_init
QApplication.exec_ = lambda self: 0

import app as app_module

try:
    app_module.main()
except SystemExit:
    pass

w = seen['w']
t = getattr(w, 'calibration_thread', None)
print('THREAD_PRESENT=%s' % (t is not None))
try:
    running = t is not None and t.isRunning()
except RuntimeError:
    # "wrapped C/C++ object has been deleted" - Qt already disposed of it,
    # which is a stronger guarantee than "not running", not a failure.
    running = False
print('THREAD_RUNNING=%s' % running)
"""


class TestMain:
    """Test main module."""

    def test_main_imports(self):
        """Test that main module imports are correct."""
        import app

        assert hasattr(app, "main")
        assert callable(app.main)

    def test_main_callable(self):
        """Test that main function is callable."""
        from app import main

        assert callable(main)


class TestLoggingHandlers:
    """
    Regression coverage for the thing that actually matters here: the
    stdout handler and the file handler must end up with *different*
    formatters. app.py used to hand basicConfig(format=...) to both
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
        import app  # noqa: F401 - import triggers basicConfig

        assert isinstance(app.stdout_handler.formatter, VisualOrderFormatter)

    def test_file_handler_uses_plain_formatter(self):
        import app  # noqa: F401 - import triggers basicConfig

        assert type(app.file_handler.formatter) is logging.Formatter
        assert not isinstance(app.file_handler.formatter, VisualOrderFormatter)


class TestHighDpiEntryPointOrdering:
    """
    The high-DPI attributes live at module scope in gui/main_window.py, which
    only works because app.py imports that module BEFORE it
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

        import app as app_module

        source = inspect.getsource(app_module)
        tree = ast.parse(source)

        import_line = None
        construct_line = None
        for node in ast.walk(tree):
            if (
                import_line is None
                and isinstance(node, ast.ImportFrom)
                and (node.module or "").startswith("gui.main_window")
            ):
                import_line = node.lineno
            if (
                construct_line is None
                and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                # DiagnosticApplication (gui/crash_handler.py) is a QApplication
                # subclass app.py constructs instead of QApplication directly,
                # to route Qt-slot exceptions to the crash handler - same
                # ordering requirement applies to it.
                and node.func.id in ("QApplication", "DiagnosticApplication")
            ):
                construct_line = node.lineno

        assert import_line is not None, "app.py no longer imports gui.main_window"
        assert construct_line is not None, "app.py no longer constructs QApplication directly"
        assert import_line < construct_line, (
            "app.py constructs QApplication on line "
            f"{construct_line} before importing gui.main_window on line {import_line}. "
            "The high-DPI attributes are set at that module's import time and Qt "
            "ignores them once a QApplication exists, so this ordering is load-bearing."
        )


class TestHighDpiRendering:
    """
    Pin that gui.main_window enables Qt's high-DPI
    rendering path - AA_EnableHighDpiScaling, AA_UseHighDpiPixmaps, and the
    PassThrough rounding policy (see the comment above that module's
    `_is_text_entry_widget` for why these three, and why they live at
    module scope there rather than duplicated in app.py
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
            "from gui.main_window import MainWindow\n"
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
        # src-layout: cwd=repo_root no longer puts the package on the child's
        # sys.path, so name it explicitly.
        env["PYTHONPATH"] = str(repo_root / "src")
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


class TestShippedEntryPointAppliesStylesheet:
    """
    app.setStyleSheet(theme.app_stylesheet()) used to exist only inside
    gui/main_window.py's own main(), reachable exclusively via
    `python -m gui.main_window` - a path nothing shipped
    (run.ps1, run.bat, `python srcpp.py`, the `speech-to-text`
    console script) ever uses. Every one of those goes through
    app.py::main(), which built its own QApplication and
    never applied the stylesheet at all: the whole themed look (peach
    checkbox tick, radio ring-and-dot, styled scrollbars/tooltip, the
    kbdFocus ring on native controls) was silently absent from every real
    launch. `theme.app_stylesheet()` returning a non-empty string already
    passed the whole time this bug was live, so a test on that function in
    isolation proves nothing - this has to run the actual shipped entry
    point and look at the QApplication instance it produces.

    Like TestHighDpiRendering above, a subprocess is used rather than an
    in-process call: app.py constructs its own process-wide QApplication
    and calls sys.exit() on the way out, neither of which plays well with
    pytest's shared QApplication or its own process. QApplication.exec_ is
    monkeypatched to capture styleSheet() and return immediately instead of
    blocking on a real event loop - this test cares whether the stylesheet
    was applied before the loop starts, not about running the loop itself.
    """

    def test_main_dot_py_entry_point_applies_a_non_empty_stylesheet(self):
        repo_root = Path(__file__).resolve().parent.parent
        script = (
            "from PyQt5.QtWidgets import QApplication\n"
            "captured = {}\n"
            "def fake_exec(self):\n"
            "    captured['stylesheet'] = self.styleSheet()\n"
            "    return 0\n"
            "QApplication.exec_ = fake_exec\n"
            "import app as app_module\n"
            "try:\n"
            "    app_module.main()\n"
            "except SystemExit:\n"
            "    pass\n"
            "sheet = captured.get('stylesheet', '')\n"
            "print('STYLESHEET_LEN=%d' % len(sheet))\n"
        )
        env = dict(os.environ)
        # Headless platform plugin - the real entry point builds a full
        # MainWindow and calls show() on it; offscreen lets that happen
        # without a real display, same as TestHighDpiRendering above.
        env["QT_QPA_PLATFORM"] = "offscreen"
        # src-layout: cwd=repo_root no longer puts the package on the child's
        # sys.path, so name it explicitly.
        env["PYTHONPATH"] = str(repo_root / "src")
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=repo_root,
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        assert result.returncode == 0, (
            f"subprocess failed (exit {result.returncode}):\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        marker = "STYLESHEET_LEN="
        line = next((out for out in result.stdout.splitlines() if out.startswith(marker)), None)
        assert line is not None, (
            f"subprocess never printed a stylesheet length:\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        length = int(line[len(marker) :])
        assert length > 0, (
            "main.main() produced a QApplication with an "
            "empty styleSheet() - the shipped entry point is not applying "
            "theme.app_stylesheet() to the real application object."
        )


class TestBackgroundWorkStopsBeforeExit:
    """
    main() must not return while the calibration thread is still running.

    The failure this guards is an access violation (exit 3221225477) with an
    empty stderr, seen on 5 of 28 Windows CI runs. Its log ends with main()'s
    own "Application shutdown sequence completed", 9ms after "Starting
    background hardware calibration" - so main() finished cleanly and the
    process died during interpreter teardown, with a QThread and the
    multiprocessing child it was still spawning both in flight. A Python spawn
    takes far longer than 9ms, so a slow runner exits mid-spawn.

    MainWindow._detach_calibration_thread already handles this, but only from
    closeEvent. This path never closes the window: exec_() returns and main()
    falls straight through to sys.exit. A fresh CI runner has no calibration
    cache, so the thread always starts there, which is why CI sees this and a
    developer machine with a warm cache almost never does.
    """

    def test_main_does_not_return_with_a_live_calibration_thread(self):
        repo_root = Path(__file__).resolve().parent.parent
        script = SPY_SCRIPT
        env = dict(os.environ)
        env["QT_QPA_PLATFORM"] = "offscreen"
        env["PYTHONPATH"] = str(repo_root / "src")
        # An empty model root, so there is no calibration cache to load and the
        # thread actually starts - the CI runner's situation, reproduced
        # deliberately. SPEECH_TO_TEXT_MODEL_DIR, not an empty cwd: the cache
        # used to be a bare relative "whisper_models/.calibration.json", so
        # simply running from elsewhere was enough to miss it. That was a bug
        # (see TestCalibrationCachePath in test_config.py) and it is now fixed,
        # which leaves the documented env override as the honest way to ask for
        # a cold machine.
        with tempfile.TemporaryDirectory() as cold:
            env["SPEECH_TO_TEXT_MODEL_DIR"] = cold
            result = subprocess.run(
                [sys.executable, "-c", script],
                cwd=cold,
                capture_output=True,
                text=True,
                env=env,
                timeout=180,
            )
        assert result.returncode == 0, (
            f"subprocess failed (exit {result.returncode}):"
            f"\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
        assert "THREAD_PRESENT=True" in result.stdout, (
            "the calibration thread never started, so this proves nothing: " + result.stdout
        )
        assert "THREAD_RUNNING=False" in result.stdout, (
            "main() returned with the calibration thread still running: " + result.stdout
        )


class TestReexecIntoProjectVenv:
    """
    app.py restarts itself on the project's .venv when started elsewhere,
    because the launchers are not the only way in - a direct `python
    src/app.py`, a double-click and an IDE run button all bypass them, and
    app.py puts src/ on sys.path itself so all of them start successfully on
    an interpreter that may have no dependencies.

    These cover the three cases that must NOT spawn. The spawning case is
    covered end-to-end by launching on a foreign interpreter; what matters
    here is that the guards hold, because a wrong one forks forever.
    """

    @staticmethod
    def _spy(monkeypatch):
        calls = []
        monkeypatch.setattr(app_module.subprocess, "run", lambda *a, **k: calls.append(a))
        return calls

    def test_the_marker_stops_a_child_re_execing_again(self, monkeypatch):
        """The loop guard. Without it a mismatch that survives the hop forks forever."""
        monkeypatch.setenv(app_module._REEXEC_MARKER, "1")
        calls = self._spy(monkeypatch)

        app_module._reexec_into_project_venv()

        assert calls == []

    def test_no_venv_means_no_spawn(self, monkeypatch, tmp_path):
        """ensure_dependencies reports this case and can say more about it."""
        monkeypatch.delenv(app_module._REEXEC_MARKER, raising=False)
        monkeypatch.setattr(app_module, "__file__", str(tmp_path / "src" / "app.py"))
        calls = self._spy(monkeypatch)

        app_module._reexec_into_project_venv()

        assert calls == []

    def test_already_on_the_venv_python_means_no_spawn(self, monkeypatch, tmp_path):
        """
        Compared with samefile, not string equality: the same interpreter
        reaches us spelled differently via symlinks, 8.3 names and case.
        """
        monkeypatch.delenv(app_module._REEXEC_MARKER, raising=False)
        venv_python = tmp_path / ".venv" / "Scripts" / "python.exe"
        venv_python.parent.mkdir(parents=True)
        venv_python.write_text("", encoding="utf-8")
        monkeypatch.setattr(app_module, "__file__", str(tmp_path / "src" / "app.py"))
        monkeypatch.setattr(app_module.sys, "executable", str(venv_python))
        calls = self._spy(monkeypatch)

        app_module._reexec_into_project_venv()

        assert calls == []


class TestStartupFailuresAreVisible:
    """
    The launchers now start the app with pythonw.exe, which has no console
    (run.bat/run.ps1). Every failure BEFORE the Qt crash handler is installed
    therefore has no stream anyone will ever read - it used to be a log line
    and a bare sys.exit(1), i.e. a window that simply never appeared.

    fatal() is the replacement, and these pin the two properties that make it
    worth having: it tells the user something, and it still exits non-zero.
    A native MessageBox rather than a Qt dialog because these failures include
    "PyQt5 would not import".
    """

    def test_fatal_exits_non_zero(self, monkeypatch):
        monkeypatch.setattr(app_module.sys, "platform", "linux")
        with pytest.raises(SystemExit) as excinfo:
            app_module.fatal("boom")
        assert excinfo.value.code == 1

    def test_fatal_shows_a_message_box_on_windows(self, monkeypatch):
        """The whole point: a console-less launch still puts the reason on screen."""
        shown = []

        class FakeUser32:
            @staticmethod
            def MessageBoxW(handle, text, title, flags):
                shown.append((text, title, flags))
                return 1

        class FakeWindll:
            user32 = FakeUser32()

        monkeypatch.setattr(app_module.sys, "platform", "win32")
        monkeypatch.setitem(sys.modules, "ctypes", type("C", (), {"windll": FakeWindll()}))

        with pytest.raises(SystemExit):
            app_module.fatal("The interface could not be loaded.", "PyQt5: no module")

        assert len(shown) == 1, "expected exactly one message box"
        text, title, _flags = shown[0]
        assert "The interface could not be loaded." in text
        assert "PyQt5: no module" in text, "the detail has to survive - it names the cause"
        # Without the log path the dialog is a dead end: the traceback that
        # actually identifies the failure only exists in the file.
        assert "speech_to_text" in text.lower() or ".log" in text.lower()
        assert title == config.APP_NAME

    def test_fatal_still_exits_when_the_message_box_itself_fails(self, monkeypatch):
        """
        The reporting path must not be able to turn a startup failure into a
        hang or a traceback of its own - the exit code is what the launcher
        and any packaging harness see.
        """

        class Exploding:
            @property
            def user32(self):
                raise OSError("no user32 here")

        monkeypatch.setattr(app_module.sys, "platform", "win32")
        monkeypatch.setitem(sys.modules, "ctypes", type("C", (), {"windll": Exploding()}))

        with pytest.raises(SystemExit) as excinfo:
            app_module.fatal("boom")
        assert excinfo.value.code == 1

    def test_say_survives_a_console_less_launch(self, monkeypatch):
        """
        Under pythonw sys.stdout is None, so a bare print() raises
        AttributeError - inside _reexec_into_project_venv(), which runs before
        logging exists and would take the whole launch down with it.
        """
        monkeypatch.setattr(app_module.sys, "stdout", None)
        app_module._say("this must not raise")
