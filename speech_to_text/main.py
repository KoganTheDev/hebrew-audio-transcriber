"""
Speech-to-Text Application Main Entry Point
Professional GUI application for audio transcription.
"""

import sys
import os
import logging
import traceback

# Ensure parent directory is in path so we can import speech_to_text package
# This allows the script to be run directly without path issues
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from speech_to_text import config
from speech_to_text.core.dependencies import ensure_dependencies

# Setup logging: fixed-width, column-aligned format with millisecond precision
# and source location (file:line) — easy to scan and to grep by level/module.
LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)-8s %(name)-32s "
    "%(filename)s:%(lineno)d - %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=logging.DEBUG,
    format=LOG_FORMAT,
    datefmt=DATE_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("speech_to_text.log", encoding="utf-8")
    ]
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
    # copy as soon as ctranslate2 loads a model later — confirmed by reproducing
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
        from PyQt5.QtWidgets import QApplication, QMessageBox
        from PyQt5.QtGui import QIcon
        from speech_to_text.gui.main_window import MainWindow
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

        logger.debug("Creating MainWindow...")
        window = MainWindow()
        logger.debug("MainWindow instance created")
        
        logger.info("Displaying main window...")
        window.show()
        logger.info("Application ready. Entering event loop.")
        
        exit_code = app.exec_()
        logger.info(f"Application event loop exited with code: {exit_code}")
        sys.exit(exit_code)
    
    except OSError as e:
        logger.error(f"OSError during application startup: {e}", exc_info=True)
        if "DLL" in str(e) or "dynamic link library" in str(e):
            logger.critical("Native DLL loading failed - missing or conflicting C++ runtime dependencies")
            print("\n" + "=" * 70)
            print("ERROR: Native DLL Loading Failed")
            print("=" * 70)
            print("\nThis usually means a required Visual C++ runtime DLL is missing")
            print("or a different copy bundled by PyQt5/faster-whisper conflicts with it.")
            print("\nPossible solutions:")
            print("1. Install/repair the Microsoft Visual C++ Redistributable (x64):")
            print("   https://aka.ms/vs/17/release/vc_redist.x64.exe")
            print("\n2. Or reinstall PyQt5 and faster-whisper:")
            print("   pip install --upgrade --force-reinstall PyQt5 faster-whisper")
            print("=" * 70)
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
