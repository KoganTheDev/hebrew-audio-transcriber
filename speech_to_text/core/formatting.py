"""
Rendering structured segments into the output transcript file.

Split out of Transcriber because formatting stopped being a model concern
once segments carried timing and speaker data: the renderer needs to know
about turn merging, bidi control characters and speaker label templates,
none of which have anything to do with running a Whisper model.

Stdlib only, and no PyQt5 - this runs inside the worker process.
"""

import base64
import html
import json
import logging
import random
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from speech_to_text.core.segments import Segment, TranscriptDocument, Word

# Confidence below which a word is worth a second look. Imported rather than
# redefined so "uncertain" means exactly one thing across the app - the same
# number gates the Hebrew term-correction pass.
from speech_to_text.core.hebrew_correct import CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Bidi control characters
# ---------------------------------------------------------------------------
# Writing "[00:01:23]" into a Hebrew line does not render as typed. Under the
# Unicode Bidirectional Algorithm, "[" and "]" are *neutral* characters with
# the Bidi_Mirrored property: in an RTL paragraph they resolve to RTL and the
# renderer substitutes the mirrored glyph, so the text displays as
# "]00:01:23[" - and the whole bracketed group can land on the wrong side of
# the line, because the digits inside it form an LTR run embedded in RTL text.
#
# The brackets are gone now - timestamps render as a range, "0:32 - 1:05" -
# but the isolate mechanism below is not optional decoration left over from
# them. The hyphen separating the two times is itself a neutral character,
# exactly like "[" and "]" were: sitting between two LTR digit runs inside an
# RTL paragraph, it can resolve either direction, and the two ends of the
# range can swap sides the same way the brackets used to. Wrapping the whole
# "M:SS - M:SS" span in one LRI/PDI pair - not each half separately - is what
# keeps "start - end" reading as start-then-end regardless of the Hebrew
# around it.
#
# Typing the brackets (or the hyphen's operands) in the opposite order "fixes"
# this in whichever program you happen to test, and breaks it in the next one,
# because it treats a rendering rule as if it were a character-order rule. It
# also corrupts the file for anything that parses timestamps. The actual fix
# is to tell the bidi algorithm what this run is:
#
#   LRI ... PDI  (U+2066 / U+2069) - Left-to-Right Isolate. Forces the enclosed
#       run to lay out LTR *and* isolates it, so it neither inherits direction
#       from the Hebrew around it nor leaks direction into it. Isolates are the
#       modern replacement for the older embedding controls precisely because
#       they don't leak.
#   RLM (U+200F) - Right-to-Left Mark. A zero-width strong RTL character. Placed
#       at the start of a line it pins the paragraph direction to RTL, so a line
#       that happens to begin with a digit or bracket doesn't flip its whole
#       layout. gui/i18n.py already uses this same trick for path lines.
LRI = "⁦"
PDI = "⁩"
# Retained deliberately even though the HTML renderer no longer emits it: the
# document declares dir="rtl", which settles paragraph direction outright, so
# there is nothing left for a strong-character hint to steer. It stays as the
# documented counterpart to the explanation above - and gui/i18n.py still uses
# the same character to anchor path lines inside the Qt UI, where there is no
# document direction to declare.
RLM = "‏"

# ---------------------------------------------------------------------------
# Turn merging
# ---------------------------------------------------------------------------
# Whisper emits a segment every few seconds - a decoder-sized unit, not a
# human-sized one. One timestamped line per segment produces a transcript
# that's technically correct and unreadable, so consecutive segments are merged
# into a "turn" until the speaker changes, the pause gets long enough to read as
# a break, or the turn simply grows too long to stay scannable.
TURN_GAP_SECONDS = 2.0
# 60s -> 30s: a 60-second block of unbroken Hebrew is exactly the "wall of
# text with a timestamp buried somewhere in the middle" shape that motivated
# this whole rewrite. Halving the cap keeps every block short enough to
# scan even before the sentence-per-<p> layout gets involved.
TURN_MAX_SECONDS = 30.0


