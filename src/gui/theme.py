"""Theme: colours, fonts, spacing, radii and the QSS builders, in one place.

Catppuccin Mocha with a peach accent, to match the HTML transcript the app
writes (core/assets/css/00-tokens.css); peach is the nearest Catppuccin
colour to the app's original copper. app_stylesheet() holds app-wide
defaults only; per-widget setStyleSheet() calls are applied later and win.
"""

import math

from PyQt5.QtCore import QRect, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QGraphicsDropShadowEffect

COLORS = {
    # Catppuccin Mocha. Hexes marked (doc) are byte-identical to the
    # transcript stylesheet's own --dark-* tokens, so those roles look
    # identical whether you're looking at the app or the document it wrote.
    "bg_primary": "#11111b",  # crust - window ground (doc)
    "bg_secondary": "#181825",  # mantle - header and nav bar
    "bg_tertiary": "#1e1e2e",  # base - cards and panels (doc)
    "surface_hover": "#313244",  # surface0 - hover step (doc)
    "border": "#45475a",  # surface1 - decorative hairline (doc). Contrast
    # against crust/mantle/base is only 2.06 / 1.92 / 1.80, well under the
    # 3:1 floor for a control signal - use this only for separators the
    # eye doesn't need to resolve on its own, never as a control's outline.
    "control_border": "#7f849c",  # overlay1 - load-bearing edge (doc).
    # 5.07 / 4.75 / 4.44 against crust/mantle/base, clearing the 3:1 floor
    # for "this is a control" outlines where `border` falls short.
    "text_primary": "#cdd6f4",  # text (doc). 12.97 / 12.14 / 11.34 against
    # crust/mantle/base, all clear of the 4.5:1 body-text floor.
    "text_secondary": "#a6adc8",  # subtext0 (doc). 8.42 / 7.89 / 7.37.
    "text_tertiary": "#9399b2",  # overlay2 - captions and small labels.
    # 6.64 / 6.22 / 5.81 - clears the 4.5:1 floor on all three grounds.
    "text_disabled": "#6c7086",  # overlay0 - disabled text and muted
    # icons ONLY. 3.84 / 3.59 / 3.36 against crust/mantle/base - this
    # deliberately fails the 4.5:1 body-text floor. It's valid here only
    # because WCAG 1.4.3 exempts inactive-control text from the contrast
    # floor, and because muted icons only need 3:1. Do not reuse this for
    # captions or any other text a user is expected to read normally.
    "accent": "#fab387",  # peach. 10.59 / 9.92 / 9.27 against crust/
    # mantle/base - see the module docstring for why peach was chosen.
    "accent_hover": "#fbc19d",  # peach lightened 18% toward white.
    "accent_dark": "#d09674",  # peach darkened 18% toward crust.
    "accent_text": "#11111b",  # crust - the ink that sits ON the accent
    # fills, not the window ground it happens to equal today. 10.59 on
    # accent, 11.80 on accent_hover, 7.41 on accent_dark - clears 4.5:1
    # on all three, named by role so a future accent change can't silently
    # break this the way reusing bg_primary would have.
    "success": "#a6e3a1",  # green (doc). 12.61 / 11.81 / 11.03.
    "error": "#f38ba8",  # red (doc). 8.10 / 7.58 / 7.08.
    "warn": "#f9e2af",  # yellow (doc).
    "focus": "#74c7ec",  # sapphire (doc). 9.93 / 9.30 / 8.69.
}


FONT_FAMILY = "Segoe UI"
# Not "Segoe UI Variable Display": it has no Hebrew glyphs, so Hebrew silently
# falls back to another face mid-line. The modern feel comes from DemiBold
# weights instead.

# QFont.Weight values, named here because "62" and "75" read as noise at
# every call site below. DemiBold - not Bold - is used for every heading
# and label role: Bold at every level reads as heavy and dated because
# nothing is held in reserve for actual emphasis. Segoe UI Semibold is a
# real installed cut on Windows, so this maps onto genuine hinted glyphs
# rather than a synthetically bolded font.
_DEMIBOLD = QFont.DemiBold


