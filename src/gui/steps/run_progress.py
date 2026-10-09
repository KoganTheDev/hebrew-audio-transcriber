"""Step 3's progress widgets: the bar and the stage checklist.

Both paint themselves and read the time at paint; TranscriptionStep owns the
one animation that asks them to repaint, so they hold no timers of their own.
"""

import time
from enum import Enum

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPaintEvent
from PyQt5.QtWidgets import QProgressBar, QSizePolicy, QWidget

from core.formatting import format_mmss
from gui.i18n import t
from gui.icons import cached_pixmap
from gui.motion import LONG_AGO, ease_out_cubic, mix, now_ms, pop_scale, progress, with_alpha
from gui.step_state import STATUS_KEYS, StepState
from gui.theme import COLORS, Fonts, Motion


class BarMode(Enum):
    IDLE = "idle"
    # No percentage exists yet: a band sweeps the empty groove.
    LOADING = "loading"
    # A gleam travels over the filled part.
    WORKING = "working"
    # The fill turns green.
    DONE = "done"


class RunProgressBar(QProgressBar):
    """A QProgressBar that paints itself, so its fill can shimmer and change
    colour. Still a real QProgressBar: value(), the value animation and
    accessibility all work as before.
    """

    _SHIMMER_BAND = 0.4  # of the groove's width
    _GLEAM_BAND_PX = 90

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setTextVisible(False)
        self.setMinimumHeight(28)
        self.mode = BarMode.IDLE
        # False when the step's animation is off: draw no moving parts, and
        # land on the finished colour at once.
        self.animating = False
        self.done_since = LONG_AGO

    def set_mode(self, mode: BarMode) -> None:
        if mode is BarMode.DONE and self.mode is not BarMode.DONE:
            self.done_since = now_ms() if self.animating else LONG_AGO
        self.mode = mode
        self.update()

    def finish_settled(self) -> bool:
        return progress(now_ms(), self.done_since, Motion.FINISH_MS) >= 1

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        now = now_ms()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        groove = QRectF(self.rect())
        radius = groove.height() / 2
        clip = QPainterPath()
        clip.addRoundedRect(groove, radius, radius)
        painter.setClipPath(clip)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.fillRect(groove, QColor(COLORS["bg_tertiary"]))

        span = self.maximum() - self.minimum()
        fraction = (self.value() - self.minimum()) / span if span > 0 else 0.0
        width = groove.width()
        fill_w = width * max(0.0, min(1.0, fraction))
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft

        def leading_rect(x: float, w: float) -> QRectF:
            # x measured from the leading edge, so RTL fills from the right.
            return QRectF(width - x - w if rtl else x, 0, w, groove.height())

        fill = leading_rect(0, fill_w)
        if fill_w > 0:
            color = QColor(COLORS["accent"])
            if self.mode is BarMode.DONE:
                f = ease_out_cubic(progress(now, self.done_since, Motion.FINISH_MS))
                color = mix(color, QColor(COLORS["success"]), f)
            painter.setBrush(color)
            r = min(radius, fill_w / 2)
            painter.drawRoundedRect(fill, r, r)

        if self.animating and self.mode is BarMode.LOADING:
            band = width * self._SHIMMER_BAND
            phase = (now % Motion.SHIMMER_MS) / Motion.SHIMMER_MS
            self._band(painter, leading_rect(-band + phase * (width + band), band), "accent", 0.24)
        elif self.animating and self.mode is BarMode.WORKING and fill_w > 0:
            band = self._GLEAM_BAND_PX
            travel = fill_w + band
            x = (now / 1000 * Motion.GLEAM_SPEED_PX_S) % travel - band
            painter.setClipRect(fill, Qt.ClipOperation.IntersectClip)
            self._band(painter, leading_rect(x, band), "#ffffff", 0.38)
        painter.end()

    @staticmethod
    def _band(painter: QPainter, rect: QRectF, color: str, peak: float) -> None:
        """A soft vertical band: transparent at both edges, `peak` alpha mid-way."""
        base = QColor(COLORS.get(color, color))
        gradient = QLinearGradient(rect.left(), 0, rect.right(), 0)
        for stop, alpha in ((0.0, 0.0), (0.5, peak), (1.0, 0.0)):
            c = QColor(base)
            c.setAlphaF(alpha)
            gradient.setColorAt(stop, c)
        painter.fillRect(rect, gradient)


class Stage(Enum):
    LOAD = "stage_loading_model"
    TRANSCRIBE = "stage_transcribing"
    SPEAKERS = "stage_speakers"
    FINISH = "stage_finishing"


_INK = {
    StepState.CURRENT: COLORS["text_primary"],
    StepState.DONE: COLORS["text_secondary"],
    StepState.PENDING: COLORS["text_tertiary"],
}


