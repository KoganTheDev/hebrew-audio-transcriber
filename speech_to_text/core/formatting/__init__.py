"""
Rendering structured segments into the output transcript file.

Split out of Transcriber because formatting stopped being a model concern
once segments carried timing and speaker data: the renderer needs to know
about turn merging, bidi control characters and speaker label templates,
none of which have anything to do with running a Whisper model.

This used to be one ~1300-line module. It is a package now because
render_html() had grown into four unrelated jobs - page chrome, per-document
content, backdrop photo lookup, and time/bidi formatting - each with its own
docstrings and test surface, and "formatting.py" stopped meaning any one
thing. The split is purely structural: every name below is either defined
here or re-exported, unchanged, from wherever it moved to, so nothing outside
this package - callers, tests, worker.py - has to change how it imports.

    timecode.py  - bidi control chars, M:SS/H:MM:SS formatting, sentence
                   splitting. No dependency on segments, turns or HTML.
    turns.py     - Turn, merge_turns(): grouping raw segments into
                   readable speaker turns.
    assets.py    - reading the inlined stylesheet, script and backdrop
                   photos off disk.
    chrome.py    - the icon sprite, toolbar, mini-player, toast and help
                   panel - the parts of the page that don't vary by document.
    document.py  - the file bar, every turn, the outline sidebar, and the
                   plain-text panel - the parts that do.

This module (the package's own __init__.py) is what remains uniquely its
own: render_html() itself, broken into the assembly steps below, plus the
JSON data-island helper and the re-exports that keep the public surface (and
tests/test_formatting.py's imports, and worker.py's) unchanged.
"""

import html
import json
import uuid
from typing import Dict, List, Optional

from speech_to_text.core.hebrew_correct import CONFIDENCE_THRESHOLD
from speech_to_text.core.segments import TranscriptDocument

from .assets import (
    _ASSETS,
    _VISTAS_DIR,
    _asset,
    _asset_bytes,
    _data_uri,
    _vista_data_uris,
    _vista_names,
    _vista_portrait_name,
)
from .chrome import (
    SPEAKER_PALETTE_SIZE,
    _ICON_DEFS,
    _button,
    _icon,
    _palette_index,
    _render_help_html,
    _render_player_html,
    _render_sprite_html,
    _render_toast_html,
    _render_toolbar_html,
    _speaker_fallback,
    _swatch_trigger_html,
    _t,
)
from .document import (
    _render_document_html,
    _render_file_bar_html,
    _render_outline_html,
    _render_plain_html,
    _render_plain_row_html,
    _render_speakers_html,
    _render_turn_html,
)
from .timecode import (
    LRI,
    PDI,
    RLM,
    _total_seconds,
    format_hhmmss,
    format_mmss,
    format_plain,
    format_range,
    split_sentences,
)
from .turns import (
    TURN_GAP_SECONDS,
    TURN_MAX_SECONDS,
    Turn,
    _speaker_indices,
    merge_turns,
)

__all__ = [
    "LRI",
    "PDI",
    "RLM",
    "format_mmss",
    "format_hhmmss",
    "format_range",
    "split_sentences",
    "format_plain",
    "TURN_GAP_SECONDS",
    "TURN_MAX_SECONDS",
    "Turn",
    "merge_turns",
    "render_html",
]


def _json_payload(data: dict) -> str:
    """
    Serialise the page's data island.

    "<" is escaped so transcript text can never terminate the surrounding
    </script> element early, whatever the audio happened to contain.
    """
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def _build_payload(
    speaker_label: Optional[str],
    title: Optional[str],
    ui_strings: Optional[Dict[str, str]],
) -> tuple:
    """
    Job 1 of render_html(): the page's data island, before any document has
    rendered.

    Returns (payload, strings) rather than just payload: `strings` (the
    already-translated UI labels, defaulted to {}) is threaded through every
    other rendering step below, not just this one, so callers get it back
    alongside the dict it also lives inside of.

    payload["low"] starts empty and is filled in as a side effect of
    rendering each document's turns (_render_document_html appends to it) -
    that mutation happens during body assembly, not here, because a turn's
    flagged words aren't known until its own Turn object is walked.
    """
    strings = dict(ui_strings or {})
    payload = {
        "threshold": CONFIDENCE_THRESHOLD,
        "filename": title or "transcript",
        "strings": strings,
        "low": {},
        # A speaker added client-side (there is no diarization run to invent
        # one for it) still needs a translated "Speaker N" fallback text, and
        # this module runs in the worker process - the page has no other way
        # to reach the format string that produced every other speaker's
        # fallback. None when speaker_label itself is None: no speaker UI
        # renders at all in that case, so nothing will ever read this key.
        "speakerLabel": speaker_label,
    }
    return payload, strings


