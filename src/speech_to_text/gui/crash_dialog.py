"""Last-resort dialog for a truly unhandled crash.

This is the one intentional exception to this app's "no modal QMessageBox
for errors" design (see theme.py's error_banner_qss docstring for why
routine failures use a non-modal banner instead). An unhandled crash has no
other UI path at all - the window may be in an unrecoverable state - so
interrupting the user here is unavoidable and expected, unlike a failed
transcription the user can just retry.
"""

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from speech_to_text import config

logger = logging.getLogger(__name__)


class CrashDialog(QDialog):
    """Shows an unhandled crash's message, log location, and full traceback on demand."""

    def __init__(self, parent, message: str, traceback_text: str) -> None:
        super().__init__(parent)
        self._message = message
        self._traceback_text = traceback_text
        self._log_path = config.resolve_log_path()

        self.setWindowTitle(f"{config.APP_NAME} - Unexpected error")
        self.setModal(True)
        self.setMinimumWidth(560)

        layout = QVBoxLayout(self)

        headline = QLabel(
            "Something went wrong and the app could not continue as normal.\n"
            "The details below can be copied into a bug report."
        )
        headline.setWordWrap(True)
        layout.addWidget(headline)

        message_label = QLabel(message or "(no message)")
        message_label.setWordWrap(True)
        message_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(message_label)

        log_row = QHBoxLayout()
        log_row.addWidget(QLabel("Log file:"))
        log_field = QLineEdit(self._log_path)
        log_field.setReadOnly(True)
        log_row.addWidget(log_field)
        layout.addLayout(log_row)

        self._details_toggle = QToolButton()
        self._details_toggle.setText("Show details")
        self._details_toggle.setCheckable(True)
        self._details_toggle.toggled.connect(self._on_toggle_details)
        layout.addWidget(self._details_toggle)

        self._details_view = QPlainTextEdit(traceback_text)
        self._details_view.setReadOnly(True)
        self._details_view.setStyleSheet("font-family: monospace;")
        self._details_view.setVisible(False)
        layout.addWidget(self._details_view)

        button_row = QHBoxLayout()

        copy_details_btn = QPushButton("Copy details")
        copy_details_btn.clicked.connect(self._on_copy_details)
        button_row.addWidget(copy_details_btn)

        copy_log_path_btn = QPushButton("Copy log file path")
        copy_log_path_btn.clicked.connect(self._on_copy_log_path)
        button_row.addWidget(copy_log_path_btn)

        button_row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        close_btn.setDefault(True)
        button_row.addWidget(close_btn)

        layout.addLayout(button_row)

    def _on_toggle_details(self, checked: bool) -> None:
        self._details_view.setVisible(checked)
        self._details_toggle.setText("Hide details" if checked else "Show details")

    def _on_copy_details(self) -> None:
        text = f"{self._message}\n\n{self._traceback_text}\n\nLog file: {self._log_path}"
        QApplication.clipboard().setText(text)

    def _on_copy_log_path(self) -> None:
        QApplication.clipboard().setText(self._log_path)
