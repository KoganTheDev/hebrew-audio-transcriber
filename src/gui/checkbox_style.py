"""Painted checkbox indicator, replacing the QSS raster tick.

QSS `image: url(...)` has no device-pixel-ratio support, so the tick was a
14 px raster stretched on scaled displays, and the 24-unit SVG's stroke landed
off-grid (one arm blobbed, the other faded). Painting with QPainter draws at
the real DPR with a stroke sized to the indicator. A QProxyStyle, because the
indicator is a style primitive (PE_IndicatorCheckBox), not a child widget.
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QCheckBox, QProxyStyle, QStyle, QStyleOption, QWidget

from gui.theme import COLORS, Border, Radius


class PaintedCheckboxStyle(QProxyStyle):
    """Draws QCheckBox's indicator (border, fill, tick) itself.

    Installed app-wide in configure_application, so every future checkbox gets
    it without opting in. Wraps the existing style: only PE_IndicatorCheckBox
    and the PM_Indicator* metrics are overridden.
    """

    # Matches the 18x18 box the QSS rule this replaces declared
    # (QCheckBox::indicator { width: 18px; height: 18px; }). Needed as an
    # explicit PM_IndicatorWidth/Height override because nothing else
    # supplies that size now that the QSS rule is gone, and the tick
    # geometry below is expressed as fractions of this box.
    SIZE = 18

    # Stroke as a fraction of the indicator's width, picked by eye from four
    # rendered candidates (0.083 / 0.105 / 0.135 / 0.165).
    _TICK_WEIGHT = 0.165

    def pixelMetric(
        self,
        metric: QStyle.PixelMetric,
        option: QStyleOption | None = None,
        widget: QWidget | None = None,
    ) -> int:
        if metric in (
            QStyle.PixelMetric.PM_IndicatorWidth,
            QStyle.PixelMetric.PM_IndicatorHeight,
        ):
            return self.SIZE
        return super().pixelMetric(metric, option, widget)

    def drawPrimitive(
        self,
        element: QStyle.PrimitiveElement,
        option: QStyleOption | None,
        painter: QPainter | None,
        widget: QWidget | None = None,
    ) -> None:
        if element == QStyle.PrimitiveElement.PE_FrameFocusRect and isinstance(widget, QCheckBox):
            # Swallowed: Qt's dotted focus frame is redundant with the
            # focus-coloured border and reads as an artifact on a dark UI.
            return
        # option/painter are typed Optional because QStyle's C++ signature
        # takes pointers; Qt never delivers null ones for a primitive it is
        # asking to be drawn. Handing anything unexpected straight to the
        # wrapped style is the safe fallback, and is what the non-checkbox
        # path does anyway.
        if (
            element != QStyle.PrimitiveElement.PE_IndicatorCheckBox
            or option is None
            or painter is None
        ):
            super().drawPrimitive(element, option, painter, widget)
            return

        rect = option.rect
        on = bool(option.state & QStyle.StateFlag.State_On)
        enabled = bool(option.state & QStyle.StateFlag.State_Enabled)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        # kbdFocus is gui/focus.py's property; QStyleOption has no such flag,
        # so it is read off the widget.
        kbd_focus = bool(widget is not None and widget.property("kbdFocus"))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Every state spelled out, matching the QSS rules this replaces: a
        # missed state would get no native fallback.
        if not enabled:
            edge = COLORS["text_disabled"] if on else COLORS["border"]
            fill = COLORS["text_disabled"] if on else COLORS["bg_tertiary"]
        elif on:
            edge = COLORS["accent_hover"] if hover else COLORS["accent"]
            fill = edge
        else:
            edge = COLORS["accent_hover"] if hover else COLORS["control_border"]
            fill = COLORS["bg_tertiary"]
        if kbd_focus:
            # Applied last, as the kbdFocus rule was last in the QSS cascade:
            # it overrides only the border colour.
            edge = COLORS["focus"]

        # Half-pixel inset: a pen is centred on its path, so stroking the
        # bounds would clip half the border.
        box = QRectF(rect).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(edge), Border.CONTROL))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(box, Radius.CHECKBOX, Radius.CHECKBOX)

        if on:
            width = rect.width()
            # The tick stays accent_text even when disabled, as in the QSS.
            pen = QPen(QColor(COLORS["accent_text"]))
            pen.setWidthF(width * self._TICK_WEIGHT)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            # Geometry - not the stroke weight - is the other half of what
            # the user reviewed and approved; kept exactly as rendered in
            # the prototype rather than re-derived from the SVG.
            path = QPainterPath()
            path.moveTo(rect.x() + width * 0.28, rect.y() + width * 0.52)
            path.lineTo(rect.x() + width * 0.44, rect.y() + width * 0.68)
            path.lineTo(rect.x() + width * 0.73, rect.y() + width * 0.33)
            painter.drawPath(path)

        painter.restore()
