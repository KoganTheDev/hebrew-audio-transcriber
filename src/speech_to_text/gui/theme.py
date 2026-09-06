"""Theme system for the Speech-to-Text Transcriber GUI.

Single source of truth for colors, fonts, spacing, and QSS (Qt stylesheet)
generation, plus the radius/border/motion constants the QSS builders read
instead of embedding literals - so a value-only redesign is a one-file
change rather than a hunt through string literals in the builder bodies.

Palette: Catppuccin Mocha, with peach as the accent. It has to match the
HTML transcript the app produces, which is styled with Catppuccin (see
speech_to_text/core/assets/css/00-tokens.css), or the app and its own
output read as two different products. Peach is the accent because it is
the nearest Catppuccin color to the app's original copper (#C9814A) by
measured RGB distance (92.9, versus 103.4 for the next closest, Mocha
red) and the only close match in the same warm register. The one
deliberate exception is the header title text, which uses a peach-toned
gradient fill as a one-off brand accent (see gradient_text_pixmap).

Ordering rule for the two stylesheet layers: app_stylesheet() is applied
once on the QApplication and holds only defaults (e.g. QToolTip, the main
window background). Per-widget setStyleSheet(...) calls made by
MainWindow and the step widgets are applied afterward on top of it, and
Qt's cascade means the more specific, later-applied per-widget sheet
always wins over the app-wide one. So anything that needs to differ per
widget instance (button variants, selected-card borders, etc.) stays a
per-widget call - app_stylesheet() is not the place to fight it.
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
# Deliberately NOT "Segoe UI Variable Display", despite it being the more
# current-looking face and despite it resolving cleanly on this machine.
# Measured with QRawFont.supportsCharacter: Variable Display has zero
# Hebrew glyph coverage (Latin/Greek/Cyrillic/Vietnamese only), while plain
# Segoe UI covers Hebrew and Arabic too. QFontInfo would still report a
# clean resolve for Variable Display, and Hebrew text would still render -
# silently, per-glyph, falling back to whatever face Qt finds next - so the
# failure doesn't show up as a missing font, it shows up as two different
# faces sharing one line (e.g. a Latin model name in Variable Display next
# to its Hebrew description in fallback-Segoe UI on the same card, in the
# Hebrew UI only). That's a worse and harder-to-spot bug than just not
# having the nicer face, so the modern feel is bought with weight instead
# (see QFont.DemiBold below, which maps to the real "Segoe UI Semibold"
# cut) rather than a family swap.

# QFont.Weight values, named here because "62" and "75" read as noise at
# every call site below. DemiBold - not Bold - is used for every heading
# and label role: Bold at every level reads as heavy and dated because
# nothing is held in reserve for actual emphasis. Segoe UI Semibold is a
# real installed cut on Windows, so this maps onto genuine hinted glyphs
# rather than a synthetically bolded font.
_DEMIBOLD = QFont.DemiBold


class _FontsMeta(type):
    """Builds each Fonts role on first use, not at class-definition time.

    This is not a style preference, it is a correctness requirement. A QFont
    constructed before a QApplication exists resolves against an
    uninitialised font database, and it keeps those wrong metrics
    afterwards: QFontMetrics on such a font reports a 227px advance for the
    header title where the same font built after QApplication reports 276px.
    speech_to_text/main.py imports this module at module level and only
    constructs its QApplication inside main(), so class-body QFont literals
    were always being built on the wrong side of that line.

    Most of the app never noticed, because a widget you merely setFont() on
    is re-resolved by Qt at paint time. What did notice is the one place
    that measures a font by hand and allocates a canvas from the answer:
    gradient_text_pixmap() sized the header title's pixmap from the
    under-reported advance, so the text painted into it was wider than the
    pixmap and lost a character off each end. The shortfall stays hidden
    while it still fits inside the padding (it did at 12pt, not at 13pt),
    which is what makes this class of bug latent rather than obvious.

    Roles are cached once a QApplication exists, and deliberately NOT cached
    before then, so an early access during import or test collection cannot
    poison the cache with a badly-resolved font for the life of the process.
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
    """Named font roles, resolved lazily by _FontsMeta - read its docstring
    before adding one as a plain class attribute, which would reintroduce
    the pre-QApplication resolution bug.

    Size gaps between roles are kept wide - a single point apart reads as
    noise rather than hierarchy - and weight carries part of the hierarchy
    too, so size is not the only lever (see _DEMIBOLD above).

    Sizes and weights live in _FontsMeta._SPECS. What each role is FOR:
      DISPLAY         step headings ("Specs", "Choose Model", "Transcribing")
      SUBTITLE_BOLD   header title via gradient_text_pixmap, step-3 headline
      BODY_BOLD       model card names, hardware values, drop zone lead line
      BODY            default body text
      BODY_BOLD_SMALL the step-3 live status line
      CAPTION         captions, error banner, model card descriptions - 9pt
                      is the floor, legible without eating step 2's tight
                      vertical budget
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
    """Named corner radii (px), grouped by what the rounded element is - not
    by size - so a later redesign can change one kind of surface without
    guessing which literal belongs to which. The values match the HTML
    transcript document's own --control-radius/--panel-radius system, so a
    control looks like a control and a surface looks like a surface the
    same way whether you're looking at the app or the document it produces.

    CONTROL (14) is deliberately larger than PANEL (12), not a typo: small
    interactive things (buttons, the progress bar) read as more current
    with a rounder, almost-pill corner, while bigger static surfaces
    (cards, panels) stay tighter so they read as "container" rather than
    "control" at a glance.
    """

    # Small interactive controls: buttons, the progress bar (track and
    # chunk), the error banner, and every native control app_stylesheet()
    # draws (checkbox/radio/spin box). The document's --control-radius.
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
    # A separator rather than an outline: the single line under the header
    # and over the nav bar, and the tooltip's edge. Distinct from ERROR_BOX
    # despite sharing a value today, because the two answer different
    # questions - ERROR_BOX is "how thick is this box's outline", HAIRLINE
    # is "how heavy is the line between two regions". A later step thickens
    # control outlines without touching separators, and one shared constant
    # would drag these along with them.
    HAIRLINE = 1


class Motion:
    """Named animation durations (ms). There is exactly one animation in the
    app today (the transcription step's progress bar, animated with
    QEasingCurve.OutCubic in transcription.py) - PROGRESS_MS names that
    duration here so a later step can retune it in one place, but wiring
    it into transcription.py is out of scope for this token layer.
    """

    PROGRESS_MS = 500
    # Budget for the micro-interactions (hover/press transitions etc.) a
    # later step adds. Shorter than PROGRESS_MS because those are small,
    # frequent state changes that should feel instant, not showcased.
    FAST_MS = 160


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
    """Armed-cancel treatment (see MainWindow._on_cancel_clicked): Cancel's
    second press stops a possibly 40-minute-long run with no further
    confirmation, so once armed the button itself should read as
    dangerous rather than relying on the neighboring hint label's wording
    alone - colour carries the warning even for a viewer who doesn't read
    the label. Same shape as button_secondary_qss (transparent fill,
    outlined) with COLORS['error'] standing in for control_border/accent
    throughout, rather than button_primary_qss's filled shape - Cancel
    should still read as the secondary action in the nav bar even while
    armed; only its colour says "the next click is destructive".

    Candidate labels that would explain the armed state in words
    ("Press again to cancel" etc.) were measured against the fixed
    130x36 nav button and all came out too wide to fit without either
    clipping or shrinking the font - both worse than no confirmation at
    all for a destructive action. So the label stays "Cancel" (it already
    fits in both languages) and the explanation moves to
    cancel_confirm_label, a plain text label beside the button with real
    room for a sentence; this function is what makes the button itself
    still carry part of that signal.
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
    # ID selector (#name) - a bare 'QFrame {...}' selector would also match QLabel,
    # since QLabel subclasses QFrame in Qt, leaking the border/background onto child text.
    # 'selected' means this card's radio button is the one currently picked -
    # not necessarily the recommended one, which gets its own separate badge.
    # Unselected uses control_border, not the decorative 'border' hairline:
    # each card is the visual boundary of a selectable radio option (it owns
    # exactly one QRadioButton), so its outline answers "which of these can
    # I pick" and needs the 3:1-clearing color even while unselected.
    # 'border' fails that floor and reads as though only the selected,
    # accent-outlined card were interactive at all.
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


