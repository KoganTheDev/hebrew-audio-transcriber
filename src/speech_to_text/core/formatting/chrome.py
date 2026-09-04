"""
Page chrome: the icon sprite, toolbar, mini-player, toast and help panel.

These are the parts of the document that are the same no matter which file or
turn is being read - "the frame around the transcript" rather than the
transcript itself, which is document.py's job instead.

Also the home for the handful of tiny helpers document.py needs too (_t,
_button, _palette_index, _speaker_fallback, SPEAKER_PALETTE_SIZE, _icon):
_icon has to live here regardless, since every icon site in this module
reaches it, and _button is built directly on top of _icon (it assembles an
icon plus a label into one <button>), so the rest of this small "generic
widget" cluster rides along rather than forcing a fourth near-empty module
for a handful of one-line functions. document.py imports what it needs from
here; chrome.py never imports from document.py, so there is no cycle.
"""

import html
import re
from typing import Dict, Optional

from .timecode import LRI, PDI

# Matches any letter in the Hebrew Unicode block. Used to tell which way an
# already-translated UI string reads, without this module (or anything else
# under speech_to_text/core) importing gui.i18n to ask it directly - see
# _input_dir()'s own docstring for why that has to be the case.
_HEBREW_LETTER = re.compile(r"[֐-׿]")


def _input_dir(text: str) -> str:
    """
    "ltr" or "rtl", guessed from whether `text` itself contains a Hebrew
    letter - the only signal this module has for which way a translated UI
    string reads.

    The document this renders into is always dir="rtl" (see
    core/formatting/__init__.py's _render_head_html()): it is the transcript
    itself, and the transcript's own content - turns, timestamps, speaker
    names - is Hebrew speech, regardless of which language the surrounding
    app chrome happens to be in. But the chrome strings (this function exists
    for their sake, not the transcript's) are the app's own UI language,
    which an English-language run makes English text sitting inside that
    RTL document. An <input> given no dir of its own inherits dir="rtl" from
    the document, and an English placeholder inside an RTL-direction field
    anchors to the right and overflows to the left - so when the field is too
    narrow to show it whole (see #search's own "release valve" comment in
    core/assets/css/16-toolbar.css), the clipped fragment is the START of the
    string, which is the unreadable half. Giving the field its own dir,
    matching the language actually inside it, fixes where the clip lands: an
    LTR field overflows at its own end, so a clipped "Search transc..." still
    reads as a truncated but legible word, not a stray fragment.
    speech_to_text.core cannot import gui.i18n to just ask it what language
    is active (see the package docstring on that hard constraint), and
    ui_strings already arrives here as plain translated data with no
    language tag riding along - threading one through render_html(),
    _build_payload(), _render_toolbar_html() and this function only to reach
    a single call site would be a lot of new plumbing for what the string
    already answers for free: every string in STRINGS is either recognisably
    Hebrew or recognisably not, so asking the string itself is both correct
    and the smaller change.
    """
    return "rtl" if _HEBREW_LETTER.search(text) else "ltr"


# Eight swatches, verified in tests/test_transcript_styles.py against the
# composited panel background. Not a soft limit picked for symmetry - it's
# the size of the PAIRS table that guarantees every colour a speaker can wear
# still reads at 4.5:1. A ninth colour someone likes but never measures is
# exactly the failure this palette-only design (rather than a free picker)
# exists to rule out, so speaker identity wraps around it via modulo rather
# than growing past it.
SPEAKER_PALETTE_SIZE = 8


def _t(strings: Dict[str, str], key: str, fallback: str) -> str:
    """
    An already-translated, HTML-escaped UI string, or its English fallback.

    The single choke point for `html.escape(strings.get(key, fallback))`,
    which used to be written out by hand at every call site that needed a
    translated label - three functions each defined a byte-identical local
    closure for it, and eleven more sites inlined it directly. One function
    means one place to get the escaping right, and a diff on this function
    is a diff every call site benefits from.
    """
    return html.escape(strings.get(key, fallback))


def _palette_index(n: int) -> int:
    """
    A speaker's (or a file's) slot in the verified 8-swatch palette.

    Same `n % SPEAKER_PALETTE_SIZE` used for a turn's speaker colour, a
    speaker row's colour, and a file's accent stripe - three different
    things that all wrap around the same eight-colour, contrast-verified
    palette, so they share the one formula that does it rather than each
    retyping the modulo.
    """
    return n % SPEAKER_PALETTE_SIZE


