"""Speech-to-Text Application Main Entry Point
Professional GUI application for audio transcription.
"""

import logging
import logging.handlers
import os
import subprocess
import sys

# This file's own directory, src/, holds config/, core/ and gui/. One dirname,
# not two - the repo root has none of them on it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from core.dependencies import ensure_dependencies
from core.log_bidi import VisualOrderFormatter

# Guards against re-execing a child that is already the child.
_REEXEC_MARKER = "SPEECH_TO_TEXT_REEXEC"


def _reexec_into_project_venv() -> None:
    """Restart on the project's .venv if started on some other interpreter.

    The launchers refuse to run on anything else, but they are not the only
    way in: a direct `python src/app.py`, a double-click and an IDE run button
    all bypass them, and the sys.path line above means every one of those
    starts successfully on an interpreter that may have no dependencies.

    Silent when there is no .venv to move to - ensure_dependencies reports
    that case and can say more about it than this can.
    """
    if os.environ.get(_REEXEC_MARKER):
        return

    src_dir = os.path.dirname(os.path.abspath(__file__))
    venv_python = os.path.join(os.path.dirname(src_dir), ".venv", "Scripts", "python.exe")
    if not os.path.isfile(venv_python):
        return

    # samefile, not string comparison: the same interpreter reaches us spelled
    # differently via symlinks, 8.3 short names and case.
    try:
        if os.path.samefile(venv_python, sys.executable):
            return
    except OSError:
        return

    os.environ[_REEXEC_MARKER] = "1"
    print(f"Switching to the project's Python: {venv_python}", flush=True)
    try:
        # subprocess and exit, not os.execv: Windows has no real exec, so
        # execv returns control to the console immediately, detaching the app
        # and handing the launcher an exit code from the wrong process.
        completed = subprocess.run(
            [venv_python, os.path.abspath(__file__), *sys.argv[1:]],
            check=False,
        )
    except OSError as exc:
        # Carry on: the dependency check still gives a better message than a
        # bare spawn traceback.
        del os.environ[_REEXEC_MARKER]
        print(f"Could not switch interpreters ({exc}); continuing on this one.", flush=True)
        return
    sys.exit(completed.returncode)


# Before the log handlers below, so the parent does not open the log file it
# is about to hand over.
_reexec_into_project_venv()

# Setup logging: fixed-width, column-aligned format with millisecond precision
# and source location (file:line) - easy to scan and to grep by level/module.
# %(process)d is not decoration. Transcription runs in a separate process
# (see core/worker.py) which re-imports this module and configures the same
# handlers, so GUI lines and worker lines land interleaved in one file.
# Without the pid there was no way to tell which process wrote a line, and
# the worker's are the interesting ones - the per-phase timings come from it.
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d %(process)-6d %(levelname)-8s %(name)-32s "
    "%(filename)s:%(lineno)d - %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Redirected stdout ("run.bat > out.txt") gets its encoding from the
# system's ANSI code page, not the console's, and strict-errors on any
# Hebrew character it can't represent. logging's StreamHandler.emit()
# catches that and calls handleError() instead of crashing, but the cost is
# a silently dropped log line. errors="backslashreplace" turns that into a
# visible, lossy fallback instead of losing the line. With bidi isolates
# now stripped from the console stream by core/log_bidi before this point,
# this is the only remaining reason for it - a real console's WriteConsoleW
# path doesn't need it at all.
try:
    # typeshed types sys.stdout as TextIO, which has no reconfigure(); only
    # the concrete TextIOWrapper does. The except clause below already covers
    # the case where it genuinely is not there.
    sys.stdout.reconfigure(errors="backslashreplace")  # type: ignore[union-attr]
except (AttributeError, ValueError):
    # AttributeError: sys.stdout is None (e.g. a windowed build with no
    # console) or something else stood in for it before this ran.
    # ValueError: the stream is already closed/detached. Either way, this
    # is best-effort robustness for an edge case - not worth failing over.
    pass

# Two different formatters, not one shared via basicConfig(format=...): the
# console gets visual order (core/log_bidi.VisualOrderFormatter, see its
# module comment and core/hebrew_text.to_visual_order for why), the log
# file keeps logical order so a real bidi-aware reader still renders it
# correctly. Setting each handler's formatter before basicConfig() matters -
# basicConfig only assigns its own formatter to handlers that don't already
# have one, so leaving format=/datefmt= out of the call keeps that explicit
# rather than relying on the fallback behaviour.
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(VisualOrderFormatter(LOG_FORMAT, DATE_FORMAT))

# Rotating, and at an absolute path resolved once - see
# config.resolve_log_path for why a relative one was a bug and
# config.LOG_MAX_BYTES for why the level stays at DEBUG.
#
# Both processes open this same file, which a RotatingFileHandler does not
# coordinate. The failure that buys is bounded and known: on Windows the
# rename a rotation performs cannot touch a file another process still holds
# open, so the rotation raises, logging swallows it through handleError, and
# one process keeps appending to an oversized file until the other lets go.
# A dropped rotation, not a corrupted log. The alternatives - a file per pid,
# or forwarding the child's records over the progress queue - each cost more
# than that is worth, and the pid in LOG_FORMAT is what actually makes the
# shared file readable.
file_handler = logging.handlers.RotatingFileHandler(
    config.resolve_log_path(),
    maxBytes=config.LOG_MAX_BYTES,
    backupCount=config.LOG_BACKUP_COUNT,
    encoding="utf-8",
)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[stdout_handler, file_handler],
)
# "app", not __name__: as the entry point, __name__ varies with the start
# method ("__main__", "app", "__mp_main__"), which made the log's module
# column report how the process was started rather than what wrote the line.
logger = logging.getLogger("app")


