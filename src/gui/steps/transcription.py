"""Step 3: transcription progress, live status, and completion result."""

import logging
import os
import time
from pathlib import Path

from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, QUrl
from PyQt5.QtGui import QDesktopServices, QFontMetrics, QHideEvent, QResizeEvent, QShowEvent
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from core import browser_open
from core.formatting import format_mmss
from core.progress_scale import (
    STATUS_ONLY_PERCENT,
    WORK_PHASE_DIARIZE_WAIT,
)
from gui import motion, theme
from gui.i18n import t
from gui.icons import ICONS, svg_to_pixmap
from gui.presenters.run_stages import Stage, next_stage, stages_for
from gui.presenters.time_estimate import TimeEstimator
from gui.steps.run_progress import BarMode, RunProgressBar, StageChecklist
from gui.theme import COLORS, Fonts, Motion, Spacing
from gui.threads import PHASE_STARTED_SECONDS
from gui.widgets import IconTextButton, make_label

logger = logging.getLogger(__name__)


class TranscriptionStep(QFrame):
    """Step 3: Transcription progress and results."""

    # After this long with no movement the time label says "calculating" - for
    # a file whose duration could not be probed, which never sends work
    # reports for the estimator to use.
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
        self._build_stage_checklist(layout)

        layout.addSpacing(Spacing.LG)

        self._build_result_panel(layout)

        layout.addStretch()

        self._init_run_state()

    def _build_page_layout(self) -> QVBoxLayout:
        """The page layout: tight blanket spacing and a stretch at both ends,
        both measured choices every later widget depends on.
        """
        layout = QVBoxLayout(self)
        # THE LAYOUT TRAP. Under AlignCenter, Qt answers too little height by
        # squeezing every item below its sizeHint, and a label whose height
        # depends on its width then draws corrupted, double-struck glyphs
        # rather than clipping. So: blanket spacing stays tight (SM - it
        # multiplies across every gap), generous gaps are explicit
        # addSpacing() calls, and nothing here may wrap (see result_path).
        layout.setSpacing(Spacing.SM)
        layout.setContentsMargins(Spacing.XXL, Spacing.XXL, Spacing.XXL, Spacing.XXL)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # Stretches at both ends keep the block centred as the window grows;
        # a trailing one alone pinned it to the top.
        layout.addStretch()

        return layout

    def _build_file_info(self, layout: QVBoxLayout) -> None:
        """The "<file> - <model>" line, the first thing on the page."""
        # File info
        self.file_info = make_label(
            font=Fonts.BODY,
            color="text_secondary",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        layout.addWidget(self.file_info)

    def _build_batch_strip(self, layout: QVBoxLayout) -> None:
        """The batch progress strip, plus the state the strip is rebuilt from."""
        # Batch strip: "3 / 10" and one segment per file, so "which file is
        # running" is always visible. Hidden for a single file (it would only
        # repeat file_info); joined by the plain SM spacing, not its own gap.
        self.batch_strip = QFrame()
        self.batch_strip.setStyleSheet("background: transparent;")
        batch_layout = QVBoxLayout(self.batch_strip)
        batch_layout.setContentsMargins(0, 0, 0, 0)
        batch_layout.setSpacing(Spacing.XS)

        self.batch_readout = make_label(
            font=Fonts.CAPTION_BOLD,
            color="text_secondary",
            align=Qt.AlignmentFlag.AlignCenter,
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
        # Paints itself so the fill can shimmer and turn green; the numbers
        # live in status_label and time_label (see RunProgressBar).
        self.progress_bar = RunProgressBar()
        layout.addWidget(self.progress_bar)

        # Animates value changes instead of snapping instantly - real
        # progress can arrive in uneven bursts (faster-whisper only reports
        # a segment once it's fully decoded, which can include several
        # temperature-retry attempts), so a big jump reads as "catching up"
        # rather than a glitch when it's smoothed over ~500ms.
        self._progress_animation = QPropertyAnimation(self.progress_bar, b"value", self)
        self._progress_animation.setDuration(Motion.PROGRESS_MS)
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
            align=Qt.AlignmentFlag.AlignCenter,
        )
        layout.addWidget(self.status_label)

        # Time info
        self.time_label = make_label(
            font=Fonts.BODY,
            color="text_secondary",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        layout.addWidget(self.time_label)

    def _build_stage_checklist(self, layout: QVBoxLayout) -> None:
        """Which stage the run is in, and how long each took.

        Hidden once the result panel shows: both together outgrow the
        window's minimum height, and the panel already says it is done.
        """
        self.stage_list = StageChecklist()
        layout.addWidget(self.stage_list, 0, Qt.AlignmentFlag.AlignHCenter)
        self.stage_list.hide()

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
        result_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        result_layout.addWidget(result_icon)

        # Success message
        self.success_msg = make_label(
            t("transcription_complete"),
            font=Fonts.SUBTITLE_BOLD,
            color="success",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        result_layout.addWidget(self.success_msg)

        # Caption and path are separate single-line labels, the path elided in
        # code (_render_result_path) - a wrapped label falls into the layout
        # trap in _build_page_layout. The full path is in the tooltip and the
        # accessible description.
        self.result_saved_caption = make_label(
            t("saved_to_caption"),
            font=Fonts.BODY,
            color="text_secondary",
            align=Qt.AlignmentFlag.AlignCenter,
        )
        result_layout.addWidget(self.result_saved_caption)

        self.result_path = make_label(
            font=Fonts.BODY,
            color="text_secondary",
            align=Qt.AlignmentFlag.AlignCenter,
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
        self.open_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.open_button.clicked.connect(self._open_result)
        open_row.addWidget(self.open_button)

        # Secondary styling: opening the transcript is the main action.
        self.folder_button = IconTextButton()
        self.folder_button.setText(t("show_in_folder"))
        self.folder_button.set_icon_spec("folder", "left")
        self.folder_button.set_text_colors(COLORS["text_primary"], hover=COLORS["accent"])
        self.folder_button.setStyleSheet(theme.button_secondary_qss())
        self.folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
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
        # 1-based indices the worker has reported as failed, and which file is
        # running - both needed to repaint the strip, which has to be able to
        # redraw from scratch whenever either changes.
        self._failed_files: set[int] = set()
        self._current_file_index = 1
        # Every measurement this run has made, and the arithmetic over them.
        # Qt-free and in gui/presenters/ on purpose: "how long is left" is a
        # decision, not a widget, and it is testable against a fake clock
        # there rather than only through a live window.
        self._estimator = TimeEstimator()
        # A 1 s tick keeps the clock and a heartbeat moving through gaps with
        # no backend message (model loading, a long segment).
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        # Whether a run is going, and whether it reports a speaker stage.
        self._running = False
        self._identify_speakers = False
        # Set once the run is over: the time label shows "Took" from it.
        self._took_seconds: float | None = None
        # One loop repaints the bar's shimmer/gleam and the checklist's
        # breathing dot; its value is the breath phase. It runs only while
        # this page is visible and Windows animation effects are on.
        self._motion = motion.breath_loop(self)
        self._motion.valueChanged.connect(self._on_motion)

    def set_file_info(self, filename: str, model: str) -> None:
        """Set file and model info for display."""
        self._file_info_args = (filename, model)
        self.file_info.setText(t("file_model_info", filename=filename, model=model.title()))

    def set_batch_files(self, filenames: list[str]) -> None:
        """(Re)build the batch strip from the GUI's own file list, at run start -
        the worker only ever names the current file, so every segment gets its
        filename up front. Hidden for a single file.
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
        self._failed_files = set()
        self._current_file_index = 1

        if len(self._batch_filenames) <= 1:
            self.batch_strip.hide()
            return

        for name in self._batch_filenames:
            segment = QFrame()
            # 6 px: a progress tick, smaller than any Spacing token.
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
        """Paint segments for `current_index` (1-based) running: before it done,
        at it current, after it pending. Failed is checked first, or a failed
        file the run moved past would paint as done.
        """
        for index, segment in enumerate(self._batch_segment_frames, start=1):
            if index in self._failed_files:
                fill, border = COLORS["error"], COLORS["error"]
            elif index < current_index:
                fill, border = COLORS["success"], COLORS["success"]
            elif index == current_index:
                fill, border = COLORS["accent"], COLORS["accent"]
            else:
                fill, border = "transparent", COLORS["border"]
            segment.setStyleSheet(
                f"background-color: {fill}; border: {theme.Border.HAIRLINE}px solid {border};"
            )

    def _reset_batch_segments(self) -> None:
        """Put every segment back to pending, with its plain filename."""
        self._failed_files = set()
        self._current_file_index = 1
        for index, segment in enumerate(self._batch_segment_frames, start=1):
            name = (
                self._batch_filenames[index - 1]
                if index <= len(self._batch_filenames)
                else str(index)
            )
            segment.setToolTip(name)
            segment.setAccessibleName(name)
        self._paint_batch_segments(current_index=self._current_file_index)

    def mark_file_failed(self, index: int) -> None:
        """Mark file `index` (1-based) failed; the run continues. The name says
        so too (tooltip and screen reader), since colour alone is weak on 6 px.
        """
        if not 1 <= index <= len(self._batch_segment_frames):
            return
        self._failed_files.add(index)

        segment = self._batch_segment_frames[index - 1]
        name = (
            self._batch_filenames[index - 1] if index <= len(self._batch_filenames) else str(index)
        )
        # Reuses the notice the transcript itself carries for a failed file,
        # rather than a second string saying the same thing in two places.
        failed = f"{name} - {t('file_failed_notice')}"
        segment.setToolTip(failed)
        segment.setAccessibleName(failed)

        self._paint_batch_segments(current_index=self._current_file_index)

    def start(self, identify_speakers: bool = False) -> None:
        """Reset the display for a fresh run and start the elapsed-time ticker."""
        self.start_time = time.time()
        self._running = True
        self._identify_speakers = identify_speakers
        self._took_seconds = None
        self.stage_list.reset(stages_for(identify_speakers))
        self.progress_bar.set_mode(BarMode.IDLE)
        self._set_motion(True)
        self._enter_stage(Stage.LOAD)
        self.stage_list.show()
        self._estimator = TimeEstimator()
        # Repaint too, or segments keep last run's failed colour and name.
        self._reset_batch_segments()
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
        self._running = False
        self._set_motion(False)

    def _set_motion(self, on: bool) -> None:
        on = on and motion.animations_enabled()
        self.progress_bar.set_motion(on)
        self.stage_list.set_motion(on)
        if on and not self.is_animating():
            self._motion.start()
        elif not on:
            self._motion.stop()
        self.progress_bar.update()
        self.stage_list.update()

    def is_animating(self) -> bool:
        return motion.is_running(self._motion)

    def _on_motion(self, value: object) -> None:
        self.stage_list.set_breath(motion.pulse_alpha(float(self._motion.currentValue())))
        self.progress_bar.update()
        self.stage_list.update()
        # After the run, the loop only stays on to play the bar's finish.
        if not self._running and self.progress_bar.finish_settled():
            self._set_motion(False)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        if self._running or not self.progress_bar.finish_settled():
            self._set_motion(True)

    def hideEvent(self, a0: QHideEvent | None) -> None:
        # Also fires when the window is minimized.
        super().hideEvent(a0)
        self._motion.stop()

    def _enter_stage(self, stage: Stage) -> None:
        self.stage_list.enter(stage)
        self.progress_bar.set_mode(BarMode.LOADING if stage is Stage.LOAD else BarMode.WORKING)

    def _advance_stage(self, name: str, seconds: float) -> None:
        """Move the checklist on from a phase report - see presenters/run_stages."""
        if not self._running:
            return
        stage = next_stage(
            self.stage_list.active,
            name,
            started=seconds == PHASE_STARTED_SECONDS,
            identify_speakers=self._identify_speakers,
        )
        if stage is not None:
            self._enter_stage(stage)

    def _tick(self) -> None:
        if self.start_time is None:
            return
        # Cycle a trailing "", ".", "..", "..." suffix on the status text as
        # a heartbeat - visible proof the app is alive even when the backend
        # hasn't sent a new message this second.
        self._dot_phase = (self._dot_phase + 1) % 4
        self.status_label.setText(self._render_status().rstrip(".") + "." * self._dot_phase)
        # Keeps the active stage's time counting when the animation is off.
        self.stage_list.update()
        self._refresh_time_label(time.time() - self.start_time)

    def _render_status(self) -> str:
        return t(self._status_key, **self._status_params)

    def update_work(self, audio_done: float, audio_total: float, sent_at: float) -> None:
        """Record audio decoded so far. sent_at is the worker's monotonic clock
        (shared system-wide), keeping queue latency out of the rate.
        """
        self._estimator.note_work(audio_done, audio_total, sent_at)
        if self.start_time is not None:
            self._refresh_time_label(time.time() - self.start_time)

    def update_phase(self, name: str, seconds: float, sent_at: float) -> None:
        """Record a measured phase. Only the diarization wait matters to the
        estimate: other phases fall between audio positions and are already in
        the rate; the wait comes after its file's audio is counted.
        """
        # Any phase at all anchors the rate's clock: the first one to arrive is
        # this batch's first file being decoded or VAD-scanned, which is the
        # moment work on audio actually begins. Before that the run is loading
        # a model, and charging that to audio-seconds would wreck the rate.
        self._estimator.note_work_started(sent_at)
        self._advance_stage(name, seconds)

        if name != WORK_PHASE_DIARIZE_WAIT:
            if self.start_time is not None:
                self._refresh_time_label(time.time() - self.start_time)
            return
        if seconds == PHASE_STARTED_SECONDS:
            self._estimator.note_wait_started(sent_at)
        else:
            self._estimator.note_wait_finished(seconds)
        if self.start_time is not None:
            self._refresh_time_label(time.time() - self.start_time)

    def update_progress(self, status_key: str, params: dict[str, object], percentage: int) -> None:
        """Show a status message (an i18n key, rendered here) and, unless the
        percentage is STATUS_ONLY_PERCENT, move the bar and the clock.
        """
        self._status_key = status_key
        self._status_params = dict(params)
        self._dot_phase = 0
        self.status_label.setText(self._render_status())

        # The estimator needs to know which file is running for the same reason
        # the strip below does, but it is told even when the strip is hidden:
        # a single-file run still has a diarization tail to predict, and the
        # file index is what bounds that file's own audio.
        if status_key == "w_file_progress":
            file_index = params.get("i")
            if isinstance(file_index, int):
                self._estimator.note_file_started(file_index)

        # w_file_progress names the running file - route it to the strip, if
        # shown, ignoring an out-of-range index from the external process.
        if status_key == "w_file_progress" and not self.batch_strip.isHidden():
            i, n = params.get("i"), params.get("n")
            if isinstance(i, int) and isinstance(n, int) and n == len(self._batch_segment_frames):
                self.batch_readout.setText(t("batch_progress_readout", i=i, n=n))
                self._current_file_index = i
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
        """Show elapsed time and the estimate, on every update and every tick.

        Elapsed alone before anything has happened; "calculating" once work is
        under way but no rate exists yet; then the measured estimate (see
        gui/presenters/time_estimate.py).
        """
        if self._took_seconds is not None:
            self.time_label.setText(t("took", elapsed=format_mmss(self._took_seconds)))
            return
        remaining = self._estimator.remaining(time.monotonic())

        if remaining is not None:
            self.time_label.setText(
                t(
                    "elapsed_remaining",
                    elapsed=format_mmss(elapsed),
                    remaining=format_mmss(remaining),
                )
            )
            return

        # No measurement yet. Before anything at all has happened, promising a
        # calculation would be as much of an invention as a number; once the
        # run is visibly under way, saying the estimate is still being worked
        # out is the honest description of exactly what is true.
        since_last_change = (
            elapsed
            if self._last_percent_change_time is None
            else time.time() - self._last_percent_change_time
        )
        under_way = self._last_percentage > 0 or since_last_change > self.STALL_SECONDS
        if not under_way:
            self.time_label.setText(t("elapsed", elapsed=format_mmss(elapsed)))
            return

        self.time_label.setText(
            t(
                "elapsed_remaining",
                elapsed=format_mmss(elapsed),
                remaining=t("calculating"),
            )
        )

    def show_result(self, file_path: str) -> None:
        """Show completion result."""
        self._result_path_value = os.path.abspath(file_path)
        # The strip goes once the batch is done: beside the result panel it
        # overflowed by 66 px and fell into the layout trap.
        self.batch_strip.hide()
        if self.start_time is not None:
            self._took_seconds = time.time() - self.start_time
            self._refresh_time_label(self._took_seconds)
        # The bar turns green; the result panel takes the checklist's place.
        self._set_motion(True)
        self.progress_bar.set_mode(BarMode.DONE)
        self.stage_list.finish()
        self.stage_list.hide()
        self.result_widget.show()
        self._render_result_path()

    def _render_result_path(self) -> None:
        """The result path as one middle-elided line, the full path in the
        tooltip and accessible description. Re-run on language change and
        resize, since both change the elision.
        """
        if self._result_path_value is None:
            return
        path = self._result_path_value
        # Width is 0 before the first layout; use the panel's until then.
        available = self.result_path.width() or self.result_widget.width()
        metrics = QFontMetrics(self.result_path.font())
        self.result_path.setText(
            metrics.elidedText(
                path,
                Qt.TextElideMode.ElideMiddle,
                available,
            )
        )
        full_text = t("saved_to", path=path)
        self.result_path.setToolTip(full_text)
        self.result_path.setAccessibleDescription(full_text)

    def resizeEvent(self, event: QResizeEvent | None) -> None:
        """Re-elide the path to the new width (a no-op before a result)."""
        super().resizeEvent(event)
        self._render_result_path()

    def _open_result(self) -> None:
        """Open the transcript in a preferred browser (core/browser_open). A
        failure is only logged - the path is on screen anyway.
        """
        if not self._result_path_value:
            return
        try:
            used = browser_open.open_html(self._result_path_value)
            logger.debug(f"opened transcript with browser: {used}")
        except Exception as e:
            logger.warning(f"Could not open transcript in a browser: {e}", exc_info=True)

    def _open_folder(self) -> None:
        """Show the transcript's folder in the OS file manager (QDesktopServices;
        webbrowser on a folder is unreliable). Failures are only logged.
        """
        if not self._result_path_value:
            return
        try:
            folder = str(Path(self._result_path_value).parent)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception as e:
            logger.warning(f"Could not open containing folder: {e}", exc_info=True)

    def retranslate(self) -> None:
        """Re-render all text in the current UI language (live toggle)."""
        self.success_msg.setText(t("transcription_complete"))
        self.result_saved_caption.setText(t("saved_to_caption"))
        self.open_button.setText(t("open_transcript"))
        self.folder_button.setText(t("show_in_folder"))
        self.status_label.setText(self._render_status())
        self.stage_list.retranslate()
        if self._file_info_args is not None:
            self.set_file_info(*self._file_info_args)
        self._render_result_path()
        if self.start_time is not None:
            self._refresh_time_label(time.time() - self.start_time)