class _FontsMeta(type):
    """Builds each Fonts role on first use - a correctness requirement.

    A QFont built before QApplication exists keeps wrong metrics (227 px vs
    276 px for the title), which clipped gradient_text_pixmap's hand-sized
    canvas. Roles are cached only once a QApplication exists, so an early
    access cannot poison the cache.
    """

    _SPECS = {
        "DISPLAY": (19, True),
        "SUBTITLE_BOLD": (13, True),
        "BODY_BOLD": (12, True),
        "BODY": (11, False),
        "BODY_BOLD_SMALL": (11, True),
        "CAPTION": (9, False),
        "CAPTION_BOLD": (9, True),
    }

    def __getattr__(cls, name: str) -> QFont:
        try:
            size, demibold = cls._SPECS[name]
        except KeyError:
            raise AttributeError(f"{cls.__name__} has no font role {name!r}") from None
        font = QFont(FONT_FAMILY, size, _DEMIBOLD) if demibold else QFont(FONT_FAMILY, size)
        # Only memoise once the font database is real - see the class
        # docstring. Before that, hand back a correct-for-now object without
        # committing to it.
        if QApplication.instance() is not None:
            setattr(cls, name, font)
        return font


class Fonts(metaclass=_FontsMeta):
    """Named font roles, built lazily by _FontsMeta (never add a plain QFont
    class attribute). Sizes are spaced widely and weight shares the hierarchy.

      DISPLAY         step headings
      SUBTITLE_BOLD   header title, step-3 headline
      BODY_BOLD       model names, hardware values, drop zone lead line
      BODY            default body text
      BODY_BOLD_SMALL the step-3 status line
      CAPTION         captions, banners, card descriptions (9 pt floor)
      CAPTION_BOLD    emphasis at caption size
    """


class Spacing:
    """Named spacing constants (px), replacing magic numbers in layouts."""

    XS = 4
    SM = 8
    MD = 12
    LG = 16
    XL = 20
    # XXL is the step page margin, spent only on steps 1 and 3, the two
    # with measured slack (an ~85px empty band under step 1's file list, a
    # large empty middle on step 3). XXXL is used sparingly, for the few
    # places on those two steps that can absorb a full 40px without
    # pushing anything else out of the fixed 650x600 window - never on
    # step 2, which has no slack to spend.
    XXL = 28
    XXXL = 40


class Radius:
    """Corner radii by kind of element, matching the transcript's
    --control-radius/--panel-radius. CONTROL (14) is rounder than PANEL (12)
    on purpose: controls read as near-pills, containers as boxes.
    """

    # Small interactive controls: buttons, the progress bar (track and
    # chunk), the error banner, and every native control app_stylesheet()
    # draws (checkbox/radio). The document's --control-radius.
    CONTROL = 14
    # Larger static surfaces that hold other widgets: model choice cards,
    # the hardware summary card, the result panel, the error banner's own
    # box (its QFrame; the ERROR_ACCENT stripe is a border width, not a
    # radius). The document's --panel-radius.
    PANEL = 12
    # The file drop zone. Kept generous and close to PANEL rather than
    # scaled up in lockstep with CONTROL: it's the single largest surface
    # on the file-select step, so it reads as a container (PANEL's role),
    # and a dashed border reads better with a bit more corner softness
    # than a solid one - hence a few px over PANEL rather than equal to it.
    DROP_ZONE = 16
    # The small pill-shaped recommendation badge on a model card. Tracks
    # CONTROL rather than keeping its own literal: at the badge's actual
    # pixel height (~20px with its padding), a radius this size exceeds
    # half that height, which is what turns a rounded rectangle into a
    # true stadium/pill shape.
    BADGE = CONTROL
    # The checkbox indicator's own rounding. Deliberately NOT Radius.BADGE:
    # the indicator is an 18x18 box, and BADGE is 14 - large enough to
    # round an 18px square into a near-circle, which would read as a second
    # radio button rather than a checkbox. 4 keeps it a visibly rounded
    # square next to the fully-circular radio.
    CHECKBOX = 4


