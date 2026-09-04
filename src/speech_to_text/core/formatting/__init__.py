"""Rendering structured segments into the output transcript file.

render_html() assembles the whole page from this package's parts: the JSON
data island the transcript's own script reads, each document's content
(document.py), the chrome that does not vary by document (chrome.py), and the
inlined CSS, JS and backdrop photos (assets.py). The other names below are
re-exported so callers keep importing them from one place.
"""

import html
import json
import uuid
from typing import Optional

from speech_to_text.core.hebrew_correct import CONFIDENCE_THRESHOLD
from speech_to_text.core.segments import TranscriptDocument

from .assets import (
    _ASSETS,
    _VISTAS_DIR,
    _asset,
    _asset_bytes,
    _asset_dir,
    _data_uri,
    _vista_data_uris,
    _vista_names,
    _vista_portrait_name,
)
from .chrome import (
    _ICON_DEFS,
    SPEAKER_PALETTE_SIZE,
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
    Sentence,
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
    "Sentence",
    "Turn",
    "merge_turns",
    "render_html",
]


def _json_payload(data: dict) -> str:
    """Serialise the page's data island.

    "<" is escaped so transcript text can never terminate the surrounding
    </script> element early, whatever the audio happened to contain.
    """
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def _build_payload(
    speaker_label: Optional[str],
    title: Optional[str],
    ui_strings: Optional[dict[str, str]],
) -> tuple:
    """The page's data island, before any document has rendered.

    Returns (payload, strings) rather than just payload: `strings` (the
    already-translated UI labels, defaulted to {}) is threaded through every
    other rendering step, so callers get it back alongside the dict it also
    lives inside of.

    payload["low"] starts empty and is filled in as a side effect of rendering
    each document's turns (_render_document_html appends to it): a turn's
    flagged words aren't known until its own Turn object is walked.
    """
    strings = dict(ui_strings or {})
    payload = {
        "threshold": CONFIDENCE_THRESHOLD,
        "filename": title or "transcript",
        "strings": strings,
        "low": {},
        # A speaker added client-side (no diarization run invents one for it)
        # still needs a translated "Speaker N" fallback, and the page has no
        # other way to reach the format string that produced every other
        # speaker's fallback. None when speaker_label itself is None: no
        # speaker UI renders then, so nothing ever reads this key.
        "speakerLabel": speaker_label,
    }
    return payload, strings


def _render_head_html(doc_id: str, title: Optional[str]) -> list[str]:
    """The <!doctype> through the closing </head>.

    data-doc-id on <html> is the key the page script stores and reloads its
    saved edits under, so it has to survive onto the root element.
    """
    return [
        "<!doctype html>",
        f'<html lang="he" dir="rtl" data-doc-id="{html.escape(doc_id)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title or 'Transcript')}</title>",
        f"<style>{_asset_dir('css')}</style>",
        "</head>",
    ]


def _render_script_html() -> str:
    """The page script's inline <script>.

    The concatenated fragments under core/assets/js/ (see _asset_dir()'s own
    docstring) are bare statement bodies, not standalone scripts: every one
    assumes it runs inside this single IIFE scope (a bare `return` in the
    first fragment returns from the IIFE; later fragments' functions and vars
    are only reachable because they all hoist into the same scope). This is
    the one place the wrapper is written, so no fragment file may carry a copy
    of its own.
    """
    return "<script>(function () {\n  'use strict';\n\n" + _asset_dir("js") + "\n})();</script>"