def _speaker_fallback(speaker_label: str, speaker: int) -> str:
    """
    A speaker's human-facing label: 0-based internally, 1-based to a reader.

    Returns unescaped text on purpose. Every call site html.escape()s this
    itself, right where it lands in an attribute or a text node - including
    the plain-text panel's heading (_render_plain_html), which used to be the
    one exception (it folded an unescaped name into a whole prefix string
    escaped once as a unit) back when a row's heading was inline text rather
    than its own element.
    """
    return speaker_label.format(n=speaker + 1)


def _button(
    label: Optional[str],
    *,
    id_attr: Optional[str] = None,
    css_class: str = "tb-btn",
    icon: Optional[str] = None,
    aria_label: Optional[str] = None,
    extra: str = "",
    wrap_label: bool = True,
) -> str:
    """
    One <button>, assembled from the parts every toolbar/help/plain-panel
    control shares: an id, a class, an optional icon glyph (via _icon()), an
    optional visible label, and an optional aria-label. This idiom was
    hand-written at twelve call sites before this helper existed.

    Attribute order is id, class, aria-label, then `extra` - matching what
    every converted call site already had, so converting them was a
    refactor, not a rendering change. `extra` is a free-form attribute
    string (aria-pressed, aria-expanded, data-label-*, type="button", ...)
    rather than a parameter per attribute: the twelve sites disagree on
    which of these they need and how many, so a parameter per attribute
    would grow this signature by one argument for every attribute even one
    site happens to need once.

    wrap_label=False renders the label as bare text instead of inside a
    <span> - needed by exactly one call site (#tour-start) whose original
    markup has no <span> around its label; forcing the wrap there would be a
    real, if harmless, change to the rendered HTML, not just a refactor.
    """
    attrs = []
    if id_attr:
        attrs.append(f'id="{id_attr}"')
    attrs.append(f'class="{css_class}"')
    if aria_label:
        attrs.append(f'aria-label="{aria_label}"')
    if extra:
        attrs.append(extra)
    icon_html = _icon(icon) if icon else ""
    if not label:
        label_html = ""
    elif wrap_label:
        label_html = f"<span>{label}</span>"
    else:
        label_html = label
    return f'<button {" ".join(attrs)}>{icon_html}{label_html}</button>'


# ---------------------------------------------------------------------------
# Icon sprite
# ---------------------------------------------------------------------------
# Every turn used to carry its own full inline SVG per icon: a play glyph in
# the timestamp button and a copy glyph in the turn's actions, byte-identical
# across every one of a batch's turns. At 435 bytes per icon body, a 200-turn
# recording shipped ~85 KB of markup that said the same nine things over and
# over. An SVG sprite fixes this the way sprites always have: each glyph is
# defined once as a <symbol> in a hidden <svg> emitted near the top of <body>
# (see _render_sprite_html()), and every use site becomes a four-attribute
# <use> reference instead of a full path list - readable with JavaScript
# disabled, since <use> is a static content reference, not a script-built
# element (the constraint that also rules out <template> cloning for this).
#
# Presentation lives on .icon in the stylesheet (core/assets/css/) (fill: none; stroke:
# currentColor; ...), not as attributes on the <symbol> or its paths - SVG's
# inheritable presentation properties cross the <use> shadow boundary the
# same way "color" crosses into a <slot>, so one CSS rule styles every
# instance instead of every glyph repeating stroke="currentColor" nine times.
_ICON_DEFS: Dict[str, str] = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "up": '<path d="M18 15l-6-6-6 6"/>',
    "down": '<path d="M6 9l6 6 6-6"/>',
    "flag": '<path d="M5 21V4h9l1 2h5v9h-6l-1-2H5"/>',
    "theme": '<path d="M21 13a9 9 0 11-10-10 7 7 0 0010 10z"/>',
    "save": '<path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M4 21h16"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h8"/>',
    "play": '<path d="M7 4l12 8-12 8z"/>',
    # Two vertical bars, stroked like every other glyph here (fill: none
    # comes from .icon in CSS - a filled pair of rectangles would be the odd
    # one out in this sprite). js/64-audio.js's bindAudio() swaps the
    # player-toggle button between #i-play and #i-pause on the audio
    # element's own play/pause events, not on the click handler directly, so
    # a programmatic pause (the range-bound stop in the timeupdate handler)
    # updates the glyph too.
    "pause": '<path d="M9 5v14"/><path d="M15 5v14"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "list": '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
    # Circle + question mark, for the toolbar's #help button and its panel's
    # own heading. The dot under the curve is a zero-length <path> rather
    # than a filled <circle>: a stroked line with no length still paints,
    # as a dot at stroke-width, because .icon sets stroke-linecap: round -
    # so the dot stays purely stroked like every other glyph in this sprite
    # instead of being the one shape here with an actual fill.
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4.5"/>'
            '<path d="M12 17.5v.01"/>',
    # The help panel's own close control. No glyph like it existed anywhere
    # else in the sprite (the panel is the first modal-shaped thing this
    # page has ever needed to dismiss), so it's new here rather than reused.
    "close": '<path d="M6 6l12 12"/><path d="M18 6L6 18"/>',
    # A pencil, for the help panel's "editing the transcript" entry - the one
    # help-list row with no existing toolbar icon to point at, since editing
    # a turn's text has never needed a button of its own (see .body's
    # contenteditable in _render_turn_html()).
    "edit": '<path d="M4 20h4L18.5 9.5a2.121 2.121 0 00-3-3L5 17v3z"/><path d="M13.5 6.5l4 4"/>',
    # A minimal head-and-shoulders mark for the per-bubble reassignment
    # control (_render_bubble_html() in core/formatting/document.py) - the
    # sentence-level sibling of the cluster header's own .spk, which needs
    # no icon of its own because it always carries a visible speaker name.
    # A bubble's control usually carries no text at all (see that function's
    # docstring), so it needs a glyph to read as a control rather than an
    # empty box.
    "user": '<path d="M12 12a4 4 0 100-8 4 4 0 000 8z"/><path d="M4.5 20c0-4.1 3.4-7.5 7.5-7.5s7.5 3.4 7.5 7.5"/>',
}


