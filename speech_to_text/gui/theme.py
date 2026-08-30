"""
Theme system for the Speech-to-Text Transcriber GUI.

Single source of truth for colors, fonts, spacing, and QSS (Qt stylesheet)
generation - and, as of this token layer, for the radius/border/motion
constants that the QSS builders read instead of embedding literals. This
keeps a later value-only redesign a one-file change instead of a hunt
through string literals scattered across the builder bodies. Palette:
Catppuccin Mocha, with peach as the accent. The app used to run a
bespoke amber/copper-on-charcoal palette, but the HTML transcript it
produces is styled with Catppuccin (see
speech_to_text/core/assets/css/00-tokens.css), so the app and its own
output read as two different products. Peach was picked as the
replacement accent because it is the nearest Catppuccin color to the
old copper accent (#C9814A) by measured RGB distance (92.9, versus
103.4 for the next closest, Mocha red) and the only close match that keeps the same warm
register the app had before - so the redesign is a palette swap, not a
mood change. The one deliberate exception is the header title text,
which uses a peach-toned gradient fill as a one-off brand accent (see
gradient_text_pixmap).

Ordering rule for the two stylesheet layers: app_stylesheet() is applied
once on the QApplication and holds only defaults (e.g. QToolTip, the main
window background). Per-widget setStyleSheet(...) calls made by
MainWindow and the step widgets are applied afterward on top of it, and
Qt's cascade means the more specific, later-applied per-widget sheet
always wins over the app-wide one. So anything that needs to differ per
widget instance (button variants, selected-card borders, etc.) stays a
per-widget call - app_stylesheet() is not the place to fight it.
"""

import os
import tempfile

from PyQt5.QtCore import QStandardPaths, Qt
from PyQt5.QtGui import QFont, QFontMetrics, QLinearGradient, QColor, QPainter, QPixmap
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
    # An earlier draft of this palette used text_disabled (3.84/3.59/3.36)
    # here instead, which would have shipped failing captions on two of
    # the three screens; caught by contrast measurement, not by eye.
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
# and label role: it's the weight that reads as deliberate and current:
# Bold at every level (the pre-redesign scale used QFont.Bold everywhere)
# reads as heavy and dated because nothing is held in reserve for actual
# emphasis. Segoe UI Semibold is a real installed cut on Windows, so this
# maps onto genuine hinted glyphs rather than a synthetically bolded font.
_DEMIBOLD = QFont.DemiBold


class _FontsMeta(type):
    """
    Builds each Fonts role on first use, not at class-definition time.

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
    pixmap and lost a character off each end. That went unseen while the
    title was 12pt (the shortfall still fit inside the padding) and appeared
    the moment the type scale moved it to 13pt.

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

    def __getattr__(cls, name):
        try:
            size, demibold = cls._SPECS[name]
        except KeyError:
            raise AttributeError(
                f"{cls.__name__} has no font role {name!r}"
            ) from None
        font = QFont(FONT_FAMILY, size, _DEMIBOLD) if demibold else QFont(FONT_FAMILY, size)
        # Only memoise once the font database is real - see the class
        # docstring. Before that, hand back a correct-for-now object without
        # committing to it.
        if QApplication.instance() is not None:
            setattr(cls, name, font)
        return font


class Fonts(metaclass=_FontsMeta):
    """
    Named font roles, resolved lazily by _FontsMeta - read its docstring
    before adding one as a plain class attribute, which would reintroduce
    the pre-QApplication resolution bug.

    The scale widens size gaps between roles (10/11/12pt used to sit one
    point apart, which reads as noise rather than hierarchy) and moves
    weight onto DemiBold so size is no longer the only lever carrying the
    hierarchy - see _DEMIBOLD above for why DemiBold specifically.

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
    # Added for the "elevated and generous" pass. XXL is the step page
    # margin (was XL) - spent on steps 1 and 3, which this redesign's room
    # analysis found had slack (an ~85px empty band under step 1's file
    # list, a large empty middle on step 3). XXXL is a bigger single jump,
    # used sparingly, for the handful of places on those two steps that can
    # absorb a full 40px without pushing anything else out of the fixed
    # 650x600 window - never used on step 2, which has no slack to spend.
    XXL = 28
    XXXL = 40