def split_sentences(text: str) -> List[str]:
    """
    Split a transcript blob into one entry per sentence.

    Shared by format_plain (one sentence per text line) and render_html (one
    sentence per <p>) so the two output formats can't quietly drift apart on
    what counts as a sentence boundary.
    """
    if not text:
        return []
    try:
        sentences = re.split(r'(?<=[.!?])\s+', text)
        return [s.strip() for s in sentences if s.strip()]
    except Exception as e:
        logger.warning(f"Could not split sentences: {e}")
        return [text]


def format_plain(text: str) -> str:
    """
    Format a transcript blob with one sentence per line.

    This is the original pre-timestamps output format, kept so the app can
    still produce exactly what it produced before (see render_html(), which
    falls back to bare, unlabelled <p> sentences when there is nothing
    structural to show).
    """
    return "\n".join(split_sentences(text))


def _total_seconds(seconds: float) -> int:
    """Coerce to a non-negative whole second count, tolerating junk input."""
    try:
        return max(int(seconds), 0)
    except (TypeError, ValueError):
        return 0


def format_mmss(seconds: float) -> str:
    """Format as m:ss - used for live progress, where hours would be noise."""
    minutes, secs = divmod(_total_seconds(seconds), 60)
    return f"{minutes}:{secs:02d}"


