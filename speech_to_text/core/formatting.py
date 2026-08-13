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
    Available backdrop photos, sorted so vista-01.webp always sorts first.

    An empty tuple - whether because the directory is missing (an installed
    copy that lost its package data) or simply has nothing in it - is not an
    error here. render_html() reads it as "no backdrop", the same way it
    already behaves before this feature existed.
    """
    if not _VISTAS_DIR.is_dir():
        return ()
    return tuple(sorted(p.name for p in _VISTAS_DIR.glob("*.webp")))


@lru_cache(maxsize=None)
def _asset_bytes(name: str) -> bytes:
    """
    Binary counterpart to _asset(): the vista photos are WebP, not text, so
    they cannot go through _asset()'s read_text/utf-8 path. Cached for the
    same reason - a batch render would otherwise re-read the same file once
    per document.
    """
    return (_ASSETS / name).read_bytes()


def _vista_data_uri(vista: Optional[str]) -> Optional[str]:
    """
    Choose a backdrop and return it as a data:image/webp;base64,... URI.

    vista=None (the default) picks uniformly at random from whatever exists.
    A caller passing a specific filename - the "vista" parameter on
    render_html() - gets exactly that one back instead, which is how tests
    get a deterministic document. Returns None, never raises, when there is
    nothing to embed: a missing or empty vistas/ directory must still produce
    a working transcript, just without a backdrop.
    """
    names = _vista_names()
    if not names:
        return None

    chosen = vista if vista is not None else random.choice(names)
    if chosen not in names:
        raise ValueError(f"unknown vista {chosen!r}; available: {', '.join(names)}")

    encoded = base64.b64encode(_asset_bytes(f"vistas/{chosen}")).decode("ascii")
    return f"data:image/webp;base64,{encoded}"


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
        vista: filename of a backdrop photo under core/assets/vistas/ to pin,
            e.g. "vista-07.webp". None (the default) picks one at random -
            a fresh choice on every render, which is what a person actually
            wants and what makes two default renders differ in tests. Pin it
            when the caller needs a specific, reproducible document.
    """
    strings = dict(ui_strings or {})
    doc_id = doc_id or uuid.uuid4().hex
    vista_uri = _vista_data_uri(vista)

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

    body: List[str] = []

    if len(documents) > 1:
        body.append('<nav class="toc" aria-label="%s"><ol>'
                    % html.escape(strings.get("files", "Files")))
        for index, document in enumerate(documents):
            body.append(
                f'<li><a href="#src-{index}">{html.escape(document.source_name)}</a></li>'
            )
        body.append("</ol></nav>")

    total = len(documents)
    for index, document in enumerate(documents):
        body.extend(_render_document_html(
            document, index, total, speaker_label, timestamps, failed_label, strings, payload,
        ))

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
    ]
    if vista_uri:
        # First child of body, ahead of everything else, so it establishes
        # the backdrop layer before any real content paints on top of it -
        # see the .backdrop / isolation:isolate comments in transcript.css
        # for why paint order here matters. No alt text and aria-hidden: it
        # is decoration, and a screen reader announcing "image" before every
        # transcript would be pure noise.
        parts.append(
            f'<div class="backdrop" aria-hidden="true" '
            f'style="background-image:url({html.escape(vista_uri)})"></div>'
        )
    parts.extend([
        _render_toolbar_html(strings),
        "<main>",
    ])
    parts.extend(body)
    parts.extend([
        "</main>",
        _render_player_html(strings),
        _render_toast_html(),
        '<script type="application/json" id="transcript-data">',
        _json_payload(payload),
        "</script>",
        f"<script>{_asset('transcript.js')}</script>",
        "</body>",
        "</html>",
    ])
    return "\n".join(parts)


def _icon(path: str) -> str:
    """An inline SVG glyph. Never an emoji - those are font-dependent."""
    return (
        '<svg class="icon" viewBox="0 0 24 24" aria-hidden="true" fill="none" '
        'stroke="currentColor" stroke-width="1.6" stroke-linecap="round" '
        f'stroke-linejoin="round">{path}</svg>'
    )


_ICON_SEARCH = _icon('<circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/>')
_ICON_UP = _icon('<path d="M18 15l-6-6-6 6"/>')
_ICON_DOWN = _icon('<path d="M6 9l6 6 6-6"/>')
_ICON_FLAG = _icon('<path d="M5 21V4h9l1 2h5v9h-6l-1-2H5"/>')
_ICON_THEME = _icon('<path d="M21 13a9 9 0 11-10-10 7 7 0 0010 10z"/>')
_ICON_SAVE = _icon('<path d="M12 3v12"/><path d="M8 11l4 4 4-4"/><path d="M4 21h16"/>')
_ICON_COPY = _icon('<rect x="9" y="9" width="11" height="11" rx="2"/>'
                   '<path d="M5 15V5a2 2 0 012-2h8"/>')
_ICON_PLAY = _icon('<path d="M7 4l12 8-12 8z"/>')
_ICON_PLUS = _icon('<path d="M12 5v14"/><path d="M5 12h14"/>')