class Radius:
    """
    Named corner radii (px), grouped by what the rounded element is - not
    by size - so a later redesign can change one kind of surface without
    guessing which literal belongs to which. Values moved from the
    pre-redesign scale (CONTROL 8 / PANEL 10 / DROP_ZONE 12 / BADGE 4) to
    the "elevated and generous" scale below, matching the HTML transcript
    document's own --control-radius/--panel-radius system so a control
    looks like a control and a surface looks like a surface the same way
    whether you're looking at the app or the document it produces.

    Note the ordering flips from before: CONTROL (14) is now larger than
    PANEL (12). That's deliberate, not a typo - small interactive things
    (buttons, the progress bar) read as more current with a rounder,
    almost-pill corner, while bigger static surfaces (cards, panels) stay
    a little tighter so they read as "container" rather than "control" at
    a glance - the same relationship the old scale expressed, just with
    softer absolute values on both ends.
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
    # CONTROL rather than keeping its own small literal: at the badge's
    # actual pixel height (~20px with its padding), a radius this size
    # exceeds half that height, which is exactly what turns a rounded
    # rectangle into a true stadium/pill shape - the look "pill-shaped"
    # already implied before the value backed it up.
    BADGE = CONTROL
    # The checkbox indicator's own rounding. Deliberately NOT Radius.BADGE
    # (which the pre-redesign code borrowed it from, coincidentally, when
    # BADGE was small enough not to matter): the checkbox indicator is an
    # 18x18 box, and BADGE is now 14 - large enough to round an 18px square
    # into a near-circle, which would read as a second radio button rather
    # than a checkbox. Kept at the old BADGE literal so the checkbox stays
    # a visibly rounded square next to the now-fully-circular radio.
    CHECKBOX = 4


class Border:
    """
    Named border widths (px), same grouping rationale as Radius: named for
    what they outline, not for their thickness. Values unchanged from
    what each builder used before this token layer existed.
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
    """
    Named animation durations (ms). There is exactly one animation in the
    app today (the transcription step's progress bar, animated with
    QEasingCurve.OutCubic in transcription.py) - PROGRESS_MS names that
    duration here so a later step can retune it in one place, but wiring
    it into transcription.py is out of scope for this token layer.
    """

    # Progress bar fill animation duration.
    PROGRESS_MS = 500
    # Budget for the micro-interactions (hover/press transitions etc.) a
    # later step adds. Shorter than PROGRESS_MS because those are small,
    # frequent state changes that should feel instant, not showcased.
    FAST_MS = 160


def button_primary_qss() -> str:
    # border: 2px solid transparent, not "none" - a keyboard-focus ring
    # needs a border to color (see the [kbdFocus] rule below and
    # gui/focus.py for why native :focus can't be used instead), and
    # Qt has no CSS 'outline' that sits outside a widget without changing
    # its box. Transparent at Border.CONTROL width is invisible in every
    # other state - same pixels as "none" once painted - so this adds a
    # new capability without changing how the button already looks; only
    # the focus rule's border-color override is new to the eye.
    return f"""
    QPushButton {{
        background-color: {COLORS['accent']};
        color: {COLORS['accent_text']};
        border: {Border.CONTROL}px solid transparent;
        border-radius: {Radius.CONTROL}px;
        padding: 10px 20px;
        font-weight: 600;
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
        color: {COLORS['text_disabled']};
    }}
    QPushButton[kbdFocus="true"] {{
        border-color: {COLORS['focus']};
    }}
    """