def progress_bar_qss() -> str:
    """No text-align/color rule here, and the bar itself runs with
    setTextVisible(False) - see TranscriptionStep. QProgressBar centres its
    percentage label over whichever of the two surfaces happens to be under
    it, so the ink has to be legible on the filled chunk AND on the empty
    groove, and with an accent-filled chunk no single color is: light ink
    reads 1.22:1 on the peach and dark ink reads 1.14:1 on the groove. The
    bar's own fill already shows progress, and the status and
    elapsed/remaining lines directly beneath it carry the detail, so the
    unreadable number is removed rather than recolored.
    """
    return f"""
    QProgressBar {{
        background-color: {COLORS["bg_tertiary"]};
        border-radius: {Radius.CONTROL}px;
        border: none;
        height: 24px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS["accent"]};
        border-radius: {Radius.CONTROL}px;
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


def result_panel_qss(object_name: str) -> str:
    # Spacing.XL, not XXL - measured empirically (see TranscriptionStep's
    # layout-spacing comment): at XXL padding the panel's own minimum
    # height, added to the rest of the step's content, exceeded the 471px
    # this step actually gets, and Qt's AlignCenter layout responded by
    # compressing the panel down to a near-empty sliver instead of
    # clipping the overflow. XL is the largest padding that stays clear of
    # that while still giving the checkmark/message/path/button stack the
    # breathing room step 3's large empty middle can afford.
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
    return f"""

    /* Generic keyboard-focus ring. Qt stylesheets have no CSS 'outline'
       box that sits outside a widget without affecting its layout, so this
       reuses border-color on widgets that already carry a border. Listed
       per control (plus QPushButton, handled in
       button_primary_qss/button_secondary_qss) rather than as a bare
       'QWidget[kbdFocus="true"]': a bare rule would also set a
       border-color on borderless widgets like labels and frames, which
       paints nothing and just adds dead CSS. */
    QRadioButton[kbdFocus="true"], QCheckBox[kbdFocus="true"], QSpinBox[kbdFocus="true"] {{
        border-color: {COLORS["focus"]};
    }}"""


def _radio_button_qss() -> str:
    return f"""

    /* QRadioButton. Setting any property on ::indicator makes Qt stop
       drawing its native indicator altogether, so every state has to be
       written explicitly - unchecked, checked, hover, disabled - or a
       missed one renders as a blank box. The checked dot can't be done
       with background-color alone: a flat fill produces a solid disc, not
       a ring with a dot inside it. qradialgradient with a hard stop at 0.45
       and a transparent stop at 0.5 fakes a "dot inside a ring" using pure
       QSS - the ring itself is just the indicator's border-color. */
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
    return f"""

    /* QCheckBox. Deliberately NO ::indicator rule of any kind here -
       unlike QRadioButton/QSpinBox, whose indicators/arrows are still
       drawn by plain QSS. The checkbox indicator is painted by
       PaintedCheckboxStyle (gui/checkbox_style.py), a QProxyStyle
       installed on the QApplication in main_window.configure_application,
       because Qt's stylesheet 'image:' mechanism has no devicePixelRatio
       concept - see that module's docstring.

       This is not merely "no rule needed": setting even ONE
       QCheckBox::indicator{...} property here (border, background,
       anything) makes Qt's internal QStyleSheetStyle claim the whole
       indicator subcontrol and paint it from the CSS box model, which
       pre-empts PaintedCheckboxStyle.drawPrimitive() before it ever runs.
       The two are mutually exclusive for this control, so the QSS side has
       to stay silent on ::indicator - hover/disabled/kbdFocus included.
       The bare QCheckBox{...} rule below still applies: it styles the
       label text, a selector Qt's CSS capture doesn't extend to. */
    QCheckBox {{
        color: {COLORS["text_primary"]};
        background: transparent;
        spacing: {Spacing.SM}px;
    }}"""