class Border:
    """Named border widths (px), same grouping rationale as Radius: named for
    what they outline, not for their thickness.
    """

    # Default width for outlined controls and cards: the secondary button,
    # model cards, and the drop zone's dashed outline.
    CONTROL = 2
    # The error banner's full box outline - thinner than CONTROL because
    # the banner already gets a heavier accent from its leading edge
    # (see ERROR_ACCENT below) and a 2px box would double up on emphasis.
    ERROR_BOX = 1
    # The error banner's left edge accent stripe - thicker than the box
    # outline on purpose, so the eye catches the colored edge first as a
    # "this is an error" flag before reading the box outline.
    ERROR_ACCENT = 3
    # Separators (under the header, over the nav bar, tooltip edge) - its own
    # constant, so thickening outlines leaves separators alone.
    HAIRLINE = 1


class Motion:
    """Named animation timings. Values were tuned by eye in the animation
    mockup (.mockups/animations/) rather than picked in code, so retune them
    there first and copy the numbers back.
    """

    # The transcription step's progress bar value animation (OutCubic).
    PROGRESS_MS = 500
    # Budget for small, frequent state changes that should feel instant.
    FAST_MS = 160

    # The current step's breath: one cycle, and how far its fill dips. Below
    # 0.75 the fill stops reading as the accent and looks like a faded step.
    BREATH_MS = 2200
    PULSE_MIN_ALPHA = 0.75
    # The connector toward the next step: dashes drift toward it at this
    # speed. (dash, gap) in px; QPen wants them in pen-width units.
    DASH_SPEED_PX_S = 20
    DASH_PATTERN = (10, 6)
    # A step completing: the check pops in (OutBack) while the pill body
    # cross-fades from accent to the done tint and the connector after it
    # sweeps from dashed to solid.
    POP_MS = 220
    CONNECTOR_FILL_MS = 350

    # Step 3's bar: a shimmer while the model loads, a gleam over the fill
    # while work runs (so it never looks frozen), green on completion.
    SHIMMER_MS = 1400
    GLEAM_SPEED_PX_S = 160
    FINISH_MS = 450

    # Moving between wizard steps: the incoming page fades in while drifting
    # this far from the side it came from.
    PAGE_MS = 200
    PAGE_SLIDE_PX = 14

    # Step 1's drop zone breathes a soft accent glow while it is empty, to
    # draw the eye there. How far the glow reaches, and its strength at the
    # top of the breath.
    HALO_BLUR_PX = 20
    HALO_MAX_ALPHA = 0.65

    # Step 2's error banner opening: its height grows from nothing while the
    # message fades in over a little longer.
    BANNER_MS = 220


def button_primary_qss() -> str:
    # border: 2px solid transparent, not "none" - a keyboard-focus ring
    # needs a border to color (see _focus_ring_qss and gui/focus.py for why
    # native :focus can't be used instead), and Qt has no CSS 'outline'
    # that sits outside a widget without changing its box. Transparent at
    # Border.CONTROL width paints the same pixels as "none" in every other
    # state, so the border costs nothing until the focus rule colors it.
    return f"""
    QPushButton {{
        background-color: {COLORS["accent"]};
        color: {COLORS["accent_text"]};
        border: {Border.CONTROL}px solid transparent;
        border-radius: {Radius.CONTROL}px;
        padding: 10px 20px;
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {COLORS["accent_hover"]};
    }}
    QPushButton:pressed {{
        background-color: {COLORS["accent_dark"]};
    }}
    QPushButton:disabled {{
        background-color: {COLORS["bg_tertiary"]};
        color: {COLORS["text_disabled"]};
    }}
    QPushButton[kbdFocus="true"] {{
        border-color: {COLORS["focus"]};
    }}
    """