def button_secondary_qss(padding: str = "8px 18px") -> str:
    """
    padding: override for small fixed-size buttons (e.g. the header
    language toggle passes "2px 4px" - the default 18px side padding plus
    the 2px border would leave almost no room for text in a ~50px button).
    """
    return f"""
    QPushButton {{
        background-color: transparent;
        color: {COLORS['text_primary']};
        border: {Border.CONTROL}px solid {COLORS['control_border']};
        border-radius: {Radius.CONTROL}px;
        padding: {padding};
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {COLORS['bg_tertiary']};
        border-color: {COLORS['accent']};
        color: {COLORS['accent']};
    }}
    QPushButton:pressed {{
        background-color: {COLORS['surface_hover']};
        border-color: {COLORS['accent_dark']};
        color: {COLORS['accent_dark']};
    }}
    QPushButton:disabled {{
        background-color: transparent;
        border-color: {COLORS['border']};
        color: {COLORS['text_disabled']};
    }}
    QPushButton[kbdFocus="true"] {{
        border-color: {COLORS['focus']};
    }}
    """


def button_danger_qss() -> str:
    """
    Armed-cancel treatment (see MainWindow._on_cancel_clicked): Cancel's
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
        color: {COLORS['error']};
        border: {Border.CONTROL}px solid {COLORS['error']};
        border-radius: {Radius.CONTROL}px;
        padding: 8px 18px;
        font-weight: 600;
        font-size: 12px;
    }}
    QPushButton:hover {{
        background-color: {COLORS['bg_tertiary']};
        border-color: {COLORS['error']};
        color: {COLORS['error']};
    }}
    QPushButton:pressed {{
        background-color: {COLORS['surface_hover']};
        border-color: {COLORS['error']};
        color: {COLORS['error']};
    }}
    QPushButton[kbdFocus="true"] {{
        border-color: {COLORS['focus']};
    }}
    """


def frame_bg_qss(color_key: str = "bg_primary") -> str:
    return f"background-color: {COLORS[color_key]};"


def text_qss(color_key: str, extra: str = "") -> str:
    """
    Style for a QLabel sitting on a colored parent frame.

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
    # Unselected uses control_border, not the decorative 'border' hairline.
    # The card is drawn at Border.CONTROL width and is the visual boundary
    # of a selectable radio option (each card owns exactly one
    # QRadioButton) - its outline is part of "which of these seven things
    # can I pick", the same question the radio's own indicator answers, so
    # it needs the 3:1-clearing color even before it becomes the selected
    # one. 'border' would fail that floor and read as though only the
    # selected card (accent-outlined) were interactive at all.
    border_color = COLORS['accent'] if selected else COLORS['control_border']
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_tertiary']};
        border: {Border.CONTROL}px solid {border_color};
        border-radius: {Radius.PANEL}px;
        padding: 0px;
    }}
    QFrame#{object_name}[kbdFocus="true"] {{
        border-color: {COLORS['focus']};
    }}
    """


def progress_bar_qss() -> str:
    """
    No text-align/color rule here, and the bar itself runs with
    setTextVisible(False) - see TranscriptionStep. QProgressBar centres its
    percentage label over whichever of the two surfaces happens to be under
    it, so the ink has to be legible on the filled chunk AND on the empty
    groove, and with an accent-filled chunk no single color is: light ink
    reads 1.22:1 on the peach and dark ink reads 1.14:1 on the groove. The
    old copper palette had the same defect more mildly (2.60:1) and it was
    simply never noticed. The bar's own fill already shows progress, and the
    status and elapsed/remaining lines directly beneath it carry the detail,
    so the unreadable number is removed rather than recolored.
    """
    return f"""
    QProgressBar {{
        background-color: {COLORS['bg_tertiary']};
        border-radius: {Radius.CONTROL}px;
        border: none;
        height: 24px;
    }}
    QProgressBar::chunk {{
        background-color: {COLORS['accent']};
        border-radius: {Radius.CONTROL}px;
    }}
    """


def drop_zone_qss(object_name: str, active: bool = False) -> str:
    bg = COLORS['bg_secondary'] if active else COLORS['bg_tertiary']
    border_color = COLORS['accent_hover'] if active else COLORS['accent']
    return f"""
    QFrame#{object_name} {{
        background-color: {bg};
        border: {Border.CONTROL}px dashed {border_color};
        border-radius: {Radius.DROP_ZONE}px;
    }}
    QFrame#{object_name}[kbdFocus="true"] {{
        border-style: solid;
        border-color: {COLORS['focus']};
    }}
    """