def _render_head_html(doc_id: str, title: Optional[str]) -> List[str]:
    """
    Job 2 of render_html(): the <!doctype> through the closing </head>.

    Kept to exactly this span - not through <body> - because the backdrop
    <style> block (job 3) and the sprite are both things that get inserted
    right after <body> opens, not inside <head>; splitting the boundary here
    rather than after "<body>" keeps each job's job title literally true.
    """
    return [
        "<!doctype html>",
        f'<html lang="he" dir="rtl" data-doc-id="{html.escape(doc_id)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title or 'Transcript')}</title>",
        f"<style>{_asset('transcript.css')}</style>",
        "</head>",
    ]


def _render_backdrop_html(vista: Optional[str]) -> List[str]:
    """
    Job 3 of render_html(): this render's photographic backdrop, as a
    per-document <style> block plus the <div> it paints onto.

    Returns [] - not a blank string, so the caller can extend() it straight
    into the parts list without an "if" at the call site - when there is no
    backdrop to embed at all (see _vista_data_uris()'s docstring for when
    that happens).
    """
    vista_uris = _vista_data_uris(vista)
    if not vista_uris:
        return []

    landscape_uri, portrait_uri = vista_uris
    # A <style> element, not the old style="background-image:url(...)"
    # attribute: an inline style attribute can only ever set ONE rule, but
    # picking the right crop per viewport needs a media query (see
    # PORTRAIT_W's comment in tools/build_vistas.py for why one crop
    # cannot serve both desktop and phone), and a media query can only
    # live inside a <style> block, not an attribute. The rule is still
    # per-document, not part of the shared transcript.css - like the old
    # inline style, it changes with which photo this render picked, while
    # the stylesheet does not.
    #
    # "<" is escaped in both URIs (the data: payload is base64, which
    # cannot itself contain "<", but escaping unconditionally rather than
    # asserting it can't costs nothing and matches _json_payload's same
    # defensive reasoning) so nothing in the embedded bytes could ever be
    # read as closing this </style> early.
    style_rules = [
        f'.backdrop{{background-image:url({html.escape(landscape_uri)})}}'
    ]
    if portrait_uri:
        # 3/4, not "orientation: portrait": orientation flips at aspect
        # ratio 1:1, but the landscape crop's cover-scaled visible width
        # is still an acceptable ~50%+ down to roughly 3:4 (see the
        # measured table in tools/build_vistas.py's PORTRAIT_W comment) -
        # switching at 1:1 would swap in the portrait crop for viewports
        # the landscape one still frames fine, for no benefit.
        style_rules.append(
            '@media (max-aspect-ratio: 3/4) { '
            f'.backdrop{{background-image:url({html.escape(portrait_uri)})}} '
            '}'
        )
    return [
        f"<style>{''.join(style_rules)}</style>",
        # Right after the sprite - the sprite paints nothing itself (zero
        # size, position:absolute), so the backdrop is still effectively the
        # first thing on the page to paint, ahead of any real content. See
        # the .backdrop / isolation:isolate comments in transcript.css for
        # why paint order here matters. No alt text and aria-hidden: it is
        # decoration, and a screen reader announcing "image" before every
        # transcript would be pure noise.
        '<div class="backdrop" aria-hidden="true"></div>',
    ]