def _render_sprite_html() -> str:
    """
    The one copy of every icon body, as <symbol> definitions.

    position:absolute + zero size (rather than display:none) is the
    standard sprite-hiding technique: some engines skip <use> resolution
    against a display:none ancestor, so the symbols are laid out at (0, 0)
    with no box instead of removed from rendering altogether. aria-hidden
    keeps a screen reader from ever landing on the defs themselves - the
    per-icon <use> sites are what carry (or intentionally omit) meaning.
    """
    symbols = "".join(
        f'<symbol id="i-{name}" viewBox="0 0 24 24">{path}</symbol>'
        for name, path in _ICON_DEFS.items()
    )
    return (
        '<svg aria-hidden="true" focusable="false" '
        'style="position:absolute;width:0;height:0;overflow:hidden">'
        f'{symbols}</svg>'
    )


def _icon(name: str) -> str:
    """A <use> reference into the sprite. Never an emoji - those are font-dependent."""
    return f'<svg class="icon" aria-hidden="true"><use href="#i-{name}"></use></svg>'


def _render_toolbar_html(strings: Dict[str, str]) -> str:
    """The document's own chrome: search, view toggles, export, save status."""
    # A local alias, not a redefinition of _t's logic: this function calls it
    # by key/fallback so often that spelling out `_t(strings, ...)` at every
    # site would bury the strings the call sites actually care about under
    # repeated boilerplate. The one-line lambda still routes through _t, so
    # there is exactly one place html.escape(strings.get(...)) is written.
    s = lambda key, fallback: _t(strings, key, fallback)

    search = s("search", "Search transcript")
    search_placeholder = s("search_placeholder", "Search")
    # dir="{search_dir}" on #search itself, not left to inherit the document's
    # own dir="rtl": see _input_dir()'s docstring for why an English-chrome
    # run needs this field to be dir="ltr" specifically, so a placeholder
    # that outgrows the field's width (a deliberate possibility - see
    # #search's own comment in core/assets/css/16-toolbar.css) clips at its
    # own end rather than its start.
    search_dir = _input_dir(search)
    return "\n".join([
        f'<header class="toolbar" role="toolbar"'
        f' aria-label="{s("toolbar", "Transcript tools")}">',
        # The toolbar's controls sit inside their own grid-column: 1 / -1
        # wrapper (see .tb-row in the stylesheet (core/assets/css/), which spans both tracks
        # rather than sitting in a single one) rather than being grid items
        # of .toolbar directly - .tb-group is a flex row (a search box, a
        # cluster of action buttons), and a bare display: flex on the grid
        # items would fight the grid's own column placement instead of just
        # occupying it. This is what ties the toolbar's controls to the
        # same track boundaries main and the sidebar sit within.
        '<div class="tb-row">',
        '<div class="tb-group tb-search">',
        _icon("search"),
        f'<input id="search" type="search" dir="{search_dir}"'
        f' placeholder="{search_placeholder}" aria-label="{search}">',
        '<span id="search-count" class="count" aria-live="polite"></span>',
        _button(None, id_attr="search-prev", css_class="icon-btn", icon="up",
                aria_label=s("search_prev", "Previous match")),
        _button(None, id_attr="search-next", css_class="icon-btn", icon="down",
                aria_label=s("search_next", "Next match")),
        "</div>",
        '<div class="tb-group tb-actions">',
        _button(s("show_uncertain", "Show uncertain words"), id_attr="toggle-flags",
                icon="flag", extra='aria-pressed="false"'),
        # Server-rendered assuming the light scheme, since that is this
        # element's state before any script runs; the page script (core/assets/js/) corrects the
        # label on init if the system/browser is actually already in dark
        # mode (see bindChrome()'s theme handling), and swaps it again on
        # every click. The label names the action ("switch to dark"), not
        # the current state - "Theme" told the reader nothing about what
        # clicking it would do.
        _button(
            s("theme_dark", "Dark mode"), id_attr="toggle-theme", icon="theme",
            aria_label=s("toggle_theme", "Switch colour scheme"),
            extra=(
                f'data-label-dark="{s("theme_dark", "Dark mode")}" '
                f'data-label-light="{s("theme_light", "Light mode")}"'
            ),
        ),
        _button(s("save_copy", "Save a copy"), id_attr="export", css_class="tb-btn primary",
                icon="save"),
        # Last BUTTON in the group, not first - it opens a panel that explains
        # every OTHER control in this row, so it reads as "more about the
        # above" rather than as the first thing a reader's eye lands on. Plain
        # .tb-btn, not .primary: help is not the action this session builds
        # toward the way #export is (see the "Tier 1" comment on
        # .tb-btn.primary in the stylesheet (core/assets/css/) for what IS in that tier and
        # why #help isn't one of them). Only #status comes after it, and that
        # is a label rather than a control competing for the same attention.
        _button(s("help", "Help"), id_attr="help", icon="help",
                extra='aria-expanded="false" aria-controls="help-panel"'),
        # Last in the group, so in this dir="rtl" document it renders at the
        # physical LEFT end of the whole toolbar row - out of the run of
        # buttons rather than wedged between two of them.
        #
        # All four state labels are rendered up front and the stylesheet
        # (core/assets/css/) shows exactly one of them, keyed off data-kind;
        # the page script (core/assets/js/) only ever flips that attribute and
        # never writes text here. That is what fixes the width: stacked in one
        # grid cell, the box measures the WIDEST of the four and stops
        # resizing as the state changes. Measured before this: the span went
        # 33px -> 78px across the four states and dragged .tb-actions from
        # 424px to 469px, so every button in the row slid sideways on every
        # debounced save (see .status in the stylesheet for why a tuned
        # min-inline-size was not the fix). data-kind is seeded to "saved"
        # here because that is the state a freshly written file is in;
        # bindChrome()'s init corrects it if this browser holds local edits.
        f'<span id="status" class="status" role="status" aria-live="polite"'
        f' data-kind="saved"><span class="status-labels">'
        f'<span data-for="saved">{s("status_saved", "Saved")}</span>'
        f'<span data-for="saving">{s("status_saving", "Saving…")}</span>'
        f'<span data-for="local">{s("status_local", "Saved in browser")}</span>'
        f'<span data-for="error">{s("status_error", "Could not save")}</span>'
        f'</span></span>',
        "</div>",
        "</div>",
        "</header>",
    ])


