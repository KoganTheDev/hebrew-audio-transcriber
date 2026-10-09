"""Wizard step indicator: the strip between the header and the stacked
widget naming where the user is in the Select File -> Choose Model ->
Transcribe flow.

It carries each step's name so the step pages themselves don't print a
DISPLAY heading - a stepper naming the steps while the page underneath also
prints its own name is the same fact said twice in the same place.

A status display, not a control: nothing here is focusable or clickable.
Each step is a pill and each gap a connector, both painted by hand because
QSS has no transitions and the current step "breathes". The connectors say
what is next: solid behind you, dashes drifting toward the step you are
about to reach, static dashes beyond that. One looping animation drives
every moving part, and it runs only while the strip is visible and Windows
animation effects are on (see motion.animations_enabled). With it stopped,
every state still reads from color and shape alone.

QHBoxLayout mirrors under RightToLeft, so step 1 lands on the right in
Hebrew with no code here. What the pills and connectors paint inside
themselves has to mirror by hand: the marker's side, and which way the
dashes drift.
"""

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QHideEvent, QPainter, QPaintEvent, QPen, QShowEvent
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QSizePolicy, QWidget

from gui import motion, theme
from gui.i18n import t
from gui.icons import cached_pixmap
from gui.motion import LONG_AGO, ease_out_cubic, mix, now_ms, pop_scale, progress, with_alpha
from gui.step_state import STATUS_KEYS, StepState
from gui.steps import Step
from gui.theme import COLORS, Fonts, Motion, Spacing

# Ordered (Step, i18n-key) pairs. The label text reuses each step's own
# former DISPLAY-heading key - see the module docstring.
_STEP_LABELS = [
    (Step.FILE_SELECT, "specs_title"),
    (Step.MODEL_SELECT, "choose_model"),
    (Step.TRANSCRIPTION, "transcribing_title"),
]

# Pill geometry, from the mockup. The marker slot holds the step number or,
# once done, the check, so every state has the same marker-gap-label shape.
# The marker side gets 2px less padding than the text side: an icon reads
# heavier than text, so equal padding would look lopsided.
_PILL_HEIGHT = 24
_MARKER = 12
_MARKER_GAP = 6
_PAD_MARKER_SIDE = 8
_PAD_TEXT_SIDE = 10
# The done pill is a faint wash of the success color, not a solid fill - a
# solid green pill would outshout the current step.
_DONE_TINT_ALPHA = 0.14
_LINE_WIDTH = 2
_CONNECTOR_MIN_WIDTH = 16


class _StepPill(QWidget):
    """One step: marker (number or check), then the step's name."""

    def __init__(self, number: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.number = number
        self.text = ""
        self.state = StepState.PENDING
        # Clock time this pill became DONE, for the pop and the cross-fade.
        self.since = LONG_AGO
        self._alpha = 1.0
        self.setFont(Fonts.CAPTION_BOLD)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)

    def set_text(self, text: str) -> None:
        self.text = text
        self.updateGeometry()
        self.update()

    def set_alpha(self, alpha: float) -> None:
        self._alpha = alpha
        self.update()

    def sizeHint(self) -> QSize:
        text_w = self.fontMetrics().horizontalAdvance(self.text)
        return QSize(
            _PAD_MARKER_SIDE + _MARKER + _MARKER_GAP + text_w + _PAD_TEXT_SIDE, _PILL_HEIGHT
        )

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        now = now_ms()
        if self.state is StepState.CURRENT:
            body = with_alpha("accent", self._alpha)
            ink = QColor(COLORS["accent_text"])
        elif self.state is StepState.DONE:
            # Cross-fade from the current step's look into the done tint, so
            # the step visibly turns into "finished" instead of swapping.
            f = ease_out_cubic(progress(now, self.since, Motion.CONNECTOR_FILL_MS))
            body = mix(QColor(COLORS["accent"]), with_alpha("success", _DONE_TINT_ALPHA), f)
            ink = mix(QColor(COLORS["accent_text"]), QColor(COLORS["success"]), f)
        else:
            body = QColor(COLORS["surface_hover"])
            ink = QColor(COLORS["text_tertiary"])

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        radius = rect.height() / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(body)
        painter.drawRoundedRect(rect, radius, radius)

        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        h = float(self.height())
        marker_x = self.width() - _PAD_MARKER_SIDE - _MARKER if rtl else _PAD_MARKER_SIDE
        if self.state is StepState.DONE:
            scale = pop_scale(now, self.since)
            painter.save()
            painter.translate(marker_x + _MARKER / 2, h / 2)
            painter.scale(scale, scale)
            painter.drawPixmap(
                QPointF(-_MARKER / 2, -_MARKER / 2),
                cached_pixmap("check", _MARKER, COLORS["success"], self.devicePixelRatioF()),
            )
            painter.restore()
        else:
            painter.setPen(ink)
            painter.drawText(
                QRectF(marker_x, 0, _MARKER, h), Qt.AlignmentFlag.AlignCenter, str(self.number)
            )

        if rtl:
            text_rect = QRectF(_PAD_TEXT_SIDE, 0, marker_x - _MARKER_GAP - _PAD_TEXT_SIDE, h)
            align = Qt.AlignmentFlag.AlignRight
        else:
            text_left = marker_x + _MARKER + _MARKER_GAP
            text_rect = QRectF(text_left, 0, self.width() - _PAD_TEXT_SIDE - text_left, h)
            align = Qt.AlignmentFlag.AlignLeft
        painter.setPen(ink)
        painter.drawText(text_rect, align | Qt.AlignmentFlag.AlignVCenter, self.text)
        painter.end()