def _spin_box_qss() -> str:
    return f"""

    /* QSpinBox. ::up-button/::down-button are styled here even though the
       app's one QSpinBox (speaker count, model_select.py) currently ships
       with setButtonSymbols(NoButtons) and never shows them - see that
       widget's own comment for why the buttons were dropped and why this
       block was deliberately kept rather than deleted alongside them, so a
       future spin box that DOES want buttons finds them already themed.
       ::up-arrow/::down-arrow are NOT styled, and styling
       ::up-button/::down-button without also supplying them leaves two
       blank dark rectangles rather than the native arrow. So a future
       widget that re-enables the buttons has to draw the arrows itself,
       with a painted QProxyStyle primitive following checkbox_style.py's
       pattern - not the rasterize-to-QSS-'image:' path, which
       checkbox_style.py's docstring explains was retired wholesale. */
    QSpinBox {{
        background-color: {COLORS["bg_tertiary"]};
        color: {COLORS["text_primary"]};
        border: {Border.CONTROL}px solid {COLORS["control_border"]};
        border-radius: {Radius.CONTROL}px;
        padding: 4px 6px;
        min-width: 32px;
    }}
    QSpinBox:hover {{
        border-color: {COLORS["accent_hover"]};
    }}
    QSpinBox:disabled {{
        color: {COLORS["text_disabled"]};
        border-color: {COLORS["border"]};
    }}
    QSpinBox[kbdFocus="true"] {{
        border-color: {COLORS["focus"]};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background-color: {COLORS["surface_hover"]};
        border: none;
        width: 16px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background-color: {COLORS["control_border"]};
    }}"""


