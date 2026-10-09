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

from core.hebrew_corrections import CONFIDENCE_THRESHOLD
from core.segments import TranscriptDocument

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
    speaker_label: str | None,
    title: str | None,
    ui_strings: dict[str, str] | None,
) -> tuple:
    """The page's data island, and the translated UI strings threaded through
    every rendering step. "low" and "words" fill in as each document renders.
    """
    strings = dict(ui_strings or {})
    payload = {
        "threshold": CONFIDENCE_THRESHOLD,
        "filename": title or "transcript",
        "strings": strings,
        "low": {},
        # Per-sentence word timings ({"0-1-2": [[start, end, "word"], ...]}),
        # so splitting a card starts the new one at a real word boundary
        # instead of an interpolated guess. ~2.5% of the document; positional
        # arrays, since key names would outweigh the values.
        "words": {},
        # A speaker added client-side (no diarization run invents one for it)
        # still needs a translated "Speaker N" fallback, and the page has no
        # other way to reach the format string that produced every other
        # speaker's fallback. None when speaker_label itself is None: no
        # speaker UI renders then, so nothing ever reads this key.
        "speakerLabel": speaker_label,
    }
    return payload, strings


def _render_head_html(doc_id: str, title: str | None) -> list[str]:
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
    """The page script: the core/assets/js/ fragments inside one IIFE, written
    only here - the fragments are bare statements sharing its scope.
    """
    return "<script>(function () {\n  'use strict';\n\n" + _asset_dir("js") + "\n})();</script>"


def _render_backdrop_html(vista: str | None) -> list[str]:
    """The backdrop's <style> and <div>, or [] when there is no photo."""
    vista_uris = _vista_data_uris(vista)
    if not vista_uris:
        return []

    landscape_uri, portrait_uri = vista_uris
    # A <style> block, since choosing the crop per viewport needs a media
    # query; per-document because the photo varies. "<" is escaped so the
    # payload can never close the </style> early.
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
        # First to paint (the sprite before it draws nothing). Decoration, so
        # aria-hidden with no alt text.
        '<div class="backdrop" aria-hidden="true"></div>',
    ]


def render_html(
    documents: list[TranscriptDocument],
    speaker_label: str | None = None,
    timestamps: bool = True,
    failed_label: str | None = None,
    title: str | None = None,
    ui_strings: dict[str, str] | None = None,
    doc_id: str | None = None,
    vista: str | None = None,
) -> str:
    """Render one or more transcripts into one self-contained RTL HTML page
    that can be read, corrected and exported.

    Args:
        documents: one TranscriptDocument per source file, in order.
        speaker_label: format string such as "דובר {n}"; also the page's
            fallback name once the user clears a custom one.
        timestamps: whether each turn shows its start time.
        failed_label: translated text for a failed document; None only when
            none failed.
        title: the <title>, and the exported filename's stem.
        ui_strings: translated labels for the page chrome - passed as data,
            since this runs in the worker, which has no gui.i18n. Missing keys
            fall back to English in the page.
        doc_id: keys the browser's saved edits; pass one so a re-render keeps
            them. Generated when omitted.
        vista: the landscape backdrop to pin ("vista-07.webp"); its portrait
            crop is found from the name. None picks one at random.

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
            # The grid puts <aside> on the visual left by source order; <main>
            # comes first so screen readers reach the transcript first.
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