class _Connector(QWidget):
    """The line between two pills. CURRENT means "leads to the next step"."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.state = StepState.PENDING
        self.since = LONG_AGO
        self._alpha = 1.0
        self._offset_px = 0.0
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_frame(self, alpha: float, offset_px: float) -> None:
        self._alpha = alpha
        self._offset_px = offset_px
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(_CONNECTOR_MIN_WIDTH, _PILL_HEIGHT)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    @staticmethod
    def _dashed(color: QColor, offset_px: float = 0.0) -> QPen:
        # QPen measures dash lengths and offsets in pen widths, not pixels.
        pen = QPen(color, _LINE_WIDTH, Qt.PenStyle.CustomDashLine)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        pen.setDashPattern([d / _LINE_WIDTH for d in Motion.DASH_PATTERN])
        pen.setDashOffset(offset_px / _LINE_WIDTH)
        return pen

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        y = self.height() / 2
        # Drawn from the side of the step before it toward the step after,
        # so "toward the next step" is the line's own forward direction in
        # both layout directions.
        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        start, end = (float(self.width()), 0.0) if rtl else (0.0, float(self.width()))

        def segment(pen: QPen, a: float, b: float) -> None:
            painter.setPen(pen)
            painter.drawLine(QPointF(a, y), QPointF(b, y))

        if self.state is StepState.DONE:
            f = ease_out_cubic(progress(now_ms(), self.since, Motion.CONNECTOR_FILL_MS))
            mid = start + (end - start) * f
            if f < 1:
                segment(self._dashed(with_alpha("accent", 0.5)), mid, end)
            if f > 0:
                solid = QPen(QColor(COLORS["success"]), _LINE_WIDTH)
                solid.setCapStyle(Qt.PenCapStyle.FlatCap)
                segment(solid, start, mid)
        elif self.state is StepState.CURRENT:
            # A shrinking dash offset slides the pattern forward along the
            # line, toward the next step.
            period = sum(Motion.DASH_PATTERN)
            segment(
                self._dashed(with_alpha("accent", self._alpha), -self._offset_px % period),
                start,
                end,
            )
        else:
            segment(self._dashed(QColor(COLORS["text_disabled"])), start, end)
        painter.end()


class StepIndicator(QFrame):
    """Three step pills joined by connectors - see the module docstring."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(theme.frame_bg_qss("bg_secondary"))
        self._current_step = Step.FILE_SELECT
        # Index of the current pill; len(_STEP_LABELS) means "all done".
        self._index: int | None = None

        layout = QHBoxLayout(self)
        # Horizontal margins match the step pages' own side margin, so the
        # pills line up with the content they describe. Spacing.SM top and
        # bottom keeps the strip off the header's accent divider.
        layout.setContentsMargins(Spacing.XXL, Spacing.SM, Spacing.XXL, Spacing.SM)
        layout.setSpacing(Spacing.SM)

        self._pills: list[_StepPill] = []
        self._connectors: list[_Connector] = []
        for i in range(len(_STEP_LABELS)):
            pill = _StepPill(i + 1)
            layout.addWidget(pill)
            self._pills.append(pill)
            if i < len(_STEP_LABELS) - 1:
                connector = _Connector()
                layout.addWidget(connector, 1)
                self._connectors.append(connector)

        self._breath = motion.breath_loop(self)
        self._breath.valueChanged.connect(self._paint_frame)

        self.set_current(Step.FILE_SELECT)

    def set_current(self, step: Step) -> None:
        """Show `step` as the current one."""
        self._current_step = step
        self._show_index([s for s, _ in _STEP_LABELS].index(step))

    def set_complete(self) -> None:
        """Show every step as done - the run has finished."""
        self._show_index(len(_STEP_LABELS))

    def retranslate(self) -> None:
        """Re-render label text and per-state accessible names (live language toggle)."""
        for pill, (_, key) in zip(self._pills, _STEP_LABELS):
            pill.set_text(t(key))
            name = f"{t(key)} - {t(STATUS_KEYS[pill.state])}"
            pill.setAccessibleName(name)
        self._paint_frame()

    def is_animating(self) -> bool:
        return motion.is_running(self._breath)

    def _show_index(self, index: int) -> None:
        # Moving forward animates the steps it completes; moving back, or
        # anything while the loop is off, just snaps.
        animate = self._index is not None and index > self._index and self.is_animating()
        now = now_ms()

        def place(item: _StepPill | _Connector, i: int) -> None:
            state = (
                StepState.DONE
                if i < index
                else StepState.CURRENT
                if i == index
                else StepState.PENDING
            )
            if state is StepState.DONE and item.state is not StepState.DONE:
                item.since = now if animate else LONG_AGO
            item.state = state

        for i, pill in enumerate(self._pills):
            place(pill, i)
        for i, connector in enumerate(self._connectors):
            place(connector, i)
        self._index = index
        self.retranslate()

    def _paint_frame(self, value: object = None) -> None:
        if self.is_animating():
            alpha = motion.pulse_alpha(float(self._breath.currentValue()))
            offset = now_ms() / 1000 * Motion.DASH_SPEED_PX_S
        else:
            alpha, offset = 1.0, 0.0
        for pill in self._pills:
            pill.set_alpha(alpha)
        for connector in self._connectors:
            connector.set_frame(alpha, offset)

    def showEvent(self, a0: QShowEvent | None) -> None:
        super().showEvent(a0)
        if motion.animations_enabled() and not self.is_animating():
            self._breath.start()

    def hideEvent(self, a0: QHideEvent | None) -> None:
        # Also fires when the window is minimized, so a minimized app isn't
        # repainting a strip nobody can see.
        super().hideEvent(a0)
        self._breath.stop()
        self._paint_frame()