def main() -> None:
    """Main entry point."""
    logger.info("=" * 70)
    logger.info(f"Starting {config.APP_NAME} v{config.APP_VERSION}")
    logger.info(f"Python {sys.version.split()[0]}")
    # Unconditionally, not just on the dependency failure: "which Python" is
    # the first question of nearly every launch problem.
    logger.info(f"Interpreter: {sys.executable}")
    logger.info(f"Platform: {sys.platform}")
    logger.info("=" * 70)

    # Ensure all dependencies are installed
    logger.info("Checking dependencies...")
    logger.debug(f"Required packages: {config.REQUIRED_PACKAGES}")
    if not ensure_dependencies(config.REQUIRED_PACKAGES):
        logger.critical("Failed to install required dependencies. Exiting.")
        sys.exit(1)

    logger.info("✓ All dependencies available")

    # Import faster-whisper (ctranslate2) before PyQt5. Both bundle their own
    # copy of MSVCP140.dll on Windows; whichever loads into the process first
    # wins the name and the other side reuses it. Importing PyQt5 first causes
    # a hard access-violation crash (0xc0000005) inside PyQt5's older bundled
    # copy as soon as ctranslate2 loads a model later - confirmed by reproducing
    # it both ways. This import order avoids the conflict; do not reorder it.
    try:
        import faster_whisper  # noqa: F401

        logger.debug("faster_whisper imported (establishes DLL load order before PyQt5)")
    except ImportError as e:
        logger.error(f"Failed to import faster_whisper: {e}", exc_info=True)
        sys.exit(1)

    logger.info("Initializing GUI...")

    # Import PyQt5 after dependencies are ensured
    try:
        from PyQt5.QtGui import QIcon

        from gui.crash_handler import (
            DiagnosticApplication,
            install_global_exception_hook,
        )
        from gui.main_window import MainWindow, configure_application

        logger.debug("PyQt5 imports successful")
    except ImportError as e:
        logger.error(f"Failed to import PyQt5: {e}", exc_info=True)
        sys.exit(1)

    try:
        # On Windows, the taskbar groups/icons processes by AppUserModelID
        # rather than by window icon alone. Without setting our own, Windows
        # falls back to python.exe's icon in the taskbar even though the
        # title bar shows the correct one.
        if sys.platform == "win32":
            try:
                import ctypes

                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(config.APP_ID)
                logger.debug(f"Set AppUserModelID: {config.APP_ID}")
            except Exception as e:
                logger.warning(f"Could not set AppUserModelID: {e}")

        # Create and run application
        logger.debug("Creating QApplication...")
        app = DiagnosticApplication(sys.argv)
        app.setWindowIcon(QIcon(config.ICON_PATH))
        logger.debug("QApplication created successfully")

        # Installed before MainWindow is built, so a crash during its
        # construction is caught too, not just crashes during app.exec_().
        install_global_exception_hook(app)

        # Apply the app stylesheet and the persisted UI language (English on
        # first-ever launch) before MainWindow is built, so every widget
        # renders themed and in the right language/layout direction from the
        # start. See configure_application's own docstring for why this is
        # a shared call rather than inlined here: this was previously two
        # lines that only set the language, with the stylesheet call missing
        # entirely - the app ran fully unstyled through this, the only entry
        # point actually shipped, while looking correct everywhere else.
        configure_application(app)

        logger.debug("Creating MainWindow...")
        window = MainWindow()
        logger.debug("MainWindow instance created")

        logger.info("Displaying main window...")
        window.show()
        logger.info("Application ready. Entering event loop.")

        exit_code = app.exec_()
        logger.info(f"Application event loop exited with code: {exit_code}")

        # Stop background work before returning, NOT only in closeEvent.
        # closeEvent covers the ordinary path where the user closes the window,
        # but the loop can also end without it - app.quit(), a session logout,
        # or the faked exec_() the tests use. On that path main() used to fall
        # straight through to sys.exit with the calibration QThread still
        # running and its multiprocessing child still spawning, and the
        # process died in interpreter teardown with an access violation and no
        # traceback. Idempotent, so the usual close-then-quit order is fine.
        window.shutdown()

        # Tear the widget tree down while the QApplication is still alive.
        # Both are locals here, so without this Python drops them at
        # interpreter shutdown in refcount order, and Qt objects outliving
        # their QApplication is the classic PyQt exit crash - an access
        # violation with no traceback. close() + deleteLater() queues the
        # deletion, processEvents() runs it, and only then does the
        # application go.
        window.close()
        window.deleteLater()
        app.processEvents()
        del window
        app.processEvents()

        sys.exit(exit_code)

    except OSError as e:
        logger.error(f"OSError during application startup: {e}", exc_info=True)
        if "DLL" in str(e) or "dynamic link library" in str(e):
            logger.critical(
                "Native DLL loading failed - missing or conflicting C++ runtime "
                "dependencies.\n"
                "This usually means a required Visual C++ runtime DLL is missing, "
                "or a different copy bundled by PyQt5/faster-whisper conflicts with it.\n"
                "Possible solutions:\n"
                "  1. Install/repair the Microsoft Visual C++ Redistributable (x64):\n"
                "     https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
                "  2. Or reinstall PyQt5 and faster-whisper:\n"
                "     pip install --upgrade --force-reinstall PyQt5 faster-whisper"
            )
            sys.exit(1)
        else:
            logger.error(f"Unexpected OSError: {e}", exc_info=True)
            raise
    except Exception as e:
        logger.error(f"Unexpected error during startup: {e}", exc_info=True)
        logger.debug(f"Exception type: {type(e).__name__}")
        raise
    finally:
        logger.debug("Application shutdown sequence completed")


if __name__ == "__main__":
    main()
