"""Step 1: file selection with drag-and-drop and a hardware specs table."""

import fnmatch
import glob
import logging
import os

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import (
    QDragEnterEvent,
    QDropEvent,
    QHideEvent,
    QIcon,
    QPaintEvent,
    QShowEvent,
)
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

import config
from gui import theme
from gui.halo import CLEARANCE as HALO_CLEARANCE
from gui.halo import DropZoneHalo
from gui.i18n import t
from gui.icons import ICONS, svg_to_pixmap
from gui.theme import COLORS, Fonts, Spacing
from gui.threads import DurationProbeThread
from gui.widgets import DropZone, make_label
from hardware_detection import HardwareDetector

logger = logging.getLogger(__name__)


def _size_mb(path: str) -> float:
    """A file's size in MB, or 0.0 if it has gone - a file deleted after the
    drop must not raise out of the drop handler.
    """
    try:
        return os.path.getsize(path) / (1024 * 1024)
    except OSError:
        return 0.0


# Minimum height of a single file row, paired with _sync_rows_height().
ROW_MIN_HEIGHT = 26

# The drop zone's folder icon, and the line weight it keeps at that size -
# see _build_drop_zone_contents.
_FOLDER_ICON_PX = 72
_FOLDER_ICON_LINE_PX = 4


class FileSelectStep(QFrame):
    """Step 1: File Selection with drag-and-drop, accepting one or many files."""

    files_selected = pyqtSignal(list, int)  # [file_path, ...], total duration_seconds

    def __init__(self, hardware: HardwareDetector, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.hardware = hardware
        self.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        layout = self._build_page_layout()
        self._build_hardware_section(layout)
        self._build_drop_zone(layout)
        self._build_selected_files_list(layout)
        self._init_selection_state()
        self.halo = DropZoneHalo(self, self.drop_zone)
        self.files_selected.connect(lambda *_: self.halo.set_empty(not self.selected_files))

    def _build_page_layout(self) -> QVBoxLayout:
        """The step's layout: its spacing decides whether the page fits."""
        layout = QVBoxLayout(self)
        # Tight blanket spacing (it multiplies across every gap - at LG this
        # page overflowed by 84 px); deliberate breaks are explicit addSpacing.
        layout.setSpacing(Spacing.XS)
        # Horizontal margins stay generous at XXL - side padding is free
        # here (it doesn't compete with any other widget for vertical room)
        # and is where the "elevated and generous" direction actually reads
        # on this step.
        layout.setContentsMargins(Spacing.XXL, Spacing.XXL, Spacing.XXL, Spacing.XXL)
        return layout

    def _build_hardware_section(self, layout: QVBoxLayout) -> None:
        """The hardware specs table that opens the page (the step's name is in
        the step indicator), plus the break below it.
        """
        # System info table - shown here (above the drop zone) since it's
        # relevant context before the user even picks a file or model.
        hw_table = self._create_hardware_table()
        layout.addWidget(hw_table)
        # Section break: specs table above, file picker below. The one other
        # deliberate gap on this step, same reasoning as the one after the
        # title.
        layout.addSpacing(Spacing.SM)

    def _build_drop_zone(self, layout: QVBoxLayout) -> None:
        """The file picker: a subheading and the clickable drop target."""
        # Subheading for the drop zone below.
        self.file_heading = make_label(
            t("select_audio_file"), font=Fonts.SUBTITLE_BOLD, color="text_primary"
        )
        layout.addWidget(self.file_heading)

        # The drop zone is also the browse button. DropZone adds keyboard
        # support; drag, drop and click are assigned onto the instance, the
        # path TestDropZoneEventPath drives.
        self.drop_zone = DropZone()
        self.drop_zone.setObjectName("dropZone")
        self.drop_zone.setStyleSheet(theme.drop_zone_qss("dropZone", active=False))
        self.drop_zone.setAcceptDrops(True)
        self.drop_zone.setCursor(Qt.CursorShape.PointingHandCursor)
        self.drop_zone.setAccessibleName(t("drop_zone_name"))
        self.drop_zone.setAccessibleDescription(t("drop_zone_desc"))
        self.drop_zone.setToolTip(t("drop_zone_desc"))
        # Assigning handlers is deliberate; mypy flags it twice per handler.
        self.drop_zone.dragEnterEvent = self._drag_enter  # type: ignore[method-assign,assignment]
        self.drop_zone.dragLeaveEvent = lambda a0: self._reset_drop_zone()  # type: ignore[method-assign]
        self.drop_zone.dropEvent = self._drop  # type: ignore[method-assign,assignment]
        self.drop_zone.mousePressEvent = lambda a0: self._browse()  # type: ignore[method-assign]
        self.drop_zone.activated.connect(self._browse)
        # A minimum at the content floor plus a stretch factor, not a fixed
        # height: Qt never compresses below an explicit minimum, so the zone
        # grows into free space and gives it back as the file list fills.
        self.drop_zone.setMinimumHeight(config.GUI_DROP_ZONE_HEIGHT)

        self._build_drop_zone_contents()

        # Keep the halo (gui/halo.py) off the heading and summary line:
        # with the layout's XS gap these make exactly HALO_CLEARANCE.
        layout.addSpacing(HALO_CLEARANCE - Spacing.XS)
        layout.addWidget(self.drop_zone, 1)
        layout.addSpacing(HALO_CLEARANCE - Spacing.XS)

    def _build_drop_zone_contents(self) -> None:
        """The icon and the three lines of prompt text inside the drop zone."""
        drop_layout = QVBoxLayout(self.drop_zone)
        drop_layout.setSpacing(config.GUI_DROP_ZONE_SPACING)
        drop_layout.setContentsMargins(
            config.GUI_DROP_ZONE_PADDING,
            config.GUI_DROP_ZONE_PADDING,
            config.GUI_DROP_ZONE_PADDING,
            config.GUI_DROP_ZONE_PADDING,
        )

        # Tabler's 2-unit line scales with the icon (6px at 72px reads
        # clumsy), so the stroke is thinned to keep the line at 4px.
        icon_px = _FOLDER_ICON_PX
        stroke = _FOLDER_ICON_LINE_PX * 24 / icon_px
        icon_svg = ICONS["folder"].replace('stroke-width="2"', f'stroke-width="{stroke:.3f}"')
        icon_label = QLabel()
        icon_pixmap = svg_to_pixmap(
            icon_svg, icon_px, COLORS["accent"], dpr=self.devicePixelRatioF()
        )
        icon_label.setPixmap(icon_pixmap)
        icon_label.setStyleSheet("background: transparent;")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(icon_label)

        # No maximum heights: caps sized to a misreported font clipped the
        # real text; the natural sizeHint is right.
        self.main_text = make_label(
            t("drop_main"),
            font=Fonts.BODY_BOLD,
            color="text_primary",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        drop_layout.addWidget(self.main_text)

        # Supported formats
        self.formats_text = make_label(
            t("drop_formats"),
            font=Fonts.CAPTION,
            color="text_secondary",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        drop_layout.addWidget(self.formats_text)

        # Alt text
        self.alt_text = make_label(
            t("drop_alt"),
            font=Fonts.CAPTION,
            color="text_tertiary",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        drop_layout.addWidget(self.alt_text)

    def _build_selected_files_list(self, layout: QVBoxLayout) -> None:
        """The summary line and the scrollable list of chosen files."""
        # Selected-files summary line, above the scrollable list.
        self.summary_label = make_label(
            t("no_file_selected"), font=Fonts.BODY, color="text_secondary"
        )
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
        self._rows_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_scroll.setStyleSheet("background: transparent;")
        self._rows_scroll.setMaximumHeight(140)
        # Stretch here as well as on the drop zone: the two share the step's
        # slack, so once files exist the list can grow toward its 140px cap
        # while the drop target gives space back, instead of the drop zone
        # holding everything and pinning the list at its bare minimum.
        layout.addWidget(self._rows_scroll, 1)
        # Hidden until a file is added, so its 54 px minimum costs nothing
        # while empty.
        self._rows_scroll.hide()

        # No trailing addStretch() here: the drop zone above carries the
        # stretch instead, so leftover room inflates the drop target rather
        # than pooling in an invisible spacer at the bottom of the step. Two
        # stretch items would split the slack between them and halve the
        # effect.

    def _init_selection_state(self) -> None:
        """The per-file bookkeeping that starts empty, plus the tab anchor.

        Runs last because _last_tab_widget points at the drop zone, which
        _build_drop_zone has to have created first.
        """
        # Parallel to each other and to the row widgets, all keyed by path -
        # simpler than one struct per file given how small this state is.
        self.selected_files: list[str] = []
        self._durations: dict[str, int] = {}
        # Files PyAV could not open. Their duration is a size-based guess, and
        # they are the ones most likely to fail once transcription starts.
        self._unprobed: set[str] = set()
        # Files whose length is still being read. Their entry in _durations is
        # a placeholder 0 until the probe lands, which is why is_probing gates
        # the Next button: a run started now would weight its progress, and
        # size its time estimate, against durations that are not real yet.
        self._pending: set[str] = set()
        self._probes: list[DurationProbeThread] = []
        self._rows: dict[str, QFrame] = {}
        # Names skipped by the latest drop, shown in the summary until the next
        # drop or reset().
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
        """Per-file durations in selected_files order; 0 for a file still being
        probed (see is_probing).
        """
        return [self._durations.get(path, 0) for path in self.selected_files]

    @property
    def is_probing(self) -> bool:
        """Whether any selected file's length is still being read."""
        return bool(self._pending)

    def _reset_drop_zone(self) -> None:
        """Reset drop zone to its normal (non-drag) styling."""
        self.drop_zone.setStyleSheet(theme.drop_zone_qss("dropZone", active=False))
        self.halo.set_drag_over(False)

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        super().paintEvent(a0)
        self.halo.paint()

    def _drag_enter(self, event: QDragEnterEvent | None) -> None:
        """Accept a drag that carries URLs. Event and mime data are both
        Optional, and a drag with no mime data does happen.
        """
        if event is None:
            return
        mime = event.mimeData()
        if mime is not None and mime.hasUrls():
            event.acceptProposedAction()
            self.drop_zone.setStyleSheet(theme.drop_zone_qss("dropZone", active=True))
            self.halo.set_drag_over(True)

    def _drop(self, event: QDropEvent | None) -> None:
        self._reset_drop_zone()
        if event is None:
            return
        mime = event.mimeData()
        if mime is None:
            return
        paths = []
        # Names skipped on THIS drop specifically, not a running total - see
        # _update_summary. A folder drop is filtered by _expand_directory
        # already (glob only ever matches supported patterns to begin with),
        # so nothing from inside a folder ever lands here; this only ever
        # catches a file dropped directly that isn't one this app can open.
        skipped_names = []
        for url in mime.urls():
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
        """Whether a directly dropped file's name matches SUPPORTED_FORMATS
        (a dropped folder is already filtered by glob).
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

    def _browse(self) -> None:
        file_filter = t("file_dialog_filter") + " (" + " ".join(config.SUPPORTED_FORMATS) + ")"
        file_paths, _ = QFileDialog.getOpenFileNames(self, t("file_dialog_title"), "", file_filter)
        if file_paths:
            self._add_files(file_paths)

    def browse_for_files(self) -> None:
        """Public entry point for the window-level Ctrl+O shortcut (see MainWindow)."""
        self._browse()

    def _add_files(self, paths: list[str]) -> None:
        """Append new files, skipping duplicates. Rows appear at once; lengths
        arrive later from a background probe (DurationProbeThread).
        """
        added = []
        for path in paths:
            if path in self.selected_files:
                continue
            self.selected_files.append(path)
            # A placeholder until the probe lands. Registered now so
            # total_duration and durations stay answerable for every listed
            # file at every moment, rather than only for probed ones.
            self._durations[path] = 0
            self._pending.add(path)
            self._add_row(path)
            added.append(path)

        if added:
            self._start_probe(added)
            self._update_summary()
            self.files_selected.emit(list(self.selected_files), self.total_duration)

    def _start_probe(self, paths: list[str]) -> None:
        """Probe `paths`' lengths on a thread of their own, retired when done."""
        probe = DurationProbeThread(paths)
        probe.probed.connect(self._on_probed)
        probe.finished.connect(lambda: self._retire_probe(probe))
        self._probes.append(probe)
        probe.start()

    def _retire_probe(self, probe: "DurationProbeThread") -> None:
        if probe in self._probes:
            self._probes.remove(probe)
        probe.deleteLater()

    def _on_probed(self, path: str, duration: int, probed: bool) -> None:
        """A length arrived - ignored if the file has since been removed."""
        if path not in self.selected_files:
            return

        self._durations[path] = duration
        self._pending.discard(path)
        if not probed:
            self._unprobed.add(path)

        self._render_row_label(path)
        self._update_summary()
        # Re-emitted per file, not once at the end: the model recommendation
        # and its time estimate are computed from the total, so they should
        # sharpen as the lengths land rather than sit wrong until the last
        # one does.
        self.files_selected.emit(list(self.selected_files), self.total_duration)

    def stop_probing(self) -> None:
        """Abandon in-flight probes and wait for their threads, so no signal
        reaches a half-destroyed widget.
        """
        for probe in list(self._probes):
            probe.probed.disconnect()
            probe.stop()
            probe.wait()
        self._probes.clear()
        self._pending.clear()

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

        label = make_label(font=Fonts.BODY, color="text_secondary")
        label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        row_layout.addWidget(label, 1)

        # Named per file (in _render_row_label), so a screen reader knows
        # which row each remove button belongs to.
        remove_btn = QPushButton()
        remove_btn.setIcon(
            QIcon(
                svg_to_pixmap(ICONS["x"], 14, COLORS["text_tertiary"], dpr=self.devicePixelRatioF())
            )
        )
        remove_btn.setFixedSize(20, 20)
        remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remove_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        # Chain each remove button into the tab order after the previous one,
        # top to bottom; removed rows drop out on their own.
        self.setTabOrder(self._last_tab_widget, remove_btn)
        self._last_tab_widget = remove_btn
        self._render_row_label(path)

    def _render_row_label(self, path: str) -> None:
        row = self._rows.get(path)
        if row is None:
            return
        # row.layout(), itemAt() and widget() are each Optional, and the
        # row is built by _add_row with exactly [icon, label, remove] - so
        # anything missing here means the row was torn down under us, and
        # there is nothing left to render into.
        row_layout = row.layout()
        if row_layout is None:
            return
        label_item = row_layout.itemAt(1)
        remove_item = row_layout.itemAt(2)
        if label_item is None or remove_item is None:
            return
        label = label_item.widget()
        remove_btn = remove_item.widget()
        if not isinstance(label, QLabel) or not isinstance(remove_btn, QPushButton):
            return
        filename = os.path.basename(path)
        if path in self._pending:
            label.setText(t("file_info_probing", filename=filename))
        else:
            duration = self._durations.get(path, 0)
            label.setText(
                t(
                    "file_info",
                    filename=filename,
                    minutes=duration // 60,
                    seconds=duration % 60,
                    size=f"{_size_mb(path):.1f}",
                )
            )
        if path in self._unprobed:
            # Warned, not rejected. A probe failure is not proof that
            # faster-whisper cannot decode the file - PyAV and ffmpeg do not
            # accept exactly the same set of containers - so blocking it would
            # refuse files that work. The point is that the duration shown is
            # a guess and this is the file to suspect if the run fails.
            label.setText("\u26a0 " + label.text())
            label.setToolTip(t("file_unreadable_tip"))
            label.setStyleSheet(theme.text_qss("warn"))

        remove_label = t("remove_file", filename=filename)
        remove_btn.setAccessibleName(remove_label)
        remove_btn.setToolTip(remove_label)

    def _remove_file(self, path: str) -> None:
        row = self._rows.pop(path, None)
        if row is not None:
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._durations.pop(path, None)
        self._unprobed.discard(path)
        self._pending.discard(path)
        if path in self.selected_files:
            self.selected_files.remove(path)

        self._update_summary()
        self.files_selected.emit(list(self.selected_files), self.total_duration)

    def _sync_rows_height(self) -> None:
        """Pin the scrolled container's minimum height to its rows.

        QScrollArea resizes the container to the viewport, and resize() honours
        minimumSize, not the layout's - so without this the rows were squeezed
        into half-height slices instead of scrolling.
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
            # Appended: the selection still shows. A count, since the line has
            # no room for names.
            skipped = len(self._skipped_last_drop)
            text = (
                text
                + " "
                + t("files_skipped" if skipped != 1 else "files_skipped_one", count=skipped)
            )
        self.summary_label.setText(text)

    def reset(self) -> None:
        """Clear every selected file and restore the placeholder label."""
        for row in self._rows.values():
            self._rows_layout.removeWidget(row)
            row.deleteLater()
        self._rows.clear()
        self.stop_probing()
        self._durations.clear()
        self._unprobed.clear()
        self.selected_files.clear()
        self._skipped_last_drop = []
        self._update_summary()
        # Every remove button just went away, so the tab-order chain (see
        # _add_row) has to restart from the drop zone too, or the next
        # file added would try to chain onto a widget mid-deleteLater().
        self._last_tab_widget = self.drop_zone
        self.halo.set_empty(True)

    def showEvent(self, event: QShowEvent | None) -> None:
        """Focus the drop zone, the first Tab stop. No ring until a key is
        actually pressed (gui/focus.py).
        """
        super().showEvent(event)
        self.drop_zone.setFocus(Qt.FocusReason.OtherFocusReason)
        self.halo.sync()

    def hideEvent(self, event: QHideEvent | None) -> None:
        # Also fires when the window is minimized.
        super().hideEvent(event)
        self.halo.sync()

    def retranslate(self) -> None:
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
        self._hw_header_labels: dict[str, QLabel] = {}
        self._hw_gpu_value_label: QLabel | None = None
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

        label_widget = make_label(
            t(label_key),
            font=Fonts.CAPTION,
            color="text_tertiary",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        cell_layout.addWidget(label_widget)
        self._hw_header_labels[label_key] = label_widget

        cell_layout.addWidget(self._hline())

        value_widget = make_label(
            value,
            font=Fonts.BODY_BOLD,
            color="text_primary",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        cell_layout.addWidget(value_widget)
        if label_key == "hw_gpu":
            self._hw_gpu_value_label = value_widget

        return cell

    # The quiet decorative hairline, not control_border: these separate cells
    # in a static table, not the edge of a control.
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
