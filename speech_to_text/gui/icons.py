"""
Icon set for the Speech-to-Text Transcriber GUI.

Uses Tabler Icons (MIT licensed, https://tabler.io/icons) — stroke-based
outline icons that recolor cleanly via the 'currentColor' substitution in
svg_to_pixmap().
"""

from PyQt5.QtCore import Qt, QByteArray
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer

_SVG_HEADER = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
)

ICONS = {
    "folder": (
        _SVG_HEADER
        + '<path d="M5 4h4l3 3h7a2 2 0 0 1 2 2v8a2 2 0 0 1 -2 2h-14a2 2 0 0 1 -2 -2v-11a2 2 0 0 1 2 -2" />'
        "</svg>"
    ),
    "microphone": (
        _SVG_HEADER
        + '<path d="M9 5a3 3 0 0 1 3 -3a3 3 0 0 1 3 3v5a3 3 0 0 1 -3 3a3 3 0 0 1 -3 -3l0 -5" />'
        '<path d="M5 10a7 7 0 0 0 14 0" />'
        '<path d="M8 21l8 0" />'
        '<path d="M12 17l0 4" />'
        "</svg>"
    ),
    "settings": (
        _SVG_HEADER
        + '<path d="M10.325 4.317c.426 -1.756 2.924 -1.756 3.35 0a1.724 1.724 0 0 0 2.573 1.066c1.543 -.94 3.31 .826 2.37 2.37a1.724 1.724 0 0 0 1.065 2.572c1.756 .426 1.756 2.924 0 3.35a1.724 1.724 0 0 0 -1.066 2.573c.94 1.543 -.826 3.31 -2.37 2.37a1.724 1.724 0 0 0 -2.572 1.065c-.426 1.756 -2.924 1.756 -3.35 0a1.724 1.724 0 0 0 -2.573 -1.066c-1.543 .94 -3.31 -.826 -2.37 -2.37a1.724 1.724 0 0 0 -1.065 -2.572c-1.756 -.426 -1.756 -2.924 0 -3.35a1.724 1.724 0 0 0 1.066 -2.573c-.94 -1.543 .826 -3.31 2.37 -2.37c1 .608 2.296 .07 2.572 -1.065" />'
        '<path d="M9 12a3 3 0 1 0 6 0a3 3 0 0 0 -6 0" />'
        "</svg>"
    ),
    "check": (
        _SVG_HEADER
        + '<path d="M5 12l5 5l10 -10" />'
        "</svg>"
    ),
    "check_circle": (
        _SVG_HEADER
        + '<path d="M3 12a9 9 0 1 0 18 0a9 9 0 1 0 -18 0" />'
        '<path d="M9 12l2 2l4 -4" />'
        "</svg>"
    ),
    "arrow_left": (
        _SVG_HEADER
        + '<path d="M5 12l14 0" />'
        '<path d="M5 12l6 6" />'
        '<path d="M5 12l6 -6" />'
        "</svg>"
    ),
    "arrow_right": (
        _SVG_HEADER
        + '<path d="M5 12l14 0" />'
        '<path d="M13 18l6 -6" />'
        '<path d="M13 6l6 6" />'
        "</svg>"
    ),
    "file": (
        _SVG_HEADER
        + '<path d="M14 3v4a1 1 0 0 0 1 1h4" />'
        '<path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2" />'
        "</svg>"
    ),
    "file_plus": (
        _SVG_HEADER
        + '<path d="M14 3v4a1 1 0 0 0 1 1h4" />'
        '<path d="M17 21h-10a2 2 0 0 1 -2 -2v-14a2 2 0 0 1 2 -2h7l5 5v11a2 2 0 0 1 -2 2" />'
        '<path d="M12 11l0 6" />'
        '<path d="M9 14l6 0" />'
        "</svg>"
    ),
    "x": (
        _SVG_HEADER
        + '<path d="M18 6l-12 12" />'
        '<path d="M6 6l12 12" />'
        "</svg>"
    ),
    "alert_triangle": (
        _SVG_HEADER
        + '<path d="M12 9v4" />'
        '<path d="M10.363 3.591l-8.106 13.534a1.914 1.914 0 0 0 1.636 2.871h16.214a1.914 1.914 0 0 0 1.636 -2.87l-8.106 -13.535a1.914 1.914 0 0 0 -3.274 0z" />'
        '<path d="M12 16h.01" />'
        "</svg>"
    ),
}


def svg_to_pixmap(svg_string: str, size: int = 24, color: str = "white") -> QPixmap:
    """
    Rasterize an SVG string (with 'currentColor' tokens) to a square QPixmap.

    Args:
        svg_string: SVG markup, e.g. an entry from ICONS.
        size: Width and height of the resulting pixmap in pixels.
        color: Replacement color for 'currentColor' tokens.

    Returns:
        QPixmap with a transparent background.
    """
    svg_with_color = svg_string.replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(svg_with_color.encode()))
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return pixmap