def _render_player_html(strings: Dict[str, str]) -> str:
    """
    A single mini-player for the whole document.

    The transcript is written beside its audio, so a relative src resolves.
    It starts hidden and stays hidden unless a timestamp is actually clicked -
    and removes itself again if the audio turns out to be missing or in a
    container the browser cannot play.
    """
    # Server-rendered assuming the button is showing a play glyph, since
    # audio has not started when the page loads (the player starts hidden
    # too - see below). js/64-audio.js's bindAudio() swaps both this label
    # and the glyph between "play"/"pause" on the audio element's own
    # play/pause events, the same "swap on load and on every change" pattern
    # syncThemeLabel() already follows for the theme toggle.
    label = _t(strings, "play_pause", "Play")
    seek_label = _t(strings, "seek", "Seek")
    # A native <input type="range">, not a custom div-based track: it is
    # keyboard-operable (arrow keys, Home/End, Page Up/Down) and announced
    # with its role, value and bounds by every screen reader for free -
    # reimplementing that on a div was rejected because it means
    # reimplementing it *correctly*, not just visually. max starts at 0 and
    # is set once loadedmetadata reports the real duration (see bindAudio()
    # in the page script (core/assets/js/)); before that, there is nothing to scrub to yet.
    # "current / total" sits in its own dir="ltr" span, with the usual
    # LRI/PDI isolate around the whole thing - same bidi shape as
    # format_range()'s "M:SS - M:SS", a neutral "/" between two LTR digit
    # runs inside an RTL document (see timecode.py's module docstring).
    toggle_button = _button(None, id_attr="player-toggle", css_class="icon-btn",
                             icon="play", aria_label=label)
    return f"""<div id="player" class="player" hidden>
{toggle_button}
<span id="player-file" class="player-file"></span>
<input id="player-seek" class="seek" type="range" min="0" max="0" step="0.1" value="0"
 aria-label="{seek_label}">
<span id="player-time" class="player-time" dir="ltr">{LRI}0:00 / 0:00{PDI}</span>
<audio id="audio" preload="none"></audio>
</div>"""


