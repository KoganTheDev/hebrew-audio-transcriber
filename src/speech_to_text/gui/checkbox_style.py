"""Painted checkbox indicator - replaces the QSS raster tick.

Why this exists instead of a QSS `image: url(...)` rule (which is what
theme.app_stylesheet() used to draw the tick with, and what this module's
class is installed in place of):

1. Qt stylesheets have no devicePixelRatio concept. `image: url(...)`
   always hands the style engine one flat raster and lets Qt rescale it to
   whatever size the rule declares, with no per-screen awareness at all -
   every OTHER icon in this app is DPR-aware (see icons.svg_to_pixmap's
   `dpr` parameter and its callers), but this path structurally cannot be,
   short of Qt's little-used multi-resolution `image: url(a); image:
   url(b)` syntax, which nothing here generates. On a 125% display that
   meant a 14x14 PNG stretched to 17.5 device px - soft by construction.
2. The source SVG is `viewBox="0 0 24 24"` with `stroke-width="2"`, so
   rasterized at 14px the stroke came out to 1.17px - sub-pixel and
   off-grid, which is why the two arms of the tick rendered at visibly
   different weights (one blobbing, one fading) rather than a uniform
   soft line.

Painting the tick directly with QPainter - the same idea as
IconTextButton's hand-painted icon in widgets.py - sidesteps both: it
draws onto the widget's real device at its real DPR, so there is no
fixed-size raster for Qt to rescale, and the stroke width is chosen as a
fraction of the indicator's own size rather than inherited from an SVG
authored for a 24px canvas.

This is a QProxyStyle rather than a QWidget subclass because QCheckBox's
indicator is a style-drawn primitive (QStyle.PE_IndicatorCheckBox), not a
child widget - overriding a primitive is the documented way to change how
a subpart of a *native* control paints without reimplementing the whole
control (focus handling, click/space toggling, label layout, etc., all of
which QCheckBox already gets right).
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QCheckBox, QProxyStyle, QStyle, QStyleOption, QWidget

from speech_to_text.gui.theme import COLORS, Border, Radius


class PaintedCheckboxStyle(QProxyStyle):
    """Draws QCheckBox's indicator (border, fill, tick) itself instead of
    deferring to the platform style plus a QSS `image:` overlay.

    Installed once on the QApplication in main_window.configure_application,
    which is the single place every real entry point (and the screenshot
    harness) constructs its QApplication - see that function's own
    docstring for why centralizing setup there matters. A QProxyStyle can
    only be applied application-wide or attached per-widget; app-wide is
    correct here even though the app has exactly one QCheckBox today,
    because the per-widget form would have to be re-attached by hand to
    every checkbox a future step adds, silently reverting to the platform's
    native (unstyled) look if anyone forgot.

    Wraps rather than replaces the app's existing style
    (`PaintedCheckboxStyle(app.style())`) so every primitive OTHER than the
    checkbox indicator - buttons, scrollbars, everything QSS still styles
    directly - keeps rendering exactly as before; only PE_IndicatorCheckBox
    and the two PM_Indicator* size metrics are overridden below.
    """

    # Matches the 18x18 box the QSS rule this replaces declared
    # (QCheckBox::indicator { width: 18px; height: 18px; }). Needed as an
    # explicit PM_IndicatorWidth/Height override because nothing else
    # supplies that size now that the QSS rule is gone, and the tick
    # geometry below is expressed as fractions of this box.
    SIZE = 18

    # Stroke weight as a fraction of the indicator's width - the user's
    # explicit pick among four rendered candidates (0.083 / 0.105 / 0.135 /
    # 0.165; see the weight-comparison prototype this was chosen from). Not
    # tuned further here: the thinnest candidate (0.083) is roughly what the
    # old 24-viewBox/stroke-width-2 SVG works out to once scaled to a 14px
    # glyph, i.e. close to the exact weight that produced the blob/fade
    # asymmetry this class exists to fix, so it was never in contention.
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
            # Swallowed, not drawn. Qt's default focus frame is a white dotted
            # rectangle around the label, and it only started appearing here
            # when the indicator moved off QSS: QStyleSheetStyle was suppressing
            # it, and delegating to the base style handed the job back. It is
            # both redundant - the indicator already takes a focus-coloured
            # border from the kbdFocus property, which is the app's own focus
            # language everywhere else - and visually wrong for a dark themed
            # UI, where a dotted system rectangle reads as a stray artifact.
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
        # kbdFocus is a dynamic property gui/focus.py stamps on whichever
        # widget currently owns the keyboard-focus ring (see that module's
        # docstring for why native :focus can't be used instead - it paints
        # for mouse-click and default focus too). QStyleOption carries no
        # such flag, so it has to be read straight off the widget rather
        # than off `option`.
        kbd_focus = bool(widget is not None and widget.property("kbdFocus"))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Border/fill selection mirrors the QCheckBox::indicator rules this
        # class replaces, state for state - see theme.app_stylesheet()'s
        # QCheckBox comment for why every state has to be spelled out
        # explicitly rather than left to fall through: a missed state is
        # exactly the failure mode that made this rewrite necessary in the
        # first place (a QSS property touched at all makes Qt stop drawing
        # any native fallback for the ones you didn't cover).
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
            # In the QSS this replaces, [kbdFocus="true"]::indicator is the
            # last-declared rule touching border-color, so it wins the
            # cascade over :checked/:hover/:disabled for that one property
            # while leaving background-color to whichever of those rules
            # set it. Doing the same override last here, after the
            # enabled/checked/hover branch above, reproduces that ordering.
            edge = COLORS["focus"]

        # Half-pixel inset so the Border.CONTROL-wide pen sits inside the
        # rect instead of straddling its edge: QPainter centers a pen ON
        # the path it strokes, so stroking the rect's own bounds directly
        # would paint half the border outside the indicator's allotted
        # space, clipped away by the parent - which reads as a thinner,
        # uneven edge and is a different, unrelated way to get the same
        # "soft border" complaint this class exists to fix.
        box = QRectF(rect).adjusted(1, 1, -1, -1)
        painter.setPen(QPen(QColor(edge), Border.CONTROL))
        painter.setBrush(QColor(fill))
        painter.drawRoundedRect(box, Radius.CHECKBOX, Radius.CHECKBOX)

        if on:
            width = rect.width()
            # Ink stays accent_text in every checked state, including
            # checked+disabled - matching the QSS this replaces, which
            # rasterized the tick with color=COLORS["accent_text"] exactly
            # once and reused that same image for :checked, :checked:hover
            # and :checked:disabled alike. Only the fill/border darkened
            # for disabled; the tick itself never did.
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
