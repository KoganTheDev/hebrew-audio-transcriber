"""Page chrome: the icon sprite, toolbar, mini-player, toast and help panel.

The frame around the transcript - the parts that are the same no matter which
file or turn is being read. The transcript itself is document.py's job.

The small generic-widget helpers (_t, _button, _icon, _palette_index,
_speaker_fallback, SPEAKER_PALETTE_SIZE) live here too rather than in a fourth
near-empty module: _icon has to be here anyway, and _button is built on it.
document.py imports from here and never the other way round, so no cycle.
"""

import html
import re
from functools import partial

from .timecode import LRI, PDI

# Matches any letter in the Hebrew Unicode block.
_HEBREW_LETTER = re.compile(r"[֐-׿]")


def _input_dir(text: str) -> str:
    """Return "ltr" or "rtl", guessed from whether `text` itself contains a Hebrew
    letter.

    The document is always dir="rtl" (the transcript is Hebrew speech
    whatever the chrome's language), so an English placeholder in a field
    that inherits that dir anchors right and overflows left: when the field
    is too narrow (a deliberate possibility - see #search's "release valve"
    comment in core/assets/css/16-toolbar.css) the clipped half is the START
    of the string. Giving the field the dir of the language actually inside
    it moves the clip to the end, so "Search transc..." still reads.

    Sniffing the string rather than being told the language: core cannot
    import gui.i18n (see the package docstring), and ui_strings arrives as
    plain translated data with no language tag - threading one through
    render_html(), _build_payload() and _render_toolbar_html() for this one
    call site is more plumbing than the string answers for free.
    """
    return "rtl" if _HEBREW_LETTER.search(text) else "ltr"


# Eight swatches, verified in tests/test_transcript_styles.py against the
# composited panel background. Not symmetry - it is the size of the PAIRS
# table that guarantees every colour a speaker can wear still reads at 4.5:1.
# A ninth colour someone likes but never measures is the failure this
# palette-only design (rather than a free picker) exists to rule out, so
# speaker identity wraps around via modulo rather than growing past it.
SPEAKER_PALETTE_SIZE = 8


def _t(strings: dict[str, str], key: str, fallback: str) -> str:
    """An already-translated, HTML-escaped UI string, or its English fallback.

    The single place `html.escape(strings.get(...))` is written, so there is
    one place to get the escaping right.
    """
    return html.escape(strings.get(key, fallback))


def _palette_index(n: int) -> int:
    """A speaker's (or a file's) slot in the verified 8-swatch palette."""
    return n % SPEAKER_PALETTE_SIZE


def _speaker_fallback(speaker_label: str, speaker: int) -> str:
    """A speaker's human-facing label: 0-based internally, 1-based to a reader.

    Returns unescaped text on purpose - every call site html.escape()s it
    itself, right where it lands in an attribute or a text node.
    """
    return speaker_label.format(n=speaker + 1)