def _render_toast_html() -> str:
    """
    A transient status announcement (currently just "copied"), driven by
    the page script (core/assets/js/) hooking into copy()'s one shared success path.

    Empty and hidden at render time: its text is set per event from the
    already-translated strings in the data payload, the same rule that
    governs every other user-visible string on this page - see the
    ui_strings note on render_html(). role="status" + aria-live="polite"
    means it is announced without stealing focus from whatever the reader was
    doing, unlike an alert() or a moved focus target would.
    """
    return '<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>'


def _render_help_html(strings: Dict[str, str]) -> str:
    """
    What every toolbar control and reading-column affordance actually does,
    plus the one hook (#tour-start) a separate guided-tour feature binds to.

    Server-rendered and hidden, never built by the page script (core/assets/js/) from nothing -
    the same "readable with JavaScript disabled" contract the sprite has
    (see the comment above _ICON_DEFS): the panel's own content has to exist
    in the markup whether or not the script that reveals it ever runs.
    [hidden] is what gates it from a sighted reader and from the
    accessibility tree alike, exactly like .toast and .player above - it is
    never opened without JavaScript, but it is always *present* without it,
    which is the property that matters here.

    #tour-start renders unconditionally even though nothing in this module
    wires it up - a guided-tour feature elsewhere binds its click handler in
    the page script (core/assets/js/). This module cannot depend on that: speech_to_text/core/
    never imports anything the GUI or the page's own script owns (see the
    package docstring in __init__.py), so the only contract between the two
    is this button's id existing in the markup.
    """
    s = lambda key, fallback: _t(strings, key, fallback)  # see _render_toolbar_html's s

    # (icon name, title key/fallback, description key/fallback) - one row
    # per control this page has, in the same top-to-bottom order those
    # controls appear on the page itself (toolbar left-to-right, then the
    # sidebar, then the reading column, then the plain-text panel at the
    # bottom), so the panel reads as a walkthrough of the page rather than
    # an alphabetised reference.
    entries = [
        ("search", s("help_search_title", "Search"),
         s("help_search_desc",
           "Type to search every turn in this recording. The chevrons - or "
           "Enter and Shift+Enter - jump to the next or previous match.")),
        ("flag", s("help_flags_title", "Show uncertain words"),
         s("help_flags_desc",
           "Highlights the words the model itself was least sure about, "
           "with a tinted, dotted underline - worth a second look before "
           "you trust them.")),
        ("theme", s("help_theme_title", "Light / dark mode"),
         s("help_theme_desc",
           "Switches this page's colour scheme and remembers your choice "
           "in this browser, independent of your system's own setting.")),
        ("save", s("help_save_title", "Save a copy"),
         s("help_save_desc",
           "Downloads a fresh copy of this page with every edit baked in. "
           "Opened from a file, the page can only save your edits to this "
           "browser automatically - this is what actually writes them to "
           "a file on disk.")),
        ("list", s("help_outline_title", "Files and speakers"),
         s("help_outline_desc",
           "Lists every file in this batch and, for each one, the "
           "speakers detected in it. Click a filename to jump straight to "
           "it.")),
        ("plus", s("help_speakers_title", "Speaker names and colours"),
         s("help_speakers_desc",
           "Rename a speaker by typing over their name in this list, and "
           "recolour them from the swatch beside it. Every sentence carries "
           "its own speaker chip - click it to reassign just that sentence, "
           "or the whole block of sentences around it, to someone else.")),
        ("play", s("help_playback_title", "Play a moment"),
         s("help_playback_desc",
           "Click a sentence's own timestamp to play just that sentence; "
           "playback stops again at its end.")),
        ("edit", s("help_editing_title", "Editing the transcript"),
         s("help_editing_desc",
           "Click into any turn's text to correct it directly, the same "
           "way you would edit a document. Changes save automatically to "
           "this browser as you type - use \"Save a copy\" to write "
           "them into a file you can keep or share.")),
        ("copy", s("help_plain_title", "Plain text"),
         s("help_plain_desc",
           "Every sentence has its own copy button too, for just that one "
           "sentence. A copy-friendly version of the whole recording sits "
           "at the bottom of the page, with its own toggles for timestamps "
           "and speaker names - edit it there directly, or copy it out with one "
           "click.")),
    ]
    items = "".join(
        f"<dt>{_icon(icon)}<span>{title}</span></dt><dd>{desc}</dd>"
        for icon, title, desc in entries
    )

    return (
        '<div id="help-panel" class="help-panel" role="dialog" aria-modal="true"'
        ' aria-labelledby="help-title" hidden>'
        '<div class="help-sheet">'
        '<div class="help-head">'
        f'<h2 id="help-title">{s("help_title", "Help")}</h2>'
        + _button(None, id_attr="help-close", css_class="icon-btn", icon="close",
                  aria_label=s("help_close", "Close help"))
        + "</div>"
        # wrap_label=False: this button's label was never wrapped in a
        # <span> (unlike every other _button() site) - see _button()'s
        # docstring for why that one difference is preserved rather than
        # normalised away.
        + _button(s("tour_start", "Start guided tour"), id_attr="tour-start",
                  css_class="tb-btn primary", wrap_label=False)
        + f'<dl class="help-list">{items}</dl>'
        "</div>"
        "</div>"
    )


