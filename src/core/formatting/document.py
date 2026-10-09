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

from core.hebrew_corrections import CONFIDENCE_THRESHOLD
from core.segments import TranscriptDocument

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
        # Keyed by the same line id _render_turn_html() gives each bubble, so
        # the page can look a card's words up by its own data-line. Sentences
        # with no word timings (a segment transcribed without them) simply
        # contribute no entry - the page treats a missing key as "cannot split
        # this one accurately" rather than guessing.
        for idx, sentence in enumerate(sentences):
            if sentence.words:
                payload["words"][f"{turn_id}-{idx}"] = [
                    [round(w.start, 2), round(w.end, 2), w.text] for w in sentence.words
                ]
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
    """Editable names and colours for this recording's speakers, in the sidebar.

    Per file: speaker 1 in one recording is rarely speaker 1 in another. The
    .speaker-row shape and data-file are what the page script selects on.
    active=True marks the panel shown before the script decides which file is
    in view; without JavaScript every panel stays visible. Not a <label>: the
    row holds two controls, so the input carries its own aria-label.
    """
    # Remove is rendered on every row and hidden by CSS at two speakers: the
    # page script can add a third without a re-render.
    remove_label = _t(strings, "remove_speaker", "Remove speaker")
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
            + _button(
                None,
                css_class="icon-btn remove-speaker",
                icon="trash",
                aria_label=remove_label,
                extra='type="button"',
            )
            + "</div>"
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
    """The end second to show for a sentence's range.

    format_range() truncates, so a sub-second sentence reads "0:00 - 0:00".
    Rounding every end up instead makes neighbours overlap ("0:00 - 0:02",
    "0:01 - 0:04"). So truncate, with a floor of one second. Display only -
    playback uses the true end.
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

    The bubble carries data-turn (so "apply to this block" finds its siblings)
    and data-start/data-end always, whatever the timestamps toggle, for
    playback. The play button shows the range (_display_end_second) but reads
    its times from the bubble, so there is one true end.

    The time is an LTR isolate (see timecode.py) and contenteditable="false",
    since the bubble sits in an editable .body and the time would otherwise be
    typed over and persisted.

    The speaker chip is always rendered - it is also the reassignment menu's
    trigger. With speaker None (attribution found no span) it is a neutral
    data-unattributed chip, so the card can still be fixed by hand. No chip at
    all only when no diarization ran.
    """
    reassign_label = html.escape(strings.get("reassign_line", "Reassign this sentence"))
    chip_html = ""
    speaker_attr = ""
    if speaker_label is not None:
        if speaker is not None:
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
        else:
            # Unattributed: no data-speaker (it must never read as speaker 0),
            # but data-unattributed so CSS and JS can recognise the state.
            unattributed_label = html.escape(strings.get("unattributed_speaker", "Unknown speaker"))
            speaker_attr = ' data-unattributed="true"'
            chip_html = (
                f'<span class="bubble-spk-anchor" contenteditable="false">'
                f'<button type="button" class="bubble-spk" data-unattributed="true"'
                f' data-fallback="{unattributed_label}"'
                f' aria-haspopup="true" aria-expanded="false" aria-label="{reassign_label}">'
                f'<span class="bubble-spk-label">{unattributed_label}</span></button>'
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
    """One <article class="turn">: an invisible wrapper around one card per
    sentence. Paints nothing, but saved edits, flags, search and block
    reassignment all key off its data-turn. `sentences` comes from the caller,
    which needs them too.
    """
    # Speaker None needs nothing here: each bubble carries its own
    # data-unattributed chip.
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
    """One sentence's line in the copy-out panel.

    Server-rendered, so the panel works without JavaScript; rebuildPlain()
    finds it by the same data-line id as its bubble and only updates it.

    The lead-in is "{LRI}n{PDI}. " (plus "{LRI}[range]{PDI} " with timestamps):
    the number and range get separate isolates with the dot outside both, or
    in RTL the dot lands on the wrong side of the number - measured in a real
    browser. No dir="ltr" wrapper: the line must stay one contenteditable text
    node. The page script strips the lead-in before an edit reaches the card.
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
    """The copy-out panel - always visible, since pasting the whole recording
    elsewhere is the document's most common use.

    One line per sentence, keyed to its bubble by data-line, with a heading
    wherever the speaker changes. The server groups by each turn's speaker;
    the page script regroups by each sentence's effective speaker once the
    user reassigns one. The sentence counter re-derives the same numbers as
    the card loop. previous_speaker starts at a sentinel, not None, since None
    is a real (unattributed) speaker and would swallow the first heading.
    """
    _no_previous_turn = object()
    s = partial(_t, strings)  # see _render_toolbar_html's s

    line_parts = []
    sentence_number = 1
    previous_speaker = _no_previous_turn
    for turn_id, turn in zip(turn_ids, turns):
        starts_run = turn.speaker != previous_speaker
        for idx, sentence in enumerate(turn.sentences()):
            if idx == 0 and starts_run and speaker_label is not None:
                # Trailing colon, identical to rebuildPlain()'s, or the panel
                # rewrites itself on the first toggle. Unattributed turns get
                # the same label as their chip rather than no heading.
                name = (
                    html.escape(_speaker_fallback(speaker_label, turn.speaker))
                    if turn.speaker is not None
                    else html.escape(strings.get("unattributed_speaker", "Unknown speaker"))
                )
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

    # Checkboxes start as the server rendered: the page rebuilds the panel on
    # load, so a checked timestamp box on a timestamps=False document would
    # fabricate ranges the user switched off.
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
