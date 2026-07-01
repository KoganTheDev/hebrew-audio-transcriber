"""
Main window for the Speech-to-Text Transcriber GUI.
3-step flow: Select File → Choose Model → Transcribe
"""

import os
import sys
import logging
import multiprocessing
import queue
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox, QFrame, QStackedWidget, QDesktopWidget
)
from PyQt5.QtCore import QThread, pyqtSignal, Qt
from PyQt5.QtGui import QFont, QIcon

from speech_to_text import config
from speech_to_text.hardware_detection import HardwareDetector
from speech_to_text.core.worker import run_transcription_process
from speech_to_text.core.calibration import run_calibration_process
from speech_to_text.gui import theme
from speech_to_text.gui.theme import COLORS, Fonts
from speech_to_text.gui.icons import ICONS, svg_to_pixmap
from speech_to_text.gui.steps import Step, FileSelectStep, ModelSelectStep, TranscriptionStep

logger = logging.getLogger(__name__)


class TranscriptionThread(QThread):
    """
    Worker thread for transcription.

    Runs the actual transcription in a separate OS process (see
    speech_to_text.core.worker) rather than in-process, and just relays
    progress/results as Qt signals. See worker.py for why: ctranslate2 and
    PyQt5 each bundle their own MSVCP140.dll on Windows, and loading both in
    one process causes an intermittent native crash.
    """
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, audio_file: str, model_size: str, device: str):
        super().__init__()
        self.audio_file = audio_file
        self.model_size = model_size
        self.device = device
        self._is_running = True
        self._process: Optional[multiprocessing.Process] = None
        logger.debug(f"TranscriptionThread created: {os.path.basename(audio_file)}")

    def run(self):
        """Launch the worker process and relay its progress/result as signals."""
        logger.info(f"TranscriptionThread started")
        try:
            self.progress.emit("Initializing...", 5)
            output_file = self._get_output_path()

            progress_queue: multiprocessing.Queue = multiprocessing.Queue()
            result_queue: multiprocessing.Queue = multiprocessing.Queue()

            self._process = multiprocessing.Process(
                target=run_transcription_process,
                args=(self.audio_file, self.model_size, self.device, output_file,
                      progress_queue, result_queue),
                daemon=True,
            )
            self._process.start()

            while self._is_running:
                try:
                    kind, *payload = progress_queue.get(timeout=0.2)
                    if kind == "progress":
                        message, percent = payload
                        self.progress.emit(message, percent)
                except queue.Empty:
                    pass

                try:
                    kind, payload = result_queue.get_nowait()
                    if kind == "finished":
                        logger.info("✓ Transcription complete")
                        self.finished.emit(payload)
                    else:
                        logger.error(f"Transcription worker error: {payload}")
                        self.error.emit(payload)
                    return
                except queue.Empty:
                    pass

                if not self._process.is_alive() and result_queue.empty():
                    self.error.emit("Transcription worker process exited unexpectedly")
                    return

            self.error.emit("Transcription cancelled")

        except Exception as e:
            logger.error(f"TranscriptionThread error: {e}", exc_info=True)
            self.error.emit(str(e))
        finally:
            if self._process and self._process.is_alive():
                self._process.terminate()

    def stop(self):
        """Stop the thread and terminate the worker process if running."""
        self._is_running = False
        if self._process and self._process.is_alive():
            self._process.terminate()

    def _get_output_path(self) -> str:
        """Get output file path."""
        input_dir = os.path.dirname(self.audio_file)
        output_file = os.path.join(input_dir, config.OUTPUT_FILENAME)
        return output_file