def format_hhmmss(seconds: float) -> str:
    """
    Format as H:MM:SS - used for transcript timestamps.

    Always includes the hour, unlike format_mmss: a transcript timestamp is a
    position someone will scrub to, and "72:15" is harder to act on than
    "1:12:15".
    """
    hours, remainder = divmod(_total_seconds(seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_range(start: float, end: float) -> str:
    """
    Format a turn's timing as "M:SS - M:SS", isolated for RTL embedding.

    A single instant told the reader *when* a turn began; it did not tell them
    where it ended, so playing it ran on past the turn into whatever came
    next. A range says exactly what will play.

    Both ends promote to H:MM:SS together, never just one, once either passes
    an hour - "0:05:00 - 1:12:15" is legible, but the unpromoted
    "5:00 - 72:15" reads as a wrong number, not as an hour boundary. See the
    module docstring for why the whole range, not just each half, sits inside
    one LRI/PDI pair: the hyphen between the two LTR digit runs is a neutral
    character and can reorder the same way the old mirrored brackets did.
    """
    promote = _total_seconds(start) >= 3600 or _total_seconds(end) >= 3600
    fmt = format_hhmmss if promote else format_mmss
    return f"{LRI}{fmt(start)} - {fmt(end)}{PDI}"


class Turn:
    """One speaker's uninterrupted stretch of speech."""

    def __init__(self, segment: Segment):
        self.start = segment.start
        self.end = segment.end
        self.speaker = segment.speaker
        self._parts = [segment.text.strip()]
        # Per-word confidences are carried through rather than dropped: they
        # are what lets the reader see which words the model itself doubted,
        # which is the difference between proofreading the whole transcript
        # and proofreading the parts that need it. Same data hebrew_correct
        # already uses to decide what it is allowed to touch.
        self.words: List[Word] = list(segment.words or [])

    def append(self, segment: Segment) -> None:
        self.end = segment.end
        text = segment.text.strip()
        if text:
            self._parts.append(text)
        if segment.words:
            self.words.extend(segment.words)

    @property
    def text(self) -> str:
        return " ".join(part for part in self._parts if part)

    def low_confidence(self, threshold: float) -> List[list]:
        """
        Words the model was unsure about, as [text, probability, occurrence].

        The occurrence index counts how many times that exact token has
        already appeared in this turn, so a word that shows up twice with
        different confidences only gets flagged where it was actually
        uncertain. It is computed over the word list rather than over the
        rendered text; the two agree because the text is built from these
        same segments, and a rare disagreement costs at most a neighbouring
        duplicate being highlighted instead.
        """
        seen: dict = {}
        flagged: List[list] = []

        for word in self.words:
            token = (word.text or "").strip()
            if not token:
                continue
            index = seen.get(token, 0)
            seen[token] = index + 1
            if word.probability < threshold:
                flagged.append([token, round(float(word.probability), 3), index])

        return flagged


def merge_turns(
    segments: List[Segment],
    gap_seconds: float = TURN_GAP_SECONDS,
    max_seconds: float = TURN_MAX_SECONDS,
) -> List[Turn]:
    """Group consecutive segments into readable speaker turns."""
    turns: List[Turn] = []

    for segment in segments:
        if not segment.text or not segment.text.strip():
            continue

        current = turns[-1] if turns else None
        if (
            current is not None
            and segment.speaker == current.speaker
            and segment.start - current.end <= gap_seconds
            and segment.end - current.start <= max_seconds
        ):
            current.append(segment)
        else:
            turns.append(Turn(segment))

    return turns


# ---------------------------------------------------------------------------
# HTML rendering
# ---------------------------------------------------------------------------
# HTML replaces the plain-text renderer entirely (see the module docstring
# for why plain text can't be fixed: a .txt viewer picks its own paragraph
# direction, and RLM only steers that choice through the Unicode
# first-strong-character rule, which line-based viewers don't apply per
# line). Declaring dir="rtl" on the document sidesteps the guessing game.
#
# Fully self-contained on purpose - this app's premise is offline operation,
# so the stylesheet and script are inlined and nothing here ever references an
# external URL, font, or script. The only src the document ever carries is a
# relative path to the audio sitting beside it.
_ASSETS = Path(__file__).parent / "assets"


@lru_cache(maxsize=None)
def _asset(name: str) -> str:
    """
    Read an inlined asset.

    Kept as real .css/.js files rather than Python string literals so they
    stay lintable and syntax-highlighted; cached because a batch render would
    otherwise re-read them once per document for no reason.
    """
    return (_ASSETS / name).read_text(encoding="utf-8")


_VISTAS_DIR = _ASSETS / "vistas"


@lru_cache(maxsize=None)
def _vista_names() -> tuple:
    """
    Available LANDSCAPE backdrop photos, sorted so vista-01.webp always sorts
    first.

    Excludes *-portrait.webp: tools/build_vistas.py writes a portrait art-
    direction crop of every photo (vista-NN-portrait.webp) next to its
    landscape original (vista-NN.webp) in the same directory, for the
    @media (max-aspect-ratio) swap in render_html(). Without this filter the
    glob below would treat both crops of the same photo as two independent
    photos, so random.choice() in _vista_data_uris() could pick a bare
    "-portrait" file as the MAIN backdrop - and worse, doubling the pool
    biases selection toward whichever photos happen to have shipped a
    portrait crop. The suffix check keeps this function's contract exactly
    what it was before portrait crops existed: one entry per photo, always
    the landscape one, with the portrait crop reached separately by
    _vista_portrait_name().

    An empty tuple - whether because the directory is missing (an installed
    copy that lost its package data) or simply has nothing in it - is not an
    error here. render_html() reads it as "no backdrop", the same way it
    already behaves before this feature existed.
    """
    if not _VISTAS_DIR.is_dir():
        return ()
    return tuple(
        sorted(
            p.name for p in _VISTAS_DIR.glob("*.webp")
            if not p.stem.endswith("-portrait")
        )
    )


def _vista_portrait_name(landscape_name: str) -> Optional[str]:
    """
    The portrait art-direction crop for a chosen landscape backdrop, e.g.
    "vista-07.webp" -> "vista-07-portrait.webp", or None if that photo has no
    portrait crop on disk.

    A missing portrait file is not an error: build_vistas.py's byte budget
    can in principle skip writing a variant, and an older installed copy of
    the package may only carry landscape crops from before this feature
    existed. render_html() reads None as "no portrait swap for this document",
    the same "missing asset degrades gracefully" contract _vista_data_uris()
    already has for a missing backdrop entirely.
    """
    candidate = f"{Path(landscape_name).stem}-portrait.webp"
    if (_VISTAS_DIR / candidate).is_file():
        return candidate
    return None


@lru_cache(maxsize=None)
def _asset_bytes(name: str) -> bytes:
    """
    Binary counterpart to _asset(): the vista photos are WebP, not text, so
    they cannot go through _asset()'s read_text/utf-8 path. Cached for the
    same reason - a batch render would otherwise re-read the same file once
    per document.
    """
    return (_ASSETS / name).read_bytes()


def _data_uri(name: str) -> str:
    """base64-encode one file under vistas/ as a data:image/webp;... URI."""
    encoded = base64.b64encode(_asset_bytes(f"vistas/{name}")).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


def _vista_data_uris(vista: Optional[str]) -> Optional[tuple]:
    """
    Choose a backdrop and return (landscape_uri, portrait_uri_or_None).

    vista=None (the default) picks uniformly at random from whatever exists.
    A caller passing a specific filename - the "vista" parameter on
    render_html() - gets exactly that one back instead, which is how tests
    (and worker.py's per-run pin, so the photo does not change mid-batch on
    every checkpoint rewrite) get a deterministic document. Returns None,
    never raises, when there is nothing to embed: a missing or empty vistas/
    directory must still produce a working transcript, just without a
    backdrop.

    The second element is None, not a duplicate of the landscape URI, when
    the chosen photo has no portrait crop on disk - render_html() then emits
    only the landscape rule and no @media swap, which is a landscape-only
    backdrop rather than a broken one (see _vista_portrait_name()'s
    docstring for why that gap can exist).
    """
    names = _vista_names()
    if not names:
        return None

    chosen = vista if vista is not None else random.choice(names)
    if chosen not in names:
        raise ValueError(f"unknown vista {chosen!r}; available: {', '.join(names)}")

    portrait_name = _vista_portrait_name(chosen)
    portrait_uri = _data_uri(portrait_name) if portrait_name else None
    return _data_uri(chosen), portrait_uri


def _json_payload(data: dict) -> str:
    """
    Serialise the page's data island.

    "<" is escaped so transcript text can never terminate the surrounding
    </script> element early, whatever the audio happened to contain.
    """
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


# Eight swatches, verified in tests/test_transcript_styles.py against the
# composited panel background. Not a soft limit picked for symmetry - it's
# the size of the PAIRS table that guarantees every colour a speaker can wear
# still reads at 4.5:1. A ninth colour someone likes but never measures is
# exactly the failure this palette-only design (rather than a free picker)
# exists to rule out, so speaker identity wraps around it via modulo rather
# than growing past it.
SPEAKER_PALETTE_SIZE = 8


def _speaker_indices(segments: List[Segment]) -> List[int]:
    """Distinct speakers in a document, in first-appearance order."""
    ordered: List[int] = []
    for segment in segments:
        if segment.speaker is not None and segment.speaker not in ordered:
            ordered.append(segment.speaker)
    return ordered


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
    """
    strings = dict(ui_strings or {})
    doc_id = doc_id or uuid.uuid4().hex
    vista_uris = _vista_data_uris(vista)

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

    parts = [
        "<!doctype html>",
        f'<html lang="he" dir="rtl" data-doc-id="{html.escape(doc_id)}">',
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{html.escape(title or 'Transcript')}</title>",
        f"<style>{_asset('transcript.css')}</style>",
        "</head>",
        "<body>",
        # First child of body: every icon site below references it, so it has
        # to exist before any of them are parsed.
        _render_sprite_html(),
    ]
    if vista_uris:
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
        # Right after the sprite - the sprite paints nothing itself (zero
        # size, position:absolute), so the backdrop is still effectively the
        # first thing on the page to paint, ahead of any real content. See
        # the .backdrop / isolation:isolate comments in transcript.css for
        # why paint order here matters. No alt text and aria-hidden: it is
        # decoration, and a screen reader announcing "image" before every
        # transcript would be pure noise.
        parts.append(f"<style>{''.join(style_rules)}</style>")
        parts.append('<div class="backdrop" aria-hidden="true"></div>')
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
# Presentation lives on .icon in transcript.css (fill: none; stroke:
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
    # one out in this sprite). transcript.js's bindAudio() swaps the
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
    def s(key: str, fallback: str) -> str:
        return html.escape(strings.get(key, fallback))

    search = s("search", "Search transcript")
    return "\n".join([
        f'<header class="toolbar" role="toolbar"'
        f' aria-label="{s("toolbar", "Transcript tools")}">',
        # The toolbar's controls sit inside their own grid-column: 1 / -1
        # wrapper (see .tb-row in transcript.css, which spans both tracks
        # rather than sitting in a single one) rather than being grid items
        # of .toolbar directly - .tb-group is a flex row (a search box, a
        # cluster of action buttons), and a bare display: flex on the grid
        # items would fight the grid's own column placement instead of just
        # occupying it. This is what ties the toolbar's controls to the
        # same track boundaries main and the sidebar sit within.
        '<div class="tb-row">',
        '<div class="tb-group tb-search">',
        _icon("search"),
        f'<input id="search" type="search" placeholder="{search}" aria-label="{search}">',
        '<span id="search-count" class="count" aria-live="polite"></span>',
        f'<button id="search-prev" class="icon-btn"'
        f' aria-label="{s("search_prev", "Previous match")}">{_icon("up")}</button>',
        f'<button id="search-next" class="icon-btn"'
        f' aria-label="{s("search_next", "Next match")}">{_icon("down")}</button>',
        "</div>",
        '<div class="tb-group tb-actions">',
        f'<button id="toggle-flags" class="tb-btn" aria-pressed="false">{_icon("flag")}'
        f'<span>{s("show_uncertain", "Show uncertain words")}</span></button>',
        # Server-rendered assuming the light scheme, since that is this
        # element's state before any script runs; transcript.js corrects the
        # label on init if the system/browser is actually already in dark
        # mode (see bindChrome()'s theme handling), and swaps it again on
        # every click. The label names the action ("switch to dark"), not
        # the current state - "Theme" told the reader nothing about what
        # clicking it would do.
        f'<button id="toggle-theme" class="tb-btn"'
        f' aria-label="{s("toggle_theme", "Switch colour scheme")}"'
        f' data-label-dark="{s("theme_dark", "Dark mode")}"'
        f' data-label-light="{s("theme_light", "Light mode")}">{_icon("theme")}'
        f'<span>{s("theme_dark", "Dark mode")}</span></button>',
        f'<button id="export" class="tb-btn primary">{_icon("save")}'
        f'<span>{s("save_copy", "Save a copy")}</span></button>',
        f'<span id="status" class="status" role="status"'
        f' aria-live="polite">{s("status_saved", "Saved")}</span>',
        # Last in the group, not first - it opens a panel that explains every
        # OTHER control in this row, so it reads as "more about the above"
        # rather than as the first thing a reader's eye lands on. Plain
        # .tb-btn, not .primary: help is not the action this session builds
        # toward the way #export is (see the "Tier 1" comment on
        # .tb-btn.primary in transcript.css for what IS in that tier and
        # why #help isn't one of them).
        f'<button id="help" class="tb-btn" aria-expanded="false"'
        f' aria-controls="help-panel">{_icon("help")}'
        f'<span>{s("help", "Help")}</span></button>',
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
    # too - see below). transcript.js's bindAudio() swaps both this label
    # and the glyph between "play"/"pause" on the audio element's own
    # play/pause events, the same "swap on load and on every change" pattern
    # syncThemeLabel() already follows for the theme toggle.
    label = html.escape(strings.get("play_pause", "Play"))
    seek_label = html.escape(strings.get("seek", "Seek"))
    # A native <input type="range">, not a custom div-based track: it is
    # keyboard-operable (arrow keys, Home/End, Page Up/Down) and announced
    # with its role, value and bounds by every screen reader for free -
    # reimplementing that on a div was rejected because it means
    # reimplementing it *correctly*, not just visually. max starts at 0 and
    # is set once loadedmetadata reports the real duration (see bindAudio()
    # in transcript.js); before that, there is nothing to scrub to yet.
    # "current / total" sits in its own dir="ltr" span, with the usual
    # LRI/PDI isolate around the whole thing - same bidi shape as
    # format_range()'s "M:SS - M:SS", a neutral "/" between two LTR digit
    # runs inside an RTL document (see the module docstring).
    return f"""<div id="player" class="player" hidden>
<button id="player-toggle" class="icon-btn" aria-label="{label}">{_icon("play")}</button>
<span id="player-file" class="player-file"></span>
<input id="player-seek" class="seek" type="range" min="0" max="0" step="0.1" value="0"
 aria-label="{seek_label}">
<span id="player-time" class="player-time" dir="ltr">{LRI}0:00 / 0:00{PDI}</span>
<audio id="audio" preload="none"></audio>
</div>"""


def _render_toast_html() -> str:
    """
    A transient status announcement (currently just "copied"), driven by
    transcript.js hooking into copy()'s one shared success path.

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

    Server-rendered and hidden, never built by transcript.js from nothing -
    the same "readable with JavaScript disabled" contract the sprite has
    (see the comment above _ICON_DEFS): the panel's own content has to exist
    in the markup whether or not the script that reveals it ever runs.
    [hidden] is what gates it from a sighted reader and from the
    accessibility tree alike, exactly like .toast and .player above - it is
    never opened without JavaScript, but it is always *present* without it,
    which is the property that matters here.

    #tour-start renders unconditionally even though nothing in this module
    wires it up - a guided-tour feature elsewhere binds its click handler in
    transcript.js. This module cannot depend on that: speech_to_text/core/
    never imports anything the GUI or the page's own script owns (see the
    module docstring), so the only contract between the two is this button's
    id existing in the markup.
    """
    def s(key: str, fallback: str) -> str:
        return html.escape(strings.get(key, fallback))

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
           "recolour them from the swatch beside it. To move a single turn "
           "to a different speaker, click that speaker's name on the turn "
           "itself.")),
        ("play", s("help_playback_title", "Play a moment"),
         s("help_playback_desc",
           "Click a timestamp to play the recording from that turn; "
           "playback stops again at the end of the turn it started from.")),
        ("edit", s("help_editing_title", "Editing the transcript"),
         s("help_editing_desc",
           "Click into any turn's text to correct it directly, the same "
           "way you would edit a document. Changes save automatically to "
           "this browser as you type - use \"Save a copy\" to write "
           "them into a file you can keep or share.")),
        ("copy", s("help_plain_title", "Plain text"),
         s("help_plain_desc",
           "A copy-friendly version of the whole recording at the bottom "
           "of the page, with its own toggles for timestamps and speaker "
           "names - edit it there directly, or copy it out with one "
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
        f'<button id="help-close" class="icon-btn"'
        f' aria-label="{s("help_close", "Close help")}">{_icon("close")}</button>'
        "</div>"
        f'<button id="tour-start" class="tb-btn primary">'
        f'{s("tour_start", "Start guided tour")}</button>'
        f'<dl class="help-list">{items}</dl>'
        "</div>"
        "</div>"
    )


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
    # Same bidi shape as the timestamp range (see the module docstring): a
    # neutral "/" sitting between two LTR digit runs, inside an RTL
    # paragraph. Without the isolate this rendered as "2 / 1" for the first
    # of two files - the slash resolved RTL and swapped which number read as
    # the position and which read as the total.
    position = (
        strings.get("file_position", "{i} / {n}")
        .replace("{i}", str(index + 1))
        .replace("{n}", str(total))
    )
    accent = index % SPEAKER_PALETTE_SIZE
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


def _swatch_trigger_html(strings: Dict[str, str]) -> str:
    """
    The one always-visible colour control per speaker row.

    Earlier this rendered all eight palette slots expanded inline - with just
    two speakers that was sixteen 44px circles stacked above the transcript,
    taller than the content the strip exists to introduce. A trigger showing
    only the *current* colour, that opens a menu of the other seven on
    demand, keeps the resting strip about one row tall regardless of how many
    speakers a file has - the menu itself is built by transcript.js's
    buildSwatchMenu(), the same on-demand-popover shape as the turn's
    reassignment menu (buildSpeakerMenu()), not a second pattern invented for
    this. The swatch's own colour comes from the shared --spk custom
    property transcript.css sets once per data-palette index and inherits
    from .speaker-row down to this dot - this button carries no colour of
    its own to fall out of sync.
    """
    label = html.escape(strings.get("speaker_colour", "Speaker colour"))
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

    Not a <label> wrapping the whole row any more: once a row holds a text
    input *and* a colour trigger that opens its own menu, "label wraps one
    control" stops being true of it. The input keeps its own aria-label
    instead - already there before this changed, so nothing lost its
    accessible name.

    No locate button or turn count any more - both were removed as clutter.
    The row is just the swatch trigger and the name input, which is why this
    no longer needs each speaker's turns at all (turns was only ever read
    here to compute the count).
    """
    rows = []
    for speaker in speakers:
        fallback = speaker_label.format(n=speaker + 1)
        palette = speaker % SPEAKER_PALETTE_SIZE
        rows.append(
            f'<div class="speaker-row" data-speaker="{speaker}" data-palette="{palette}">'
            + _swatch_trigger_html(strings) +
            f'<input class="speaker-name" type="text" value=""'
            f' placeholder="{html.escape(fallback)}"'
            f' aria-label="{html.escape(fallback)}">'
            "</div>"
        )

    apply_all = (
        f'<button class="link-btn apply-all">'
        f'{html.escape(strings.get("apply_names_all", "Use these names in all files"))}</button>'
    )
    add_label = html.escape(strings.get("add_speaker", "Add speaker"))
    add_speaker = (
        f'<button type="button" class="tb-btn add-speaker">{_icon("plus")}'
        f'<span>{add_label}</span></button>'
    )
    title = html.escape(strings.get("speakers", "Speakers"))
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

    No longer takes turns_by_doc: that was only ever threaded down so
    _render_speakers_html could show a per-speaker turn count, and the count
    (along with the locate button beside it) is gone. render_html still
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
            f'<h2 class="outline-title">{html.escape(strings.get("files", "Files"))}</h2>'
            f'<ol class="outline-files">{"".join(items)}</ol>'
        )
    if panels:
        sections.append(f'<div class="outline-speakers">{"".join(panels)}</div>')

    label = html.escape(strings.get("outline", "Files and speakers"))
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
        label = html.escape(speaker_label.format(n=turn.speaker + 1))
        palette = turn.speaker % SPEAKER_PALETTE_SIZE
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

    copy_label = html.escape(strings.get("copy_turn", "Copy this turn"))
    actions = (
        f'<span class="turn-actions"><button class="icon-btn copy-turn"'
        f' aria-label="{copy_label}">{_icon("copy")}</button></span>'
    )

    speaker_attr = (
        f' data-speaker="{turn.speaker}" data-palette="{turn.speaker % SPEAKER_PALETTE_SIZE}"'
        if turn.speaker is not None else ""
    )
    body_label = html.escape(strings.get("turn_text", "Turn text"))

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
        # bracketedRange() - see that function's comment, and the module
        # docstring's LRI/PDI explanation, for why the brackets have to sit
        # inside the isolate rather than around it.
        bare = format_range(turn.start, turn.end).replace(LRI, "").replace(PDI, "")
        prefix_parts.append(f"{LRI}[{bare}]{PDI}")
    if speaker_label is not None and turn.speaker is not None:
        prefix_parts.append(f"{speaker_label.format(n=turn.speaker + 1)}:")
    prefix_text = f"{' '.join(prefix_parts)} " if prefix_parts else ""

    body_text = "\n".join(split_sentences(turn.text))
    body_label = html.escape(strings.get("turn_text", "Turn text"))
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
    def s(key: str, fallback: str) -> str:
        return html.escape(strings.get(key, fallback))

    rows = "".join(
        _render_plain_row_html(turn, turn_id, speaker_label, timestamps, strings)
        for turn_id, turn in zip(turn_ids, turns)
    )
    return f"""<section class="plain">
<h2 class="plain-title"><span>{s('plain_text', 'Plain text')}</span>
<span class="summary-hint">{s('plain_hint', 'to paste into another app')}</span></h2>
<div class="plain-controls">
<label><input type="checkbox" class="opt-ts" checked> {s('opt_timestamps', 'Timestamps')}</label>
<label><input type="checkbox" class="opt-spk" checked> {s('opt_speakers', 'Speaker names')}</label>
<button class="tb-btn copy-all">{_icon("copy")}<span>{s('copy_all', 'Copy all')}</span></button>
</div>
<div class="plain-text" tabindex="-1">{rows}</div>
</section>"""