def button_secondary_qss(padding: str = "8px 18px") -> str:
    """padding: override for small fixed-size buttons (e.g. the header
    language toggle passes "2px 4px" - the default 18px side padding plus
    the 2px border would leave almost no room for text in a ~50px button).
    """
    return f"""
    QPushButton {{
        background-color: transparent;
        color: {COLORS["text_primary"]};
        border: {Border.CONTROL}px solid {COLORS["control_border"]};
        border-radius: {Radius.CONTROL}px;
        padding: {padding};
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {COLORS["bg_tertiary"]};
        border-color: {COLORS["accent"]};
        color: {COLORS["accent"]};
    }}
    QPushButton:pressed {{
        background-color: {COLORS["surface_hover"]};
        border-color: {COLORS["accent_dark"]};
        color: {COLORS["accent_dark"]};
    }}
    QPushButton:disabled {{
        background-color: transparent;
        border-color: {COLORS["border"]};
        color: {COLORS["text_disabled"]};
    }}
    QPushButton[kbdFocus="true"] {{
        border-color: {COLORS["focus"]};
    }}
    """


def button_danger_qss() -> str:
    """Armed Cancel: the secondary button's outline shape in the error colour,
    so the button itself warns that the next press stops the run. The label
    stays "Cancel" (every longer one overflowed the 130x36 button in some
    language); cancel_confirm_label beside it explains.
    """
    return f"""
    QPushButton {{
        background-color: transparent;
        color: {COLORS["error"]};
        border: {Border.CONTROL}px solid {COLORS["error"]};
        border-radius: {Radius.CONTROL}px;
        padding: 8px 18px;
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {COLORS["bg_tertiary"]};
        border-color: {COLORS["error"]};
        color: {COLORS["error"]};
    }}
    QPushButton:pressed {{
        background-color: {COLORS["surface_hover"]};
        border-color: {COLORS["error"]};
        color: {COLORS["error"]};
    }}
    QPushButton[kbdFocus="true"] {{
        border-color: {COLORS["focus"]};
    }}
    """


def frame_bg_qss(color_key: str = "bg_primary") -> str:
    return f"background-color: {COLORS[color_key]};"


def text_qss(color_key: str, extra: str = "") -> str:
    """Style for a QLabel sitting on a colored parent frame.

    Explicitly sets 'background: transparent' - without it, once any ancestor
    in the widget tree has a stylesheet, Qt renders plain QLabels with an
    opaque background instead of showing the parent frame's color through.
    """
    return f"color: {COLORS[color_key]}; background: transparent; {extra}"


def card_qss(object_name: str, selected: bool = False) -> str:
    # #name selector: a bare QFrame selector would also hit QLabel (a QFrame
    # subclass). Unselected cards use control_border, not the decorative
    # hairline: each card is a selectable option and needs a 3:1 outline.
    border_color = COLORS["accent"] if selected else COLORS["control_border"]
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS["bg_tertiary"]};
        border: {Border.CONTROL}px solid {border_color};
        border-radius: {Radius.PANEL}px;
        padding: 0px;
    }}
    QFrame#{object_name}[kbdFocus="true"] {{
        border-color: {COLORS["focus"]};
    }}
    """


def card_facts_qss(object_name: str) -> str:
    """The hairline that separates a model card's facts from its purpose line."""
    return f"""
    QFrame#{object_name} {{
        background: transparent;
        border: none;
        border-top: {Border.HAIRLINE}px solid {COLORS["border"]};
    }}
    """


def option_panel_qss(object_name: str) -> str:
    """The speakers and custom terms panels under the model cards.

    A step darker than the cards and outlined with the decorative hairline,
    not control_border: the panel is a container, not something to pick, so
    its edge should not compete with the cards' selectable outlines.
    """
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS["bg_secondary"]};
        border: {Border.HAIRLINE}px solid {COLORS["border"]};
        border-radius: {Radius.PANEL}px;
    }}
    """


def round_button_qss() -> str:
    """The speaker count's - and + buttons: secondary buttons, fully round."""
    return button_secondary_qss(padding="0px") + "QPushButton { border-radius: 16px; }"


