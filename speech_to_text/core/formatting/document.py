"""
Rendering one document's worth of transcript: the file bar, every turn, the
outline sidebar's per-file content, and the plain-text copy-out panel.

Where chrome.py is "the same on every page", this module is "differs per
document, per turn, per speaker" - the part of the old formatting.py that
actually reads a TranscriptDocument's segments. It draws its small generic
widgets (_t, _button, _icon, _palette_index, _speaker_fallback) from
chrome.py rather than duplicating them - see chrome.py's module docstring for
why that module is their home.
"""

import html
from typing import Dict, List, Optional

from .chrome import (
    _button,
    _icon,
    _palette_index,
    _speaker_fallback,
    _swatch_trigger_html,
    _t,
)
from .timecode import (
    LRI,
    PDI,
    format_hhmmss,
    format_range,
    split_sentences,
)
from .turns import Turn, _speaker_indices
from speech_to_text.core.hebrew_correct import CONFIDENCE_THRESHOLD
from speech_to_text.core.segments import TranscriptDocument


def _render_file_bar_html(source_name: str, index: int, total: int, strings: Dict[str, str]) -> str:
    """
    The one piece of chrome that stays on screen for the whole file.

    Everything else about a batch of recordings looks alike - same card
    shape, same turn structure - so scrolling from one file's turns into the
    next one's is easy to miss until the speaker names stop making sense.
    Pinning the filename (and a per-file accent, cycled through the same
    verified palette speakers use) below the toolbar means the reader always
    knows which recording they're looking at, not just at the section
    boundary they may have scrolled straight past.
    """
    # Same bidi shape as the timestamp range (see timecode.py's module
    # docstring): a neutral "/" sitting between two LTR digit runs, inside an
    # RTL paragraph. Without the isolate this rendered as "2 / 1" for the
    # first of two files - the slash resolved RTL and swapped which number
    # read as the position and which read as the total.
    position = (
        strings.get("file_position", "{i} / {n}")
        .replace("{i}", str(index + 1))
        .replace("{n}", str(total))
    )
    accent = _palette_index(index)
    return (
        f'<header class="file-bar" data-file-accent="{accent}">'
        f"<h1>{html.escape(source_name)}</h1>"
        f'<span class="file-position" dir="ltr">{LRI}{html.escape(position)}{PDI}</span>'
        "</header>"
    )


def _render_document_html(
    document: TranscriptDocument,
    index: int,
    total: int,
    turns: List[Turn],
    speaker_label: Optional[str],
    timestamps: bool,
    failed_label: Optional[str],
    strings: Dict[str, str],
    payload: dict,
) -> List[str]:
    """One <section class="source">: sticky file bar, turns, plain text.

    No speakers strip here any more - it rendered the same roster twice (once
    per file, in the very column the reader was trying to read) and the
    sidebar is now the one place speaker management lives; see
    _render_outline_html().

    turns is this document's merge_turns() result, computed once by the
    caller (render_html) and passed in rather than recomputed here - see the
    comment where render_html builds turns_by_doc for why.
    """
    # The audio filename is the source name: output lands next to its input,
    # so a relative reference is all the page needs. Quoting happens in the
    # page (encodeURIComponent) rather than here, so the attribute keeps the
    # human-readable name.
    audio_attr = f' data-audio="{html.escape(document.source_name)}"' if not document.failed else ""

    lines = [
        f'<section class="source" id="src-{index}" data-file="{index}"{audio_attr}>',
        _render_file_bar_html(document.source_name, index, total, strings),
    ]

    if document.failed:
        lines.append(f'<p class="failed">{html.escape(failed_label or "")}</p>')
        lines.append("</section>")
        return lines

    turn_ids = [f"{index}-{position}" for position in range(len(turns))]

    for turn_id, turn in zip(turn_ids, turns):
        flagged = turn.low_confidence(CONFIDENCE_THRESHOLD)
        if flagged:
            payload["low"][turn_id] = flagged
        lines.append(_render_turn_html(turn, turn_id, speaker_label, timestamps, strings))

    lines.append(_render_plain_html(turns, turn_ids, speaker_label, timestamps, strings))
    lines.append("</section>")
    return lines


