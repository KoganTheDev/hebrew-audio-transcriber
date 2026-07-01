"""
Theme system for the Speech-to-Text Transcriber GUI.

Single source of truth for colors, fonts, spacing, and QSS (Qt stylesheet)
generation. Palette: amber/copper accent on charcoal — a warm, tactile,
mixing-console feel with a single solid accent color (no dual-tone
gradients, which read as generic AI-generated UI). The one deliberate
exception is the header title text, which uses a copper-toned gradient
fill as a one-off brand accent (see gradient_text_pixmap).
"""

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QFontMetrics, QLinearGradient, QColor, QPainter, QPixmap

COLORS = {
    "bg_primary": "#16151A",
    "bg_secondary": "#1C1B21",
    "bg_tertiary": "#201F26",
    "accent": "#C9814A",
    "accent_hover": "#D99B6B",
    "accent_dark": "#A8672F",
    "success": "#7A9B6E",
    "text_primary": "#EDEAE4",
    "text_secondary": "#A8A29A",
    "text_tertiary": "#6E6A63",
    "border": "#332F35",
    "border_light": "#48434A",
}

FONT_FAMILY = "Segoe UI"


class Fonts:
    """Named QFont constants, reused instead of constructing QFont(...) inline everywhere."""

    TITLE = QFont(FONT_FAMILY, 14, QFont.Bold)
    SUBTITLE_BOLD = QFont(FONT_FAMILY, 12, QFont.Bold)
    BODY_BOLD = QFont(FONT_FAMILY, 11, QFont.Bold)
    BODY = QFont(FONT_FAMILY, 10)
    BODY_BOLD_SMALL = QFont(FONT_FAMILY, 10, QFont.Bold)
    CAPTION = QFont(FONT_FAMILY, 9)
    CAPTION_BOLD = QFont(FONT_FAMILY, 9, QFont.Bold)


class Spacing:
    """Named spacing constants (px), replacing magic numbers in layouts."""

    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 20


def button_primary_qss() -> str:
    return f"""
    QPushButton {{
        background-color: {COLORS['accent']};
        color: {COLORS['bg_primary']};
        border: none;
        border-radius: 8px;
        padding: 10px 20px;
        font-weight: 700;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {COLORS['accent_hover']};
    }}
    QPushButton:pressed {{
        background-color: {COLORS['accent_dark']};
    }}
    QPushButton:disabled {{
        background-color: {COLORS['bg_tertiary']};
        color: {COLORS['text_tertiary']};
    }}
    """


def button_secondary_qss() -> str:
    return f"""
    QPushButton {{
        background-color: transparent;
        color: {COLORS['text_primary']};
        border: 2px solid {COLORS['border_light']};
        border-radius: 8px;
        padding: 8px 18px;
        font-weight: 700;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {COLORS['bg_tertiary']};
        border-color: {COLORS['accent']};
        color: {COLORS['accent']};
    }}
    """


def frame_bg_qss(color_key: str = "bg_primary") -> str:
    return f"background-color: {COLORS[color_key]};"


def text_qss(color_key: str, extra: str = "") -> str:
    """
    Style for a QLabel sitting on a colored parent frame.

    Explicitly sets 'background: transparent' — without it, once any ancestor
    in the widget tree has a stylesheet, Qt renders plain QLabels with an
    opaque background instead of showing the parent frame's color through.
    """
    return f"color: {COLORS[color_key]}; background: transparent; {extra}"


def card_qss(object_name: str, recommended: bool = False) -> str:
    # ID selector (#name) — a bare 'QFrame {...}' selector would also match QLabel,
    # since QLabel subclasses QFrame in Qt, leaking the border/background onto child text.
    border_color = COLORS['accent'] if recommended else COLORS['border']
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_tertiary']};
        border: 2px solid {border_color};
        border-radius: 10px;
        padding: 0px;
    }}
    """


def progress_bar_qss() -> str:
    return f"""
    QProgressBar {{
        background-color: {COLORS['bg_tertiary']};
        border-radius: 8px;
        border: none;
        height: 24px;
        text-align: center;
        color: {COLORS['text_primary']};
    }}
    QProgressBar::chunk {{
        background-color: {COLORS['accent']};
        border-radius: 8px;
    }}
    """


def drop_zone_qss(object_name: str, active: bool = False) -> str:
    bg = COLORS['bg_secondary'] if active else COLORS['bg_tertiary']
    border_color = COLORS['accent_hover'] if active else COLORS['accent']
    return f"""
    QFrame#{object_name} {{
        background-color: {bg};
        border: 2px dashed {border_color};
        border-radius: 12px;
    }}
    """


def header_qss(object_name: str) -> str:
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_secondary']};
        border: none;
        border-bottom: 1px solid {COLORS['accent']};
        padding: 0px;
    }}
    """


def nav_bar_qss(object_name: str) -> str:
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_secondary']};
        border-top: 1px solid {COLORS['border']};
        padding: 12px 16px;
    }}
    """


def badge_qss() -> str:
    return f"""
    QLabel {{
        background-color: {COLORS['accent']};
        color: {COLORS['bg_primary']};
        border-radius: 4px;
        padding: 3px 8px;
        font-weight: 700;
        font-size: 9px;
    }}
    """


def hardware_card_qss(object_name: str) -> str:
    # No QSS padding here — the child QHBoxLayout's own contentsMargins provide
    # the inset instead. Stacking both ate nearly all of the card's fixed
    # height and clipped the icon/text.
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_tertiary']};
        border-radius: 10px;
    }}
    """


def result_panel_qss(object_name: str) -> str:
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_tertiary']};
        border-radius: 10px;
        padding: 16px;
    }}
    """


def gradient_text_pixmap(
    text: str,
    font: QFont,
    start_color_key: str = "accent",
    end_color_key: str = "accent_hover",
    padding: int = 4,
) -> QPixmap:
    """
    Render text filled with a vertical linear gradient, as a QPixmap.

    Qt stylesheets can't apply a gradient to text color (only to
    background-color), so this paints the text as an alpha mask and
    composites a gradient-filled pixmap into it. Used for the header title
    only — a deliberate one-off brand accent, not the general theme.
    """
    metrics = QFontMetrics(font)
    width = metrics.horizontalAdvance(text) + padding * 2
    height = metrics.height() + padding * 2

    mask = QPixmap(width, height)
    mask.fill(Qt.transparent)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(mask.rect(), Qt.AlignCenter, text)
    painter.end()

    result = QPixmap(width, height)
    result.fill(Qt.transparent)
    result_painter = QPainter(result)
    result_painter.drawPixmap(0, 0, mask)
    result_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0, QColor(COLORS[start_color_key]))
    gradient.setColorAt(1, QColor(COLORS[end_color_key]))
    result_painter.fillRect(result.rect(), gradient)
    result_painter.end()

    return result