class CalibrationThread(QThread):
    """
    Runs the one-time hardware calibration benchmark in the background.

    Only actually benchmarks on first run — HardwareDetector already loads
    a cached result synchronously if one exists, in which case MainWindow
    won't even start this thread. Same subprocess-isolation reasoning as
    TranscriptionThread: this loads faster-whisper, so it can't safely share
    a process with PyQt5.
    """
    calibrated = pyqtSignal(float)
    failed = pyqtSignal(str)

    def __init__(self, cpu_cores: int):
        super().__init__()
        self.cpu_cores = cpu_cores
        self._process: Optional[multiprocessing.Process] = None

    def run(self):
        logger.info("Starting background hardware calibration...")
        try:
            result_queue: multiprocessing.Queue = multiprocessing.Queue()
            self._process = multiprocessing.Process(
                target=run_calibration_process,
                args=(self.cpu_cores, result_queue),
                daemon=True,
            )
            self._process.start()

            while True:
                try:
                    kind, payload = result_queue.get(timeout=0.5)
                    if kind == "ok":
                        logger.info(f"Calibration finished: {payload:.4f}s/audio-s")
                        self.calibrated.emit(payload)
                    else:
                        logger.warning(f"Calibration failed: {payload}")
                        self.failed.emit(payload)
                    return
                except queue.Empty:
                    if not self._process.is_alive():
                        self.failed.emit("Calibration process exited unexpectedly")
                        return
        except Exception as e:
            logger.error(f"CalibrationThread error: {e}", exc_info=True)
            self.failed.emit(str(e))


