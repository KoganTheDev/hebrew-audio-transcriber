"""Step 1: file selection with drag-and-drop and a hardware specs table."""

import fnmatch
import glob
import logging
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QDragEnterEvent, QDropEvent, QIcon
from PyQt5.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from speech_to_text import config
from speech_to_text.gui import theme
from speech_to_text.gui.audio_utils import get_audio_duration
from speech_to_text.gui.i18n import t
from speech_to_text.gui.icons import ICONS, svg_to_pixmap
from speech_to_text.gui.theme import COLORS, Fonts, Spacing
from speech_to_text.gui.widgets import DropZone
from speech_to_text.hardware_detection import HardwareDetector

logger = logging.getLogger(__name__)

# Minimum height of a single file row, paired with _sync_rows_height().
ROW_MIN_HEIGHT = 26


class FileSelectStep(QFrame):
    """Step 1: File Selection with drag-and-drop, accepting one or many files."""

    files_selected = pyqtSignal(list, int)  # [file_path, ...], total duration_seconds

    def __init__(self, hardware: HardwareDetector, parent=None):
        super().__init__(parent)
        self.hardware = hardware
        self.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        layout = QVBoxLayout(self)
        # Blanket spacing cut LG -> XS. This step turned out NOT to have the
        # slack the original room analysis assumed (it counted the empty
        # band at the bottom without accounting for the trailing stretch and
        # the drop zone's old fixed height - see the setMinimumHeight note
        # below), and layout.setSpacing() multiplies across every one of
        # this layout's seven gaps: at LG that was 112px before a single
        # widget was drawn, which is what pushed the step from marginally
        # tight to actually overflowing (measured with probe.py: 84px over
        # the 471px this step gets). Kept tight; the explicit addSpacing()
        # calls below put deliberate air back only at the two section
        # boundaries that read as a break, the same technique used to fix
        # step 3's equivalent overflow.
        layout.setSpacing(Spacing.XS)
        # Horizontal margins stay generous at XXL - side padding is free
        # here (it doesn't compete with any other widget for vertical room)
        # and is where the "elevated and generous" direction actually reads
        # on this step.
        layout.setContentsMargins(Spacing.XXL, Spacing.XXL, Spacing.XXL, Spacing.XXL)

        # No page title here any more - "Specs" is now carried by the
        # wizard step indicator above the stacked widget (see
        # gui/stepper.py and MainWindow._init_ui), which already prints
        # this step's name once. A second DISPLAY heading here would say
        # the same thing again in the same place on screen; see the
        # stepper's module docstring for the full reasoning. The hardware
        # table below is now the first thing on the page.

        # System info table - shown here (above the drop zone) since it's
        # relevant context before the user even picks a file or model.
        hw_table = self._create_hardware_table()
        layout.addWidget(hw_table)
        # Section break: specs table above, file picker below. The one other
        # deliberate gap on this step, same reasoning as the one after the
        # title.
        layout.addSpacing(Spacing.SM)

        # Subheading for the drop zone below.
        self.file_heading = QLabel(t("select_audio_file"))
        self.file_heading.setFont(Fonts.SUBTITLE_BOLD)
        self.file_heading.setStyleSheet(theme.text_qss("text_primary"))
        layout.addWidget(self.file_heading)

        # Drop zone - large and spacious. Also acts as the browse button: the
        # whole area is clickable to open a file dialog, in addition to drag-and-drop.
        # DropZone (gui/widgets.py) is what makes it a real keyboard control -
        # StrongFocus plus a Space/Enter key handler - while every line below
        # keeps assigning the drag/drop/click handlers onto the instance
        # exactly as before, since tests/test_gui.py::TestDropZoneEventPath
        # sends real Qt events through this exact wiring.
        self.drop_zone = DropZone()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setStyleSheet(theme.drop_zone_qss("dropZone", active=False))
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.setCursor(Qt.PointingHandCursor)
        self.drop_zone.setAccessibleName(t("drop_zone_name"))
        self.drop_zone.setAccessibleDescription(t("drop_zone_desc"))
        self.drop_zone.setToolTip(t("drop_zone_desc"))
        self.drop_zone.dragEnterEvent = self._drag_enter
        self.drop_zone.dragLeaveEvent = lambda e: self._reset_drop_zone()
        self.drop_zone.dropEvent = self._drop
        self.drop_zone.mousePressEvent = lambda e: self._browse()
        self.drop_zone.activated.connect(self._browse)
        # A minimum plus a layout stretch factor, not a fixed height, and the
        # minimum has to sit AT the content floor rather than above it. A
        # fixed height clamps min==max so the zone can never yield; but a
        # minimum above the content floor is just as rigid downward - Qt
        # treats an explicit minimumHeight as a hard limit it will not
        # compress past, so a 210px minimum still overflowed the step the
        # moment the file list appeared and claimed its own 54px. The floor
        # is now the zone's real content minimum (icon + three lines), and
        # the generosity comes from the stretch factor on addWidget below:
        # the zone expands into whatever slack the step has, which is most
        # of the window while no file is selected, and gives that space
        # back as the list grows.
        self.drop_zone.setMinimumHeight(config.GUI_DROP_ZONE_HEIGHT)

        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setSpacing(config.GUI_DROP_ZONE_SPACING)
        drop_layout.setContentsMargins(
            config.GUI_DROP_ZONE_PADDING,
            config.GUI_DROP_ZONE_PADDING,
            config.GUI_DROP_ZONE_PADDING,
            config.GUI_DROP_ZONE_PADDING,
        )

        # Folder icon. The pixmap itself is still rasterized at a fixed
        # 48px (svg_to_pixmap's `size` arg controls the actual glyph, not
        # this label's box), so no maximumHeight is needed here - a QLabel
        # showing nothing but a pixmap already sizes to that pixmap.
        icon_label = QLabel()
        icon_pixmap = svg_to_pixmap(
            ICONS["folder"], 48, COLORS["accent"], dpr=self.devicePixelRatioF()
        )
        icon_label.setPixmap(icon_pixmap)
        icon_label.setStyleSheet("background: transparent;")
        icon_label.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(icon_label)

        # Main text. No setMaximumHeight - see the note above
        # GUI_DROP_ZONE_HEIGHT in config.py: these caps (20/16/16px) were
        # sized against a font database that under-reported its own text
        # height, so they clip the real, correctly-resolved label the
        # instant a QApplication exists for real - removed rather than
        # bumped, since a label's natural sizeHint is already the right
        # answer once the font resolves correctly, and a stale cap would
        # just reintroduce the same clipping the next time a font metric
        # shifts.
        self.main_text = QLabel(t("drop_main"))
        self.main_text.setFont(Fonts.BODY_BOLD)
        self.main_text.setStyleSheet(theme.text_qss("text_primary"))
        self.main_text.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.main_text)

        # Supported formats
        self.formats_text = QLabel(t("drop_formats"))
        self.formats_text.setFont(Fonts.CAPTION)
        self.formats_text.setStyleSheet(theme.text_qss("text_secondary"))
        self.formats_text.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.formats_text)

        # Alt text
        self.alt_text = QLabel(t("drop_alt"))
        self.alt_text.setFont(Fonts.CAPTION)
        self.alt_text.setStyleSheet(theme.text_qss("text_tertiary"))
        self.alt_text.setAlignment(Qt.AlignCenter)
        drop_layout.addWidget(self.alt_text)

        layout.addWidget(self.drop_zone, 1)

        # Selected-files summary line, above the scrollable list.
        self.summary_label = QLabel(t("no_file_selected"))
        self.summary_label.setFont(Fonts.BODY)
        self.summary_label.setStyleSheet(theme.text_qss("text_secondary"))
        layout.addWidget(self.summary_label)

        # Selected-files list. A scroll area rather than a fixed row list -
        # dropping a folder can queue an arbitrary number of files (see the
        # "Out of scope" note: there is deliberately no cap), so the row
        # count is unbounded even though the window is fixed-size.
        self._rows_container = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(Spacing.XS)
        self._rows_layout.addStretch()

        self._rows_scroll = QScrollArea()
        self._rows_scroll.setWidget(self._rows_container)
        self._rows_scroll.setWidgetResizable(True)
        self._rows_scroll.setFrameShape(QFrame.NoFrame)
        self._rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._rows_scroll.setStyleSheet("background: transparent;")
        self._rows_scroll.setMaximumHeight(140)
        # Stretch here as well as on the drop zone: the two share the step's
        # slack, so once files exist the list can grow toward its 140px cap
        # while the drop target gives space back, instead of the drop zone
        # holding everything and pinning the list at its bare minimum.
        layout.addWidget(self._rows_scroll, 1)
        # Hidden until the first file is added (see _update_summary): a
        # hidden widget's QLayoutItem is treated as empty by QBoxLayout, so
        # it claims none of its 54px minimum while the list has nothing to
        # show - the single largest remaining piece of slack on this step
        # once the drop zone stopped being fixed-height and the blanket
        # spacing was cut.
        self._rows_scroll.hide()

        # No trailing addStretch() here: the drop zone above carries the
        # stretch instead, so leftover room inflates the drop target rather
        # than pooling in an invisible spacer at the bottom of the step. Two
        # stretch items would split the slack between them and halve the
        # effect.

        # Parallel to each other and to the row widgets, all keyed by path -
        # simpler than one struct per file given how small this state is.
        self.selected_files: list[str] = []
        self._durations: dict[str, int] = {}
        self._rows: dict[str, QFrame] = {}
        # Basenames skipped by the most recent drop (see _drop) - rendered
        # into the summary line by _update_summary until the next drop
        # replaces it or reset() clears it. Not cleared by browse_for_files
        # or _remove_file: those aren't drops, and a skip note from one
        # drop staying visible while the user removes an unrelated file
        # from the list is still an accurate statement about what happened.
        self._skipped_last_drop: list[str] = []
        # Tab-order chain anchor - see _add_row. Starts at the drop zone,
        # the first (and while the list is empty, only) focusable thing on
        # this step.
        self._last_tab_widget = self.drop_zone

    @property
    def total_duration(self) -> int:
        return sum(self._durations.values())

    @property
    def durations(self) -> list[int]:
        """Per-file durations, in the same order as selected_files."""
        return [self._durations[path] for path in self.selected_files]

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
        paths = []
        # Names skipped on THIS drop specifically, not a running total - see
        # _update_summary. A folder drop is filtered by _expand_directory
        # already (glob only ever matches supported patterns to begin with),
        # so nothing from inside a folder ever lands here; this only ever
        # catches a file dropped directly that isn't one this app can open.
        skipped_names = []
        for url in event.mimeData().urls():
            local_path = url.toLocalFile()
            if not local_path:
                continue
            if os.path.isdir(local_path):
                paths.extend(self._expand_directory(local_path))
            elif self._is_supported_file(local_path):
                paths.append(local_path)
            else:
                skipped_names.append(os.path.basename(local_path))
        self._skipped_last_drop = skipped_names
        if paths:
            self._add_files(paths)
        # _add_files only calls _update_summary when it actually changes the
        # list (e.g. every dropped path was already selected), but a skip
        # note needs to render even then - and even when nothing at all was
        # added (every dropped file was unsupported) - so this always runs,
        # on top of whatever _add_files already did.
        self._update_summary()

    @staticmethod
    def _is_supported_file(path: str) -> bool:
        """Whether `path` matches one of config.SUPPORTED_FORMATS' glob
        patterns ("*.mp3", not a bare ".mp3" - see that constant's
        docstring), by filename rather than by opening the file. Used to
        filter a file dropped directly onto the zone; _expand_directory
        already filters a dropped folder's contents the same way via
        glob.glob itself, so this only needs to cover the direct-drop case.
        """
        name = os.path.basename(path).lower()
        return any(fnmatch.fnmatch(name, pattern.lower()) for pattern in config.SUPPORTED_FORMATS)

    @staticmethod
    def _expand_directory(dir_path: str) -> list[str]:
        """A dropped folder expands to the supported audio directly inside it -
        non-recursive (a subfolder of unrelated files shouldn't silently get
        pulled in) and sorted (so batch order is predictable and reproducible
        rather than whatever the filesystem happens to hand back).
        """
        found = []
        for pattern in config.SUPPORTED_FORMATS:
            found.extend(glob.glob(os.path.join(dir_path, pattern)))
        return sorted(found)

    def _browse(self):
        file_filter = t("file_dialog_filter") + " (" + " ".join(config.SUPPORTED_FORMATS) + ")"
        file_paths, _ = QFileDialog.getOpenFileNames(self, t("file_dialog_title"), "", file_filter)
        if file_paths:
            self._add_files(file_paths)

    def browse_for_files(self) -> None:
        """Public entry point for the window-level Ctrl+O shortcut (see MainWindow)."""
        self._browse()

    def _add_files(self, paths: list[str]) -> None:
        """Append new files, skipping any already listed - a second drop never duplicates."""
        changed = False
        for path in paths:
            if path in self.selected_files:
                continue
            self.selected_files.append(path)
            self._durations[path] = get_audio_duration(path)
            self._add_row(path)
            changed = True

        if changed:
            self._update_summary()
            self.files_selected.emit(list(self.selected_files), self.total_duration)

    def _add_row(self, path: str) -> None:
        row = QFrame()
        row.setStyleSheet("background: transparent;")
        # A floor per row - necessary, but not sufficient on its own. See
        # _sync_rows_height() for the half that actually makes it stick.
        row.setMinimumHeight(ROW_MIN_HEIGHT)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(Spacing.XS)

        icon = QLabel()
        icon.setPixmap(
            svg_to_pixmap(
                ICONS["check_circle"], 16, COLORS["success"], dpr=self.devicePixelRatioF()
            )
        )
        icon.setStyleSheet("background: transparent;")
        icon.setFixedSize(16, 16)
        row_layout.addWidget(icon)

        label = QLabel()
        label.setFont(Fonts.BODY)
        label.setStyleSheet(theme.text_qss("text_secondary"))
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row_layout.addWidget(label, 1)

        # A bare 20px "x" glyph with no label of any kind before this step -
        # the icon alone tells a sighted mouse user "remove", but says
        # nothing to a screen reader and nothing to anyone hovering without
        # already knowing the convention. {filename} (set in
        # _render_row_label, since it's the one place both _add_row and
        # retranslate() already funnel through) disambiguates which row's
        # button this is once more than one file is queued.
        remove_btn = QPushButton()
        remove_btn.setIcon(
            QIcon(
                svg_to_pixmap(ICONS["x"], 14, COLORS["text_tertiary"], dpr=self.devicePixelRatioF())
            )
        )
        remove_btn.setFixedSize(20, 20)
        remove_btn.setCursor(Qt.PointingHandCursor)
        remove_btn.setFocusPolicy(Qt.StrongFocus)
        hover_bg = COLORS["bg_tertiary"]
        remove_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none; }"
            f"QPushButton:hover {{ background-color: {hover_bg}; border-radius: 4px; }}"
            f'QPushButton[kbdFocus="true"] {{ background-color: {hover_bg}; border-radius: 4px; '
            f"border: 1px solid {COLORS['focus']}; }}"
        )
        remove_btn.clicked.connect(lambda: self._remove_file(path))
        row_layout.addWidget(remove_btn)

        # Insert before the trailing stretch, which stays last so new rows
        # keep appearing at the top of the list rather than after the spacer.
        self._rows_layout.insertWidget(self._rows_layout.count() - 1, row)
        self._rows[path] = row
        # Chains each new row's remove button onto the previous focusable
        # widget's tab order (starting from the drop zone itself), so
        # Tab visits the list top-to-bottom in the same order the rows are
        # drawn. Rows removed later just drop out of the chain on their own
        # (a destroyed widget is skipped by Qt's own tab-order walk) rather
        # than needing to be unlinked here.
        self.setTabOrder(self._last_tab_widget, remove_btn)
        self._last_tab_widget = remove_btn
        self._render_row_label(path)

    def _render_row_label(self, path: str) -> None:
        row = self._rows.get(path)
        if row is None:
            return
        label = row.layout().itemAt(1).widget()
        duration = self._durations[path]
        size_mb = os.path.getsize(path) / (1024 * 1024)
        filename = os.path.basename(path)
        label.setText(
            t(
                "file_info",
                filename=filename,
                minutes=duration // 60,
                seconds=duration % 60,
                size=f"{size_mb:.1f}",
            )
        )
        remove_btn = row.layout().itemAt(2).widget()
        remove_label = t("remove_file", filename=filename)
        remove_btn.setAccessibleName(remove_label)
        remove_btn.setToolTip(remove_label)

    def _remove_file(self, path: str) -> None:
        row = self._rows.pop(path, None)
        if row is not None:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._durations.pop(path, None)
        if path in self.selected_files:
            self.selected_files.remove(path)

        self._update_summary()
        self.files_selected.emit(list(self.selected_files), self.total_duration)

    def _sync_rows_height(self) -> None:
        """Give the scrolled container an explicit minimum height matching the
        rows it holds.

        A setMinimumHeight on each row is not enough on its own.
        setWidgetResizable(True) makes QScrollArea call resize() on the
        container to match the viewport, and QWidget.resize() clamps to
        minimumSize(), which defaults to zero - it never consults the
        layout's own minimum. So the container really does get resized to the
        viewport height, and its QVBoxLayout then compresses the rows past
        their own minimums to fit, which is why the list rendered as stacked
        half-height slices of text rather than scrolling. Setting the
        container's minimumSize is what makes that resize refuse to shrink
        below the rows' combined height, which is in turn the condition that
        makes the scroll area show a scrollbar at all.
        """
        rows = len(self._rows)
        if not rows:
            self._rows_container.setMinimumHeight(0)
            return
        spacing = self._rows_layout.spacing() * (rows - 1)
        self._rows_container.setMinimumHeight(rows * ROW_MIN_HEIGHT + spacing)

    def _update_summary(self) -> None:
        self._sync_rows_height()
        # The row list only earns its 54px once there's something in it -
        # see the .hide() call where _rows_scroll is built. Toggled here
        # (the one place both _add_files and _remove_file already funnel
        # through) rather than at each call site.
        self._rows_scroll.setVisible(bool(self.selected_files))
        if not self.selected_files:
            text = t("no_file_selected")
        else:
            total = self.total_duration
            # Separate singular key rather than one template with a count in
            # it: Hebrew changes the verb and the noun together for one file
            # (נבחר קובץ אחד against נבחרו N קבצים), so no single string
            # could have read correctly in both languages at both counts.
            count = len(self.selected_files)
            text = t(
                "files_summary" if count != 1 else "files_summary_one",
                count=count,
                minutes=total // 60,
                seconds=total % 60,
            )
        if self._skipped_last_drop:
            # Appended rather than swapped in: the user still needs to see
            # what IS selected, not just what wasn't. Count only, no
            # filenames - this line has little width to spare (see
            # FileSelectStep's module-level layout comments), and "3
            # skipped" already answers the question a vanished file would
            # otherwise raise silently.
            skipped = len(self._skipped_last_drop)
            text = (
                text
                + " "
                + t("files_skipped" if skipped != 1 else "files_skipped_one", count=skipped)
            )
        self.summary_label.setText(text)

    def reset(self):
        """Clear every selected file and restore the placeholder label."""
        for row in self._rows.values():
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self._durations.clear()
        self.selected_files.clear()
        self._skipped_last_drop = []
        self._update_summary()
        # Every remove button just went away, so the tab-order chain (see
        # _add_row) has to restart from the drop zone too, or the next
        # file added would try to chain onto a widget mid-deleteLater().
        self._last_tab_widget = self.drop_zone

    def showEvent(self, event) -> None:
        """Seed a sensible Tab starting point whenever this step becomes
        visible: the drop zone, since it's both the first thing on the page
        and, on a fresh run, the only way to make any progress at all (see
        DropZone's docstring in gui/widgets.py).

        This does NOT paint a focus ring by itself - gui/focus.py's
        KeyboardFocusTracker only stamps the ring while keyboard modality
        is active, and setFocus() here runs regardless of how the step
        became visible (including the very first launch, before the user
        has touched a key at all), so the ring stays invisible until an
        actual Tab press earns it.
        """
        super().showEvent(event)
        self.drop_zone.setFocus(Qt.OtherFocusReason)

    def retranslate(self):
        """Re-render all text in the current UI language (live toggle)."""
        self.file_heading.setText(t("select_audio_file"))
        self.main_text.setText(t("drop_main"))
        self.formats_text.setText(t("drop_formats"))
        self.alt_text.setText(t("drop_alt"))
        for key, label in self._hw_header_labels.items():
            label.setText(t(key))
        if self._hw_gpu_value_label is not None and not self._hw_has_gpu:
            self._hw_gpu_value_label.setText(t("hw_no_gpu"))
        for path in self.selected_files:
            self._render_row_label(path)
        self._update_summary()

    def _create_hardware_table(self) -> QFrame:
        """Create a compact tabular system-info display (CPU / RAM / GPU)."""
        card = QFrame()
        card.setObjectName("hardwareCard")
        card.setStyleSheet(theme.hardware_card_qss("hardwareCard"))

        outer = QVBoxLayout(card)
        # Internal padding widened (MD/SM -> LG/MD) for the "elevated and
        # generous" pass - this card sits right under the page's DISPLAY
        # heading and there's vertical room to spend on step 1 (see the
        # room analysis in Spacing's docstring), so a bit more air inside
        # the card reads as intentional rather than merely bigger text.
        outer.setContentsMargins(Spacing.LG, Spacing.MD, Spacing.LG, Spacing.MD)
        outer.setSpacing(Spacing.XS)
        # No in-card header here - the page title above the card already
        # reads "Specs", so a repeated label inside would be redundant.

        # Table: one cell per metric, each with its own header/value split by
        # a divider line, and vertical divider lines between cells - a real
        # row/column grid rather than plain text spread across a bare card.
        hw_info = self.hardware.get_hardware_info()
        self._hw_has_gpu = hw_info["has_gpu"]
        gpu_text = hw_info["gpu_name"] if hw_info["has_gpu"] else t("hw_no_gpu")
        # Header labels are keyed by i18n key so retranslate() can re-render
        # them; the GPU value cell is also tracked because "No GPU" is text.
        self._hw_header_labels = {}
        self._hw_gpu_value_label = None
        columns = [
            ("hw_cpu_cores", str(hw_info["cpu_cores"])),
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

    # Both dividers read COLORS['border'], the decorative hairline, not
    # COLORS['control_border']. They separate cells inside a static table;
    # they are not the edge of anything interactive, so they sit below the
    # 3:1 floor on purpose and should stay quiet. This used to read a
    # 'border_light' key that the Catppuccin repaint folded into
    # control_border, which made these table rules noticeably brighter than
    # they had ever been - a side effect of a compatibility alias, not a
    # decision anyone made.
    @staticmethod
    def _hline() -> QFrame:
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background-color: {COLORS['border']};")
        return line

    @staticmethod
    def _vline() -> QFrame:
        line = QFrame()
        line.setFixedWidth(1)
        line.setStyleSheet(f"background-color: {COLORS['border']};")
        return line