def _render_toolbar_html(strings: Dict[str, str]) -> str:
    """The document's own chrome: search, view toggles, export, save status."""
    def s(key: str, fallback: str) -> str:
        return html.escape(strings.get(key, fallback))

    search = s("search", "Search transcript")
    return "\n".join([
        f'<header class="toolbar" role="toolbar"'
        f' aria-label="{s("toolbar", "Transcript tools")}">',
        '<div class="tb-group tb-search">',
        _ICON_SEARCH,
        f'<input id="search" type="search" placeholder="{search}" aria-label="{search}">',
        '<span id="search-count" class="count" aria-live="polite"></span>',
        f'<button id="search-prev" class="icon-btn"'
        f' aria-label="{s("search_prev", "Previous match")}">{_ICON_UP}</button>',
        f'<button id="search-next" class="icon-btn"'
        f' aria-label="{s("search_next", "Next match")}">{_ICON_DOWN}</button>',
        "</div>",
        '<div class="tb-group tb-actions">',
        f'<button id="toggle-flags" class="tb-btn" aria-pressed="false">{_ICON_FLAG}'
        f'<span>{s("show_uncertain", "Uncertain words")}</span></button>',
        f'<button id="toggle-theme" class="tb-btn"'
        f' aria-label="{s("toggle_theme", "Switch colour scheme")}">{_ICON_THEME}'
        f'<span>{s("theme", "Theme")}</span></button>',
        f'<button id="export" class="tb-btn primary">{_ICON_SAVE}'
        f'<span>{s("save_copy", "Save a copy")}</span></button>',
        f'<span id="status" class="status" role="status"'
        f' aria-live="polite">{s("status_saved", "Saved")}</span>',
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
    label = html.escape(strings.get("play_pause", "Play or pause"))
    return f"""<div id="player" class="player" hidden>
<button id="player-toggle" class="icon-btn" aria-label="{label}">{_ICON_PLAY}</button>
<span id="player-file" class="player-file"></span>
<span id="player-time" class="player-time" dir="ltr">0:00</span>
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
    speaker_label: Optional[str],
    timestamps: bool,
    failed_label: Optional[str],
    strings: Dict[str, str],
    payload: dict,
) -> List[str]:
    """One <section class="source">: sticky file bar, speakers strip, turns, plain text."""
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

    turns = merge_turns(document.segments)
    speakers = _speaker_indices(document.segments)

    if speaker_label is not None and speakers:
        lines.append(_render_speakers_html(index, speakers, speaker_label, strings))

    for position, turn in enumerate(turns):
        turn_id = f"{index}-{position}"
        flagged = turn.low_confidence(CONFIDENCE_THRESHOLD)
        if flagged:
            payload["low"][turn_id] = flagged
        lines.append(_render_turn_html(turn, turn_id, speaker_label, timestamps, strings))

    lines.append(_render_plain_html(strings))
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
    this. The swatch's own colour comes from the .speaker-row[data-palette]
    CSS rule already in transcript.css, keyed off the row's data-palette -
    this button carries no colour of its own to fall out of sync.
    """
    label = html.escape(strings.get("speaker_colour", "Speaker colour"))
    return (
        f'<button type="button" class="swatch-trigger" aria-haspopup="true"'
        f' aria-expanded="false" aria-label="{label}">'
        '<span class="swatch" aria-hidden="true"></span></button>'
    )


def _render_speakers_html(
    file_index: int,
    speakers: List[int],
    speaker_label: str,
    strings: Dict[str, str],
) -> str:
    """
    Editable names, colours and roster for this recording's speakers.

    Per file rather than global: speaker 1 in one recording is rarely the same
    person as speaker 1 in another, so names stay local and an explicit action
    copies them across when it really is the same meeting.

    Not a <label> wrapping the whole row any more: once a row holds a text
    input *and* a colour trigger that opens its own menu, "label wraps one
    control" stops being true of it. The input keeps its own aria-label
    instead - already there before this changed, so nothing lost its
    accessible name.
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
        f'<button type="button" class="tb-btn add-speaker">{_ICON_PLUS}'
        f'<span>{add_label}</span></button>'
    )
    title = html.escape(strings.get("speakers", "Speakers"))
    return (
        f'<div class="speakers" data-file="{file_index}">'
        f'<span class="speakers-title">{title}</span>'
        + "".join(rows) + apply_all + add_speaker + "</div>"
    )


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
            f'{_ICON_PLAY}<span dir="ltr">{format_range(turn.start, turn.end)}</span></button>'
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
        header_parts.append(
            f'<button type="button" class="spk" data-speaker="{turn.speaker}"'
            f' data-palette="{palette}" data-fallback="{label}"'
            f' aria-haspopup="true" aria-expanded="false">{label}</button>'
        )

    copy_label = html.escape(strings.get("copy_turn", "Copy this turn"))
    actions = (
        f'<span class="turn-actions"><button class="icon-btn copy-turn"'
        f' aria-label="{copy_label}">{_ICON_COPY}</button></span>'
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


def _render_plain_html(strings: Dict[str, str]) -> str:
    """
    The copy-out panel.

    Always visible, not collapsed inside a <details> - it was the thing this
    document gets used for most (pasting the whole recording somewhere else)
    and burying the most-used feature one click below a "Plain text" summary
    line was the wrong trade. Rebuilt from the live DOM on every edit, so it
    can never drift from the cards above it.
    """
    def s(key: str, fallback: str) -> str:
        return html.escape(strings.get(key, fallback))

    return f"""<section class="plain">
<h2 class="plain-title"><span>{s('plain_text', 'Plain text')}</span>
<span class="summary-hint">{s('plain_hint', 'to paste into another app')}</span></h2>
<div class="plain-controls">
<label><input type="checkbox" class="opt-ts" checked> {s('opt_timestamps', 'Timestamps')}</label>
<label><input type="checkbox" class="opt-spk" checked> {s('opt_speakers', 'Speaker names')}</label>
<button class="tb-btn copy-all">{_ICON_COPY}<span>{s('copy_all', 'Copy all')}</span></button>
</div>
<pre class="plain-text" tabindex="0"></pre>
</section>"""