class MainWindow(QMainWindow):
    """Main application window - lightweight tool interface."""

    def __init__(self):
        super().__init__()
        logger.info("Initializing MainWindow...")

        self.setWindowTitle(config.APP_NAME)
        self.setWindowIcon(QIcon(config.ICON_PATH))
        self.move(100, 50)
        self.setFixedSize(config.GUI_WINDOW_WIDTH, config.GUI_WINDOW_HEIGHT)
        # Fixed-size window: no resize/maximize, so layouts never need to adapt.
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowMaximizeButtonHint)
        self.setStyleSheet(f"QMainWindow {{ background-color: {COLORS['bg_primary']}; }}")

        self.hardware = HardwareDetector()
        self.current_step = Step.FILE_SELECT
        self.transcription_thread: Optional[QThread] = None
        self.selected_file: Optional[str] = None
        self.selected_model: Optional[str] = None
        self.audio_duration: int = 0
        self.calibration_thread: Optional[QThread] = None

        # Build UI
        self._init_ui()

        # Center on screen
        self.center_on_screen()

        # Kick off the one-time hardware calibration in the background, if no
        # cached result was already loaded by HardwareDetector. Runs while
        # the user is still picking a file, so real numbers are usually
        # ready before they reach the model-select step.
        if self.hardware.tiny_seconds_per_audio_second is None:
            self.calibration_thread = CalibrationThread(self.hardware.cpu_count)
            self.calibration_thread.calibrated.connect(self._on_calibration_done)
            self.calibration_thread.failed.connect(self._on_calibration_failed)
            self.calibration_thread.start()

        logger.info("✓ MainWindow ready")

    def _on_calibration_done(self, tiny_seconds_per_audio_second: float):
        """Apply a finished background calibration and refresh any visible estimates."""
        self.hardware.set_calibration(tiny_seconds_per_audio_second)
        self.model_step.update_audio_duration(self.audio_duration)
        logger.debug("Refreshed model time estimates with calibrated values")

    def _on_calibration_failed(self, message: str):
        logger.warning(f"Hardware calibration failed, keeping placeholder estimates: {message}")

    def center_on_screen(self):
        """Center window on screen."""
        screen = QDesktopWidget().screenGeometry()
        x = (screen.width() - self.width()) // 2
        y = (screen.height() - self.height()) // 2
        self.move(x, y)
        logger.debug(f"Window centered at ({x}, {y})")

    def _init_ui(self):
        """Initialize UI."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QFrame()
        header.setObjectName("header")
        header.setStyleSheet(theme.header_qss("header"))
        header.setFixedHeight(50)

        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 8, 16, 8)
        header_layout.setSpacing(10)

        # Title — centered, gradient-filled text (the one deliberate use of a
        # gradient in this theme, as a brand accent rather than a UI backdrop).
        title = QLabel()
        title_pixmap = theme.gradient_text_pixmap("Hebrew Audio Transcriber", Fonts.SUBTITLE_BOLD)
        title.setPixmap(title_pixmap)
        title.setStyleSheet("background: transparent;")
        title.setAlignment(Qt.AlignCenter)
        header_layout.addStretch()
        header_layout.addWidget(title)
        header_layout.addStretch()
        main_layout.addWidget(header)

        # Content area
        content_widget = QWidget()
        content_widget.setStyleSheet(theme.frame_bg_qss("bg_primary"))
        content_layout = QVBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)

        # Stacked widget for steps
        self.stacked_widget = QStackedWidget()
        self.stacked_widget.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        # Create steps
        self.file_step = FileSelectStep(self.hardware)
        self.file_step.file_selected.connect(self._on_file_selected)

        self.model_step = ModelSelectStep(self.hardware)
        self.model_step.model_selected.connect(self._on_model_selected)

        self.transcription_step = TranscriptionStep()

        self.stacked_widget.addWidget(self.file_step)
        self.stacked_widget.addWidget(self.model_step)
        self.stacked_widget.addWidget(self.transcription_step)

        content_layout.addWidget(self.stacked_widget)
        main_layout.addWidget(content_widget)

        # Navigation bar
        nav_widget = QFrame()
        nav_widget.setObjectName("navBar")
        nav_widget.setStyleSheet(theme.nav_bar_qss("navBar"))
        nav_layout = QHBoxLayout(nav_widget)
        nav_layout.setSpacing(8)

        # Back and Next are given the same fixed size — minimum-size alone
        # lets each button grow to fit its own text/icon, so their rendered
        # widths drifted apart (e.g. "  Back" + icon vs "Next" + icon). Wide
        # enough for next_btn's longest state too ("New File" + icon).
        nav_btn_size = (130, 36)

        # Back button
        self.back_btn = QPushButton()
        back_pixmap = svg_to_pixmap(ICONS["arrow_left"], 16, COLORS['text_primary'])
        self.back_btn.setIcon(QIcon(back_pixmap))
        self.back_btn.setText("  Back")
        self.back_btn.setFixedSize(*nav_btn_size)
        self.back_btn.setFont(Fonts.BODY_BOLD)
        self.back_btn.setStyleSheet(theme.button_secondary_qss())
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.hide()
        nav_layout.addWidget(self.back_btn)

        nav_layout.addStretch()

        # Next button
        self.next_btn = QPushButton("Next")
        next_pixmap = svg_to_pixmap(ICONS["arrow_right"], 16, COLORS['bg_primary'])
        self.next_btn.setIcon(QIcon(next_pixmap))
        self.next_btn.setLayoutDirection(Qt.RightToLeft)
        self.next_btn.setFixedSize(*nav_btn_size)
        self.next_btn.setFont(Fonts.BODY_BOLD)
        self.next_btn.setStyleSheet(theme.button_primary_qss())
        self.next_btn.clicked.connect(self._go_next)
        self.next_btn.setEnabled(False)
        nav_layout.addWidget(self.next_btn)

        main_layout.addWidget(nav_widget)

    def _on_file_selected(self, file_path: str, duration: int):
        """Handle file selection."""
        self.selected_file = file_path
        self.audio_duration = duration
        self.next_btn.setEnabled(True)
        logger.debug(f"File selected: {file_path} ({duration}s)")

    def _on_model_selected(self, model: str):
        """Handle model selection."""
        self.selected_model = model
        self.next_btn.setEnabled(True)
        logger.debug(f"Model selected: {model}")

    def _go_back(self):
        """Go to previous step."""
        if self.current_step == Step.MODEL_SELECT:
            self.current_step = Step.FILE_SELECT
            self.stacked_widget.setCurrentIndex(0)
            self.back_btn.hide()
            self.next_btn.setEnabled(self.selected_file is not None)
        logger.debug(f"Navigated to: {self.current_step}")

    def _go_next(self):
        """Go to next step."""
        if self.current_step == Step.FILE_SELECT:
            # Refresh time estimates in place instead of rebuilding the widget.
            self.model_step.update_audio_duration(self.audio_duration)
            # A model is always pre-selected (the recommended one), so carry
            # that selection over instead of leaving Next disabled until the
            # user re-clicks an already-checked radio button.
            self.selected_model = self.model_step.selected_model

            self.current_step = Step.MODEL_SELECT
            self.stacked_widget.setCurrentIndex(1)
            self.back_btn.show()
            self.back_btn.setEnabled(True)
            self.next_btn.setEnabled(self.selected_model is not None)

        elif self.current_step == Step.MODEL_SELECT:
            if not self.selected_model:
                QMessageBox.warning(self, "No Model", "Please select a model")
                return

            # Proceed to transcription once the model is selected.
            self._start_transcription()

        logger.debug(f"Navigated to: {self.current_step}")

    def _start_transcription(self):
        """Start transcription thread."""
        self.current_step = Step.TRANSCRIPTION
        self.stacked_widget.setCurrentIndex(2)
        self.back_btn.hide()
        self.next_btn.hide()

        filename = os.path.basename(self.selected_file)
        self.transcription_step.set_file_info(filename, self.selected_model)

        logger.info(f"Starting transcription: {filename} with {self.selected_model} model")

        self.transcription_thread = TranscriptionThread(
            self.selected_file,
            self.selected_model,
            "cpu"  # Auto-detect would go here
        )
        self.transcription_thread.progress.connect(self.transcription_step.update_progress)
        self.transcription_thread.finished.connect(self._on_transcription_complete)
        self.transcription_thread.error.connect(self._on_transcription_error)
        self.transcription_thread.start()

    def _on_transcription_complete(self, output_file: str):
        """Handle transcription completion."""
        logger.info(f"Transcription complete: {output_file}")
        self.transcription_step.show_result(output_file)

        # Show completion options. This reuses next_btn, so its icon/layout
        # need to switch too — a forward arrow reads as "proceed to the next
        # step", which is misleading for what's actually a reset action.
        self.next_btn.setText("New File")
        self.next_btn.setLayoutDirection(Qt.LeftToRight)
        self.next_btn.setIcon(QIcon(svg_to_pixmap(ICONS["file_plus"], 16, COLORS['bg_primary'])))
        self.next_btn.show()
        self.next_btn.clicked.disconnect()
        self.next_btn.clicked.connect(self._reset)

    def _on_transcription_error(self, error_msg: str):
        """Handle transcription error."""
        logger.error(f"Transcription error: {error_msg}")
        QMessageBox.critical(self, "Transcription Error", error_msg)
        self._reset()

    def _reset(self):
        """Reset to file selection."""
        self.current_step = Step.FILE_SELECT
        self.stacked_widget.setCurrentIndex(0)
        self.selected_file = None
        self.selected_model = None
        self.audio_duration = 0
        self.back_btn.hide()
        self.next_btn.setEnabled(False)
        self.next_btn.setText("Next")
        self.next_btn.setLayoutDirection(Qt.RightToLeft)
        self.next_btn.setIcon(QIcon(svg_to_pixmap(ICONS["arrow_right"], 16, COLORS['bg_primary'])))
        self.next_btn.show()
        self.next_btn.clicked.disconnect()
        self.next_btn.clicked.connect(self._go_next)
        self.file_step.file_label.setText("No file selected")
        self.file_step.file_label.setStyleSheet(theme.text_qss("text_secondary"))
        self.file_step.file_icon.hide()
        self.file_step.selected_file = None
        self.file_step.selected_duration = 0
        logger.debug("Reset to file selection step")

    def closeEvent(self, event):
        """Stop any running transcription before the window closes."""
        if self.current_step == Step.TRANSCRIPTION and self.transcription_thread:
            self.transcription_thread.stop()
            self.transcription_thread.wait()
        logger.info("Application closed by user")
        event.accept()


def main():
    """Entry point for GUI."""
    from PyQt5.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