def _button(
    label: str | None,
    *,
    id_attr: str | None = None,
    css_class: str = "tb-btn",
    icon: str | None = None,
    aria_label: str | None = None,
    extra: str = "",
    wrap_label: bool = True,
) -> str:
    """One <button>: an id, a class, an optional icon glyph, a label and an
    aria-label.

    `extra` is a free-form attribute string (aria-pressed, aria-expanded,
    data-label-*, ...) rather than a parameter per attribute: the call sites
    disagree on which they need, so a parameter each would grow this
    signature for every attribute even one site wants once.

    wrap_label=False renders the label as bare text instead of inside a
    <span> - needed by #tour-start alone, whose markup has no <span> around
    its label.
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
    return f"<button {' '.join(attrs)}>{icon_html}{label_html}</button>"


# An SVG sprite rather than a full inline SVG per icon site: at 435 bytes per
# icon body, a 200-turn recording shipped ~85 KB of byte-identical markup.
# Each glyph is defined once as a <symbol> in a hidden <svg> near the top of
# <body> (see _render_sprite_html()) and every use site is a <use> reference.
# <use> is a static content reference, not a script-built element, so the page
# still reads with JavaScript disabled - the constraint that also rules out
# <template> cloning here.
#
# Presentation lives on .icon in the stylesheet (core/assets/css/), not as
# attributes on the <symbol> or its paths: SVG's inheritable presentation
# properties cross the <use> shadow boundary, so one CSS rule styles every
# instance.
_ICON_DEFS: dict[str, str] = {
    "search": '<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>',
    "up": '<path d="M18 15l-6-6-6 6"/>',
    "down": '<path d="M6 9l6 6 6-6"/>',
    "flag": '<path d="M5 21V4h9l1 2h5v9h-6l-1-2H5"/>',
    "theme": '<path d="M21 13a9 9 0 11-10-10 7 7 0 0010 10z"/>',
    "save": '<path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M4 21h16"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 012-2h8"/>',
    "play": '<path d="M7 4l12 8-12 8z"/>',
    # js/64-audio.js's bindAudio() swaps the player-toggle button between
    # #i-play and #i-pause on the audio element's own play/pause events, not
    # on the click handler, so a programmatic pause (the range-bound stop in
    # the timeupdate handler) updates the glyph too.
    "pause": '<path d="M9 5v14"/><path d="M15 5v14"/>',
    "plus": '<path d="M12 5v14"/><path d="M5 12h14"/>',
    "list": '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
    # The dot under the question mark is a zero-length <path>, not a filled
    # <circle>: .icon sets stroke-linecap: round, so a stroked line with no
    # length still paints as a dot at stroke-width - keeping the glyph purely
    # stroked like the rest of the sprite instead of needing a fill.
    "help": '<circle cx="12" cy="12" r="9"/><path d="M9.09 9a3 3 0 015.83 1c0 2-3 2.5-3 4.5"/>'
    '<path d="M12 17.5v.01"/>',
    "close": '<path d="M6 6l12 12"/><path d="M18 6L6 18"/>',
    # A pencil, for the help panel's "editing the transcript" entry - the one
    # help-list row with no toolbar icon to point at, since editing a turn's
    # text has no button of its own (see .body's contenteditable in
    # _render_turn_html()).
    "edit": '<path d="M4 20h4L18.5 9.5a2.121 2.121 0 00-3-3L5 17v3z"/><path d="M13.5 6.5l4 4"/>',
    # For the per-bubble reassignment control (_render_bubble_html() in
    # document.py), which usually carries no text at all and so needs a glyph
    # to read as a control rather than an empty box.
    "user": '<path d="M12 12a4 4 0 100-8 4 4 0 000 8z"/><path d="M4.5 20c0-4.1 3.4-7.5 7.5-7.5s7.5 3.4 7.5 7.5"/>',
}


def _render_sprite_html() -> str:
    """The one copy of every icon body, as <symbol> definitions, with ids
    "i-<name>" that every _icon() <use> resolves against.

    position:absolute + zero size, not display:none: some engines skip <use>
    resolution against a display:none ancestor. aria-hidden keeps a screen
    reader off the defs themselves - the per-icon <use> sites carry (or
    intentionally omit) the meaning.
    """
    symbols = "".join(
        f'<symbol id="i-{name}" viewBox="0 0 24 24">{path}</symbol>'
        for name, path in _ICON_DEFS.items()
    )
    return (
        '<svg aria-hidden="true" focusable="false" '
        'style="position:absolute;width:0;height:0;overflow:hidden">'
        f"{symbols}</svg>"
    )


def _icon(name: str) -> str:
    """A <use> reference into the sprite. Never an emoji - those are font-dependent."""
    return f'<svg class="icon" aria-hidden="true"><use href="#i-{name}"></use></svg>'


def _render_toolbar_html(strings: dict[str, str]) -> str:
    """The document's own chrome: search, view toggles, export, save status."""
    # An alias, not a second escaping path: it still routes through _t.
    s = partial(_t, strings)

    search = s("search", "Search transcript")
    search_placeholder = s("search_placeholder", "Search")
    # dir on #search itself rather than inheriting the document's dir="rtl" -
    # see _input_dir()'s docstring.
    search_dir = _input_dir(search)
    return "\n".join(
        [
            f'<header class="toolbar" role="toolbar"'
            f' aria-label="{s("toolbar", "Transcript tools")}">',
            # .tb-row is a grid-column: 1 / -1 wrapper rather than the groups
            # being grid items of .toolbar directly: .tb-group is a flex row,
            # and a bare display: flex on a grid item would fight the grid's
            # own column placement instead of occupying it. This is what ties
            # the toolbar to the same track boundaries as main and the sidebar.
            '<div class="tb-row">',
            '<div class="tb-group tb-search">',
            _icon("search"),
            f'<input id="search" type="search" dir="{search_dir}"'
            f' placeholder="{search_placeholder}" aria-label="{search}">',
            '<span id="search-count" class="count" aria-live="polite"></span>',
            _button(
                None,
                id_attr="search-prev",
                css_class="icon-btn",
                icon="up",
                aria_label=s("search_prev", "Previous match"),
            ),
            _button(
                None,
                id_attr="search-next",
                css_class="icon-btn",
                icon="down",
                aria_label=s("search_next", "Next match"),
            ),
            "</div>",
            '<div class="tb-group tb-actions">',
            _button(
                s("show_uncertain", "Show uncertain words"),
                id_attr="toggle-flags",
                icon="flag",
                extra='aria-pressed="false"',
            ),
            # Server-rendered assuming the light scheme; bindChrome() in the
            # page script (core/assets/js/) corrects the label on init from
            # data-label-dark / data-label-light if the browser is already
            # dark, and swaps it on every click. The label names the action
            # ("switch to dark"), not the current state.
            _button(
                s("theme_dark", "Dark mode"),
                id_attr="toggle-theme",
                icon="theme",
                aria_label=s("toggle_theme", "Switch colour scheme"),
                extra=(
                    f'data-label-dark="{s("theme_dark", "Dark mode")}" '
                    f'data-label-light="{s("theme_light", "Light mode")}"'
                ),
            ),
            _button(
                s("save_copy", "Save a copy"),
                id_attr="export",
                css_class="tb-btn primary",
                icon="save",
            ),
            # Last button in the group, not first: it explains every other
            # control in this row, so it reads as "more about the above".
            # Plain .tb-btn, not .primary - help is not the action the session
            # builds toward the way #export is (see the "Tier 1" comment on
            # .tb-btn.primary in core/assets/css/).
            _button(
                s("help", "Help"),
                id_attr="help",
                icon="help",
                extra='aria-expanded="false" aria-controls="help-panel"',
            ),
            # Last in the group, so in this dir="rtl" document it lands at the
            # physical LEFT end of the row rather than between two buttons.
            #
            # All four state labels are rendered up front and the stylesheet
            # shows exactly one, keyed off data-kind; the page script only ever
            # flips that attribute and never writes text here. Stacked in one
            # grid cell, the box measures the WIDEST of the four and stops
            # resizing as the state changes. Measured before this: the span
            # went 33px -> 78px across the four states and dragged .tb-actions
            # from 424px to 469px, so every button slid sideways on every
            # debounced save (see .status in the stylesheet for why a tuned
            # min-inline-size was not the fix). data-kind seeds to "saved", the
            # state of a freshly written file; bindChrome()'s init corrects it
            # if this browser holds local edits.
            f'<span id="status" class="status" role="status" aria-live="polite"'
            f' data-kind="saved"><span class="status-labels">'
            f'<span data-for="saved">{s("status_saved", "Saved")}</span>'
            f'<span data-for="saving">{s("status_saving", "Saving…")}</span>'
            f'<span data-for="local">{s("status_local", "Saved in browser")}</span>'
            f'<span data-for="error">{s("status_error", "Could not save")}</span>'
            f"</span></span>",
            "</div>",
            "</div>",
            "</header>",
        ]
    )


