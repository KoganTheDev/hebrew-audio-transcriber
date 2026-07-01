"""Step 1: file selection with drag-and-drop and a hardware specs table."""

import os
import logging

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QFileDialog, QFrame,
)
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent

from speech_to_text import config
from speech_to_text.hardware_detection import HardwareDetector
from speech_to_text.gui import theme
from speech_to_text.gui.theme import COLORS, Fonts, Spacing
from speech_to_text.gui.icons import ICONS, svg_to_pixmap
from speech_to_text.gui.audio_utils import get_audio_duration

logger = logging.getLogger(__name__)


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