def count_pill_qss() -> str:
    """The term count beside the custom terms title."""
    return f"""
    QLabel {{
        background-color: {COLORS["text_secondary"]};
        color: {COLORS["accent_text"]};
        border-radius: 8px;
        padding: 1px 7px;
        font-weight: 700;
        font-size: 9pt;
    }}
    """


def term_chip_qss() -> str:
    return f"""
    QLabel {{
        background-color: {COLORS["bg_tertiary"]};
        color: {COLORS["text_primary"]};
        border: {Border.HAIRLINE}px solid {COLORS["border"]};
        border-radius: 10px;
        padding: 2px 9px;
    }}
    """


def drop_zone_qss(object_name: str, active: bool = False) -> str:
    bg = COLORS["bg_secondary"] if active else COLORS["bg_tertiary"]
    border_color = COLORS["accent_hover"] if active else COLORS["accent"]
    return f"""
    QFrame#{object_name} {{
        background-color: {bg};
        border: {Border.CONTROL}px dashed {border_color};
        border-radius: {Radius.DROP_ZONE}px;
    }}
    QFrame#{object_name}[kbdFocus="true"] {{
        border-style: solid;
        border-color: {COLORS["focus"]};
    }}
    """


def header_qss(object_name: str) -> str:
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS["bg_secondary"]};
        border: none;
        border-bottom: {Border.HAIRLINE}px solid {COLORS["accent"]};
        padding: 0px;
    }}
    """


def nav_bar_qss(object_name: str) -> str:
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS["bg_secondary"]};
        border-top: {Border.HAIRLINE}px solid {COLORS["border"]};
        padding: 12px 16px;
    }}
    """


def badge_qss() -> str:
    # Padding has to keep pace with Radius.BADGE (see the Radius docstring):
    # the radius only reads as a pill if the label has enough vertical room
    # for the curve to show, rather than getting clipped flat.
    return f"""
    QLabel {{
        background-color: {COLORS["accent"]};
        color: {COLORS["accent_text"]};
        border-radius: {Radius.BADGE}px;
        padding: 4px 10px;
        font-weight: 600;
        font-size: 9px;
    }}
    """


def hardware_card_qss(object_name: str) -> str:
    # No QSS padding here - the child QHBoxLayout's own contentsMargins provide
    # the inset instead. Stacking both ate nearly all of the card's fixed
    # height and clipped the icon/text.
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS["bg_tertiary"]};
        border-radius: {Radius.PANEL}px;
    }}
    """


def error_banner_qss(object_name: str) -> str:
    """Inline error banner - shown in place of a modal QMessageBox popup so a
    failed transcription doesn't interrupt the user with a blocking dialog.
    """
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS["bg_tertiary"]};
        border: {Border.ERROR_BOX}px solid {COLORS["error"]};
        border-left: {Border.ERROR_ACCENT}px solid {COLORS["error"]};
        border-radius: {Radius.PANEL}px;
    }}
    """


def line_edit_qss() -> str:
    """A single-line text field, with the secondary buttons' control outline.
    :focus rather than the kbdFocus property: a text
    field shows its caret whichever way focus arrived, so the ring should too.
    """
    return f"""
    QLineEdit {{
        background-color: {COLORS["bg_tertiary"]};
        color: {COLORS["text_primary"]};
        border: {Border.CONTROL}px solid {COLORS["control_border"]};
        border-radius: {Radius.CONTROL}px;
        padding: 7px 12px;
        selection-background-color: {COLORS["accent"]};
        selection-color: {COLORS["accent_text"]};
    }}
    QLineEdit:focus {{
        border-color: {COLORS["focus"]};
    }}
    """