def _render_backdrop_html(vista: Optional[str]) -> list[str]:
    """The photographic backdrop for this render: a per-document <style> block
    plus the <div> it paints onto.

    Returns [] - not a blank string, so the caller can extend() it straight
    into the parts list without an "if" at the call site - when there is no
    backdrop to embed at all (see _vista_data_uris()'s docstring for when
    that happens).
    """
    vista_uris = _vista_data_uris(vista)
    if not vista_uris:
        return []

    landscape_uri, portrait_uri = vista_uris
    # A <style> element, not a style="background-image:url(...)" attribute:
    # an inline style attribute can only ever set ONE rule, but picking the
    # right crop per viewport needs a media query (see PORTRAIT_W's comment
    # in tools/build_vistas.py for why one crop cannot serve both desktop
    # and phone), and a media query can only live inside a <style> block.
    # The rule stays per-document rather than joining the shared stylesheet
    # (core/assets/css/): it changes with which photo this render picked.
    #
    # "<" is escaped in both URIs (the data: payload is base64, which
    # cannot itself contain "<", but escaping unconditionally rather than
    # asserting it can't costs nothing and matches _json_payload's same
    # defensive reasoning) so nothing in the embedded bytes could ever be
    # read as closing this </style> early.
    style_rules = [f".backdrop{{background-image:url({html.escape(landscape_uri)})}}"]
    if portrait_uri:
        # 3/4, not "orientation: portrait": orientation flips at aspect
        # ratio 1:1, but the landscape crop's cover-scaled visible width
        # is still an acceptable ~50%+ down to roughly 3:4 (see the
        # measured table in tools/build_vistas.py's PORTRAIT_W comment) -
        # switching at 1:1 would swap in the portrait crop for viewports
        # the landscape one still frames fine, for no benefit.
        style_rules.append(
            "@media (max-aspect-ratio: 3/4) { "
            f".backdrop{{background-image:url({html.escape(portrait_uri)})}} "
            "}"
        )
    return [
        f"<style>{''.join(style_rules)}</style>",
        # Right after the sprite, which paints nothing itself (zero size,
        # position:absolute), so the backdrop is still effectively the first
        # thing on the page to paint. See the .backdrop / isolation:isolate
        # comments in the stylesheet (core/assets/css/) for why paint order
        # here matters. aria-hidden and no alt text: it is decoration, and a
        # screen reader announcing "image" before every transcript would be
        # pure noise.
        '<div class="backdrop" aria-hidden="true"></div>',
    ]


def render_html(
    documents: list[TranscriptDocument],
    speaker_label: Optional[str] = None,
    timestamps: bool = True,
    failed_label: Optional[str] = None,
    title: Optional[str] = None,
    ui_strings: Optional[dict[str, str]] = None,
    doc_id: Optional[str] = None,
    vista: Optional[str] = None,
) -> str:
    """Render one or more transcripts into a single, self-contained RTL HTML
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
            looked up from this same name (see _vista_portrait_name()) so
            callers never have to know it exists. None (the default) picks one
            at random, a fresh choice on every render. Pin it when the caller
            needs a reproducible document - worker.py does this once per batch
            so the photo does not change on every per-file checkpoint rewrite.

    """
    doc_id = doc_id or uuid.uuid4().hex
    payload, strings = _build_payload(speaker_label, title, ui_strings)

    body: list[str] = []

    # Computed once here and threaded into _render_document_html rather than
    # recomputed there: merge_turns() is not free, it walks every segment. A
    # spy test pins the single call.
    turns_by_doc = [merge_turns(document.segments) for document in documents]

    total = len(documents)
    for index, document in enumerate(documents):
        body.extend(
            _render_document_html(
                document,
                index,
                total,
                turns_by_doc[index],
                speaker_label,
                timestamps,
                failed_label,
                strings,
                payload,
            )
        )

    outline_html = _render_outline_html(documents, speaker_label, strings)

    parts = _render_head_html(doc_id, title)
    parts.extend(
        [
            "<body>",
            # First child of body: every icon site below references it, so it has
            # to exist before any of them are parsed.
            _render_sprite_html(),
        ]
    )
    parts.extend(_render_backdrop_html(vista))
    parts.extend(
        [
            _render_toolbar_html(strings),
            # .layout is the grid that puts <aside> on the visual left of the
            # RTL document by pure source order (grid-template-columns's first
            # track maps to the inline-start edge, which is the right in RTL) -
            # see the .layout comment in the stylesheet (core/assets/css/).
            # <main> stays first so a screen reader or a JS-disabled reader
            # hits the transcript before the navigation aside, whichever side
            # each lands on visually.
            '<div class="layout">',
            "<main>",
        ]
    )
    parts.extend(body)
    parts.append("</main>")
    if outline_html:
        parts.append(outline_html)
    parts.extend(
        [
            "</div>",
            _render_player_html(strings),
            _render_toast_html(),
            _render_help_html(strings),
            '<script type="application/json" id="transcript-data">',
            _json_payload(payload),
            "</script>",
            _render_script_html(),
            "</body>",
            "</html>",
        ]
    )
    return "\n".join(parts)