def _render_speakers_html(
    file_index: int,
    speakers: List[int],
    speaker_label: str,
    strings: Dict[str, str],
    active: bool = False,
) -> str:
    """
    Editable names and colours for this recording's speakers.

    Lives in the outline sidebar (see _render_outline_html()), one panel per
    file with only the in-view file's panel shown - the .speaker-row shape
    and data-file attribute are unchanged from when this rendered inline in
    the reading column, which is what keeps applyNames(fileIndex),
    recolourSpeaker, addSpeaker and bakeFormState() in transcript.js working
    against the same selectors without a rewrite.

    Per file rather than global: speaker 1 in one recording is rarely the same
    person as speaker 1 in another, so names stay local and an explicit action
    copies them across when it really is the same meeting.

    active=True marks the panel transcript.js should show by default before
    its own IntersectionObserver has decided which file is in view (the first
    file, same as which file's turns are on screen at load) - see
    .outline.js-ready .speakers:not(.active) in transcript.css. Without
    JavaScript every panel stays visible (no CSS rule hides a non-.active one
    unless .js-ready is present), so speaker names are still readable for
    every file, not just the first, on a script-disabled open.

    Not a <label> wrapping the whole row: once a row holds a text input *and*
    a colour trigger that opens its own menu, "label wraps one control"
    stops being true of it, so the input carries its own aria-label instead.

    The row is just the swatch trigger and the name input - no per-speaker
    turn count next to it - which is why this never needs each speaker's
    turns at all.
    """
    rows = []
    for speaker in speakers:
        fallback = html.escape(_speaker_fallback(speaker_label, speaker))
        palette = _palette_index(speaker)
        rows.append(
            f'<div class="speaker-row" data-speaker="{speaker}" data-palette="{palette}">'
            + _swatch_trigger_html(strings) +
            f'<input class="speaker-name" type="text" value=""'
            f' placeholder="{fallback}"'
            f' aria-label="{fallback}">'
            "</div>"
        )

    apply_all = (
        f'<button class="link-btn apply-all">'
        f'{_t(strings, "apply_names_all", "Use these names in all files")}</button>'
    )
    add_speaker = _button(_t(strings, "add_speaker", "Add speaker"),
                           css_class="tb-btn add-speaker", icon="plus", extra='type="button"')
    title = _t(strings, "speakers", "Speakers")
    cls = "speakers active" if active else "speakers"
    return (
        f'<div class="{cls}" data-file="{file_index}">'
        f'<span class="speakers-title">{title}</span>'
        + "".join(rows) + apply_all + add_speaker + "</div>"
    )


def _render_outline_html(
    documents: List[TranscriptDocument],
    speaker_label: Optional[str],
    strings: Dict[str, str],
) -> Optional[str]:
    """
    The sidebar: which file is which, and each file's speaker roster.

    Replaces two things that used to live inside the reading column: the
    <nav class="toc"> file list (present only for a multi-file batch) and the
    per-file speakers strip (rendered inline in every <section class="source">
    by _render_document_html - see its docstring). Both belong to
    "where am I, who is this" rather than to the transcript text itself, so
    moving them out of the column the reader is scrolling through is a
    relocation, not new functionality.

    Doesn't take turns_by_doc: nothing in this sidebar shows a per-speaker
    turn count, so there's nothing here that needs it. render_html still
    computes turns_by_doc once for _render_document_html's own use - see the
    comment there.

    Returns None - so the caller can skip emitting an empty <aside> and the
    matching toolbar toggle button - when there is neither a file list to
    show (a single-document render) nor any speaker to manage.
    """
    total = len(documents)
    show_files = total > 1

    panels = []
    for index, document in enumerate(documents):
        if document.failed:
            continue
        speakers = _speaker_indices(document.segments)
        if speaker_label is not None and speakers:
            panels.append(
                _render_speakers_html(
                    index, speakers, speaker_label, strings,
                    active=index == 0,
                )
            )

    if not show_files and not panels:
        return None

    sections = []
    if show_files:
        items = []
        for index, document in enumerate(documents):
            current = ' aria-current="true"' if index == 0 else ""
            items.append(
                f'<li><a href="#src-{index}" class="outline-file" data-file="{index}"{current}>'
                f'{html.escape(document.source_name)}</a></li>'
            )
        sections.append(
            f'<h2 class="outline-title">{_t(strings, "files", "Files")}</h2>'
            f'<ol class="outline-files">{"".join(items)}</ol>'
        )
    if panels:
        sections.append(f'<div class="outline-speakers">{"".join(panels)}</div>')

    label = _t(strings, "outline", "Files and speakers")
    return f'<aside class="outline" aria-label="{label}" id="outline">{"".join(sections)}</aside>'