def _render_player_html(strings: dict[str, str]) -> str:
    """A single mini-player for the whole document.

    The transcript is written beside its audio, so a relative src resolves.
    It starts hidden and stays hidden unless a timestamp is actually clicked -
    and removes itself again if the audio turns out to be missing or in a
    container the browser cannot play.
    """
    # Server-rendered as "play", since audio has not started at load;
    # js/64-audio.js's bindAudio() swaps both this label and the glyph on the
    # audio element's own play/pause events.
    label = _t(strings, "play_pause", "Play")
    seek_label = _t(strings, "seek", "Seek")
    # A native <input type="range">, not a div-based track: keyboard-operable
    # (arrows, Home/End, Page Up/Down) and announced with role, value and
    # bounds for free. Reimplementing that on a div means reimplementing it
    # *correctly*, not just visually. max starts at 0 and bindAudio() sets it
    # once loadedmetadata reports the real duration.
    # "current / total" sits in its own dir="ltr" span inside an LRI/PDI
    # isolate - same bidi shape as format_range()'s "M:SS - M:SS" (see
    # timecode.py's module docstring).
    toggle_button = _button(
        None, id_attr="player-toggle", css_class="icon-btn", icon="play", aria_label=label
    )
    return f"""<div id="player" class="player" hidden>
{toggle_button}
<span id="player-file" class="player-file"></span>
<input id="player-seek" class="seek" type="range" min="0" max="0" step="0.1" value="0"
 aria-label="{seek_label}">
<span id="player-time" class="player-time" dir="ltr">{LRI}0:00 / 0:00{PDI}</span>
<audio id="audio" preload="none"></audio>
</div>"""


