"""Speech-to-Text Application Main Entry Point
Professional GUI application for audio transcription.
"""

import logging
import os
import sys

# Ensure parent directory is in path so we can import speech_to_text package
# This allows the script to be run directly without path issues
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speech_to_text import config
from speech_to_text.core.dependencies import ensure_dependencies
from speech_to_text.core.log_bidi import VisualOrderFormatter

# Setup logging: fixed-width, column-aligned format with millisecond precision
# and source location (file:line) - easy to scan and to grep by level/module.
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)-32s %(filename)s:%(lineno)d - %(message)s"
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
    sys.stdout.reconfigure(errors="backslashreplace")
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

file_handler = logging.FileHandler("speech_to_text.log", encoding="utf-8")
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

logging.basicConfig(
    level=logging.DEBUG,
    handlers=[stdout_handler, file_handler],
)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    logger.info("=" * 70)
    logger.info(f"Starting {config.APP_NAME} v{config.APP_VERSION}")
    logger.info(f"Python {sys.version.split()[0]}")
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
        from PyQt5.QtWidgets import QApplication

        from speech_to_text.gui.main_window import MainWindow, configure_application

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
        app = QApplication(sys.argv)
        app.setWindowIcon(QIcon(config.ICON_PATH))
        logger.debug("QApplication created successfully")

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
