"""The breathing glow around step 1's empty drop zone, to draw the eye there.

Painted by the page behind the zone as thin rounded rings fading outward,
not a QGraphicsDropShadowEffect, which would re-blur the whole zone on every
frame of a breath that never stops. Only the ring band repaints.
"""

import math

from PyQt5.QtCore import QObject, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPen, QRegion
from PyQt5.QtWidgets import QWidget

from gui import motion
from gui.motion import breath
from gui.theme import COLORS, Motion, Radius

# Gap the page keeps between the zone and its neighbours: the glow's full
# reach, where the rings stop.
CLEARANCE = Motion.HALO_BLUR_PX

_RINGS = 20
# Breathing strength runs between these fractions of HALO_MAX_ALPHA; with
# animation effects off it holds at _STILL.
_LOW, _STILL = 0.4, 0.7


class DropZoneHalo(QObject):
    """Glow around `zone`, painted onto `page` (the zone's parent)."""

    def __init__(self, page: QWidget, zone: QWidget) -> None:
        super().__init__(page)
        self._page = page
        self._zone = zone
        self._empty = True
        self._drag_over = False
        self._loop = motion.breath_loop(self)
        self._loop.valueChanged.connect(self._repaint)

    def set_empty(self, empty: bool) -> None:
        """Whether the zone still has nothing in it - no glow once it does."""
        self._empty = empty
        self.sync()

    def set_drag_over(self, over: bool) -> None:
        """A drag over the zone holds the glow steady and brighter."""
        self._drag_over = over
        self.sync()

    def is_breathing(self) -> bool:
        return motion.is_running(self._loop)

    def sync(self) -> None:
        """Start or stop breathing to match visibility and state."""
        breathe = (
            self._page.isVisible()
            and self._empty
            and not self._drag_over
            and motion.animations_enabled()
        )
        if breathe and not self.is_breathing():
            self._loop.start()
        elif not breathe:
            self._loop.stop()
        self._repaint()

    def strength(self) -> tuple[float, str] | None:
        """Peak alpha and colour key of the glow right now, or None for none."""
        if not self._empty:
            return None
        if self._drag_over:
            return Motion.HALO_MAX_ALPHA, "accent_hover"
        if self.is_breathing():
            level = _LOW + (1 - _LOW) * breath(float(self._loop.currentValue()))
            return Motion.HALO_MAX_ALPHA * level, "accent"
        return Motion.HALO_MAX_ALPHA * _STILL, "accent"

    def _repaint(self, value: object = None) -> None:
        zone = self._zone.geometry()
        reach = Motion.HALO_BLUR_PX + 2
        band = QRegion(zone.adjusted(-reach, -reach, reach, reach)) - QRegion(zone)
        # The rounded corners are see-through, so they repaint with the band.
        r = Radius.DROP_ZONE
        for x, y in (
            (zone.left(), zone.top()),
            (zone.right() - r + 1, zone.top()),
            (zone.left(), zone.bottom() - r + 1),
            (zone.right() - r + 1, zone.bottom() - r + 1),
        ):
            band = band.united(QRegion(x, y, r, r))
        self._page.update(band)

    def paint(self) -> None:
        """Draw the glow; call from the page's paintEvent, after its own."""
        strength = self.strength()
        if strength is None or not self._zone.isVisible():
            return
        peak, color_key = strength
        zone = QRectF(self._zone.geometry())
        painter = QPainter(self._page)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        # Hard stop at CLEARANCE so the outer ring's anti-aliasing never
        # reaches the neighbours (QRectF edges sit 1px past QRect's).
        reach = CLEARANCE - 1
        painter.setClipRect(zone.adjusted(-reach, -reach, reach, reach))
        # A CSS-style glow: blur b is a Gaussian of sigma b/2, and d px past
        # the edge the strength is 0.5 * erfc(d / (sigma * sqrt 2)).
        sigma = Motion.HALO_BLUR_PX / 2
        step = Motion.HALO_BLUR_PX / _RINGS
        for i in range(_RINGS):
            d = (i + 0.5) * step
            color = QColor(COLORS[color_key])
            color.setAlphaF(min(1.0, peak * 0.5 * math.erfc(d / (sigma * math.sqrt(2)))))
            painter.setPen(QPen(color, step))
            radius = Radius.DROP_ZONE + d
            painter.drawRoundedRect(zone.adjusted(-d, -d, d, d), radius, radius)
        painter.end()
