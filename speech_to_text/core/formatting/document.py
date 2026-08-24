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
import math
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
    format_instant,
    format_range,
)
from .turns import Sentence, Turn, _speaker_indices
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

    # Bubbles carry no visible number any more - only the plain-text panel
    # below numbers sentences now (see _render_plain_html()'s own running
    # counter) - so this loop no longer needs to track a running sentence
    # count of its own the way it did when _render_bubble_html() still took
    # one.
    for turn_id, turn in zip(turn_ids, turns):
        flagged = turn.low_confidence(CONFIDENCE_THRESHOLD)
        if flagged:
            payload["low"][turn_id] = flagged
        sentences = turn.sentences()
        lines.append(_render_turn_html(
            turn, turn_id, sentences, speaker_label, timestamps, strings,
        ))

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


def _render_bubble_html(
    sentence: Sentence,
    line_id: str,
    timestamps: bool,
    strings: Dict[str, str],
) -> str:
    """
    One <div class="bubble">: an individually-timed sentence.

    The messaging-app-style unit the turn (now a cluster - see
    _render_turn_html's own docstring) is made of. data-start/data-end live
    on the bubble itself, unconditionally, the same way the turn article
    already always carries data-start regardless of the timestamps toggle -
    see this function's caller. That is what lets per-bubble playback (the
    "no feature loss" checklist item this replaces the turn-only version of)
    work independent of whether the visible timestamp span is shown.

    No sentence number is shown here any more - numbering now lives only in
    the plain-text panel below (see _render_plain_row_html()), where a
    reader can pair a number with the sentence's own timestamp range. The
    bubble keeps data-line/data-start/data-end regardless, since JS keys on
    all three for playback, editing and per-sentence speaker overrides.

    The time is an LTR run inside RTL text, so it gets the same LRI/PDI
    isolate plus dir="ltr" the file position (_render_file_bar_html) and the
    plain-panel lead-in (_render_plain_row_html) already use - see
    timecode.py's module docstring for why a bare digit run still needs it
    once it sits next to other LTR runs inside one RTL line.

    It also carries contenteditable="false", because a bubble sits inside
    .body, which is contenteditable="true" so the sentence text can be
    corrected in place. Without the opt-out the timestamp is editable too: it
    is an ordinary text node inside an editable subtree, so a user can type
    over it or delete it with a backspace at the start of a line, and
    readParagraphs() would then persist the damage. The plain-panel lead-in
    already guards itself the same way for the same reason - see
    _render_plain_row_html.

    The .bubble-spk-anchor/.bubble-spk pair is the per-sentence counterpart
    to the cluster header's .spk-anchor/.spk (_render_turn_html) - the "no
    feature loss" checklist's "Reassign speaker" row explicitly asks for
    this at bubble scope, since a mid-cluster diarization miss cannot
    otherwise be corrected by hand at all. It carries no data-speaker of its
    own at render time: this module has no client-side state to read (an
    override lives only in localStorage, via state.assignLine), so the
    button renders inert and transcript.js's paintBubbleOverride() /
    applyLineAssignments() (js/24-speakers-menus.js) fill it in - and blank
    it back out - entirely client-side, the same division of labour
    applyAssignments() already has with the cluster-level .spk. Always
    present, not injected only when an override exists, for the same reason
    every other control on this page is server-rendered: it has to be a
    valid click target the moment the page loads, with or without
    JavaScript history to replay. contenteditable="false" for the same
    reason as .ts above - it is UI chrome sitting inside .body's editable
    region, not sentence text.
    """
    reassign_label = html.escape(strings.get("reassign_line", "Reassign this sentence"))
    lines = [
        f'<div class="bubble" data-line="{line_id}"'
        f' data-start="{sentence.start:.2f}" data-end="{sentence.end:.2f}">',
        f"<p>{html.escape(sentence.text)}</p>",
        f'<span class="bubble-spk-anchor" contenteditable="false">'
        f'<button type="button" class="bubble-spk" aria-haspopup="true"'
        f' aria-expanded="false" aria-label="{reassign_label}">{_icon("user")}'
        f'<span class="bubble-spk-label"></span></button>'
        f'</span>',
    ]
    if timestamps:
        # A real <button>, like the cluster header's own timestamp, not a
        # styled <span>. The click target has to be reachable by keyboard:
        # a span is inert to Tab whatever it is styled to look like, so a
        # hover and focus affordance on one is a promise the markup cannot
        # keep. Reusing the existing play_from string means this adds no new
        # i18n key - the label differs only in the instant it names.
        aria = html.escape(
            strings.get("play_from", "Play from {t}")
            .replace("{t}", format_hhmmss(sentence.start))
        )
        lines.append(
            f'<button type="button" class="ts" dir="ltr" contenteditable="false"'
            f' aria-label="{aria}">{format_instant(sentence.start)}</button>'
        )
    lines.append("</div>")
    return "".join(lines)


def _render_turn_html(
    turn: Turn,
    turn_id: str,
    sentences: List[Sentence],
    speaker_label: Optional[str],
    timestamps: bool,
    strings: Dict[str, str],
) -> str:
    """One <article class="turn">: an optional header, then one bubble per sentence.

    "turn" is now the WhatsApp-style CLUSTER of same-speaker bubbles, not the
    unit of text itself - see the sentence-bubbles plan, 1.2, for why
    data-turn stays on this element unchanged rather than being replaced:
    everything already keyed on it (saved edits, localStorage, low-confidence
    flags, plain-row sync, outline, search) keeps working untouched, and only
    the level one down (the bubble) is new.

    sentences comes from the caller (_render_document_html) rather than
    being computed here purely to avoid calling turn.sentences() twice for
    the same turn - it also feeds that caller's low-confidence check.
    Bubbles no longer carry a visible number, so unlike sentences this
    function needs no per-document running count from its caller any more;
    see _render_plain_html() for where that count still lives.
    """
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
    for idx, sentence in enumerate(sentences):
        line_id = f"{turn_id}-{idx}"
        lines.append(
            _render_bubble_html(sentence, line_id, timestamps, strings)
        )
    lines.append("</div>")
    lines.append("</article>")
    return "\n".join(lines)


