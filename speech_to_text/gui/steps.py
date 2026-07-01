"""
Wizard step widgets for the Speech-to-Text Transcriber GUI.
3-step flow: Select File -> Choose Model -> Transcribe
"""

import os
import time
import logging
from enum import Enum

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QRadioButton, QButtonGroup,
    QFileDialog, QProgressBar, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal, QTimer, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QDragEnterEvent, QDropEvent

from speech_to_text import config
from speech_to_text.hardware_detection import HardwareDetector
from speech_to_text.gui import theme
from speech_to_text.gui.theme import COLORS, Fonts, Spacing
from speech_to_text.gui.icons import ICONS, svg_to_pixmap
from speech_to_text.gui.audio_utils import get_audio_duration

logger = logging.getLogger(__name__)


class Step(Enum):
    """Application steps."""
    FILE_SELECT = 0
    MODEL_SELECT = 1
    TRANSCRIPTION = 2


class FileSelectStep(QFrame):
    """Step 1: File Selection with drag-and-drop."""

    file_selected = pyqtSignal(str, int)  # file_path, duration_seconds

    def __init__(self, hardware: HardwareDetector, parent=None):
        super().__init__(parent)
        self.hardware = hardware
        self.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.LG)
        layout.setContentsMargins(Spacing.XL, Spacing.XL, Spacing.XL, Spacing.XL)

        # Title — "Specs" now, since the system-info table is the first
        # thing on this page.
        title = QLabel("Specs")
        title.setFont(Fonts.TITLE)
        title.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(title)

        # System info table — shown here (above the drop zone) since it's
        # relevant context before the user even picks a file or model.
        hw_table = self._create_hardware_table()
        layout.addWidget(hw_table)

        # Subheading for the drop zone below.
        file_heading = QLabel("Select Audio File")
        file_heading.setFont(Fonts.SUBTITLE_BOLD)
        file_heading.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(file_heading)

        # Drop zone - large and spacious. Also acts as the browse button: the
        # whole area is clickable to open a file dialog, in addition to drag-and-drop.
        self.drop_zone = QFrame()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setStyleSheet(theme.drop_zone_qss("dropZone", active=False))
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.setCursor(Qt.PointingHandCursor)
        self.drop_zone.dragEnterEvent = self._drag_enter
        self.drop_zone.dragLeaveEvent = lambda e: self._reset_drop_zone()
        self.drop_zone.dropEvent = self._drop
        self.drop_zone.mousePressEvent = lambda e: self._browse()
        self.drop_zone.setFixedHeight(config.GUI_DROP_ZONE_HEIGHT)

        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setSpacing(config.GUI_DROP_ZONE_SPACING)
        drop_layout.setContentsMargins(config.GUI_DROP_ZONE_PADDING, config.GUI_DROP_ZONE_PADDING,
                                        config.GUI_DROP_ZONE_PADDING, config.GUI_DROP_ZONE_PADDING)

        # Folder icon
        icon_label = QLabel()
        icon_pixmap = svg_to_pixmap(ICONS["folder"], 48, COLORS['accent'])
        icon_label.setPixmap(icon_pixmap)
        icon_label.setStyleSheet("background: transparent;")
        icon_label.setAlignment(Qt.AlignCenter)
        icon_label.setMaximumHeight(52)
        drop_layout.addWidget(icon_label)

        # Main text
        main_text = QLabel("Drag your audio or video file here")
        main_text.setFont(Fonts.BODY_BOLD)
        main_text.setStyleSheet(theme.text_qss("text_primary"))
        main_text.setAlignment(Qt.AlignCenter)
        main_text.setMaximumHeight(20)
        drop_layout.addWidget(main_text)

        # Supported formats
        formats_text = QLabel("MP3, WAV, M4A, FLAC, OGG, MP4, MKV")
        formats_text.setFont(Fonts.CAPTION)
        formats_text.setStyleSheet(theme.text_qss("text_secondary"))
        formats_text.setAlignment(Qt.AlignCenter)
        formats_text.setMaximumHeight(16)
        drop_layout.addWidget(formats_text)

        # Alt text
        alt_text = QLabel("or click anywhere here to browse")
        alt_text.setFont(Fonts.CAPTION)
        alt_text.setStyleSheet(theme.text_qss("text_tertiary"))
        alt_text.setAlignment(Qt.AlignCenter)
        alt_text.setMaximumHeight(16)
        drop_layout.addWidget(alt_text)

        layout.addWidget(self.drop_zone)

        # File info display (icon + label, replaces the old '✓ {filename}' text glyph)
        file_info_row = QHBoxLayout()
        file_info_row.setSpacing(Spacing.XS)
        self.file_icon = QLabel()
        self.file_icon.setStyleSheet("background: transparent;")
        self.file_icon.setFixedSize(16, 16)
        self.file_icon.hide()
        file_info_row.addWidget(self.file_icon)

        self.file_label = QLabel("No file selected")
        self.file_label.setFont(Fonts.BODY)
        self.file_label.setStyleSheet(theme.text_qss("text_secondary"))
        self.file_label.setMaximumHeight(18)
        file_info_row.addWidget(self.file_label)
        file_info_row.addStretch()
        layout.addLayout(file_info_row)

        layout.addStretch()

        self.selected_file = None
        self.selected_duration = 0

    def _reset_drop_zone(self):
        """Reset drop zone to its normal (non-drag) styling."""
        self.drop_zone.setStyleSheet(theme.drop_zone_qss("dropZone", active=False))

    def _drag_enter(self, event: QDragEnterEvent):
        """Handle drag enter event over the drop zone."""
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self.drop_zone.setStyleSheet(theme.drop_zone_qss("dropZone", active=True))

    def _drop(self, event: QDropEvent):
        self._reset_drop_zone()
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            self._select_file(files[0])

    def _browse(self):
        file_filter = "Audio/Video Files (" + " ".join(config.SUPPORTED_FORMATS) + ")"
        file_path, _ = QFileDialog.getOpenFileName(self, "Select File", "", file_filter)
        if file_path:
            self._select_file(file_path)

    def _select_file(self, file_path: str):
        self.selected_file = file_path
        filename = os.path.basename(file_path)

        # Get duration
        self.selected_duration = get_audio_duration(file_path)
        duration_min = self.selected_duration // 60
        duration_sec = self.selected_duration % 60

        # Update display
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        self.file_icon.setPixmap(svg_to_pixmap(ICONS["check_circle"], 16, COLORS['success']))
        self.file_icon.show()
        self.file_label.setText(f"{filename} | {duration_min}m {duration_sec}s | {size_mb:.1f} MB")
        self.file_label.setStyleSheet(theme.text_qss("success", "font-weight: 600;"))

        # Emit signal with file and duration
        self.file_selected.emit(file_path, self.selected_duration)

    def _create_hardware_table(self) -> QFrame:
        """Create a compact tabular system-info display (CPU / RAM / GPU)."""
        card = QFrame()
        card.setObjectName("hardwareCard")
        card.setStyleSheet(theme.hardware_card_qss("hardwareCard"))

        outer = QVBoxLayout(card)
        outer.setContentsMargins(Spacing.MD, Spacing.SM, Spacing.MD, Spacing.SM)
        outer.setSpacing(Spacing.XS)
        # No in-card header here — the page title above the card already
        # reads "Specs", so a repeated label inside would be redundant.

        # Table: one cell per metric, each with its own header/value split by
        # a divider line, and vertical divider lines between cells — a real
        # row/column grid rather than plain text spread across a bare card.
        hw_info = self.hardware.get_hardware_info()
        gpu_text = hw_info['gpu_name'] if hw_info['has_gpu'] else "No GPU"
        columns = [
            ("CPU CORES", str(hw_info['cpu_cores'])),
            ("RAM", f"{hw_info['ram_gb']} GB"),
            ("GPU", gpu_text),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)

        for i, (label, value) in enumerate(columns):
            col = i * 2  # odd columns hold vertical divider lines
            grid.addWidget(self._create_table_cell(label, value), 0, col)
            if i < len(columns) - 1:
                grid.addWidget(self._vline(), 0, col + 1)

        outer.addLayout(grid)

        return card

    def _create_table_cell(self, label: str, value: str) -> QWidget:
        """One table cell: header label, a divider line, then the value."""
        cell = QWidget()
        cell.setStyleSheet("background: transparent;")
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(Spacing.MD, 0, Spacing.MD, 0)
        cell_layout.setSpacing(Spacing.XS)

        label_widget = QLabel(label)
        label_widget.setFont(Fonts.CAPTION)
        label_widget.setStyleSheet(theme.text_qss("text_tertiary"))
        label_widget.setAlignment(Qt.AlignCenter)
        cell_layout.addWidget(label_widget)

        cell_layout.addWidget(self._hline())

        value_widget = QLabel(value)
        value_widget.setFont(Fonts.BODY_BOLD)
        value_widget.setStyleSheet(theme.text_qss("text_primary"))
        value_widget.setAlignment(Qt.AlignCenter)
        cell_layout.addWidget(value_widget)

        return cell

    @staticmethod
    def _hline() -> QFrame:
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {COLORS['border_light']};")
        return line

    @staticmethod
    def _vline() -> QFrame:
        line = QFrame()
        line.setFixedWidth(1)
        line.setStyleSheet(f"background-color: {COLORS['border_light']};")
        return line


