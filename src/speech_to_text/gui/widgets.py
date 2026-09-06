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

from speech_to_text.gui import theme
from speech_to_text.gui.icons import ICONS, svg_to_pixmap


def make_label(
    text: str = "",
    *,
    font: QFont | None = None,
    color: str | None = None,
    align: Qt.Alignment | Qt.AlignmentFlag | None = None,
    parent: QWidget | None = None,
) -> QLabel:
    """Build a styled QLabel in one call instead of four statements.

    Almost every label in this app is the same four-line shape - construct
    with text, setFont(a Fonts constant), setStyleSheet(theme.text_qss(key)),
    and often setAlignment. Repeated across the three steps and the main
    window that came to 27 QLabel constructions and 22 text_qss calls, and
    the cost was not just typing: with the font and the color key on
    separate lines from the construction, a label that quietly lost its
    setStyleSheet line looked exactly like one that never needed it, so
    "does this label match its neighbours" was never readable at a glance.

    Colors stay color KEYS routed through theme.text_qss - the same names
    the call sites already used - rather than becoming a second vocabulary
    for naming a color. Passing None for font, color or align skips that
    call entirely, so a label built here is byte-identical to the hand-
    written one it replaces, including which properties are left at Qt's
    defaults.

    Deliberately narrow: labels that only carry a pixmap, or that need word
    wrap, a size policy or an object name, are still built by hand (or get
    those extras set on the result). Widening this into a kitchen-sink
    constructor would trade four honest lines for one line of keyword soup.
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
    """Step 1's file drop target, made a first-class keyboard control.

    Before this it was a bare QFrame with mousePressEvent monkey-patched
    onto the instance (see FileSelectStep._init_ui): clickable with a
    mouse, but with no focus policy and no key handler at all. That made it
    the single worst accessibility gap in the app, not just a papercut - the
    drop zone is also the browse button (there is no separate "Browse..."
    button anywhere), so a keyboard-only user could not select a file,
    which means they could not use the app at all. Every other step is
    unreachable without first getting past this one.

    StrongFocus makes it tab-stoppable; Space and Enter/Return open the
    same file dialog a mouse click does, mirroring the convention every
    native Qt button already uses for those two keys.

    Drag-and-drop and the mouse click are deliberately NOT handled here.
    FileSelectStep still assigns dragEnterEvent/dragLeaveEvent/dropEvent/
    mousePressEvent onto the instance exactly as before - moving that
    wiring into this class would be a bigger change than this step calls
    for, and tests/test_gui.py::TestDropZoneEventPath sends real Qt drag/
    drop events through that exact path and has to keep passing unmodified.
    This class only adds the pieces that were entirely missing: focus and
    a key handler.
    """

    # Emitted on Space/Enter/Return. FileSelectStep connects this to the
    # same _browse() a mouse click already calls, so both input paths open
    # the identical QFileDialog rather than two subtly different ones.
    activated = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def event(self, a0: QEvent | None) -> bool:
        # A plain QShortcut for the window-level "Enter advances" binding
        # (see MainWindow) would otherwise steal Return/Enter before this
        # widget's own keyPressEvent ever saw it - Qt asks the focused
        # widget for permission via ShortcutOverride before honouring any
        # QShortcut, and a widget that doesn't accept it loses the key
        # entirely. Accepting it here for the three keys this widget cares
        # about is what lets "Enter opens the browse dialog while the drop
        # zone is focused" win over "Enter advances to the next step"
        # instead of the two racing.
        # isinstance rather than a cast: only QKeyEvent carries key(), and
        # a ShortcutOverride always is one. The None arm exists because the
        # override signature permits it, not because Qt sends it.
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
    """QPushButton that paints its icon and text itself, as one centered
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
            # dpr is part of the key, not just (icon, size, color): without
            # it, whichever ratio painted first (e.g. 1x during an
            # off-screen warmup) would get reused for every later repaint
            # regardless of which screen the button actually ended up on -
            # a cached 1x pixmap stretched to fill a 1.25x/1.5x button looks
            # exactly like the un-cached bug this fixes, just intermittently.
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