def _render_toast_html() -> str:
    """A transient status announcement (currently just "copied"), driven by
    the page script (core/assets/js/) from copy()'s shared success path.

    Empty and hidden at render time: its text is set per event from the
    already-translated strings in the data payload (see the ui_strings note
    on render_html()). role="status" + aria-live="polite" announces it
    without stealing focus, unlike an alert() or a moved focus target.
    """
    return '<div id="toast" class="toast" role="status" aria-live="polite" hidden></div>'


def _render_help_html(strings: dict[str, str]) -> str:
    """What every toolbar control and reading-column affordance actually does,
    plus the one hook (#tour-start) a separate guided-tour feature binds to.

    Server-rendered and hidden, never built by the page script - the same
    "readable with JavaScript disabled" contract the sprite has. [hidden]
    gates it from a sighted reader and the accessibility tree alike, like
    .toast and .player: never opened without JavaScript, but always present.

    #tour-start renders unconditionally even though nothing here wires it up.
    core/ cannot import anything the GUI or the page script owns (see the
    package docstring in __init__.py), so this button's id existing in the
    markup is the entire contract between the two.
    """
    s = partial(_t, strings)  # see _render_toolbar_html's s

    # (icon name, title key/fallback, description key/fallback), in the order
    # the controls appear on the page (toolbar, sidebar, reading column, then
    # the plain-text panel), so the panel reads as a walkthrough rather than
    # an alphabetised reference.
    entries = [
        (
            "search",
            s("help_search_title", "Search"),
            s(
                "help_search_desc",
                "Type to search every turn in this recording. The chevrons - or "
                "Enter and Shift+Enter - jump to the next or previous match.",
            ),
        ),
        (
            "flag",
            s("help_flags_title", "Show uncertain words"),
            s(
                "help_flags_desc",
                "Highlights the words the model itself was least sure about, "
                "with a tinted, dotted underline - worth a second look before "
                "you trust them.",
            ),
        ),
        (
            "theme",
            s("help_theme_title", "Light / dark mode"),
            s(
                "help_theme_desc",
                "Switches this page's colour scheme and remembers your choice "
                "in this browser, independent of your system's own setting.",
            ),
        ),
        (
            "save",
            s("help_save_title", "Save a copy"),
            s(
                "help_save_desc",
                "Downloads a fresh copy of this page with every edit baked in. "
                "Opened from a file, the page can only save your edits to this "
                "browser automatically - this is what actually writes them to "
                "a file on disk.",
            ),
        ),
        (
            "list",
            s("help_outline_title", "Files and speakers"),
            s(
                "help_outline_desc",
                "Lists every file in this batch and, for each one, the "
                "speakers detected in it. Click a filename to jump straight to "
                "it.",
            ),
        ),
        (
            "plus",
            s("help_speakers_title", "Speaker names and colours"),
            s(
                "help_speakers_desc",
                "Rename a speaker by typing over their name in this list, and "
                "recolour them from the swatch beside it. Every sentence carries "
                "its own speaker chip - click it to reassign just that sentence, "
                "or the whole block of sentences around it, to someone else.",
            ),
        ),
        (
            "play",
            s("help_playback_title", "Play a moment"),
            s(
                "help_playback_desc",
                "Click a sentence's own timestamp to play just that sentence; "
                "playback stops again at its end.",
            ),
        ),
        (
            "edit",
            s("help_editing_title", "Editing the transcript"),
            s(
                "help_editing_desc",
                "Click into any turn's text to correct it directly, the same "
                "way you would edit a document. Changes save automatically to "
                'this browser as you type - use "Save a copy" to write '
                "them into a file you can keep or share.",
            ),
        ),
        (
            "copy",
            s("help_plain_title", "Plain text"),
            s(
                "help_plain_desc",
                "Every sentence has its own copy button too, for just that one "
                "sentence. A copy-friendly version of the whole recording sits "
                "at the bottom of the page, with its own toggles for timestamps "
                "and speaker names - edit it there directly, or copy it out with one "
                "click.",
            ),
        ),
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
        + _button(
            None,
            id_attr="help-close",
            css_class="icon-btn",
            icon="close",
            aria_label=s("help_close", "Close help"),
        )
        + "</div>"
        # wrap_label=False: this button's label is not wrapped in a <span>,
        # unlike every other _button() site - see _button()'s docstring.
        + _button(
            s("tour_start", "Start guided tour"),
            id_attr="tour-start",
            css_class="tb-btn primary",
            wrap_label=False,
        )
        + f'<dl class="help-list">{items}</dl>'
        "</div>"
        "</div>"
    )


