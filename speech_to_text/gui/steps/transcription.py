"""Step 3: transcription progress, live status, and completion result."""

import os
import time
import logging

from PyQt5.QtWidgets import QVBoxLayout, QLabel, QProgressBar, QFrame
from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation, QEasingCurve

from speech_to_text.gui import theme
from speech_to_text.gui.i18n import t
from speech_to_text.gui.theme import COLORS, Fonts, Spacing
from speech_to_text.gui.icons import ICONS, svg_to_pixmap

logger = logging.getLogger(__name__)


class TranscriptionStep(QFrame):
    """Step 3: Transcription progress and results."""

    # Once this many seconds pass with no real percentage movement, the
    # elapsed*(100-pct)/pct projection is stale (it was only ever valid for
    # the pace measured up to the last real update) and left unchecked
    # balloons into an obviously-wrong, ever-growing number. Switch to an
    # honest "calculating..." instead of trusting it past this point.
    STALL_SECONDS = 5

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.XL)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)
        layout.setAlignment(Qt.AlignCenter)

        # Title
        self.title = QLabel(t("transcribing_title"))
        self.title.setFont(Fonts.TITLE)
        self.title.setStyleSheet(theme.text_qss("text_primary"))
        self.title.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.title)

        # File info
        self.file_info = QLabel()
        self.file_info.setFont(Fonts.BODY)
        self.file_info.setStyleSheet(theme.text_qss("text_secondary"))
        self.file_info.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.file_info)

        layout.addSpacing(Spacing.XL)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(theme.progress_bar_qss())
        self.progress_bar.setMinimumHeight(28)
        layout.addWidget(self.progress_bar)

        # Animates value changes instead of snapping instantly — real
        # progress can arrive in uneven bursts (faster-whisper only reports
        # a segment once it's fully decoded, which can include several
        # temperature-retry attempts), so a big jump reads as "catching up"
        # rather than a glitch when it's smoothed over ~500ms.
        self._progress_animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_animation.setDuration(500)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)

        # Status and times
        self.status_label = QLabel(t("w_initializing"))
        self.status_label.setFont(Fonts.BODY_BOLD_SMALL)
        self.status_label.setStyleSheet(theme.text_qss("text_primary"))
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        # Time info
        self.time_label = QLabel()
        self.time_label.setFont(Fonts.BODY)
        self.time_label.setStyleSheet(theme.text_qss("text_secondary"))
        self.time_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.time_label)

        layout.addSpacing(Spacing.MD - 2)

        # Result display (hidden until done)
        self.result_widget = QFrame()
        self.result_widget.setObjectName("resultPanel")
        self.result_widget.setStyleSheet(theme.result_panel_qss("resultPanel"))
        result_layout = QVBoxLayout(self.result_widget)
        result_layout.setSpacing(Spacing.SM)

        # Checkmark icon
        result_icon = QLabel()
        result_pixmap = svg_to_pixmap(ICONS["check"], 48, COLORS['success'])
        result_icon.setPixmap(result_pixmap)
        result_icon.setStyleSheet("background: transparent;")
        result_icon.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(result_icon)

        # Success message
        self.success_msg = QLabel(t("transcription_complete"))
        self.success_msg.setFont(Fonts.SUBTITLE_BOLD)
        self.success_msg.setStyleSheet(theme.text_qss("success"))
        self.success_msg.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(self.success_msg)

        # File path
        self.result_path = QLabel()
        self.result_path.setFont(Fonts.BODY)
        self.result_path.setStyleSheet(theme.text_qss("text_secondary"))
        self.result_path.setAlignment(Qt.AlignCenter)
        self.result_path.setWordWrap(True)
        result_layout.addWidget(self.result_path)

        self.result_widget.hide()
        layout.addWidget(self.result_widget)

        layout.addStretch()

        self.start_time = None
        self._last_percentage = 0
        self._last_percent_change_time = None
        # Status text is stored as an i18n key + params (not rendered text)
        # so a mid-run language toggle can re-render the live status.
        self._status_key = "w_initializing"
        self._status_params = {}
        self._file_info_args = None   # (filename, model) once a run starts
        self._result_path_value = None
        self._dot_phase = 0
        # Ticks once a second so the elapsed/remaining time and a "still
        # working" heartbeat keep moving even during real backend gaps with
        # no new progress message (e.g. while the model is still loading, or
        # a long segment is still being decoded) — otherwise the UI looks
        # frozen even though work is genuinely happening in the background
        # process.
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def set_file_info(self, filename: str, model: str):
        """Set file and model info for display."""
        self._file_info_args = (filename, model)
        self.file_info.setText(t("file_model_info", filename=filename, model=model.title()))

    def start(self):
        """Reset the display for a fresh run and start the elapsed-time ticker."""
        self.start_time = time.time()
        self._last_percentage = 0
        self._last_percent_change_time = self.start_time
        self._status_key = "w_initializing"
        self._status_params = {}
        self._dot_phase = 0
        self.progress_bar.setValue(0)
        self.status_label.setText(t("w_initializing"))
        self.time_label.setText(t("elapsed", elapsed="0:00"))
        self.result_widget.hide()
        self._timer.start()

    def stop(self):
        """Stop the elapsed-time ticker (run finished, failed, or was cancelled)."""
        self._timer.stop()

    def _tick(self):
        if self.start_time is None:
            return
        # Cycle a trailing "", ".", "..", "..." suffix on the status text as
        # a heartbeat — visible proof the app is alive even when the backend
        # hasn't sent a new message this second.
        self._dot_phase = (self._dot_phase + 1) % 4
        self.status_label.setText(self._render_status().rstrip(".") + "." * self._dot_phase)
        self._refresh_time_label(time.time() - self.start_time)

    def _render_status(self) -> str:
        return t(self._status_key, **self._status_params)

    def update_progress(self, status_key: str, params: dict, percentage: int):
        """
        Update status text and, for real percentage updates, the progress
        bar and elapsed/estimated-remaining time.

        status_key/params identify an i18n message (rendered here, in the
        current UI language - the worker only ever sends keys).

        percentage == -1 is a status-only sentinel (see
        TranscriptionThread._relay_progress_message): faster-whisper is
        doing real work — decoding a segment, retrying it at a different
        temperature — but we don't have a new, trustworthy percentage yet,
        so only the descriptive text is updated; the bar and ETA are left
        exactly where they were.
        """
        self._status_key = status_key
        self._status_params = dict(params)
        self._dot_phase = 0
        self.status_label.setText(self._render_status())

        if percentage >= 0:
            if percentage != self._last_percentage:
                self._animate_progress_to(percentage)
            self._last_percentage = percentage
            self._last_percent_change_time = time.time()

        if self.start_time is not None:
            self._refresh_time_label(time.time() - self.start_time)

    def _animate_progress_to(self, percentage: int) -> None:
        self._progress_animation.stop()
        self._progress_animation.setStartValue(self.progress_bar.value())
        self._progress_animation.setEndValue(percentage)
        self._progress_animation.start()

    def _refresh_time_label(self, elapsed: float) -> None:
        """
        Recompute elapsed + estimated-remaining from the last known progress
        percentage. Called both on every real progress update and on every
        1-second tick, so "Est. remaining" stays visible and keeps counting
        down throughout the whole run instead of only appearing momentarily
        each time a backend message arrives.

        If the percentage hasn't moved in a while (STALL_SECONDS), the
        elapsed*(100-pct)/pct projection is no longer trustworthy — it was
        only ever a snapshot of the pace up to the last real update, and
        without correction it balloons the longer a single hard-to-decode
        segment takes. Showing "calculating..." is more honest than a
        confidently-wrong, ever-growing number.
        """
        percentage = self._last_percentage
        since_last_change = (
            elapsed if self._last_percent_change_time is None
            else time.time() - self._last_percent_change_time
        )

        if percentage <= 0:
            self.time_label.setText(t("elapsed", elapsed=self._format_mmss(elapsed)))
        elif since_last_change > self.STALL_SECONDS:
            self.time_label.setText(t(
                "elapsed_remaining",
                elapsed=self._format_mmss(elapsed), remaining=t("calculating"),
            ))
        else:
            # Simple linear projection from work done so far.
            remaining = elapsed * (100 - percentage) / percentage
            self.time_label.setText(t(
                "elapsed_remaining",
                elapsed=self._format_mmss(elapsed), remaining=self._format_mmss(remaining),
            ))

    @staticmethod
    def _format_mmss(seconds: float) -> str:
        total = max(int(seconds), 0)
        minutes, secs = divmod(total, 60)
        return f"{minutes}:{secs:02d}"

    def show_result(self, file_path: str):
        """Show completion result."""
        self._result_path_value = os.path.abspath(file_path)
        self.result_widget.show()
        self.result_path.setText(t("saved_to", path=self._result_path_value))

    def retranslate(self):
        """Re-render all text in the current UI language (live toggle)."""
        self.title.setText(t("transcribing_title"))
        self.success_msg.setText(t("transcription_complete"))
        self.status_label.setText(self._render_status())
        if self._file_info_args is not None:
            self.set_file_info(*self._file_info_args)
        if self._result_path_value is not None:
            self.result_path.setText(t("saved_to", path=self._result_path_value))
        if self.start_time is not None:
            self._refresh_time_label(time.time() - self.start_time)
