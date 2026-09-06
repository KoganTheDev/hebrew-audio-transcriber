"""Rendering one document's worth of transcript: the file bar, every turn, the
outline sidebar's per-file content, and the plain-text copy-out panel.

Where chrome.py is "the same on every page", this module is "differs per
document, per turn, per speaker" - the part that actually reads a
TranscriptDocument's segments. Its small generic widgets (_t, _button, _icon,
_palette_index, _speaker_fallback) come from chrome.py rather than being
duplicated here.
"""

import html
from functools import partial

from speech_to_text.core.hebrew_correct import CONFIDENCE_THRESHOLD
from speech_to_text.core.segments import TranscriptDocument

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
)
from .turns import Sentence, Turn, _speaker_indices


def _render_file_bar_html(source_name: str, index: int, total: int, strings: dict[str, str]) -> str:
    """The one piece of chrome that stays on screen for the whole file.

    Everything else about a batch of recordings looks alike - same card
    shape, same turn structure - so scrolling from one file's turns into the
    next one's is easy to miss until the speaker names stop making sense.
    Pinning the filename (and a per-file accent, cycled through the same
    verified palette speakers use) below the toolbar keeps the answer on
    screen, not just at a section boundary the reader may have scrolled past.
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
    turns: list[Turn],
    speaker_label: str | None,
    timestamps: bool,
    failed_label: str | None,
    strings: dict[str, str],
    payload: dict,
) -> list[str]:
    """One <section class="source">: sticky file bar, turns, plain text.

    Speaker management lives in the sidebar, not here - see
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
        sentences = turn.sentences()
        lines.append(
            _render_turn_html(
                turn,
                turn_id,
                sentences,
                speaker_label,
                timestamps,
                strings,
            )
        )

    lines.append(_render_plain_html(turns, turn_ids, speaker_label, timestamps, strings))
    lines.append("</section>")
    return lines


def _render_speakers_html(
    file_index: int,
    speakers: list[int],
    speaker_label: str,
    strings: dict[str, str],
    active: bool = False,
) -> str:
    """Editable names and colours for this recording's speakers.

    Lives in the outline sidebar (see _render_outline_html()), one panel per
    file with only the in-view file's shown. The .speaker-row shape and its
    data-file attribute are the contract applyNames(fileIndex),
    recolourSpeaker, addSpeaker and bakeFormState() in the page script
    (core/assets/js/) select against.

    Per file rather than global: speaker 1 in one recording is rarely the same
    person as speaker 1 in another, so names stay local and an explicit action
    copies them across when it really is the same meeting.

    active=True marks the panel the page script should show by default before
    its own IntersectionObserver has decided which file is in view (the first
    file, same as which file's turns are on screen at load) - see
    .outline.js-ready .speakers:not(.active) in the stylesheet
    (core/assets/css/). Without JavaScript every panel stays visible (nothing
    hides a non-.active one unless .js-ready is present), so speaker names are
    readable for every file on a script-disabled open.

    Not a <label> wrapping the whole row: once a row holds a text input *and*
    a colour trigger that opens its own menu, "label wraps one control" stops
    being true of it, so the input carries its own aria-label instead.
    """
    rows = []
    for speaker in speakers:
        fallback = html.escape(_speaker_fallback(speaker_label, speaker))
        palette = _palette_index(speaker)
        rows.append(
            f'<div class="speaker-row" data-speaker="{speaker}" data-palette="{palette}">'
            + _swatch_trigger_html(strings)
            + f'<input class="speaker-name" type="text" value=""'
            f' placeholder="{fallback}"'
            f' aria-label="{fallback}">'
            "</div>"
        )

    apply_all = (
        f'<button class="link-btn apply-all">'
        f"{_t(strings, 'apply_names_all', 'Use these names in all files')}</button>"
    )
    add_speaker = _button(
        _t(strings, "add_speaker", "Add speaker"),
        css_class="tb-btn add-speaker",
        icon="plus",
        extra='type="button"',
    )
    title = _t(strings, "speakers", "Speakers")
    cls = "speakers active" if active else "speakers"
    return (
        f'<div class="{cls}" data-file="{file_index}">'
        f'<span class="speakers-title">{title}</span>'
        + "".join(rows)
        + apply_all
        + add_speaker
        + "</div>"
    )