def _swatch_trigger_html(strings: dict[str, str]) -> str:
    """The one always-visible colour control per speaker row.

    Showing only the current colour and opening the other seven on demand
    keeps the resting strip about a row tall however many speakers a file
    has; all eight inline meant sixteen 44px circles for two speakers, taller
    than the content the strip introduces. The menu is built by the page
    script's buildSwatchMenu(), the same on-demand-popover shape as the
    turn's buildSpeakerMenu(). The dot's colour comes from the shared --spk
    custom property the stylesheet sets per data-palette index and inherits
    from .speaker-row, so this button carries no colour of its own to fall
    out of sync.
    """
    label = _t(strings, "speaker_colour", "Speaker colour")
    # .swatch-rest, a distinct class from the popover's own dots (.swatch),
    # not just a distinct selector: the popover opens as a sibling still
    # inside .speaker-row, so an unscoped `.speaker-row[data-palette] .swatch`
    # reaches into it and ties on specificity with the popover's own per-dot
    # rule, leaving source order to decide which paints. Two classes that
    # cannot collide removes the possibility instead of out-specificity-ing
    # it, which the next selector added here would only re-break.
    return (
        f'<button type="button" class="swatch-trigger" aria-haspopup="true"'
        f' aria-expanded="false" aria-label="{label}">'
        '<span class="swatch-rest" aria-hidden="true"></span></button>'
    )
