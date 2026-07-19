"""
Main window for the Speech-to-Text Transcriber GUI.
3-step flow: Select File → Choose Model → Transcribe
"""

import os
import sys
import logging
from typing import Optional

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox, QFrame, QStackedWidget, QDesktopWidget
)
from PyQt5.QtCore import QThread, Qt
from PyQt5.QtGui import QFont, QIcon

from speech_to_text import config
from speech_to_text.hardware_detection import HardwareDetector
from speech_to_text.gui import theme
from speech_to_text.gui import i18n
from speech_to_text.gui.i18n import t
from speech_to_text.gui.theme import COLORS, Fonts
from speech_to_text.gui.steps import Step, FileSelectStep, ModelSelectStep, TranscriptionStep
from speech_to_text.gui.threads import TranscriptionThread, CalibrationThread
from speech_to_text.gui.widgets import IconTextButton

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window - lightweight tool interface."""

    def __init__(self):
        super().__init__()
        logger.info("Initializing MainWindow...")

        self.setWindowTitle(t("app_title"))
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
        # Rendered as a pixmap, so retranslate() re-renders it on language switch.
        self.title_label = QLabel()
        self.title_label.setPixmap(theme.gradient_text_pixmap(t("app_title"), Fonts.SUBTITLE_BOLD))
        self.title_label.setStyleSheet("background: transparent;")
        self.title_label.setAlignment(Qt.AlignCenter)

        # EN/HE toggle at the trailing edge of the header (label shows the
        # TARGET language). A same-width invisible spacer at the leading edge
        # keeps the title optically centered.
        lang_btn_width = 52
        self.lang_btn = QPushButton()
        self.lang_btn.setFixedSize(lang_btn_width, 30)
        self.lang_btn.setFont(Fonts.CAPTION_BOLD)
        self.lang_btn.setStyleSheet(theme.button_secondary_qss(padding="2px 4px"))
        self.lang_btn.setCursor(Qt.PointingHandCursor)
        self.lang_btn.clicked.connect(self._toggle_language)

        header_spacer = QWidget()
        header_spacer.setFixedWidth(lang_btn_width)
        header_spacer.setStyleSheet("background: transparent;")

        header_layout.addWidget(header_spacer)
        header_layout.addStretch()
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.lang_btn)
        main_layout.addWidget(header)

        i18n.language_manager.language_changed.connect(self._on_language_changed)

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

        # Back button (text/icon set per language by _retranslate_chrome).
        # IconTextButton draws its own label so the icon side can be chosen
        # visually, independent of layout direction (see gui/widgets.py).
        self.back_btn = IconTextButton()
        self.back_btn.setFixedSize(*nav_btn_size)
        self.back_btn.setFont(Fonts.BODY_BOLD)
        self.back_btn.setStyleSheet(theme.button_secondary_qss())
        self.back_btn.set_text_colors(COLORS['text_primary'], hover=COLORS['accent'])
        self.back_btn.clicked.connect(self._go_back)
        self.back_btn.hide()
        nav_layout.addWidget(self.back_btn)

        # Cancel button — only shown during Step.TRANSCRIPTION, in the same
        # slot as Back (which is hidden at that point). Stops the worker
        # process and returns to Choose Model rather than closing the app.
        self.cancel_btn = IconTextButton()
        self.cancel_btn.setFixedSize(*nav_btn_size)
        self.cancel_btn.setFont(Fonts.BODY_BOLD)
        self.cancel_btn.setStyleSheet(theme.button_secondary_qss())
        self.cancel_btn.set_text_colors(COLORS['text_primary'], hover=COLORS['accent'])
        self.cancel_btn.clicked.connect(self._cancel_transcription)
        self.cancel_btn.hide()
        nav_layout.addWidget(self.cancel_btn)

        nav_layout.addStretch()

        # Next button (text/icon set by _set_next_button_mode)
        self.next_btn = IconTextButton()
        self.next_btn.setFixedSize(*nav_btn_size)
        self.next_btn.setFont(Fonts.BODY_BOLD)
        self.next_btn.setStyleSheet(theme.button_primary_qss())
        self.next_btn.set_text_colors(COLORS['bg_primary'], disabled=COLORS['text_tertiary'])
        self.next_btn.clicked.connect(self._go_next)
        self.next_btn.setEnabled(False)
        nav_layout.addWidget(self.next_btn)

        main_layout.addWidget(nav_widget)

        self._next_btn_mode = "next"
        self._retranslate_chrome()

    def _retranslate_chrome(self):
        """(Re-)apply window title, header, and nav button text/icons/directions."""
        self.setWindowTitle(t("app_title"))
        self.title_label.setPixmap(theme.gradient_text_pixmap(t("app_title"), Fonts.SUBTITLE_BOLD))
        # Toggle shows the language it switches TO.
        self.lang_btn.setText("עב" if i18n.get_language() == "en" else "EN")

        rtl = i18n.is_rtl()
        # Back's arrow points against the reading direction, on the leading
        # side of the text: [← Back] mirrors to [חזרה →].
        self.back_btn.setText(t("nav_back"))
        self.back_btn.set_icon_spec("arrow_right" if rtl else "arrow_left",
                                    side="right" if rtl else "left")

        # Cancel's x sits on the leading side of the text in both languages.
        self.cancel_btn.setText(t("nav_cancel"))
        self.cancel_btn.set_icon_spec("x", side="right" if rtl else "left")

        self._set_next_button_mode(self._next_btn_mode)

    def _set_next_button_mode(self, mode: str):
        """
        Configure next_btn for its current role: "next" (forward arrow on
        the trailing side, pointing along the reading direction) or
        "new_file" (reset action after completion - plus-file icon on the
        leading side, no directional claim).
        """
        self._next_btn_mode = mode
        rtl = i18n.is_rtl()
        if mode == "new_file":
            # Reset action: plus-file icon on the leading side of the text.
            self.next_btn.setText(t("nav_new_file"))
            self.next_btn.set_icon_spec("file_plus", side="right" if rtl else "left")
        else:
            # Forward arrow on the trailing side of the text, pointing along
            # the reading direction: [Next →] mirrors to [← הבא].
            self.next_btn.setText(t("nav_next"))
            self.next_btn.set_icon_spec("arrow_left" if rtl else "arrow_right",
                                        side="left" if rtl else "right")

    def _toggle_language(self):
        i18n.set_language("he" if i18n.get_language() == "en" else "en")

    def _on_language_changed(self, lang: str):
        """Apply app-wide layout direction and re-render every visible string."""
        from PyQt5.QtWidgets import QApplication
        QApplication.instance().setLayoutDirection(
            Qt.RightToLeft if lang == "he" else Qt.LeftToRight
        )
        self._retranslate_chrome()
        for i in range(self.stacked_widget.count()):
            self.stacked_widget.widget(i).retranslate()
        # The RTL/LTR flip relocates the buttons (the toggle jumps to the
        # opposite side of the header) without Qt sending them a Leave
        # event, so the clicked button keeps its :hover styling until the
        # mouse happens to pass over it again. Clear the stale under-mouse
        # flag and re-polish so hover state matches reality.
        for btn in self.findChildren(QPushButton):
            btn.setAttribute(Qt.WA_UnderMouse, False)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            btn.update()

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
                QMessageBox.warning(self, t("no_model_title"), t("no_model_body"))
                return

            # Proceed to transcription once the model is selected.
            self._start_transcription()

        logger.debug(f"Navigated to: {self.current_step}")

    def _start_transcription(self):
        """Start transcription thread."""
        self.model_step.clear_error()
        self.current_step = Step.TRANSCRIPTION
        self.stacked_widget.setCurrentIndex(2)
        self.back_btn.hide()
        self.next_btn.hide()
        self.cancel_btn.show()

        filename = os.path.basename(self.selected_file)
        self.transcription_step.set_file_info(filename, self.selected_model)
        self.transcription_step.start()

        logger.info(f"Starting transcription: {filename} with {self.selected_model} model")

        self.transcription_thread = TranscriptionThread(
            self.selected_file,
            self.selected_model,
            "cpu",  # Auto-detect would go here
            self.audio_duration,  # real PyAV-measured duration, for accurate progress
        )
        self.transcription_thread.progress.connect(self.transcription_step.update_progress)
        self.transcription_thread.finished.connect(self._on_transcription_complete)
        self.transcription_thread.error.connect(self._on_transcription_error)
        self.transcription_thread.start()

    def _on_transcription_complete(self, output_file: str):
        """Handle transcription completion."""
        logger.info(f"Transcription complete: {output_file}")
        self.cancel_btn.hide()
        self.transcription_step.stop()
        # Force the bar to a definitive 100% on completion, regardless of
        # whether every trailing progress message was relayed in time.
        self.transcription_step.update_progress("w_complete", {}, 100)
        self.transcription_step.show_result(output_file)

        # Show completion options. This reuses next_btn, so its icon/layout
        # need to switch too — a forward arrow reads as "proceed to the next
        # step", which is misleading for what's actually a reset action.
        self._set_next_button_mode("new_file")
        self.next_btn.show()
        self.next_btn.clicked.disconnect()
        self.next_btn.clicked.connect(self._reset)

    def _on_transcription_error(self, error_key: str, error_params: dict):
        """
        Handle a genuine transcription failure (not a user cancel — that's
        handled separately by _cancel_transcription).

        Receives an i18n key + params (rendered at display time, so the
        banner survives a language toggle). Shows an inline banner on the
        Choose Model step instead of a modal QMessageBox, and returns there
        (rather than all the way back to file selection) so the user can
        retry - e.g. with a smaller model - without having to re-pick the file.
        """
        logger.error(f"Transcription error: {error_key} {error_params}")
        self.cancel_btn.hide()
        self.transcription_step.stop()
        self.model_step.show_error(error_key, error_params)
        self._return_to_model_select()

    def _cancel_transcription(self):
        """Stop a running transcription and return to Choose Model."""
        logger.info("Transcription cancelled by user")
        self.transcription_step.stop()
        if self.transcription_thread:
            # Disconnect first: stop() causes the thread to emit its own
            # "Transcription cancelled" error signal, which we don't want
            # routed through _on_transcription_error (that's for genuine
            # failures only).
            self.transcription_thread.error.disconnect(self._on_transcription_error)
            self.transcription_thread.finished.disconnect(self._on_transcription_complete)
            self.transcription_thread.stop()
            self.transcription_thread.wait()
        self.cancel_btn.hide()
        self._return_to_model_select()

    def _return_to_model_select(self):
        """Go back to the Choose Model step, keeping the selected file/model."""
        self.current_step = Step.MODEL_SELECT
        self.stacked_widget.setCurrentIndex(1)
        self.back_btn.show()
        self.back_btn.setEnabled(True)
        self._set_next_button_mode("next")
        self.next_btn.show()
        self.next_btn.setEnabled(self.selected_model is not None)
        try:
            self.next_btn.clicked.disconnect()
        except TypeError:
            pass  # already disconnected (e.g. no prior completion state)
        self.next_btn.clicked.connect(self._go_next)

    def _reset(self):
        """Reset to file selection."""
        self.model_step.clear_error()
        self.current_step = Step.FILE_SELECT
        self.stacked_widget.setCurrentIndex(0)
        self.selected_file = None
        self.selected_model = None
        self.audio_duration = 0
        self.back_btn.hide()
        self.next_btn.setEnabled(False)
        self._set_next_button_mode("next")
        self.next_btn.show()
        self.next_btn.clicked.disconnect()
        self.next_btn.clicked.connect(self._go_next)
        self.file_step.reset()
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

    i18n.apply_saved_language(app)

    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