def term_row_qss(object_name: str) -> str:
    """One row of the terms dialog's list, and its remove button - the same
    icon-only button the step 1 file list uses, with the hover fill one step
    darker because these rows already sit on bg_tertiary.

    Scoped to the row's object name: a bare background rule on the list's
    holder would cascade into every row and button inside it.
    """
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS["bg_tertiary"]};
        border-radius: 10px;
    }}
    QFrame#{object_name}:hover {{
        background-color: {COLORS["surface_hover"]};
    }}
    QFrame#{object_name} QPushButton {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: 4px;
    }}
    QFrame#{object_name} QPushButton:hover {{
        background-color: {COLORS["bg_primary"]};
    }}
    QFrame#{object_name} QPushButton[kbdFocus="true"] {{
        background-color: {COLORS["bg_primary"]};
        border-color: {COLORS["focus"]};
    }}
    """


def result_panel_qss(object_name: str) -> str:
    # XL, not XXL: XXL padding falls into step 3's layout trap
    # (TranscriptionStep._build_page_layout).
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS["bg_tertiary"]};
        border-radius: {Radius.PANEL}px;
        padding: {Spacing.XL}px;
    }}
    """


def _main_window_qss() -> str:
    return f"""
    QMainWindow {{
        background-color: {COLORS["bg_primary"]};
    }}"""


def _tooltip_qss() -> str:
    return f"""
    QToolTip {{
        background-color: {COLORS["bg_tertiary"]};
        color: {COLORS["text_primary"]};
        border: {Border.HAIRLINE}px solid {COLORS["control_border"]};
        border-radius: {Radius.CONTROL}px;
        padding: {Spacing.XS}px {Spacing.SM}px;
    }}"""


def _focus_ring_qss() -> str:
    # QSS has no outline box outside the layout, so the ring recolours an
    # existing border - listed per bordered control (buttons have their own),
    # since a bare QWidget rule would only add dead CSS to borderless ones.
    return f"""
    QRadioButton[kbdFocus="true"], QCheckBox[kbdFocus="true"] {{
        border-color: {COLORS["focus"]};
    }}"""


def _radio_button_qss() -> str:
    # Any ::indicator property turns off the native indicator, so every state
    # is written out (a missed one renders blank). The checked dot is a
    # radial gradient with a hard stop: a flat fill would be a solid disc.
    return f"""
    QRadioButton {{
        color: {COLORS["text_primary"]};
        background: transparent;
        spacing: {Spacing.SM}px;
    }}
    QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 9px;
        border: {Border.CONTROL}px solid {COLORS["control_border"]};
        background-color: {COLORS["bg_tertiary"]};
    }}
    QRadioButton::indicator:hover {{
        border-color: {COLORS["accent_hover"]};
    }}
    QRadioButton::indicator:checked {{
        border-color: {COLORS["accent"]};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {COLORS["accent"]}, stop:0.45 {COLORS["accent"]}, stop:0.5 transparent);
    }}
    QRadioButton::indicator:checked:hover {{
        border-color: {COLORS["accent_hover"]};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {COLORS["accent_hover"]}, stop:0.45 {COLORS["accent_hover"]}, stop:0.5 transparent);
    }}
    QRadioButton::indicator:disabled {{
        border-color: {COLORS["border"]};
        background-color: {COLORS["bg_tertiary"]};
    }}
    QRadioButton::indicator:checked:disabled {{
        border-color: {COLORS["text_disabled"]};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {COLORS["text_disabled"]}, stop:0.45 {COLORS["text_disabled"]}, stop:0.5 transparent);
    }}
    QRadioButton[kbdFocus="true"]::indicator {{
        border-color: {COLORS["focus"]};
    }}"""


def _checkbox_qss() -> str:
    # No ::indicator rule at all: even one property makes QStyleSheetStyle
    # claim the indicator and pre-empt PaintedCheckboxStyle
    # (gui/checkbox_style.py), which paints it at the real device pixel ratio.
    return f"""
    QCheckBox {{
        color: {COLORS["text_primary"]};
        background: transparent;
        spacing: {Spacing.SM}px;
    }}"""