def _render_outline_html(
    documents: list[TranscriptDocument],
    speaker_label: str | None,
    strings: dict[str, str],
) -> str | None:
    """The sidebar: which file is which, and each file's speaker roster.

    Both belong to "where am I, who is this" rather than to the transcript
    text, so they sit outside the column the reader scrolls through. The file
    list only appears for a multi-file batch.

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
                    index,
                    speakers,
                    speaker_label,
                    strings,
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
                f"{html.escape(document.source_name)}</a></li>"
            )
        sections.append(
            f'<h2 class="outline-title">{_t(strings, "files", "Files")}</h2>'
            f'<ol class="outline-files">{"".join(items)}</ol>'
        )
    if panels:
        sections.append(f'<div class="outline-speakers">{"".join(panels)}</div>')

    label = _t(strings, "outline", "Files and speakers")
    return f'<aside class="outline" aria-label="{label}" id="outline">{"".join(sections)}</aside>'


def _display_end_second(sentence: Sentence) -> int:
    """The end second to SHOW for one sentence's range - on its own card and in
    the plain-text panel.

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
    itself is left alone - the true data-end used for playback is the
    sentence's own untouched end, not this display-only value.
    """
    return max(int(sentence.end), int(sentence.start) + 1)


def _render_bubble_html(
    sentence: Sentence,
    line_id: str,
    turn_id: str,
    timestamps: bool,
    speaker_label: str | None,
    speaker: int | None,
    strings: dict[str, str],
) -> str:
    """One <div class="bubble">: a full-width card for one sentence.

    data-turn rides along on the bubble itself, in addition to the wrapping
    .turn already carrying it, so the "apply to this whole block"
    reassignment (js/24-speakers-menus.js) can select every sibling card in
    the block without walking back up to .turn first.

    data-start/data-end live on the bubble unconditionally, whatever the
    timestamps toggle says: that is what lets per-bubble playback work
    independent of whether a visible timestamp span was rendered.

    The play control shows the sentence's RANGE, its end taken from
    _display_end_second() so a sub-second sentence does not read as
    "0:00 - 0:00". The button's own data-start/data-end are deliberately NOT
    set - bindAudio() (js/64-audio.js) reads the range off the wrapping
    .bubble via btn.closest('.bubble'), so a second copy could drift from the
    true (un-rounded) end playback actually uses.

    The time is an LTR run inside RTL text, so it takes the same LRI/PDI
    isolate plus dir="ltr" the file position and the plain-panel lead-in use -
    see timecode.py's module docstring.

    It also carries contenteditable="false", because a bubble sits inside
    .body, which is contenteditable="true" so the sentence text can be
    corrected in place. Without the opt-out the timestamp is editable too: an
    ordinary text node in an editable subtree, so a user can type over it or
    backspace it away at the start of a line, and readParagraphs() would then
    persist the damage.

    The .bubble-spk-anchor/.bubble-spk pair is the speaker chip AND the
    reassignment affordance in one control. It is always rendered filled, in
    the turn's speaker colour, with the turn's own name - never blank, since
    a blank chip is not a valid resting state.
    reassignLine()/paintBubbleOverride() (js/24-speakers-menus.js) repaint it
    when an override is set or cleared, restoring the block's own identity on
    a clear. Absent entirely when there is no speaker at all (no diarization).

    The copy button copies just this one sentence - see bubblePlainText() in
    js/32-plain-text.js.
    """
    reassign_label = html.escape(strings.get("reassign_line", "Reassign this sentence"))
    chip_html = ""
    speaker_attr = ""
    if speaker_label is not None and speaker is not None:
        label = html.escape(_speaker_fallback(speaker_label, speaker))
        palette = _palette_index(speaker)
        speaker_attr = f' data-speaker="{speaker}" data-palette="{palette}"'
        chip_html = (
            f'<span class="bubble-spk-anchor" contenteditable="false">'
            f'<button type="button" class="bubble-spk" data-speaker="{speaker}"'
            f' data-palette="{palette}" data-fallback="{label}"'
            f' aria-haspopup="true" aria-expanded="false" aria-label="{reassign_label}">'
            f'<span class="bubble-spk-label">{label}</span></button>'
            f"</span>"
        )

    lines = [
        f'<div class="bubble" data-line="{line_id}" data-turn="{turn_id}"'
        f' data-start="{sentence.start:.2f}" data-end="{sentence.end:.2f}"{speaker_attr}>',
        chip_html,
        f"<p>{html.escape(sentence.text)}</p>",
    ]
    if timestamps:
        # A real <button>, not a styled <span>: the click target has to be
        # reachable by keyboard. Reuses play_from - the label differs only in
        # the instant it names.
        aria = html.escape(
            strings.get("play_from", "Play from {t}").replace("{t}", format_hhmmss(sentence.start))
        )
        display_end = _display_end_second(sentence)
        lines.append(
            f'<button type="button" class="ts" dir="ltr" contenteditable="false"'
            f' aria-label="{aria}">{_icon("play")}'
            f'<span dir="ltr">{format_range(sentence.start, display_end)}</span></button>'
        )
    copy_label = _t(strings, "copy_line", "Copy this sentence")
    lines.append(
        _button(
            None,
            css_class="icon-btn copy-line",
            icon="copy",
            aria_label=copy_label,
            extra='contenteditable="false"',
        )
    )
    lines.append("</div>")
    return "".join(lines)


def _render_turn_html(
    turn: Turn,
    turn_id: str,
    sentences: list[Sentence],
    speaker_label: str | None,
    timestamps: bool,
    strings: dict[str, str],
) -> str:
    """One <article class="turn">: a transparent grouping wrapper, then one card per sentence.

    The wrapper paints nothing, but it stays in the DOM as an invisible key:
    saved edits, localStorage, low-confidence flags, plain-row sync, the
    outline and search all key off its data-turn, and it is the unit an
    "apply to this whole block" reassignment (js/24-speakers-menus.js) acts
    on. data-start and data-speaker ride on it for the same reason.

    sentences comes from the caller (_render_document_html) rather than being
    computed here, to avoid calling turn.sentences() twice for one turn - the
    caller's low-confidence check needs it too.
    """
    speaker_attr = (
        f' data-speaker="{turn.speaker}" data-palette="{_palette_index(turn.speaker)}"'
        if turn.speaker is not None
        else ""
    )
    body_label = _t(strings, "turn_text", "Turn text")

    lines = [
        f'<article class="turn" data-turn="{turn_id}" data-start="{turn.start:.2f}"{speaker_attr}>',
        f'<div class="body" contenteditable="true" role="textbox"'
        f' aria-multiline="true" aria-label="{body_label}">',
    ]
    for idx, sentence in enumerate(sentences):
        line_id = f"{turn_id}-{idx}"
        lines.append(
            _render_bubble_html(
                sentence, line_id, turn_id, timestamps, speaker_label, turn.speaker, strings
            )
        )
    lines.append("</div>")
    lines.append("</article>")
    return "\n".join(lines)


def _render_plain_line_html(
    sentence: Sentence,
    line_id: str,
    number: int,
    timestamps: bool,
    strings: dict[str, str],
) -> str:
    """One sentence's own line in the copy-out panel.

    Rendered server-side, not built from nothing by the page script
    (core/assets/js/), so the panel is readable - and editable via native
    contenteditable - with JavaScript disabled, the way a bubble's own <p>
    already is. rebuildPlain() (js/32-plain-text.js) finds this element by its
    data-line id, the SAME id the matching .bubble carries (see
    _render_bubble_html()), and only updates its text or moves it rather than
    recreating it. That 1:1 line-to-bubble keying is what lets a heading land
    mid-turn; the caller decides whether one precedes this line, see
    _render_plain_html().

    Each line leads with "{LRI}{number}{PDI}. " - or, with timestamps on,
    "{LRI}{number}{PDI}. {LRI}[{range}]{PDI} " - the number and the range
    each sit in their OWN isolate, with the dot and the space between them
    OUTSIDE both. A single isolate around the whole lead-in puts the dot
    inside an LTR run: in an RTL paragraph the digit sits at the run's right
    edge and the text flows leftward from there, so a dot that trails the
    digit *inside* the isolate renders to the digit's right - wrong, since a
    Hebrew reader's eye moves right to left and the dot has to separate the
    number from what comes next, on its LEFT. Splitting the lead-in into two
    isolates makes the dot and the space between them ordinary neutral
    characters in the surrounding RTL paragraph, which is what puts them on
    the correct side. Verified by measuring painted glyph x-positions in a
    real browser, not reasoned about - see the review plan's "the RTL dot"
    section for the numbers.

    No dir="ltr" element wraps any of this - unlike the file-position span,
    this text has to stay a single contenteditable text node (one
    <span class="plain-body">, matching the card's single <p> contenteditable
    contract) so a wrapping element isn't available here.

    js/32-plain-text.js's input handler strips this lead-in
    (stripLineNumber()) before the edited text ever reaches the matching
    bubble's <p> - otherwise a future edit through this panel would bake a
    stale number and a stale timestamp into the transcript text itself.
    """
    lead = f"{LRI}{number}{PDI}. "
    if timestamps:
        # _display_end_second(), not sentence.end: see its docstring for the
        # degenerate "0:00 - 0:00" it exists to avoid. The isolates are
        # stripped and re-added around the whole bracketed range below, since
        # the lead-in's two isolates have to nest as described above.
        bare = (
            format_range(sentence.start, _display_end_second(sentence))
            .replace(LRI, "")
            .replace(PDI, "")
        )
        lead += f"{LRI}[{bare}]{PDI} "
    body_text = f"{lead}{sentence.text}"
    body_label = _t(strings, "turn_text", "Turn text")
    return (
        f'<div class="plain-line" data-line="{line_id}">'
        f'<span class="plain-body" contenteditable="true" role="textbox"'
        f' aria-label="{body_label}">{html.escape(body_text)}</span>'
        "</div>"
    )


def _render_plain_html(
    turns: list[Turn],
    turn_ids: list[str],
    speaker_label: str | None,
    timestamps: bool,
    strings: dict[str, str],
) -> str:
    """The copy-out panel.

    Always visible, not collapsed inside a <details>: pasting the whole
    recording elsewhere is what this document gets used for most, and burying
    the most-used feature one click below a summary line was the wrong trade.

    One <div class="plain-line" data-line="..."> per sentence (see
    _render_plain_line_html()), each keyed to its matching .bubble by the SAME
    data-line id, with a standalone <div class="plain-heading"> wherever the
    speaker changes from the sentence before. The panel groups by each
    sentence's EFFECTIVE speaker, not by which turn it sits in, so a
    client-side per-sentence reassignment (state.assignLine,
    js/24-speakers-menus.js) can break a sentence out into its own heading
    section mid-turn. This server render has no override to apply (overrides
    live only in client-side localStorage), so it groups purely by each turn's
    own speaker - correct for a fresh page - and rebuildPlain()
    (js/32-plain-text.js) recomputes the same run boundary client-side,
    walking bubbles instead of turns, once an override exists.

    Keeps its own per-document sentence counter, starting at 1, rather than
    receiving one from _render_document_html's turn loop: both loops walk the
    same turns in the same order and re-derive the same sentence texts, so two
    independent counts land on identical numbers - which they must - without
    sharing mutable state.

    previous_speaker tracks the last TURN's speaker, not a per-sentence value,
    since a heading can only start at a turn boundary in a server render.
    """
    s = partial(_t, strings)  # see _render_toolbar_html's s

    line_parts = []
    sentence_number = 1
    previous_speaker = None
    for turn_id, turn in zip(turn_ids, turns):
        starts_run = turn.speaker != previous_speaker
        for idx, sentence in enumerate(turn.sentences()):
            if idx == 0 and starts_run and speaker_label is not None and turn.speaker is not None:
                # Trailing colon, matching rebuildPlain()'s heading in
                # js/32-plain-text.js - the two MUST produce identical text
                # or the panel visibly rewrites itself the first time a
                # checkbox is toggled. It reads as a label rather than as a
                # stray one-word line, which matters most where this panel
                # is actually used: pasted into an app that keeps none of
                # the bold styling the heading has on screen.
                name = html.escape(_speaker_fallback(speaker_label, turn.speaker))
                line_parts.append(
                    f'<div class="plain-heading" contenteditable="false">{name}:</div>'
                )
            line_id = f"{turn_id}-{idx}"
            line_parts.append(
                _render_plain_line_html(
                    sentence,
                    line_id,
                    sentence_number,
                    timestamps,
                    strings,
                )
            )
            sentence_number += 1
        previous_speaker = turn.speaker
    rows = "".join(line_parts)

    # Each checkbox starts in the state the server actually rendered, never
    # hardcoded `checked`: a bubble carries data-start/data-end
    # unconditionally (playback needs them even when no range is displayed)
    # and 99-init.js calls rebuildPlain() on load, so a checked opt-ts on a
    # timestamps=False document would make the page fabricate bracketed ranges
    # the renderer deliberately left out - the reader sees timestamps they
    # switched off appearing by themselves. Same for opt-spk with no
    # speaker_label.
    ts_checked = " checked" if timestamps else ""
    spk_checked = " checked" if speaker_label is not None else ""

    copy_all_button = _button(s("copy_all", "Copy all"), css_class="tb-btn copy-all", icon="copy")
    return f"""<section class="plain">
<h2 class="plain-title"><span>{s("plain_text", "Plain text")}</span>
<span class="summary-hint">{s("plain_hint", "to paste into another app")}</span></h2>
<div class="plain-controls">
<label><input type="checkbox" class="opt-ts"{ts_checked}> {s("opt_timestamps", "Timestamps")}</label>
<label><input type="checkbox" class="opt-spk"{spk_checked}> {s("opt_speakers", "Speaker names")}</label>
{copy_all_button}
</div>
<div class="plain-text" tabindex="-1">{rows}</div>
</section>"""
