"""Step 3: transcription progress, live status, and completion result."""

import logging
import os
import time
import webbrowser
from pathlib import Path

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QFontMetrics, QResizeEvent
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from speech_to_text.core.formatting import format_mmss
from speech_to_text.core.progress_scale import STATUS_ONLY_PERCENT
from speech_to_text.gui import theme
from speech_to_text.gui.i18n import t
from speech_to_text.gui.icons import ICONS, svg_to_pixmap
from speech_to_text.gui.theme import COLORS, Fonts, Spacing
from speech_to_text.gui.widgets import IconTextButton, make_label

logger = logging.getLogger(__name__)


class TranscriptionStep(QFrame):
    """Step 3: Transcription progress and results."""

    # Once this many seconds pass with no real percentage movement, the
    # elapsed*(100-pct)/pct projection is stale (it was only ever valid for
    # the pace measured up to the last real update) and left unchecked
    # balloons into an obviously-wrong, ever-growing number. Switch to an
    # honest "calculating..." instead of trusting it past this point.
    STALL_SECONDS = 5

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(theme.frame_bg_qss("bg_primary"))

        layout = self._build_page_layout()

        # No page title here any more - "Transcribing" is now carried by
        # the wizard step indicator above the stacked widget (see
        # gui/stepper.py). File info becomes the first thing on the page.
        self._build_file_info(layout)
        self._build_batch_strip(layout)

        layout.addSpacing(Spacing.LG)

        self._build_progress_bar(layout)
        self._build_status_and_times(layout)

        layout.addSpacing(Spacing.LG)

        self._build_result_panel(layout)

        layout.addStretch()

        self._init_run_state()

    def _build_page_layout(self) -> QVBoxLayout:
        """The page's own QVBoxLayout, spaced and stretched before any child
        goes into it.

        Split out on its own because the two decisions encoded here - a
        deliberately tight blanket spacing, and a stretch at BOTH ends - are
        the ones that every widget added later silently depends on, and both
        were arrived at by measurement rather than taste.
        """
        layout = QVBoxLayout(self)
        # Step 3 has a large empty middle at 650x600 (see the room analysis
        # in theme.Spacing's docstring) - the most slack of any of the
        # three steps - so the outer margin moves up a full notch (XL ->
        # XXL). The blanket inter-widget spacing is deliberately kept
        # tight (SM), NOT bumped the same way: this layout has nine items
        # (title, file info, two explicit addSpacing gaps, progress bar,
        # status, time, the result panel, a trailing stretch), and
        # layout.setSpacing() multiplies across every one of those eight
        # gaps. Measured empirically: at a generous blanket spacing,
        # combined with the taller DISPLAY heading and the result panel's
        # own widened padding, the nine items' minimum height exceeds the
        # 471px this step actually gets (650x600 minus the header and nav
        # bar), and because the layout carries an explicit AlignCenter, Qt
        # doesn't just clip the overflow - it compresses every item below
        # its sizeHint, and any width-dependent label caught in that
        # squeeze (the result panel's path label used to be a wrapped
        # two-line QLabel and is exactly this case - see the comment above
        # its construction for why it no longer wraps) renders as visibly
        # corrupted double-struck glyphs once squeezed below the height its
        # content needs - worse than merely looking cramped. Kept at SM;
        # the two explicit
        # addSpacing() calls below carry the "generous gap before a major
        # section" emphasis instead, since spending space there only costs
        # one gap, not eight.
        layout.setSpacing(Spacing.SM)
        layout.setContentsMargins(Spacing.XXL, Spacing.XXL, Spacing.XXL, Spacing.XXL)
        layout.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs

        # Leading stretch, paired with the trailing one added after
        # result_widget below. With only a trailing stretch, every pixel of
        # slack a resized window hands this step collects at the bottom -
        # the content (and the completion panel especially) stays pinned to
        # the top of the page while an ever-growing dead band opens up
        # underneath it, which is exactly what a "floating in space" bug
        # looks like the moment the window is enlarged rather than left at
        # its default size. Two zero-stretch spacers split whatever slack
        # exists evenly between them instead, so the whole block - file
        # info through the result panel - stays vertically centered as the
        # window grows, which is what layout.setAlignment(Qt.AlignCenter)
        # above was already declaring as the intent; a lone trailing
        # stretch is what had been overriding it in practice.
        layout.addStretch()

        return layout

    def _build_file_info(self, layout: QVBoxLayout) -> None:
        """The "<file> - <model>" line, the first thing on the page."""
        # File info
        self.file_info = make_label(
            font=Fonts.BODY,
            color="text_secondary",
            align=Qt.AlignCenter,  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs
        )
        layout.addWidget(self.file_info)

    def _build_batch_strip(self, layout: QVBoxLayout) -> None:
        """The batch progress strip, plus the state the strip is rebuilt from."""
        # Batch strip: "3 / 10" plus one small segment per file, shown only
        # for a batch (n > 1 - see set_batch_files). A single ten-file run
        # used to have no on-screen answer to "which file is running" beyond
        # whatever text update_progress happened to be showing at that
        # instant; this makes that state a first-class, always-visible part
        # of the page instead of something you had to catch mid-scroll of
        # the status line.
        #
        # Hidden (not just empty) for a single-file run - see
        # set_batch_files - because a one-segment "strip" would just be
        # visual noise repeating what file_info already says. Placed here,
        # joined to file_info and to the progress bar by the layout's
        # ordinary SM inter-item spacing rather than its own explicit
        # addSpacing(): the two existing addSpacing(LG) calls in this
        # layout are reserved for "generous gap before a major section" (see
        # the layout-spacing comment in _build_page_layout) - inserting a
        # third would widen the file_info-to-progress-bar gap for every run,
        # batch or not, not just add room for this one new, usually-hidden
        # widget.
        self.batch_strip = QFrame()
        self.batch_strip.setStyleSheet("background: transparent;")
        batch_layout = QVBoxLayout(self.batch_strip)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(Spacing.XS)

        self.batch_readout = make_label(
            font=Fonts.CAPTION_BOLD,
            color="text_secondary",
            align=Qt.AlignCenter,  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs
        )
        batch_layout.addWidget(self.batch_readout)

        # One QFrame per file, laid out with equal stretch so N segments
        # always fill the same total width regardless of N. A plain
        # QHBoxLayout (not a QFrame() with a layout) - there is no shared
        # border/background to paint around the row itself, just the
        # per-segment frames.
        self._batch_segments_row = QHBoxLayout()
        self._batch_segments_row.setSpacing(Spacing.XS)
        batch_layout.addLayout(self._batch_segments_row)

        layout.addWidget(self.batch_strip)
        self.batch_strip.hide()

        self._batch_filenames: list[str] = []
        self._batch_segment_frames: list[QFrame] = []

    def _build_progress_bar(self, layout: QVBoxLayout) -> None:
        """The progress bar and the animation that smooths its value changes."""
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(theme.progress_bar_qss())
        self.progress_bar.setMinimumHeight(28)
        # The percentage is not drawn inside the bar - see progress_bar_qss()
        # for why no ink is legible over both the filled chunk and the empty
        # groove. Progress is carried by the fill itself plus status_label and
        # time_label below.
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        # Animates value changes instead of snapping instantly - real
        # progress can arrive in uneven bursts (faster-whisper only reports
        # a segment once it's fully decoded, which can include several
        # temperature-retry attempts), so a big jump reads as "catching up"
        # rather than a glitch when it's smoothed over ~500ms.
        self._progress_animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_animation.setDuration(500)
        self._progress_animation.setEasingCurve(QEasingCurve.OutCubic)

    def _build_status_and_times(self, layout: QVBoxLayout) -> None:
        """The two lines under the bar that actually carry the numbers, since
        the bar itself draws no text (see _build_progress_bar).
        """
        # Status and times
        self.status_label = make_label(
            t("w_initializing"),
            font=Fonts.BODY_BOLD_SMALL,
            color="text_primary",
            align=Qt.AlignCenter,  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs
        )
        layout.addWidget(self.status_label)

        # Time info
        self.time_label = make_label(
            font=Fonts.BODY,
            color="text_secondary",
            align=Qt.AlignCenter,  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs
        )
        layout.addWidget(self.time_label)

    def _build_result_panel(self, layout: QVBoxLayout) -> None:
        """The completion panel: checkmark, success message, saved path, and
        the two actions that open it. Hidden until show_result().
        """
        # Result display (hidden until done)
        self.result_widget = QFrame()
        self.result_widget.setObjectName("resultPanel")
        self.result_widget.setStyleSheet(theme.result_panel_qss("resultPanel"))
        # The one drop shadow this redesign keeps (see theme.elevation_shadow
        # for why not more): the result panel is static, never inside a
        # QScrollArea, and step 3's empty middle leaves room for a shadow to
        # actually bleed into without being clipped by a tight parent layout.
        self.result_widget.setGraphicsEffect(theme.elevation_shadow())
        result_layout = QVBoxLayout(self.result_widget)
        result_layout.setSpacing(Spacing.SM)

        # Checkmark icon
        result_icon = QLabel()
        result_pixmap = svg_to_pixmap(
            ICONS["check"], 48, COLORS["success"], dpr=self.devicePixelRatioF()
        )
        result_icon.setPixmap(result_pixmap)
        result_icon.setStyleSheet("background: transparent;")
        result_icon.setAlignment(Qt.AlignCenter)  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs
        result_layout.addWidget(result_icon)

        # Success message
        self.success_msg = make_label(
            t("transcription_complete"),
            font=Fonts.SUBTITLE_BOLD,
            color="success",
            align=Qt.AlignCenter,  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs
        )
        result_layout.addWidget(self.success_msg)

        # File path - caption and path are two separate labels now, not one
        # wrapped two-line string. They used to be a single QLabel with an
        # explicit "\n" and setWordWrap(True), which made the label's height
        # a function of its width (Qt's heightForWidth). That interacted
        # badly with this layout's Qt.AlignCenter (see _build_page_layout's
        # comment and show_result()'s note on the batch-strip removal,
        # the same failure mode caught twice): minimumSizeHint() reported
        # 50px for "Saved to:\n<long path>" at its real width, but the
        # allocated height was 37px - 13px short, with hundreds of spare
        # pixels elsewhere in the panel, so this was never the window being
        # too small. AlignCenter's compression only measures against a
        # child's sizeHint at ITS current width, and a width-dependent
        # sizeHint under a center-aligned layout is exactly the trap that
        # corrupts glyphs; it does not reliably clip cleanly instead.
        #
        # The caption is now a plain, unwrapped, single-line label - fixed
        # text, fixed height, no heightForWidth involved. The path is a
        # second plain label, also single-line and unwrapped, with its text
        # middle-elided in code (_render_result_path) to fit the panel's
        # actual width rather than wrapped to it - so its height depends
        # only on the font's line height, never on its width, and the
        # AlignCenter trap has nothing left to grab onto. The full,
        # unelided path still reaches the user via tooltip and accessible
        # description (set in _render_result_path), and via "Show in
        # folder" / "Open transcript" right below it.
        self.result_saved_caption = make_label(
            t("saved_to_caption"),
            font=Fonts.BODY,
            color="text_secondary",
            align=Qt.AlignCenter,  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs
        )
        result_layout.addWidget(self.result_saved_caption)

        self.result_path = make_label(
            font=Fonts.BODY,
            color="text_secondary",
            align=Qt.AlignCenter,  # type: ignore[attr-defined]  # Qt.AlignmentFlag in the stubs
        )
        self.result_path.setWordWrap(False)
        result_layout.addWidget(self.result_path)

        result_layout.addLayout(self._build_result_actions_row())

        self.result_widget.hide()
        layout.addWidget(self.result_widget)

    def _build_result_actions_row(self) -> QHBoxLayout:
        """The "Open transcript" / "Show in folder" pair, centered by a
        stretch on either side.
        """
        # The output stopped being a text file and became a small application:
        # it is editable, it names speakers, it exports. Ending the run by
        # printing a path and leaving the user to find it in Explorer wastes
        # that. The button opens it in the default browser, which is where it
        # is meant to be read.
        open_row = QHBoxLayout()
        open_row.setSpacing(Spacing.SM)
        open_row.addStretch()
        self.open_button = IconTextButton()
        self.open_button.setText(t("open_transcript"))
        self.open_button.set_icon_spec("file", "left")
        self.open_button.set_text_colors(COLORS["bg_primary"], disabled=COLORS["text_tertiary"])
        self.open_button.setStyleSheet(theme.button_primary_qss())
        self.open_button.setCursor(Qt.PointingHandCursor)  # type: ignore[attr-defined]  # Qt.CursorShape
        self.open_button.clicked.connect(self._open_result)
        open_row.addWidget(self.open_button)

        # Secondary to "Open transcript" - the transcript is the thing you
        # came here for, so it stays the primary/filled action; revealing
        # the folder is the thing people reach for right after (attach the
        # file elsewhere, copy it, check it actually landed where expected)
        # so it gets button_secondary_qss rather than a second filled
        # button competing for the same attention.
        self.folder_button = IconTextButton()
        self.folder_button.setText(t("show_in_folder"))
        self.folder_button.set_icon_spec("folder", "left")
        self.folder_button.set_text_colors(COLORS["text_primary"], hover=COLORS["accent"])
        self.folder_button.setStyleSheet(theme.button_secondary_qss())
        self.folder_button.setCursor(Qt.PointingHandCursor)  # type: ignore[attr-defined]  # Qt.CursorShape
        self.folder_button.clicked.connect(self._open_folder)
        open_row.addWidget(self.folder_button)

        open_row.addStretch()
        return open_row

    def _init_run_state(self) -> None:
        """The non-widget state a run reads and writes, plus the heartbeat
        timer that keeps the page moving between backend messages.
        """
        self.start_time: float | None = None
        self._last_percentage = 0
        self._last_percent_change_time: float | None = None
        # Status text is stored as an i18n key + params (not rendered text)
        # so a mid-run language toggle can re-render the live status.
        self._status_key = "w_initializing"
        self._status_params: dict[str, object] = {}
        # (filename, model) once a run starts
        self._file_info_args: tuple[str, str] | None = None
        self._result_path_value: str | None = None
        self._dot_phase = 0
        # Ticks once a second so the elapsed/remaining time and a "still
        # working" heartbeat keep moving even during real backend gaps with
        # no new progress message (e.g. while the model is still loading, or
        # a long segment is still being decoded) - otherwise the UI looks
        # frozen even though work is genuinely happening in the background
        # process.
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def set_file_info(self, filename: str, model: str) -> None:
        """Set file and model info for display."""
        self._file_info_args = (filename, model)
        self.file_info.setText(t("file_model_info", filename=filename, model=model.title()))

    def set_batch_files(self, filenames: list[str]) -> None:
        """(Re)build the batch strip's segments from the GUI's own selected-
        file list - called once, when a run starts (see
        MainWindow._start_transcription), NOT derived from the worker's
        w_file_progress messages.

        This matters because w_file_progress only ever names the file
        CURRENTLY running ({"i", "n", "name"} - see core/worker.py); if
        segment tooltips were populated one at a time as each file's
        message arrived, every segment except the current one would show
        no filename at all until its own turn came up. MainWindow already
        holds the full list in self.selected_files from step 1, so passing
        it in here up front means every segment - done, current, and still-
        pending - has its real filename from the very first paint.

        Hidden for n <= 1 (see the layout comment above self.batch_strip):
        for a single file, file_info's own text already names it, so a
        one-segment strip would only repeat that.
        """
        self._batch_filenames = list(filenames)

        # Tear down any segments from a previous run before rebuilding -
        # set_batch_files can be called more than once per process (a
        # second file batch after "New File"), and stale QFrames left in
        # the row would just accumulate.
        while self._batch_segments_row.count():
            item = self._batch_segments_row.takeAt(0)
            # takeAt() is Optional: count() and takeAt() are separate calls,
            # so nothing in the type system ties one to the other. Stopping
            # is the only safe response - continuing would spin forever on a
            # count that never drops.
            if item is None:
                break
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._batch_segment_frames = []

        if len(self._batch_filenames) <= 1:
            self.batch_strip.hide()
            return

        for name in self._batch_filenames:
            segment = QFrame()
            # A fixed literal, not one of the named Spacing/Radius tokens -
            # these segments are a new, much smaller kind of element (a
            # progress tick, not a control or a panel) that none of the
            # existing scales were sized for. 6px is tall enough to read as
            # a distinct filled/empty mark at the strip's compact width,
            # short enough that ten of them plus the readout label stay
            # well inside step 3's spare vertical budget.
            segment.setFixedHeight(6)
            segment.setToolTip(name)
            segment.setAccessibleName(name)
            self._batch_segments_row.addWidget(segment)
            self._batch_segment_frames.append(segment)

        # Sensible default before the worker's first w_file_progress message
        # for file 1 arrives (which happens almost immediately, but not
        # instantly) - the strip should never paint with every segment
        # pending, which would look broken rather than merely "about to
        # start".
        self.batch_readout.setText(t("batch_progress_readout", i=1, n=len(self._batch_filenames)))
        self._paint_batch_segments(current_index=1)
        self.batch_strip.show()

    def _paint_batch_segments(self, current_index: int) -> None:
        """Repaint every segment for `current_index` (1-based) being the file
        now running. Segments before it are done, the one at it is current,
        everything after is still pending.

        Deliberately only three states. The worker has no channel back to
        the GUI for "this particular file failed" mid-batch - a failed file
        is recorded in the output document itself (file_failed_notice) and
        the batch continues past it (see core/worker.py) - so a fourth
        "failed" segment state would have nothing real to drive it. Showing
        one anyway (e.g. guessing from the next w_file_progress arriving
        "too fast") would be inventing a signal the worker never sent,
        which is worse than the strip honestly not knowing.
        """
        for index, segment in enumerate(self._batch_segment_frames, start=1):
            if index < current_index:
                fill, border = COLORS["success"], COLORS["success"]
            elif index == current_index:
                fill, border = COLORS["accent"], COLORS["accent"]
            else:
                fill, border = "transparent", COLORS["border"]
            segment.setStyleSheet(
                f"background-color: {fill}; border: {theme.Border.HAIRLINE}px solid {border};"
            )

    def start(self) -> None:
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

    def stop(self) -> None:
        """Stop the elapsed-time ticker (run finished, failed, or was cancelled)."""
        self._timer.stop()

    def _tick(self) -> None:
        if self.start_time is None:
            return
        # Cycle a trailing "", ".", "..", "..." suffix on the status text as
        # a heartbeat - visible proof the app is alive even when the backend
        # hasn't sent a new message this second.
        self._dot_phase = (self._dot_phase + 1) % 4
        self.status_label.setText(self._render_status().rstrip(".") + "." * self._dot_phase)
        self._refresh_time_label(time.time() - self.start_time)

    def _render_status(self) -> str:
        return t(self._status_key, **self._status_params)

    def update_progress(self, status_key: str, params: dict[str, object], percentage: int) -> None:
        """Update status text and, for real percentage updates, the progress
        bar and elapsed/estimated-remaining time.

        status_key/params identify an i18n message (rendered here, in the
        current UI language - the worker only ever sends keys).

        percentage == STATUS_ONLY_PERCENT is a status-only sentinel (see
        TranscriptionThread._relay_progress_message): faster-whisper is
        doing real work - decoding a segment, retrying it at a different
        temperature - but we don't have a new, trustworthy percentage yet,
        so only the descriptive text is updated; the bar and ETA are left
        exactly where they were.
        """
        self._status_key = status_key
        self._status_params = dict(params)
        self._dot_phase = 0
        self.status_label.setText(self._render_status())

        # w_file_progress is the one worker message that names which file
        # in the batch is running (see core/worker.py) - route it to the
        # batch strip in addition to the status line above. Guarded on the
        # strip actually being visible: set_batch_files() already hid it
        # for n <= 1, and a stray message with an out-of-range "i" (there
        # shouldn't be one, but this is a public method fed by an external
        # process) would otherwise index past _batch_segment_frames.
        if status_key == "w_file_progress" and not self.batch_strip.isHidden():
            i, n = params.get("i"), params.get("n")
            if isinstance(i, int) and isinstance(n, int) and n == len(self._batch_segment_frames):
                self.batch_readout.setText(t("batch_progress_readout", i=i, n=n))
                self._paint_batch_segments(current_index=i)

        if percentage != STATUS_ONLY_PERCENT:
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
        """Recompute elapsed + estimated-remaining from the last known progress
        percentage. Called both on every real progress update and on every
        1-second tick, so "Est. remaining" stays visible and keeps counting
        down throughout the whole run instead of only appearing momentarily
        each time a backend message arrives.

        If the percentage hasn't moved in a while (STALL_SECONDS), the
        elapsed*(100-pct)/pct projection is no longer trustworthy - it was
        only ever a snapshot of the pace up to the last real update, and
        without correction it balloons the longer a single hard-to-decode
        segment takes. Showing "calculating..." is more honest than a
        confidently-wrong, ever-growing number.
        """
        percentage = self._last_percentage
        since_last_change = (
            elapsed
            if self._last_percent_change_time is None
            else time.time() - self._last_percent_change_time
        )

        if percentage <= 0:
            self.time_label.setText(t("elapsed", elapsed=format_mmss(elapsed)))
        elif since_last_change > self.STALL_SECONDS:
            self.time_label.setText(
                t(
                    "elapsed_remaining",
                    elapsed=format_mmss(elapsed),
                    remaining=t("calculating"),
                )
            )
        else:
            # Simple linear projection from work done so far.
            remaining = elapsed * (100 - percentage) / percentage
            self.time_label.setText(
                t(
                    "elapsed_remaining",
                    elapsed=format_mmss(elapsed),
                    remaining=format_mmss(remaining),
                )
            )

    def show_result(self, file_path: str) -> None:
        """Show completion result."""
        self._result_path_value = os.path.abspath(file_path)
        # "Which file is running" stops being a meaningful question once
        # the whole batch is done - and, measured empirically, leaving the
        # batch strip up here is not just redundant but actively harmful:
        # with a ten-file batch's strip AND the result panel both
        # competing for step 3's fixed 471px, the layout's own minimum
        # height overflowed the allocation by 66px, and AlignCenter
        # responded by squeezing result_path below the height its wrapped
        # "Saved to:\n<path>" text needs - the exact corrupted-label
        # failure mode the layout-spacing comment on this class's __init__
        # already warns about, just triggered by a second widget instead
        # of over-generous spacing. Hiding the strip here, rather than
        # trying to shrink it further, is what keeps the result panel the
        # one thing competing for that space again.
        self.batch_strip.hide()
        self.result_widget.show()
        self._render_result_path()

    def _render_result_path(self) -> None:
        """Render self._result_path_value into result_path as one middle-elided
        line, and put the full path where truncation costs nothing: the
        tooltip and the accessible description. See the comment above
        result_path's construction for why this replaced a wrapped two-line
        label.

        Called from three places - show_result, retranslate (the path's
        Hebrew rendering differs from English, see the RLM anchor on the
        "saved_to" i18n key used for the tooltip/accessible text below), and
        resizeEvent (the elision has to be recomputed whenever the panel's
        available width changes, which a window resize or maximize does) -
        so it always reflects both the current language and the current
        width rather than whatever was true when show_result last ran.
        """
        if self._result_path_value is None:
            return
        path = self._result_path_value
        # result_path.width() is 0 before its first real layout pass (e.g.
        # a test that builds the step but never shows it) - fall back to
        # the panel's own width in that case rather than eliding against
        # zero, which would render as just an ellipsis. Either way this
        # self-corrects on the next real resizeEvent once the widget has an
        # actual width.
        available = self.result_path.width() or self.result_widget.width()
        metrics = QFontMetrics(self.result_path.font())
        self.result_path.setText(
            metrics.elidedText(
                path,
                Qt.ElideMiddle,  # type: ignore[attr-defined]  # Qt.TextElideMode in the stubs
                available,
            )
        )
        full_text = t("saved_to", path=path)
        self.result_path.setToolTip(full_text)
        self.result_path.setAccessibleDescription(full_text)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        """Keep the elided path in sync with the panel's actual width - see
        _render_result_path's docstring. A no-op whenever there is no
        result yet (the guard inside _render_result_path), so this costs
        nothing on every other resize this step sees before a run has
        completed.
        """
        super().resizeEvent(event)
        self._render_result_path()

    def _open_result(self) -> None:
        """Open the finished transcript in the default browser.

        webbrowser rather than os.startfile: the output is HTML, and the
        association for .html is the browser on every platform this runs on,
        while startfile is Windows-only. A failure here is not worth an error
        dialog - the path is on screen either way, so it is logged and the
        user can still open it themselves.
        """
        if not self._result_path_value:
            return
        try:
            webbrowser.open(Path(self._result_path_value).as_uri())
        except Exception as e:
            logger.warning(f"Could not open transcript in a browser: {e}")

    def _open_folder(self) -> None:
        """Reveal the transcript's containing folder in the OS file manager.

        QDesktopServices.openUrl rather than webbrowser: a directory has no
        browser association to hand off to (webbrowser.open on a folder
        path is undefined/unreliable across platforms), whereas
        QDesktopServices asks the OS shell directly to show the path -
        Explorer on Windows, Finder on macOS, whatever the desktop
        environment provides on Linux. Same swallow-and-log handling as
        _open_result and for the same reason: the path is already sitting
        on screen in result_path either way, so a failure here isn't worth
        interrupting the user over.
        """
        if not self._result_path_value:
            return
        try:
            folder = str(Path(self._result_path_value).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception as e:
            logger.warning(f"Could not open containing folder: {e}")

    def retranslate(self) -> None:
        """Re-render all text in the current UI language (live toggle)."""
        self.success_msg.setText(t("transcription_complete"))
        self.result_saved_caption.setText(t("saved_to_caption"))
        self.open_button.setText(t("open_transcript"))
        self.folder_button.setText(t("show_in_folder"))
        self.status_label.setText(self._render_status())
        if self._file_info_args is not None:
            self.set_file_info(*self._file_info_args)
        self._render_result_path()
        if self.start_time is not None:
            self._refresh_time_label(time.time() - self.start_time)