def _scroll_bar_qss() -> str:
    # Slim and flat. The step buttons collapse to zero size (QSS has no
    # display: none); the page areas stay transparent, or they paint a second,
    # wider bar behind the handle.
    return f"""
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:vertical {{
        background-color: {COLORS["border"]};
        border-radius: {Radius.BADGE}px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {COLORS["control_border"]};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
    }}

    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {COLORS["border"]};
        border-radius: {Radius.BADGE}px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {COLORS["control_border"]};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}"""


def app_stylesheet() -> str:
    """App-wide QSS defaults, kept small (per-widget sheets override it).

    Themes the natively drawn radio, checkbox and scrollbar, which
    are light-blue Windows controls otherwise, and the focus ring - scoped to
    [kbdFocus="true"], not :focus, which rings mouse and default focus too
    (gui/focus.py).
    """
    return (
        f"{_main_window_qss()}{_tooltip_qss()}{_focus_ring_qss()}"
        f"{_radio_button_qss()}{_checkbox_qss()}"
        f"{_scroll_bar_qss()}\n    "
    )


def elevation_shadow(
    blur_radius: int = 32, y_offset: int = 10, alpha: int = 130
) -> QGraphicsDropShadowEffect:
    """A soft, wide shadow for static surfaces that should look raised.

    Used sparingly: on Mocha's near-black ramp a shadow has little darkness to
    add (hence the wide blur), and QGraphicsDropShadowEffect paints outside its
    widget and glitches inside a QScrollArea. So only the step-3 result panel
    and the error banner, both static with room around them.
    """
    effect = QGraphicsDropShadowEffect()
    effect.setBlurRadius(blur_radius)
    effect.setOffset(0, y_offset)
    effect.setColor(QColor(0, 0, 0, alpha))
    return effect


def gradient_text_pixmap(
    text: str,
    font: QFont,
    start_color_key: str = "accent",
    end_color_key: str = "accent_hover",
    padding: int = 4,
    dpr: float = 1.0,
) -> QPixmap:
    """Text filled with a vertical gradient, as a QPixmap - QSS cannot colour
    text with a gradient. The header title only.

    dpr: the target screen's ratio; the pixmap is allocated at size * dpr and
    tagged with it, so it draws 1:1 instead of being stretched.
    """
    # Metrics from a paint device carrying the real dpr: the plain form
    # under-measures on scaled screens and clips the title.
    device = QPixmap(1, 1)
    device.setDevicePixelRatio(dpr)
    metrics = QFontMetrics(font, device)
    width = metrics.horizontalAdvance(text) + padding * 2
    height = metrics.height() + padding * 2
    # Logical (device-independent) drawing rect - painting on a QPixmap
    # that has setDevicePixelRatio() applied happens in these coordinates,
    # not in the pixmap's raw pixel dimensions, so this is reused for both
    # painters below instead of each mask/result's own .rect().
    logical_rect = QRect(0, 0, width, height)

    pixel_width = math.ceil(width * dpr)
    pixel_height = math.ceil(height * dpr)

    mask = QPixmap(pixel_width, pixel_height)
    mask.setDevicePixelRatio(dpr)
    mask.fill(Qt.GlobalColor.transparent)
    painter = QPainter(mask)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(logical_rect, Qt.AlignmentFlag.AlignCenter, text)
    painter.end()

    result = QPixmap(pixel_width, pixel_height)
    result.setDevicePixelRatio(dpr)
    result.fill(Qt.GlobalColor.transparent)
    result_painter = QPainter(result)
    result_painter.drawPixmap(0, 0, mask)
    result_painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0, QColor(COLORS[start_color_key]))
    gradient.setColorAt(1, QColor(COLORS[end_color_key]))
    result_painter.fillRect(logical_rect, gradient)
    result_painter.end()

    return result