def _display_end_second(sentence) -> int:
    """
    The end second to SHOW for one sentence's range in the plain-text panel.

    format_range() truncates both ends via int(), so a sentence under a
    second long - routine, since sentences sit closer together than that -
    renders its end equal to its start: "0:00 - 0:00", which reads as broken
    rather than as a real, very short sentence.

    Rounding the end up unconditionally fixes that and buys a worse problem.
    The NEXT sentence's start is still truncated, so consecutive ranges
    overlap: "1. [0:00 - 0:02]" followed by "2. [0:01 - 0:04]", and two
    sentences both claiming to begin at 0:20. Overlapping ranges read as a
    bug, and they undermine the one thing these ranges exist for - finding
    and playing one specific sentence.

    So truncate normally and only impose a floor of one second. A sentence
    long enough to cross a whole-second boundary keeps its true truncated
    end and stays flush with its neighbour; only a sub-second sentence is
    widened, and only to the smallest non-degenerate value. format_range()
    itself is left alone - the turn header still uses it un-rounded.
    """
    return max(int(sentence.end), int(sentence.start) + 1)


def _render_plain_row_html(
    turn: Turn,
    turn_id: str,
    first_number: int,
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

    first_number is this turn's first sentence's number in the per-document
    running count _render_plain_html keeps - see that function's docstring.
    Each line of body_text gets its own number AND, when timestamps are on,
    its own timestamp range, rather than the row as a whole getting either -
    a turn can hold several sentences, and a single per-row number or range
    could not identify any one of them. The row prefix therefore keeps only
    the speaker name now; the range that used to live there has moved down
    to sit beside each sentence's own number instead.

    Uses turn.sentences() (Turn.sentences(), turns.py), not
    split_sentences(turn.text) as this used to: the text is the same either
    way, but only Sentence carries the per-sentence start/end each line's own
    range needs.
    """
    prefix_parts = []
    if speaker_label is not None and turn.speaker is not None:
        prefix_parts.append(f"{_speaker_fallback(speaker_label, turn.speaker)}:")
    prefix_text = f"{' '.join(prefix_parts)} " if prefix_parts else ""

    # Each line leads with "{LRI}{number}.{PDI} " - or, with timestamps on,
    # "{LRI}{number}. [{range}]{PDI} " - all inside ONE isolate rather than
    # a separate one per piece: the number, the dot and the bracketed range
    # are one continuous LTR run, so a second isolate around the range would
    # only add control characters with nothing to isolate it from. No
    # dir="ltr" element wraps it - unlike the file-position span, this text
    # has to stay a single contenteditable text node (one
    # <span class="plain-body">, matching the card's single <div class="body">
    # contenteditable contract) so a wrapping element isn't available here.
    #
    # NOTE for the JS pass that follows this one: js/32-plain-text.js's input
    # handler currently does `bodyEl.textContent.split('\n')` to rebuild the
    # paragraph array it writes back into the card via writeParagraphs(). That
    # will now capture this lead-in as part of the paragraph text unless it
    # is stripped first - the lead-in has to come back out before a
    # plain-panel edit is written back to the card, or every future edit
    # through this panel bakes a stale number and a stale timestamp into the
    # transcript text itself. Not fixed here: this module is Python-only and
    # does not touch transcript.js.
    sentence_lines = []
    for idx, sentence in enumerate(turn.sentences()):
        number = first_number + idx
        if timestamps:
            # format_range() truncates both ends via int(), so a sentence
            # under a second long (routine - sentences are often closer
            # together than that) would render its end the same as its
            # start: "0:00 - 0:00", which reads as broken rather than as a
            # real, very short sentence. Rounding the END second UP with
            # math.ceil() (and leaving the start alone) is enough to avoid
            # that degenerate range without touching format_range() itself,
            # which the turn header above still uses un-rounded - and a
            # rounded-up end is also the more useful choice for playback,
            # since it is guaranteed to include the sentence's own tail
            # rather than cutting it off.
            bare = (
                format_range(sentence.start, _display_end_second(sentence))
                .replace(LRI, "")
                .replace(PDI, "")
            )
            lead = f"{LRI}{number}. [{bare}]{PDI}"
        else:
            lead = f"{LRI}{number}.{PDI}"
        sentence_lines.append(f"{lead} {sentence.text}")
    body_text = "\n".join(sentence_lines)
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

    Keeps its own per-document sentence counter, starting at 1, rather than
    receiving one from _render_document_html's turn-rendering loop: both
    loops walk the same turns in the same order and re-derive the same
    sentence texts from the same turn.text, so two independent counts over
    one identical sequence land on identical numbers without the two loops
    needing to share mutable state - see the sentence-bubbles plan, 1.2, for
    why the numbers must match at all.
    """
    s = lambda key, fallback: _t(strings, key, fallback)  # see _render_toolbar_html's s

    row_parts = []
    sentence_number = 1
    for turn_id, turn in zip(turn_ids, turns):
        row_parts.append(_render_plain_row_html(
            turn, turn_id, sentence_number, speaker_label, timestamps, strings,
        ))
        sentence_number += len(turn.sentences())
    rows = "".join(row_parts)
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