def render_html(
    documents: List[TranscriptDocument],
    speaker_label: Optional[str] = None,
    timestamps: bool = True,
    failed_label: Optional[str] = None,
    title: Optional[str] = None,
    ui_strings: Optional[Dict[str, str]] = None,
    doc_id: Optional[str] = None,
    vista: Optional[str] = None,
) -> str:
    """
    Render one or more transcripts into a single, self-contained RTL HTML
    document that can be read, corrected and exported.

    Args:
        documents: one TranscriptDocument per source file, in the order they
            should appear. Every document renders through the same
            <section class="source"> shape, whether there is one or many - so
            there's no "single file" special case to get subtly wrong.
        speaker_label: format string for a speaker name, e.g. "דובר {n}".
            Rendered here and also handed to the page as each speaker's
            fallback, because the browser has no way to rebuild it once the
            user clears a custom name.
        timestamps: whether each turn carries its start time.
        failed_label: pre-translated text shown for a document whose `failed`
            flag is set. None is only safe if no document is marked failed.
        title: the document <title>, and the stem of the exported filename.
        ui_strings: already-translated labels for the page's own chrome
            (search, save, plain text, …). This module runs in the worker
            process, which has no access to gui.i18n and does not know the UI
            language, so the strings arrive as data - the same reason
            speaker_label does. Missing keys fall back to English inside the
            page.
        doc_id: identity used to key the browser's saved edits. Generated when
            not supplied; pass one to keep a re-render addressing the same
            saved edits.
        vista: filename of the LANDSCAPE backdrop photo under
            core/assets/vistas/ to pin, e.g. "vista-07.webp" - always the
            bare landscape name, never a "-portrait" one; that variant is
            looked up automatically from this same name (see
            _vista_portrait_name()) so callers never have to know it exists.
            None (the default) picks one at random - a fresh choice on every
            render, which is what a person actually wants and what makes two
            default renders differ in tests. Pin it when the caller needs a
            specific, reproducible document - worker.py does this once per
            batch so the photo does not change on every per-file checkpoint
            rewrite.

    Broken into four jobs, in the order this function performs them: build
    the data payload (_build_payload), render each document's own content
    (the loop below, via _render_document_html), assemble <head>
    (_render_head_html) and the per-document backdrop CSS
    (_render_backdrop_html), then stitch everything into the final page. The
    last of those stays inline here rather than becoming a fifth helper: it
    is the one step that actually needs every other step's output in hand,
    so factoring it out would just move the same assembly code one call
    deeper for no clarity gained.
    """
    doc_id = doc_id or uuid.uuid4().hex
    payload, strings = _build_payload(speaker_label, title, ui_strings)

    # The file list used to render as a <nav class="toc"> inline at the top
    # of the reading column - the same column every file's turns scroll
    # through, so it scrolled out of reach after the first file. It is now
    # part of the outline sidebar instead of a second copy alongside it: see
    # _render_outline_html(), which also absorbs the per-file speakers strip
    # that _render_document_html used to render inline (same reasoning -
    # speaker management is navigation-adjacent, not reading content).
    body: List[str] = []

    # Computed once, here, rather than inside _render_document_html: the
    # outline sidebar used to need each document's turns too, to show a
    # per-speaker turn count next to the (now-removed) locate button, so this
    # stayed a single list threaded to both call sites rather than have
    # merge_turns() - which is not free, it walks every segment - group the
    # same document's segments into turns twice. The outline no longer reads
    # turns at all, but _render_document_html still does, so the single-call
    # structure (and its spy test) stays.
    turns_by_doc = [merge_turns(document.segments) for document in documents]

    total = len(documents)
    for index, document in enumerate(documents):
        body.extend(_render_document_html(
            document, index, total, turns_by_doc[index], speaker_label, timestamps,
            failed_label, strings, payload,
        ))

    outline_html = _render_outline_html(documents, speaker_label, strings)

    parts = _render_head_html(doc_id, title)
    parts.extend([
        "<body>",
        # First child of body: every icon site below references it, so it has
        # to exist before any of them are parsed.
        _render_sprite_html(),
    ])
    parts.extend(_render_backdrop_html(vista))
    parts.extend([
        _render_toolbar_html(strings),
        # .layout is the grid that puts <aside> on the visual left of the
        # RTL document by pure source order (grid-template-columns's first
        # track maps to the inline-start edge, which is the right in RTL) -
        # see the .layout comment in transcript.css. <main> stays first so a
        # screen reader or a JS-disabled reader hits the actual transcript
        # before the navigation/speaker-management aside, matching normal
        # reading order regardless of which side either lands on visually.
        '<div class="layout">',
        "<main>",
    ])
    parts.extend(body)
    parts.append("</main>")
    if outline_html:
        parts.append(outline_html)
    parts.extend([
        "</div>",
        _render_player_html(strings),
        _render_toast_html(),
        _render_help_html(strings),
        '<script type="application/json" id="transcript-data">',
        _json_payload(payload),
        "</script>",
        f"<script>{_asset('transcript.js')}</script>",
        "</body>",
        "</html>",
    ])
    return "\n".join(parts)