class StageChecklist(QWidget):
    """One row per stage: marker, name, and how long it took.

    The times are the GUI's own clock between stage changes, which happen
    on the worker's phase reports - measured, never predicted. A stage the
    run passed straight through (a two-speaker channel split has no separate
    speaker pass) gets its check but no time, since none was spent there.
    """

    ROW_HEIGHT = 26
    ROW_GAP = 2
    WIDTH = 260
    _PAD = 10
    _MARKER = 12
    _GAP = 8
    _DOT = 8

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.setFont(Fonts.CAPTION_BOLD)
        self.stages: list[Stage] = []
        self.active: Stage | None = None
        self.finished = False
        self._spent: dict[Stage, float] = {}
        self._active_since = 0.0
        self._done_since: dict[Stage, float] = {}
        self.animating = False
        self.breath_alpha = 1.0
        # Seconds, for the stage times; swappable so tests can drive it.
        self.clock = time.monotonic

    def reset(self, stages: list[Stage]) -> None:
        self.stages = list(stages)
        self.active = None
        self.finished = False
        self._spent = {}
        self._done_since = {}
        self.updateGeometry()
        self._refresh_accessible()
        self.update()

    def enter(self, stage: Stage) -> None:
        """Make `stage` the running one, closing the clock on the previous."""
        if stage is self.active or stage not in self.stages:
            return
        now = self.clock()
        self._close_active(now)
        self.active = stage
        self._active_since = now
        # Stages left behind tick over to done - pop their checks.
        for s in self.stages[: self.stages.index(stage)]:
            self._done_since.setdefault(s, now_ms() if self.animating else LONG_AGO)
        # Re-entering an earlier stage (the next file of a batch) makes the
        # stages after it pending again until the run reaches them.
        for s in self.stages[self.stages.index(stage) :]:
            self._done_since.pop(s, None)
        self._refresh_accessible()
        self.update()

    def finish(self) -> None:
        self._close_active(self.clock())
        self.active = None
        self.finished = True
        for s in self.stages:
            self._done_since.setdefault(s, LONG_AGO)
        self._refresh_accessible()
        self.update()

    def _close_active(self, now: float) -> None:
        if self.active is not None:
            self._spent[self.active] = self._spent.get(self.active, 0.0) + (
                now - self._active_since
            )

    def state_of(self, stage: Stage) -> StepState:
        if self.finished:
            return StepState.DONE
        if self.active is None:
            return StepState.PENDING
        i, a = self.stages.index(stage), self.stages.index(self.active)
        if i < a:
            return StepState.DONE
        return StepState.CURRENT if i == a else StepState.PENDING

    def seconds_in(self, stage: Stage) -> float | None:
        spent = self._spent.get(stage)
        if stage is self.active:
            return (spent or 0.0) + (self.clock() - self._active_since)
        return spent

    def _refresh_accessible(self) -> None:
        parts = [f"{t(s.value)} - {t(STATUS_KEYS[self.state_of(s)])}" for s in self.stages]
        self.setAccessibleName(t("stages_name"))
        self.setAccessibleDescription(", ".join(parts))

    def retranslate(self) -> None:
        self._refresh_accessible()
        self.update()

    def sizeHint(self) -> QSize:
        n = len(self.stages)
        return QSize(self.WIDTH, n * self.ROW_HEIGHT + max(0, n - 1) * self.ROW_GAP)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        w = float(self.width())
        now = now_ms()
        caption = Fonts.CAPTION

        for i, stage in enumerate(self.stages):
            top = i * (self.ROW_HEIGHT + self.ROW_GAP)
            row = QRectF(0, top, w, self.ROW_HEIGHT)
            state = self.state_of(stage)
            cy = top + self.ROW_HEIGHT / 2

            if state is StepState.CURRENT:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(COLORS["bg_tertiary"]))
                painter.drawRoundedRect(row, 10, 10)

            marker_x = w - self._PAD - self._MARKER if rtl else self._PAD
            mx = marker_x + self._MARKER / 2
            if state is StepState.DONE:
                scale = pop_scale(now, self._done_since.get(stage, LONG_AGO))
                painter.save()
                painter.translate(mx, cy)
                painter.scale(scale, scale)
                painter.drawPixmap(
                    QPointF(-self._MARKER / 2, -self._MARKER / 2),
                    cached_pixmap(
                        "check", self._MARKER, COLORS["success"], self.devicePixelRatioF()
                    ),
                )
                painter.restore()
            else:
                dot = (
                    with_alpha("accent", self.breath_alpha)
                    if state is StepState.CURRENT
                    else QColor(COLORS["surface_hover"])
                )
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(dot)
                painter.drawEllipse(QPointF(mx, cy), self._DOT / 2, self._DOT / 2)

            ink = _INK[state]
            label_w = w - 2 * self._PAD - self._MARKER - self._GAP
            if rtl:
                label = QRectF(self._PAD, top, label_w, self.ROW_HEIGHT)
                label_align = Qt.AlignmentFlag.AlignRight
                time_align = Qt.AlignmentFlag.AlignLeft
            else:
                label = QRectF(self._PAD + self._MARKER + self._GAP, top, label_w, self.ROW_HEIGHT)
                label_align = Qt.AlignmentFlag.AlignLeft
                time_align = Qt.AlignmentFlag.AlignRight
            painter.setFont(self.font())
            painter.setPen(QColor(ink))
            painter.drawText(label, label_align | Qt.AlignmentFlag.AlignVCenter, t(stage.value))

            seconds = self.seconds_in(stage)
            if seconds is not None and (state is not StepState.DONE or seconds >= 0.5):
                painter.setFont(caption)
                painter.setPen(QColor(COLORS["text_tertiary"]))
                painter.drawText(
                    label, time_align | Qt.AlignmentFlag.AlignVCenter, format_mmss(seconds)
                )
        painter.end()
