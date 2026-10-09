"""Paint every window's Windows title bar in the app's own colours.

Left alone, Windows draws a bright white title bar above a dark app - the
lightest thing on screen, sitting directly on top of the header. Windows 11
lets an app pick its caption colours through DwmSetWindowAttribute while
keeping the native bar, and keeping the native bar is the point: dragging,
edge resize, snapping, the Snap Layouts flyout, the window shadow and the
buttons' screen-reader roles all stay Windows' own. A frameless window with
a hand-drawn bar would have to rebuild every one of those.

Windows 10 has no caption-colour attribute, only the dark-mode switch, so
there the bar comes out near-black rather than this exact colour. Anywhere
else this does nothing.
"""

import ctypes
import logging
import sys

from PyQt5.QtCore import QEvent, QObject
from PyQt5.QtWidgets import QApplication, QWidget

from gui.theme import COLORS

logger = logging.getLogger(__name__)

# DWMWINDOWATTRIBUTE values (dwmapi.h). Dark mode was 19 before Windows 10
# 20H1 and 20 since, so both are tried; caption and text colour exist from
# Windows 11 (build 22000) only.
_DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
_DWMWA_USE_IMMERSIVE_DARK_MODE = 20
_DWMWA_CAPTION_COLOR = 35
_DWMWA_TEXT_COLOR = 36

# Caption = the app header's own colour, so the title bar and the header
# read as one surface; text = the app's primary text colour.
_CAPTION_KEY = "bg_secondary"
_TEXT_KEY = "text_primary"


def _colorref(hex_color: str) -> int:
    """'#rrggbb' -> a Win32 COLORREF, which is 0x00BBGGRR."""
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (1, 3, 5))
    return (b << 16) | (g << 8) | r


def _set_attribute(hwnd: int, attribute: int, value: int) -> bool:
    data = ctypes.c_int(value)
    result: int = ctypes.windll.dwmapi.DwmSetWindowAttribute(
        ctypes.c_void_p(hwnd), attribute, ctypes.byref(data), ctypes.sizeof(data)
    )
    return result == 0  # S_OK


def apply_title_bar_colors(window: QWidget) -> None:
    """Colour `window`'s native title bar. Safe to call on any platform."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(window.winId())
        if not _set_attribute(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE, 1):
            _set_attribute(hwnd, _DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, 1)
        _set_attribute(hwnd, _DWMWA_CAPTION_COLOR, _colorref(COLORS[_CAPTION_KEY]))
        _set_attribute(hwnd, _DWMWA_TEXT_COLOR, _colorref(COLORS[_TEXT_KEY]))
    except (AttributeError, OSError) as e:
        # A cosmetic nicety: never worth failing a window over.
        logger.debug(f"Could not colour the title bar: {e}")


class TitleBarColorizer(QObject):
    """Colours each top-level window's title bar the first time it is shown.

    One app-wide filter rather than a call in every window class, so a
    dialog added later - or a QMessageBox - gets the same bar without
    anyone remembering to ask for it. Applied at Show, after Qt has created
    the native window, and once per window: DWM keeps the setting for the
    window's lifetime.
    """

    _DONE = "_titleBarColored"

    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        app.installEventFilter(self)

    def eventFilter(self, a0: QObject | None, a1: QEvent | None) -> bool:
        if (
            a1 is not None
            and a1.type() == QEvent.Type.Show
            and isinstance(a0, QWidget)
            and a0.isWindow()
            and not a0.property(self._DONE)
        ):
            a0.setProperty(self._DONE, True)
            apply_title_bar_colors(a0)
        return False
