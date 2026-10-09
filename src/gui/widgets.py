"""Custom widgets used by the main window."""

from PyQt5.QtCore import QEvent, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QIcon, QKeyEvent, QPainter, QPaintEvent, QPixmap
from PyQt5.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QStyle,
    QStyleOptionButton,
    QStylePainter,
    QWidget,
)

from gui import theme
from gui.icons import ICONS, svg_to_pixmap


def make_label(
    text: str = "",
    *,
    font: QFont | None = None,
    color: str | None = None,
    align: Qt.Alignment | Qt.AlignmentFlag | None = None,
    parent: QWidget | None = None,
) -> QLabel:
    """Build a styled QLabel in one call: text, font, colour key (through
    theme.text_qss) and alignment. None skips that call, so the result matches
    a hand-built label exactly. Deliberately narrow - pixmaps, word wrap and
    size policies are set on the result.
    """
    label = QLabel(text, parent)
    if font is not None:
        label.setFont(font)
    if color is not None:
        label.setStyleSheet(theme.text_qss(color))
    if align is not None:
        label.setAlignment(align)
    return label


class DropZone(QFrame):
    """Step 1's drop target as a keyboard control: tab-stoppable, with
    Space/Enter opening the file dialog. It is also the only browse button, so
    without this a keyboard user could not use the app at all.

    Drag, drop and click stay assigned onto the instance by FileSelectStep,
    the path TestDropZoneEventPath drives with real events.
    """

    # Emitted on Space/Enter/Return. FileSelectStep connects this to the
    # same _browse() a mouse click already calls, so both input paths open
    # the identical QFileDialog rather than two subtly different ones.
    activated = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def event(self, a0: QEvent | None) -> bool:
        # Accept ShortcutOverride for our keys, or the window's "Enter
        # advances" QShortcut takes Enter before keyPressEvent sees it.
        if (
            a0 is not None
            and a0.type() == QEvent.Type.ShortcutOverride
            and isinstance(a0, QKeyEvent)
            and a0.key()
            in (
                Qt.Key.Key_Space,
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
            )
        ):
            a0.accept()
            return True
        return super().event(a0)

    def keyPressEvent(self, a0: QKeyEvent | None) -> None:
        if a0 is not None and a0.key() in (
            Qt.Key.Key_Space,
            Qt.Key.Key_Return,
            Qt.Key.Key_Enter,
        ):
            self.activated.emit()
            a0.accept()
            return
        super().keyPressEvent(a0)


class IconTextButton(QPushButton):
    """QPushButton that paints its icon and label itself, with an explicit
    visual icon side. A stock button welds the icon to the leading edge, so
    "icon on the left of Hebrew text" (the mirrored Next) is unreachable.
    The QSS frame is still the style's; only the content is painted here.
    """

    GAP = 8  # px between icon and text

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._icon_name: str | None = None
        self._icon_side = "left"  # visual side: "left" | "right"
        self._icon_px = 16
        self._color_normal = "#ffffff"
        self._color_hover: str | None = None  # None: no hover color change
        self._color_disabled: str | None = None  # None: use the normal color
        # paintEvent runs on every hover change and repaint - rasterizing
        # the SVG each time (XML parse + render) is wasteful, so pixmaps
        # are cached per (icon, size, color); at most one entry per state.
        self._pixmap_cache: dict[tuple[str, int, str, float], QPixmap] = {}

    def set_icon_spec(self, icon_name: str, side: str) -> None:
        """Set which ICONS entry to draw and on which visual side."""
        self._icon_name = icon_name
        self._icon_side = side
        self.update()

    def set_text_colors(
        self, normal: str, hover: str | None = None, disabled: str | None = None
    ) -> None:
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

    def paintEvent(self, a0: QPaintEvent | None) -> None:
        # Frame/background from QSS, with text and icon blanked out - the
        # label content is drawn manually below.
        opt = QStyleOptionButton()
        self.initStyleOption(opt)
        opt.text = ""
        opt.icon = QIcon()
        style_painter = QStylePainter(self)
        style_painter.drawControl(QStyle.ControlElement.CE_PushButton, opt)
        style_painter.end()

        color = self._current_color()
        fm = self.fontMetrics()
        text = self.text()
        text_w = fm.horizontalAdvance(text)

        pixmap = None
        icon_span = 0
        if self._icon_name:
            # dpr in the key, or a pixmap painted at one ratio is reused,
            # blurry, on a screen with another.
            dpr = self.devicePixelRatioF()
            cache_key = (self._icon_name, self._icon_px, color, dpr)
            pixmap = self._pixmap_cache.get(cache_key)
            if pixmap is None:
                pixmap = svg_to_pixmap(ICONS[self._icon_name], self._icon_px, color, dpr=dpr)
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