def _render_turn_html(
    turn: Turn,
    turn_id: str,
    speaker_label: Optional[str],
    timestamps: bool,
    strings: Dict[str, str],
) -> str:
    """One <article class="turn">: an optional header, then one <p> per sentence."""
    header_parts = []
    if timestamps:
        # dir="ltr" is what the browser acts on for layout; the LRI/PDI isolate
        # characters from format_range() are kept too so copied plain text
        # still orders correctly outside the browser. data-end rides beside
        # data-start because playback now has to stop somewhere, not just
        # start somewhere - see the timeupdate handler in transcript.js.
        aria = html.escape(strings.get("play_from", "Play from {t}")
                           .replace("{t}", format_hhmmss(turn.start)))
        header_parts.append(
            f'<button class="ts" dir="ltr" data-start="{turn.start:.2f}"'
            f' data-end="{turn.end:.2f}" aria-label="{aria}">'
            f'{_icon("play")}<span dir="ltr">{format_range(turn.start, turn.end)}</span></button>'
        )

    if speaker_label is not None and turn.speaker is not None:
        # Speakers are 0-based internally and 1-based to a human reader. The
        # fallback rides along so the page can restore it when a custom name
        # is cleared or a turn is reassigned to a speaker with no custom name
        # of its own - the page cannot rebuild a translated label itself.
        # A <button>, not a <span>, now: this is the control that opens the
        # reassignment menu (see bindMenus() in transcript.js), so it
        # has to be reachable and activatable the way any control is.
        label = html.escape(_speaker_fallback(speaker_label, turn.speaker))
        palette = _palette_index(turn.speaker)
        # Wrapped in .spk-anchor (position: relative, sized to hug just this
        # button) rather than leaving .spk itself as the reassignment menu's
        # anchor - the menu is inserted as this wrapper's child, a *sibling*
        # of .spk, because the HTML content model forbids interactive
        # descendants (the menu's own <button>s) inside a <button>. See
        # .spk-anchor's comment in transcript.css for the full reasoning.
        header_parts.append(
            f'<span class="spk-anchor">'
            f'<button type="button" class="spk" data-speaker="{turn.speaker}"'
            f' data-palette="{palette}" data-fallback="{label}"'
            f' aria-haspopup="true" aria-expanded="false">{label}</button>'
            f'</span>'
        )

    copy_label = _t(strings, "copy_turn", "Copy this turn")
    copy_button = _button(None, css_class="icon-btn copy-turn", icon="copy", aria_label=copy_label)
    actions = f'<span class="turn-actions">{copy_button}</span>'

    speaker_attr = (
        f' data-speaker="{turn.speaker}" data-palette="{_palette_index(turn.speaker)}"'
        if turn.speaker is not None else ""
    )
    body_label = _t(strings, "turn_text", "Turn text")

    # An <h2> holding nothing but a copy button is a heading that says nothing,
    # so with neither a timestamp nor a speaker the actions stand on their own
    # and the turn is just its text - which is also what the plain-output path
    # looked like before any of this existed.
    header = f"<h2>{''.join(header_parts)}{actions}</h2>" if header_parts else actions

    lines = [
        f'<article class="turn" data-turn="{turn_id}"'
        f' data-start="{turn.start:.2f}"{speaker_attr}>',
        header,
        f'<div class="body" contenteditable="true" role="textbox"'
        f' aria-multiline="true" aria-label="{body_label}">',
    ]
    for sentence in split_sentences(turn.text):
        lines.append(f"<p>{html.escape(sentence)}</p>")
    lines.append("</div>")
    lines.append("</article>")
    return "\n".join(lines)