def _swatch_trigger_html(strings: Dict[str, str]) -> str:
    """
    The one always-visible colour control per speaker row.

    Earlier this rendered all eight palette slots expanded inline - with just
    two speakers that was sixteen 44px circles stacked above the transcript,
    taller than the content the strip exists to introduce. A trigger showing
    only the *current* colour, that opens a menu of the other seven on
    demand, keeps the resting strip about one row tall regardless of how many
    speakers a file has - the menu itself is built by the page script (core/assets/js/)'s
    buildSwatchMenu(), the same on-demand-popover shape as the turn's
    reassignment menu (buildSpeakerMenu()), not a second pattern invented for
    this. The swatch's own colour comes from the shared --spk custom
    property the stylesheet (core/assets/css/) sets once per data-palette index and inherits
    from .speaker-row down to this dot - this button carries no colour of
    its own to fall out of sync.
    """
    label = _t(strings, "speaker_colour", "Speaker colour")
    # A distinct class from the popover's own dots (.swatch), not just a
    # distinct selector - see the CSS comment on .swatch-rest for why this is
    # a structural fix rather than a specificity patch: an unscoped
    # .speaker-row[data-palette] .swatch descendant rule used to reach into
    # the popover too (it opens as a sibling still inside .speaker-row), and
    # tied on specificity with the popover's own per-dot rule, so source
    # order silently decided which one painted. Two classes that can never
    # collide removes the possibility outright rather than out-specificity-ing
    # it, which the next selector added here would only re-break.
    return (
        f'<button type="button" class="swatch-trigger" aria-haspopup="true"'
        f' aria-expanded="false" aria-label="{label}">'
        '<span class="swatch-rest" aria-hidden="true"></span></button>'
    )