def _scroll_bar_qss() -> str:
    return f"""

    /* QScrollBar. Slim and flat, no arrow buttons - the model list on the
       model-select step is the one place this is visible today. Both
       add-line/sub-line subcontrols are collapsed to zero size rather than
       hidden, because 'display: none' isn't a QSS property; zero size is
       the documented way to remove a scrollbar's step buttons. The
       page-step area (::add-page/::sub-page) is left transparent so only
       the groove and handle read as the bar - a background there would
       paint a second, wider bar behind the actual handle. */
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
    """Application-wide QSS, applied once on the QApplication instance. Holds
    only defaults that every widget should inherit unless a more specific
    per-widget setStyleSheet(...) call overrides it (see the ordering rule
    in the module docstring) - so this stays deliberately small.

    QRadioButton, QCheckBox, QSpinBox and QScrollBar are drawn entirely by
    the native Windows style when unstyled, which renders them as
    light-blue Windows controls on top of the Catppuccin Mocha ground the
    rest of the app uses. They are themed here rather than per-widget
    because every instance of each control should look the same everywhere
    it appears. The keyboard-focus ring (_focus_ring_qss) is app-wide for
    the same reason; it is scoped to the [kbdFocus="true"] dynamic property
    rather than the native :focus pseudo-state, which paints for default
    and mouse-click focus too and so put a sapphire ring around the header
    language toggle on every launch - see gui/focus.py.
    """
    return (
        f"{_main_window_qss()}{_tooltip_qss()}{_focus_ring_qss()}"
        f"{_radio_button_qss()}{_checkbox_qss()}{_spin_box_qss()}"
        f"{_scroll_bar_qss()}\n    "
    )


def elevation_shadow(
    blur_radius: int = 32, y_offset: int = 10, alpha: int = 130
) -> QGraphicsDropShadowEffect:
    """A soft drop shadow for the handful of static, non-scrolling surfaces
    that should read as physically raised off the window's crust ground.

    Deliberately NOT used everywhere elevation could apply - two reasons,
    both specific to this app's palette and layout rather than shadows in
    general:

    1. Catppuccin Mocha's crust/mantle/base ramp (#11111b / #181825 /
       #1e1e2e - see the module docstring) is already a near-black-to-
       less-black progression, so a shadow on top of it has very little
       darkness left to add. A shadow that would read clearly on a white
       or mid-gray ground is close to invisible here; this compensates
       with a wider blur (soft ambient falloff reads even at low contrast)
       rather than a tighter, more opaque shadow that would just look like
       a hard dark smear at the surface's edge.
    2. QGraphicsDropShadowEffect is a known source of repaint artifacts on
       a widget living inside a QScrollArea, and it paints outside the
       widget's own rect - clipped away entirely unless the parent layout
       already has margin room for it to bleed into. That rules it out for
       the model-select cards (see ModelSelectStep, which tried and
       dropped it - repaint glitches on scroll, no clean way to reserve
       the bleed margin inside the scroll viewport) even though a
       "selected card" shadow was the first thing tried there.

    So: applied only to the step-3 result panel and the step-2/3 error
    banner - both static, both sitting in a plain QVBoxLayout with margin
    to spare, neither ever inside a QScrollArea.
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
    """Render text filled with a vertical linear gradient, as a QPixmap.

    Qt stylesheets can't apply a gradient to text color (only to
    background-color), so this paints the text as an alpha mask and
    composites a gradient-filled pixmap into it. Used for the header title
    only - a deliberate one-off brand accent, not the general theme.

    dpr: devicePixelRatio of the screen/widget this will be shown on
    (typically the MainWindow's - pass window.devicePixelRatioF()). The
    backing stores are allocated at (logical size) * dpr, rounded up, and
    tagged with setDevicePixelRatio(dpr) so the QLabel that displays this
    draws it 1:1 instead of Qt (or Windows, pre-high-DPI-awareness)
    stretching a 1x raster into something visibly soft. This is the app's
    only hand-rasterized pixmap; everything else is drawn from vector QSS
    or painted directly.
    """
    # A device-aware QFontMetrics, not the bare single-argument form: the
    # single-argument form resolves metrics against the application's
    # default font database, which has no idea this pixmap is destined for
    # a higher-dpr screen and under-measures accordingly, which clips the
    # title. A throwaway 1x1 QPixmap carrying the real dpr gives
    # QFontMetrics a paint device to measure against that matches what
    # will actually be rendered below.
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
