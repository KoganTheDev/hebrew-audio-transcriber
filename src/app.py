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


def _say(message: str) -> None:
    """Print, but survive pythonw.exe, where sys.stdout is None."""
    if sys.stdout is None:
        return
    try:
        print(message, flush=True)
    except (AttributeError, OSError):
        pass


def fatal(message: str, detail: str = "") -> None:
    """Log a startup failure, show it, and exit non-zero.

    The app starts console-less, so a pre-GUI failure would otherwise be
    invisible. A native MessageBox via ctypes, not Qt: these failures include
    PyQt5 itself not importing. Falls back to stderr off Windows.
    """
    logger.critical(message + (f"\n\n{detail}" if detail else ""))
    body = message if not detail else f"{message}\n\n{detail}"
    body += f"\n\nFull details: {config.resolve_log_path()}"
    shown = False
    if sys.platform == "win32":
        try:
            import ctypes

            # MB_ICONERROR | MB_SETFOREGROUND, so it is not lost behind
            # whatever the user was looking at when they double-clicked.
            ctypes.windll.user32.MessageBoxW(None, body, config.APP_NAME, 0x10 | 0x10000)
            shown = True
        except Exception:
            logger.debug("Could not show the startup error dialog", exc_info=True)
    if not shown and sys.stderr is not None:
        try:
            print(body, file=sys.stderr, flush=True)
        except (AttributeError, OSError):
            pass
    sys.exit(1)


def _reexec_into_project_venv() -> None:
    """Restart on the project's .venv if started on another interpreter - a
    direct `python src/app.py` or an IDE run button bypasses the launchers.
    Silent without a .venv; ensure_dependencies reports that.
    """
    if os.environ.get(_REEXEC_MARKER):
        return

    src_dir = os.path.dirname(os.path.abspath(__file__))
    scripts = os.path.join(os.path.dirname(src_dir), ".venv", "Scripts")
    venv_python = os.path.join(scripts, "python.exe")
    venv_pythonw = os.path.join(scripts, "pythonw.exe")
    if not os.path.isfile(venv_python):
        return

    # Either venv interpreter is the venv: the launchers start pythonw.exe,
    # and re-running that on python.exe would open a console.
    # samefile, not string comparison: the same interpreter reaches us spelled
    # differently via symlinks, 8.3 short names and case.
    try:
        for candidate in (venv_python, venv_pythonw):
            if os.path.isfile(candidate) and os.path.samefile(candidate, sys.executable):
                return
    except OSError:
        return

    # A console-less start stays console-less.
    windowed = os.path.basename(sys.executable).lower() == "pythonw.exe"
    target = venv_pythonw if windowed and os.path.isfile(venv_pythonw) else venv_python

    os.environ[_REEXEC_MARKER] = "1"
    _say(f"Switching to the project's Python: {target}")
    try:
        # subprocess and exit, not os.execv: Windows has no real exec, so
        # execv returns control to the console immediately, detaching the app
        # and handing the launcher an exit code from the wrong process.
        completed = subprocess.run(
            [target, os.path.abspath(__file__), *sys.argv[1:]],
            check=False,
        )
    except OSError as exc:
        # Carry on: the dependency check still gives a better message than a
        # bare spawn traceback.
        del os.environ[_REEXEC_MARKER]
        _say(f"Could not switch interpreters ({exc}); continuing on this one.")
        return
    sys.exit(completed.returncode)


# Before the log handlers below, so the parent does not open the log file it
# is about to hand over.
_reexec_into_project_venv()

# Column-aligned, with milliseconds and file:line. The pid tells GUI lines
# from worker lines - the worker re-imports this module and logs to the same
# file, and its per-phase timings are the interesting part.
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d %(process)-6d %(levelname)-8s %(name)-32s "
    "%(filename)s:%(lineno)d - %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# Redirected stdout uses the ANSI code page, which cannot encode Hebrew; with
# backslashreplace the line is mangled but kept rather than silently dropped.
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

# Two formatters: visual order for the console (core/log_bidi), logical order
# for the file, which bidi-aware viewers render. Set before basicConfig, which
# only formats handlers that have no formatter.
stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(VisualOrderFormatter(LOG_FORMAT, DATE_FORMAT))

# Rotating, at an absolute path (config.resolve_log_path). Both processes
# write it; on Windows a rotation fails while the other holds the file, so it
# grows past the limit until released - a dropped rotation, never corruption,
# and cheaper than per-process files.
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
        fatal(
            "Some required components could not be installed.",
            "Check your internet connection and run the launcher again. If it keeps "
            "failing, the log names the package that could not be installed.",
        )

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
        fatal("The transcription engine could not be loaded.", f"faster-whisper: {e}")

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
        fatal("The application's interface could not be loaded.", f"PyQt5: {e}")

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

        # Stylesheet, language and the rest before any widget exists.
        configure_application(app)

        logger.debug("Creating MainWindow...")
        window = MainWindow()
        logger.debug("MainWindow instance created")

        logger.info("Displaying main window...")
        window.show()
        logger.info("Application ready. Entering event loop.")

        exit_code = app.exec_()
        logger.info(f"Application event loop exited with code: {exit_code}")

        # Stop background work here too, not only in closeEvent: the loop can
        # end without a close (app.quit, logout), and a live calibration
        # thread then crashed interpreter teardown. Idempotent.
        window.shutdown()

        # Destroy the widgets while the QApplication still exists: Qt objects
        # outliving it is the classic PyQt exit crash.
        window.close()
        window.deleteLater()
        app.processEvents()
        del window
        app.processEvents()

        sys.exit(exit_code)

    except OSError as e:
        logger.error(f"OSError during application startup: {e}", exc_info=True)
        if "DLL" in str(e) or "dynamic link library" in str(e):
            fatal(
                "A Windows component the app depends on is missing.",
                "This usually means the Microsoft Visual C++ Redistributable (x64) is "
                "not installed, or a copy bundled by PyQt5/faster-whisper conflicts "
                "with it.\n\n"
                "Install or repair it from:\n"
                "https://aka.ms/vs/17/release/vc_redist.x64.exe\n\n"
                "If it is already installed, reinstalling the two packages usually "
                "clears the conflict:\n"
                "pip install --upgrade --force-reinstall PyQt5 faster-whisper",
            )
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
