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
from speech_to_text.gui.i18n import t
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
        self.title = QLabel(t("specs_title"))
        self.title.setFont(Fonts.TITLE)
        self.title.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(self.title)

        # System info table — shown here (above the drop zone) since it's
        # relevant context before the user even picks a file or model.
        hw_table = self._create_hardware_table()
        layout.addWidget(hw_table)

        # Subheading for the drop zone below.
        self.file_heading = QLabel(t("select_audio_file"))
        self.file_heading.setFont(Fonts.SUBTITLE_BOLD)
        self.file_heading.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(self.file_heading)

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
        self.main_text = QLabel(t("drop_main"))
        self.main_text.setFont(Fonts.BODY_BOLD)
        self.main_text.setStyleSheet(theme.text_qss("text_primary"))
        self.main_text.setAlignment(Qt.AlignCenter)
        self.main_text.setMaximumHeight(20)
        drop_layout.addWidget(self.main_text)

        # Supported formats
        self.formats_text = QLabel(t("drop_formats"))
        self.formats_text.setFont(Fonts.CAPTION)
        self.formats_text.setStyleSheet(theme.text_qss("text_secondary"))
        self.formats_text.setAlignment(Qt.AlignCenter)
        self.formats_text.setMaximumHeight(16)
        drop_layout.addWidget(self.formats_text)

        # Alt text
        self.alt_text = QLabel(t("drop_alt"))
        self.alt_text.setFont(Fonts.CAPTION)
        self.alt_text.setStyleSheet(theme.text_qss("text_tertiary"))
        self.alt_text.setAlignment(Qt.AlignCenter)
        self.alt_text.setMaximumHeight(16)
        drop_layout.addWidget(self.alt_text)

        layout.addWidget(self.drop_zone)

        # File info display (icon + label, replaces the old '✓ {filename}' text glyph)
        file_info_row = QHBoxLayout()
        file_info_row.setSpacing(Spacing.XS)
        self.file_icon = QLabel()
        self.file_icon.setStyleSheet("background: transparent;")
        self.file_icon.setFixedSize(16, 16)
        self.file_icon.hide()
        file_info_row.addWidget(self.file_icon)

        self.file_label = QLabel(t("no_file_selected"))
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
        file_filter = t("file_dialog_filter") + " (" + " ".join(config.SUPPORTED_FORMATS) + ")"
        file_path, _ = QFileDialog.getOpenFileName(self, t("file_dialog_title"), "", file_filter)
        if file_path:
            self._select_file(file_path)

    def _select_file(self, file_path: str):
        self.selected_file = file_path

        # Get duration
        self.selected_duration = get_audio_duration(file_path)

        # Update display
        self.file_icon.setPixmap(svg_to_pixmap(ICONS["check_circle"], 16, COLORS['success']))
        self.file_icon.show()
        self._render_file_label()
        self.file_label.setStyleSheet(theme.text_qss("success", "font-weight: 600;"))

        # Emit signal with file and duration
        self.file_selected.emit(file_path, self.selected_duration)

    def _render_file_label(self):
        """Render the selected-file info line in the current UI language."""
        size_mb = os.path.getsize(self.selected_file) / (1024 * 1024)
        self.file_label.setText(t(
            "file_info",
            filename=os.path.basename(self.selected_file),
            minutes=self.selected_duration // 60,
            seconds=self.selected_duration % 60,
            size=f"{size_mb:.1f}",
        ))

    def reset(self):
        """Clear the selected file and restore the placeholder label."""
        self.selected_file = None
        self.selected_duration = 0
        self.file_icon.hide()
        self.file_label.setText(t("no_file_selected"))
        self.file_label.setStyleSheet(theme.text_qss("text_secondary"))

    def retranslate(self):
        """Re-render all text in the current UI language (live toggle)."""
        self.title.setText(t("specs_title"))
        self.file_heading.setText(t("select_audio_file"))
        self.main_text.setText(t("drop_main"))
        self.formats_text.setText(t("drop_formats"))
        self.alt_text.setText(t("drop_alt"))
        for key, label in self._hw_header_labels.items():
            label.setText(t(key))
        if self._hw_gpu_value_label is not None and not self._hw_has_gpu:
            self._hw_gpu_value_label.setText(t("hw_no_gpu"))
        if self.selected_file is not None:
            self._render_file_label()
        else:
            self.file_label.setText(t("no_file_selected"))

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
        self._hw_has_gpu = hw_info['has_gpu']
        gpu_text = hw_info['gpu_name'] if hw_info['has_gpu'] else t("hw_no_gpu")
        # Header labels are keyed by i18n key so retranslate() can re-render
        # them; the GPU value cell is also tracked because "No GPU" is text.
        self._hw_header_labels = {}
        self._hw_gpu_value_label = None
        columns = [
            ("hw_cpu_cores", str(hw_info['cpu_cores'])),
            ("hw_ram", f"{hw_info['ram_gb']} GB"),
            ("hw_gpu", gpu_text),
        ]

        grid = QGridLayout()
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(0)

        for i, (label_key, value) in enumerate(columns):
            col = i * 2  # odd columns hold vertical divider lines
            grid.addWidget(self._create_table_cell(label_key, value), 0, col)
            if i < len(columns) - 1:
                grid.addWidget(self._vline(), 0, col + 1)

        outer.addLayout(grid)

        return card

    def _create_table_cell(self, label_key: str, value: str) -> QWidget:
        """One table cell: header label, a divider line, then the value."""
        cell = QWidget()
        cell.setStyleSheet("background: transparent;")
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(Spacing.MD, 0, Spacing.MD, 0)
        cell_layout.setSpacing(Spacing.XS)

        label_widget = QLabel(t(label_key))
        label_widget.setFont(Fonts.CAPTION)
        label_widget.setStyleSheet(theme.text_qss("text_tertiary"))
        label_widget.setAlignment(Qt.AlignCenter)
        cell_layout.addWidget(label_widget)
        self._hw_header_labels[label_key] = label_widget

        cell_layout.addWidget(self._hline())

        value_widget = QLabel(value)
        value_widget.setFont(Fonts.BODY_BOLD)
        value_widget.setStyleSheet(theme.text_qss("text_primary"))
        value_widget.setAlignment(Qt.AlignCenter)
        cell_layout.addWidget(value_widget)
        if label_key == "hw_gpu":
            self._hw_gpu_value_label = value_widget

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