class ModelSelectStep(QFrame):
    """Step 2: Model Selection with recommendation and time estimates."""

    model_selected = pyqtSignal(str)  # model_size

    def __init__(self, hardware: HardwareDetector, parent=None):
        super().__init__(parent)
        self.hardware = hardware
        self.audio_duration = 0
        self._desc_labels = {}  # model_name -> QLabel showing "description | Est: ..."
        self._cards = {}        # model_name -> QFrame card
        self._badges = {}       # model_name -> "RECOMMENDED" QLabel (always created, shown/hidden)
        self._user_touched_model = False  # True once the user manually picks a model
        self._syncing = False   # True while we're programmatically re-checking a radio
        self.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        layout = QVBoxLayout(self)
        layout.setSpacing(Spacing.SM)
        layout.setContentsMargins(Spacing.XL, Spacing.MD, Spacing.XL, Spacing.MD)

        # Title
        title = QLabel("Choose Model")
        title.setFont(Fonts.TITLE)
        title.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(title)

        # Error banner — shown inline (instead of a modal popup) if a
        # transcription attempt fails and the user is sent back here to
        # retry. Hidden until show_error() is called.
        self.error_banner = QFrame()
        self.error_banner.setObjectName("modelErrorBanner")
        self.error_banner.setStyleSheet(theme.error_banner_qss("modelErrorBanner"))
        self.error_banner.hide()
        error_layout = QHBoxLayout(self.error_banner)
        error_layout.setContentsMargins(Spacing.SM, Spacing.XS, Spacing.SM, Spacing.XS)
        error_layout.setSpacing(Spacing.XS)

        error_icon = QLabel()
        error_icon.setPixmap(svg_to_pixmap(ICONS["alert_triangle"], 16, COLORS['error']))
        error_icon.setStyleSheet("background: transparent;")
        error_layout.addWidget(error_icon)

        self.error_label = QLabel()
        self.error_label.setFont(Fonts.CAPTION)
        self.error_label.setStyleSheet(theme.text_qss("error"))
        self.error_label.setWordWrap(True)
        error_layout.addWidget(self.error_label, 1)

        layout.addWidget(self.error_banner)

        # All model cards are laid out directly (no scroll area) — sized to
        # fit every option in the fixed window without needing to scroll.
        models_layout = QVBoxLayout()
        models_layout.setSpacing(Spacing.XS + 2)
        models_layout.setContentsMargins(0, 0, 0, 0)

        # Model selection
        self.model_group = QButtonGroup()
        self.model_radios = {}
        recommended_model, _ = hardware.recommend_model(self.audio_duration)
        self.selected_model = recommended_model
        self._current_recommended = recommended_model

        for i, (model_name, model_info) in enumerate(config.MODELS.items()):
            model_card = self._create_model_card(
                i, model_name, model_info,
                is_recommended=(model_name == recommended_model)
            )
            models_layout.addWidget(model_card)

        layout.addLayout(models_layout)
        layout.addStretch()

    def show_error(self, message: str) -> None:
        """Show an inline failure banner (used instead of a modal popup)."""
        self.error_label.setText(f"Transcription failed: {message}")
        self.error_banner.show()

    def clear_error(self) -> None:
        self.error_banner.hide()

    def _on_radio_toggled(self, name: str, checked: bool) -> None:
        if checked:
            self.selected_model = name
            self.model_selected.emit(name)
            self._apply_selection(name)
            if not self._syncing:
                # A real click (not our own programmatic re-sync) — stop
                # auto-following the recommendation as it updates.
                self._user_touched_model = True

    def _apply_selection(self, name: str) -> None:
        """Move the accent border to whichever card's radio is currently picked."""
        for card_name, card in self._cards.items():
            card.setStyleSheet(theme.card_qss(f"modelCard_{card_name}", selected=(card_name == name)))

    def _create_model_card(self, idx: int, name: str, info: dict, is_recommended: bool = False) -> QFrame:
        """Create and return a model selection card with radio button and details."""
        card = QFrame()
        object_name = f"modelCard_{name}"
        card.setObjectName(object_name)
        # Initially, the recommended model is also the selected one.
        card.setStyleSheet(theme.card_qss(object_name, selected=is_recommended))

        layout = QHBoxLayout(card)
        layout.setContentsMargins(Spacing.MD, Spacing.XS, Spacing.MD, Spacing.XS)
        layout.setSpacing(Spacing.MD)

        # Radio button
        radio = QRadioButton()
        radio.setChecked(is_recommended)
        radio.toggled.connect(lambda checked: self._on_radio_toggled(name, checked))
        self.model_group.addButton(radio, idx)
        self.model_radios[name] = radio
        radio.setStyleSheet(f"QRadioButton {{ color: {COLORS['text_primary']}; }}")
        layout.addWidget(radio)

        # Model name and description
        text_layout = QVBoxLayout()
        text_layout.setSpacing(2)

        model_label = QLabel(name.title())
        model_label.setFont(Fonts.BODY_BOLD)
        model_label.setStyleSheet(theme.text_qss("text_primary"))
        text_layout.addWidget(model_label)

        # Description + time estimate (kept up to date via update_audio_duration)
        desc = info.get('description', '')
        time_est, _ = self.hardware.estimate_transcription_time(self.audio_duration, name)
        time_str = self.hardware.get_time_estimate_display(time_est)

        desc_label = QLabel(f"{desc} | Est: {time_str}")
        desc_label.setFont(Fonts.CAPTION)
        desc_label.setStyleSheet(theme.text_qss("text_secondary"))
        text_layout.addWidget(desc_label)
        self._desc_labels[name] = desc_label

        layout.addLayout(text_layout)
        layout.addStretch()

        # Recommended badge — always created so update_audio_duration can
        # show/hide it as the real recommendation shifts, instead of only
        # ever reflecting the recommendation computed at construction time.
        badge = QLabel("RECOMMENDED")
        badge.setStyleSheet(theme.badge_qss())
        badge.setVisible(is_recommended)
        layout.addWidget(badge)
        self._badges[name] = badge

        card.setFixedHeight(56)
        self._cards[name] = card
        return card

    def update_audio_duration(self, seconds: int) -> None:
        """
        Recompute time estimates and the real recommendation in place, once
        the actual audio duration (and possibly a freshly finished hardware
        calibration) is known.
        """
        self.audio_duration = seconds
        for name, label in self._desc_labels.items():
            info = config.MODELS[name]
            time_est, _ = self.hardware.estimate_transcription_time(seconds, name)
            time_str = self.hardware.get_time_estimate_display(time_est)
            label.setText(f"{info.get('description', '')} | Est: {time_str}")

        recommended_model, _ = self.hardware.recommend_model(seconds)
        self._apply_recommendation(recommended_model)

    def _apply_recommendation(self, recommended_model: str) -> None:
        """
        Move the RECOMMENDED badge to recommended_model and, if the user
        hasn't manually picked a model yet, follow it with the selection.

        The accent border is a separate concept (see _apply_selection) —
        it always tracks whichever card's radio is actually checked, not
        the recommendation, so a manually-picked model stays highlighted
        even after the recommendation moves elsewhere.
        """
        if recommended_model == self._current_recommended:
            return
        self._current_recommended = recommended_model

        for name, badge in self._badges.items():
            badge.setVisible(name == recommended_model)

        if not self._user_touched_model:
            self._syncing = True
            self.model_radios[recommended_model].setChecked(True)
            self._syncing = False


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
        title = QLabel("Transcribing")
        title.setFont(Fonts.TITLE)
        title.setStyleSheet(theme.text_qss("text_primary"))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

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
        self.status_label = QLabel("Initializing...")
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
        success_msg = QLabel("Transcription Complete!")
        success_msg.setFont(Fonts.SUBTITLE_BOLD)
        success_msg.setStyleSheet(theme.text_qss("success"))
        success_msg.setAlignment(Qt.AlignCenter)
        result_layout.addWidget(success_msg)

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
        self._status_base = ""
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
        self.file_info.setText(f"{filename} | Model: {model.title()}")

    def start(self):
        """Reset the display for a fresh run and start the elapsed-time ticker."""
        self.start_time = time.time()
        self._last_percentage = 0
        self._last_percent_change_time = self.start_time
        self._status_base = "Initializing"
        self._dot_phase = 0
        self.progress_bar.setValue(0)
        self.status_label.setText("Initializing...")
        self.time_label.setText("Elapsed: 0:00")
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
        self.status_label.setText(self._status_base + "." * self._dot_phase)
        self._refresh_time_label(time.time() - self.start_time)

    def update_progress(self, status: str, percentage: int):
        """
        Update status text and, for real percentage updates, the progress
        bar and elapsed/estimated-remaining time.

        percentage == -1 is a status-only sentinel (see
        TranscriptionThread._relay_progress_message): faster-whisper is
        doing real work — decoding a segment, retrying it at a different
        temperature — but we don't have a new, trustworthy percentage yet,
        so only the descriptive text is updated; the bar and ETA are left
        exactly where they were.
        """
        self._status_base = status.rstrip(".")
        self._dot_phase = 0
        self.status_label.setText(status)

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
            self.time_label.setText(f"Elapsed: {self._format_mmss(elapsed)}")
        elif since_last_change > self.STALL_SECONDS:
            self.time_label.setText(
                f"Elapsed: {self._format_mmss(elapsed)}  |  Est. remaining: calculating..."
            )
        else:
            # Simple linear projection from work done so far.
            remaining = elapsed * (100 - percentage) / percentage
            self.time_label.setText(
                f"Elapsed: {self._format_mmss(elapsed)}  |  Est. remaining: {self._format_mmss(remaining)}"
            )

    @staticmethod
    def _format_mmss(seconds: float) -> str:
        total = max(int(seconds), 0)
        minutes, secs = divmod(total, 60)
        return f"{minutes}:{secs:02d}"

    def show_result(self, file_path: str):
        """Show completion result."""
        self.result_widget.show()
        self.result_path.setText(f"Saved to:\n{os.path.abspath(file_path)}")
