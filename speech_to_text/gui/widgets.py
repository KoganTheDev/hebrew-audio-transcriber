"""Custom widgets used by the main window."""

from PyQt5.QtGui import QColor, QIcon, QPainter
from PyQt5.QtWidgets import QPushButton, QStyle, QStyleOptionButton, QStylePainter

from speech_to_text.gui.icons import ICONS, svg_to_pixmap


class IconTextButton(QPushButton):
    """
    QPushButton that paints its icon and text itself, as one centered
    group with an explicitly chosen VISUAL icon side.

    Why this exists: a stock QPushButton welds the icon to the leading
    edge of its layout direction, and Hebrew text only renders adjacent
    to the icon when the button is RightToLeft - which makes "icon on the
    visual left of Hebrew text" (the mirrored Next button) unreachable
    with setIcon/setLayoutDirection combinations (verified empirically).
    Here the QSS frame (background, border, hover/pressed/disabled
    states) is still painted by the style; only the label content is
    drawn manually, so placement is direction-independent.
    """

    GAP = 8  # px between icon and text

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon_name = None
        self._icon_side = "left"     # visual side: "left" | "right"
        self._icon_px = 16
        self._color_normal = "#ffffff"
        self._color_hover = None     # None: no hover color change
        self._color_disabled = None  # None: use the normal color
        # paintEvent runs on every hover change and repaint - rasterizing
        # the SVG each time (XML parse + render) is wasteful, so pixmaps
        # are cached per (icon, size, color); at most one entry per state.
        self._pixmap_cache = {}

    def set_icon_spec(self, icon_name: str, side: str) -> None:
        """Set which ICONS entry to draw and on which visual side."""
        self._icon_name = icon_name
        self._icon_side = side
        self.update()

    def set_text_colors(self, normal: str, hover: str = None, disabled: str = None) -> None:
        """Colors for text and icon per widget state (hex strings)."""
        self._color_normal = normal
        self._color_hover = hover
        self._color_disabled = disabled
        self.update()

    def _current_color(self) -> str:
        if not self.isEnabled() and self._color_disabled:
            return self._color_disabled
        if self.isEnabled() and self.underMouse() and self._color_hover:
            return self._color_hover
        return self._color_normal

    def paintEvent(self, event):
        # Frame/background from QSS, with text and icon blanked out - the
        # label content is drawn manually below.
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        opt.icon = QIcon()
        style_painter = QStylePainter(self)
        style_painter.drawControl(QStyle.CE_PushButton, opt)
        style_painter.end()

        color = self._current_color()
        fm = self.fontMetrics()
        text = self.text()
        text_w = fm.horizontalAdvance(text)

        pixmap = None
        icon_span = 0
        if self._icon_name:
            cache_key = (self._icon_name, self._icon_px, color)
            pixmap = self._pixmap_cache.get(cache_key)
            if pixmap is None:
                pixmap = svg_to_pixmap(ICONS[self._icon_name], self._icon_px, color)
                self._pixmap_cache[cache_key] = pixmap
            icon_span = self._icon_px + (self.GAP if text else 0)

        x = (self.width() - (text_w + icon_span)) // 2
        icon_y = (self.height() - self._icon_px) // 2
        text_baseline = (self.height() + fm.ascent() - fm.descent()) // 2

        painter = QPainter(self)
        painter.setFont(self.font())
        painter.setPen(QColor(color))
        if pixmap is not None and self._icon_side == "left":
            painter.drawPixmap(x, icon_y, pixmap)
            painter.drawText(x + icon_span, text_baseline, text)
        elif pixmap is not None:
            painter.drawText(x, text_baseline, text)
            painter.drawPixmap(x + text_w + self.GAP, icon_y, pixmap)
        else:
            painter.drawText(x, text_baseline, text)
        painter.end()