def _render_plain_row_html(
    turn: Turn,
    turn_id: str,
    speaker_label: Optional[str],
    timestamps: bool,
    strings: Dict[str, str],
) -> str:
    """
    One turn's row in the copy-out panel: an inert prefix, an editable body.

    Rendered server-side (not built by transcript.js from nothing) so the
    plain-text panel is readable - and, per Phase 4, editable via native
    contenteditable even with JavaScript disabled reaching it, exactly the
    way a turn's own <div class="body"> already is. transcript.js's
    rebuildPlain() finds this same element by its data-turn id afterwards
    and only ever updates its text, never recreates it from scratch, unless
    a speaker was added client-side with no server-rendered turn to match.
    """
    prefix_parts = []
    if timestamps:
        # Same bracket-inside-the-isolate shape as transcript.js's
        # bracketedRange() - see that function's comment, and timecode.py's
        # module docstring's LRI/PDI explanation, for why the brackets have
        # to sit inside the isolate rather than around it.
        bare = format_range(turn.start, turn.end).replace(LRI, "").replace(PDI, "")
        prefix_parts.append(f"{LRI}[{bare}]{PDI}")
    if speaker_label is not None and turn.speaker is not None:
        prefix_parts.append(f"{_speaker_fallback(speaker_label, turn.speaker)}:")
    prefix_text = f"{' '.join(prefix_parts)} " if prefix_parts else ""

    body_text = "\n".join(split_sentences(turn.text))
    body_label = _t(strings, "turn_text", "Turn text")
    return (
        f'<div class="plain-row" data-turn="{turn_id}">'
        f'<span class="plain-prefix" contenteditable="false">{html.escape(prefix_text)}</span>'
        f'<span class="plain-body" contenteditable="true" role="textbox"'
        f' aria-multiline="true" aria-label="{body_label}">{html.escape(body_text)}</span>'
        "</div>"
    )


def _render_plain_html(
    turns: List[Turn],
    turn_ids: List[str],
    speaker_label: Optional[str],
    timestamps: bool,
    strings: Dict[str, str],
) -> str:
    """
    The copy-out panel.

    Always visible, not collapsed inside a <details> - it was the thing this
    document gets used for most (pasting the whole recording somewhere else)
    and burying the most-used feature one click below a "Plain text" summary
    line was the wrong trade.

    One <div class="plain-row" data-turn="..."> per turn (see
    _render_plain_row_html()), rendered up front rather than built from
    nothing by transcript.js - the same "readable and editable without
    JavaScript" property every turn card already has. transcript.js's
    rebuildPlain() then keeps each row's text in step with its card (and the
    reverse) by data-turn id: no parsing either direction, so editing either
    the row or the card cannot desync it from the other, it just writes the
    same paragraph array readParagraphs() already produces from a card.
    """
    s = lambda key, fallback: _t(strings, key, fallback)  # see _render_toolbar_html's s

    rows = "".join(
        _render_plain_row_html(turn, turn_id, speaker_label, timestamps, strings)
        for turn_id, turn in zip(turn_ids, turns)
    )
    copy_all_button = _button(s('copy_all', 'Copy all'), css_class="tb-btn copy-all", icon="copy")
    return f"""<section class="plain">
<h2 class="plain-title"><span>{s('plain_text', 'Plain text')}</span>
<span class="summary-hint">{s('plain_hint', 'to paste into another app')}</span></h2>
<div class="plain-controls">
<label><input type="checkbox" class="opt-ts" checked> {s('opt_timestamps', 'Timestamps')}</label>
<label><input type="checkbox" class="opt-spk" checked> {s('opt_speakers', 'Speaker names')}</label>
{copy_all_button}
</div>
<div class="plain-text" tabindex="-1">{rows}</div>
</section>"""