def header_qss(object_name: str) -> str:
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_secondary']};
        border: none;
        border-bottom: {Border.HAIRLINE}px solid {COLORS['accent']};
        padding: 0px;
    }}
    """


def nav_bar_qss(object_name: str) -> str:
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_secondary']};
        border-top: {Border.HAIRLINE}px solid {COLORS['border']};
        padding: 12px 16px;
    }}
    """


def badge_qss() -> str:
    # padding widened slightly alongside the BADGE radius bump (4px -> 14px,
    # tracking Radius.CONTROL - see Radius docstring): the taller radius
    # only reads as a pill if the label has enough vertical room for the
    # curve to show, rather than getting clipped flat by tight padding.
    return f"""
    QLabel {{
        background-color: {COLORS['accent']};
        color: {COLORS['accent_text']};
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
        background-color: {COLORS['bg_tertiary']};
        border-radius: {Radius.PANEL}px;
    }}
    """


def error_banner_qss(object_name: str) -> str:
    """
    Inline error banner - shown in place of a modal QMessageBox popup so a
    failed transcription doesn't interrupt the user with a blocking dialog.
    """
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_tertiary']};
        border: {Border.ERROR_BOX}px solid {COLORS['error']};
        border-left: {Border.ERROR_ACCENT}px solid {COLORS['error']};
        border-radius: {Radius.PANEL}px;
    }}
    """


def result_panel_qss(object_name: str) -> str:
    # Padding widened from 16px (Spacing.LG) to Spacing.XL: step 3 has a
    # large empty middle at 650x600, and the result panel is the one
    # surface on that step that benefits from more breathing room around
    # its checkmark/message/path/button stack. Stopped at XL rather than
    # XXL - measured empirically (see TranscriptionStep's layout-spacing
    # comment): at XXL padding the panel's own minimum height, added to
    # the rest of the step's content, exceeded the 471px this step
    # actually gets, and Qt's AlignCenter layout responded by compressing
    # the panel itself down to a near-empty sliver instead of clipping the
    # overflow. XL is the largest padding that stays clear of that.
    return f"""
    QFrame#{object_name} {{
        background-color: {COLORS['bg_tertiary']};
        border-radius: {Radius.PANEL}px;
        padding: {Spacing.XL}px;
    }}
    """


def _glyph_cache_dir() -> str:
    """
    A per-user, app-owned directory for the generated glyphs.

    GenericCacheLocation rather than CacheLocation because the latter is
    derived from QCoreApplication's organization/application names, which
    this app never sets (its QSettings identity is passed explicitly - see
    gui/i18n.py), so it would resolve off the host executable's name and
    differ between a normal run and a frozen build. This is
    %LOCALAPPDATA%\cache on Windows and ~/.cache elsewhere, both per-user,
    with our own subdirectory under it.

    The mode is only honoured on POSIX; Windows already scopes
    LOCALAPPDATA to the user, so it is belt and braces rather than the
    primary control.
    """
    base = QStandardPaths.writableLocation(QStandardPaths.GenericCacheLocation)
    if not base:
        base = tempfile.gettempdir()
    cache_dir = os.path.join(base, "HebrewAudioTranscriber", "glyphs")
    os.makedirs(cache_dir, mode=0o700, exist_ok=True)
    return cache_dir


def _glyph_image_url(icon_name: str, size: int, color: str, rotation: int = 0) -> str:
    """
    Rasterize an ICONS[...] entry (see gui/icons.py) to a cached temp PNG
    and return a QSS 'image: url(...)' fragment pointing at it - or "" if
    that fails for any reason. Shared by every QSS rule in this module that
    needs a glyph QSS can't draw from borders/background alone: the
    checkbox tick and the spin box up/down arrows.

    QSS can draw a control's fill and border from plain
    background-color/border rules, but not an arbitrary glyph on top of
    it - 'image:' needs a real raster asset. svg_to_pixmap() needs a
    QPainter, which needs a QApplication to already exist, so this is only
    ever called lazily from app_stylesheet() (applied to the QApplication
    after it's constructed), never at module import time, when no
    QApplication is guaranteed to exist yet (e.g. under pytest collection).

    The filename encodes every input that changes the pixel content - icon,
    size, color, rotation - rather than just the glyph's role, so a palette
    change lands on a different name instead of quietly reusing yesterday's
    color forever.

    It is written to a per-user cache directory of our own, NOT the shared
    temp dir, and it is regenerated on every run rather than reused when a
    file already happens to be sitting at that path. Both halves of that
    matter, and the second is the important one: a predictable name in a
    shared directory plus a bare os.path.exists check means any process
    that can write there can pre-create the file, and this function would
    then hand Qt an image nobody here produced. The glyphs in question are
    a checkbox tick and the spin box arrows - the tick sits on the control
    that decides whether diarization runs at all, so a spoofed "checked"
    state is a real misrepresentation, and either way it feeds unvetted
    bytes to an image decoder. Regenerating unconditionally removes the
    trust-on-existence entirely, and costs three small rasterizations once
    per process.

    Deliberately swallows every exception: this is a cosmetic asset, not
    something that should be able to crash stylesheet construction. On
    failure the caller's control still works via its plain background/
    border rules - it just loses the glyph on top, which is a fallback
    worth having rather than a half-built pipeline that silently ships a
    blank box (checkbox) or an unlabeled button (spin box arrows).
    """
    color_tag = color.lstrip("#")
    cache_name = f"glyph_{icon_name}_{size}_{color_tag}_{rotation}.png"
    try:
        cache_path = os.path.join(_glyph_cache_dir(), cache_name)

        from PyQt5.QtGui import QTransform

        from speech_to_text.gui.icons import ICONS, svg_to_pixmap

        pixmap = svg_to_pixmap(ICONS[icon_name], size=size, color=color)
        if rotation:
            pixmap = pixmap.transformed(QTransform().rotate(rotation), Qt.SmoothTransformation)

        # Rendered to a fresh O_EXCL file and moved into place, rather than
        # saved straight onto the final name. Writing to the destination
        # directly would follow anything already sitting there, and would
        # also let a second instance starting at the same moment read a
        # half-written PNG; os.replace is atomic and swaps the name itself.
        handle, staging = tempfile.mkstemp(prefix=cache_name, suffix=".part",
                                           dir=os.path.dirname(cache_path))
        os.close(handle)
        try:
            if not pixmap.save(staging, "PNG"):
                os.unlink(staging)
                return ""
            os.replace(staging, cache_path)
        except Exception:
            if os.path.exists(staging):
                os.unlink(staging)
            raise
    except Exception:
        return ""
    # QSS's url() wants forward slashes even on Windows; a raw Windows path
    # with backslashes is silently ignored by Qt's stylesheet parser.
    return f"image: url({cache_path.replace(chr(92), '/')});"


def app_stylesheet() -> str:
    """
    Application-wide QSS, applied once on the QApplication instance. Holds
    only defaults that every widget should inherit unless a more specific
    per-widget setStyleSheet(...) call overrides it (see the ordering rule
    in the module docstring) - so this stays deliberately small.

    Currently:
      - the main window background, moved here from the setStyleSheet(...)
        call MainWindow.__init__ used to make directly (kept as a QSS rule
        rather than a QPalette tweak so it still cascades the same way).
      - a QToolTip rule. Nothing in the app sets a tooltip today, so this
        rule has no visible effect yet - it exists so a later step can add
        tooltips without also having to invent their styling.
      - QRadioButton, QCheckBox, QSpinBox and QScrollBar rules. These four
        are drawn entirely by the native Windows style when unstyled -
        nothing in this codebase ever touched them before this step - so
        without a rule here they render as light-blue Windows controls on
        top of the Catppuccin Mocha ground the rest of the app now uses.
        They belong here rather than per-widget because every instance of
        each control should look the same everywhere they appear.
      - a [kbdFocus="true"] rule as the keyboard-focus ring, scoped to that
        dynamic property rather than the native :focus pseudo-state. Native
        :focus paints for default and mouse-click focus too - which is what
        put a sapphire ring around the header language toggle on every
        launch, before this property existed - so the ring is gated behind
        gui/focus.py's KeyboardFocusTracker instead, the same "was focus
        just given by a keyboard" gate the app's own generated HTML
        transcript already uses via data-kbd (see
        core/assets/js/94-layout.js's bindKeyboardModality()).
    """
    tick_image = _glyph_image_url("check", size=14, color=COLORS["accent_text"])
    # arrow_right rotated -90/+90 becomes an up/down chevron. Tinted
    # text_secondary rather than text_primary so the arrows read as quieter
    # than the spin box's own value text, the way a native spinner's arrows
    # usually sit a notch below the field's foreground in visual weight.
    up_arrow_image = _glyph_image_url("arrow_right", size=10, color=COLORS["text_secondary"], rotation=-90)
    down_arrow_image = _glyph_image_url("arrow_right", size=10, color=COLORS["text_secondary"], rotation=90)
    return f"""
    QMainWindow {{
        background-color: {COLORS['bg_primary']};
    }}
    QToolTip {{
        background-color: {COLORS['bg_tertiary']};
        color: {COLORS['text_primary']};
        border: {Border.HAIRLINE}px solid {COLORS['control_border']};
        border-radius: {Radius.CONTROL}px;
        padding: {Spacing.XS}px {Spacing.SM}px;
    }}

    /* Generic keyboard-focus ring. Qt stylesheets have no CSS 'outline'
       box that sits outside a widget without affecting its layout, so this
       reuses border-color on widgets that already carry a border. Scoped
       to [kbdFocus="true"] (see gui/focus.py), not the native :focus
       pseudo-state - :focus paints for default and mouse-click focus too,
       which is the exact bug this property exists to fix. It's applied to
       the controls that get their own border rules below (plus
       QPushButton, handled in button_secondary_qss/button_primary_qss)
       rather than a bare 'QWidget[kbdFocus="true"]', because a bare rule
       would also paint a border-color on borderless widgets that have
       never had one (labels, frames), which does nothing useful and just
       adds dead CSS that looks like it should be doing something. */
    QRadioButton[kbdFocus="true"], QCheckBox[kbdFocus="true"], QSpinBox[kbdFocus="true"] {{
        border-color: {COLORS['focus']};
    }}

    /* QRadioButton. Setting any property on ::indicator makes Qt stop
       drawing its native indicator altogether, so every state has to be
       written explicitly - unchecked, checked, hover, disabled - or a
       missed one renders as a blank box (see module-level note in the
       redesign plan this step follows). The checked dot can't be done with
       background-color alone: a flat fill produces a solid disc, not a
       ring with a dot inside it. qradialgradient with a hard stop at 0.45
       and a transparent stop at 0.5 fakes a "dot inside a ring" using pure
       QSS - the ring itself is just the indicator's border-color. */
    QRadioButton {{
        color: {COLORS['text_primary']};
        background: transparent;
        spacing: {Spacing.SM}px;
    }}
    QRadioButton::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 9px;
        border: {Border.CONTROL}px solid {COLORS['control_border']};
        background-color: {COLORS['bg_tertiary']};
    }}
    QRadioButton::indicator:hover {{
        border-color: {COLORS['accent_hover']};
    }}
    QRadioButton::indicator:checked {{
        border-color: {COLORS['accent']};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {COLORS['accent']}, stop:0.45 {COLORS['accent']}, stop:0.5 transparent);
    }}
    QRadioButton::indicator:checked:hover {{
        border-color: {COLORS['accent_hover']};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {COLORS['accent_hover']}, stop:0.45 {COLORS['accent_hover']}, stop:0.5 transparent);
    }}
    QRadioButton::indicator:disabled {{
        border-color: {COLORS['border']};
        background-color: {COLORS['bg_tertiary']};
    }}
    QRadioButton::indicator:checked:disabled {{
        border-color: {COLORS['text_disabled']};
        background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5,
            stop:0 {COLORS['text_disabled']}, stop:0.45 {COLORS['text_disabled']}, stop:0.5 transparent);
    }}
    QRadioButton[kbdFocus="true"]::indicator {{
        border-color: {COLORS['focus']};
    }}

    /* QCheckBox. Same "own every state" rule as the radio indicator above.
       The checked fill is a plain accent-filled rounded square - that
       alone already reads unambiguously as "on" next to its label - with a
       tick glyph layered on top via 'image:' when the rasterized icon is
       available (see _checkbox_tick_image_url). QSS can't draw a tick from
       borders/background the way the radio dot is faked with a gradient,
       so the glyph has to come from an actual asset; the fill alone is the
       deliberate fallback if that asset ever fails to generate. */
    QCheckBox {{
        color: {COLORS['text_primary']};
        background: transparent;
        spacing: {Spacing.SM}px;
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: {Radius.CHECKBOX}px;
        border: {Border.CONTROL}px solid {COLORS['control_border']};
        background-color: {COLORS['bg_tertiary']};
    }}
    QCheckBox::indicator:hover {{
        border-color: {COLORS['accent_hover']};
    }}
    QCheckBox::indicator:checked {{
        border-color: {COLORS['accent']};
        background-color: {COLORS['accent']};
        {tick_image}
    }}
    QCheckBox::indicator:checked:hover {{
        border-color: {COLORS['accent_hover']};
        background-color: {COLORS['accent_hover']};
        {tick_image}
    }}
    QCheckBox::indicator:disabled {{
        border-color: {COLORS['border']};
        background-color: {COLORS['bg_tertiary']};
    }}
    QCheckBox::indicator:checked:disabled {{
        border-color: {COLORS['text_disabled']};
        background-color: {COLORS['text_disabled']};
        {tick_image}
    }}
    QCheckBox[kbdFocus="true"]::indicator {{
        border-color: {COLORS['focus']};
    }}

    /* QSpinBox. Styling ::up-button/::down-button at all makes Qt stop
       drawing its native arrow glyph on top of them - the same
       "own every state" trap documented above for ::indicator, just for
       a subcontrol's decoration instead of the whole control. The first
       version of this rule styled the button backgrounds without
       supplying ::up-arrow/::down-arrow, which left two blank dark
       rectangles - worse than the native look, because it reads as a
       broken control rather than an unstyled one. ::up-arrow/::down-arrow
       need an explicit width/height or Qt reserves no space for the
       image and it silently doesn't paint, so both are set here. */
    QSpinBox {{
        background-color: {COLORS['bg_tertiary']};
        color: {COLORS['text_primary']};
        border: {Border.CONTROL}px solid {COLORS['control_border']};
        border-radius: {Radius.CONTROL}px;
        padding: 4px 6px;
        min-width: 32px;
    }}
    QSpinBox:hover {{
        border-color: {COLORS['accent_hover']};
    }}
    QSpinBox:disabled {{
        color: {COLORS['text_disabled']};
        border-color: {COLORS['border']};
    }}
    QSpinBox[kbdFocus="true"] {{
        border-color: {COLORS['focus']};
    }}
    QSpinBox::up-button, QSpinBox::down-button {{
        background-color: {COLORS['surface_hover']};
        border: none;
        width: 16px;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
        background-color: {COLORS['control_border']};
    }}
    QSpinBox::up-arrow {{
        {up_arrow_image}
        width: 10px;
        height: 10px;
    }}
    QSpinBox::down-arrow {{
        {down_arrow_image}
        width: 10px;
        height: 10px;
    }}

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
        background-color: {COLORS['border']};
        border-radius: {Radius.BADGE}px;
        min-height: 24px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {COLORS['control_border']};
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
        background-color: {COLORS['border']};
        border-radius: {Radius.BADGE}px;
        min-width: 24px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {COLORS['control_border']};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
    }}
    """


def elevation_shadow(blur_radius: int = 32, y_offset: int = 10, alpha: int = 130) -> QGraphicsDropShadowEffect:
    """
    A soft drop shadow for the handful of static, non-scrolling surfaces
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
) -> QPixmap:
    """
    Render text filled with a vertical linear gradient, as a QPixmap.

    Qt stylesheets can't apply a gradient to text color (only to
    background-color), so this paints the text as an alpha mask and
    composites a gradient-filled pixmap into it. Used for the header title
    only - a deliberate one-off brand accent, not the general theme.
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
