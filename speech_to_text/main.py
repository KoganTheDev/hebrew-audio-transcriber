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

# Setup logging with standard format (ISO 8601 timestamps, detailed info)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("speech_to_text.log")
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
    logger.info("Initializing GUI...")
    
    # Import PyQt5 after dependencies are ensured
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        from speech_to_text.gui.main_window import MainWindow
        logger.debug("PyQt5 imports successful")
    except ImportError as e:
        logger.error(f"Failed to import PyQt5: {e}", exc_info=True)
        sys.exit(1)
    
    try:
        # Create and run application
        logger.debug("Creating QApplication...")
        app = QApplication(sys.argv)
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
            logger.critical("PyTorch DLL loading failed - missing C++ runtime dependencies")
            print("\n" + "=" * 70)
            print("ERROR: PyTorch DLL Loading Failed")
            print("=" * 70)
            print("\nThis error typically means PyTorch requires additional system libraries.")
            print("\nPossible solutions:")
            print("1. Install Visual C++ Redistributable:")
            print("   https://support.microsoft.com/en-us/help/2977003")
            print("\n2. Or try reinstalling torch:")
            print("   pip install --upgrade --force-reinstall torch")
            print("\n3. Or use CPU-only version (might already be installed)")
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
