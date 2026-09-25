"""
Turn a colour-coded .docx transcript into an RTTM diarization reference, by
transcribing the matching audio with this app's own Transcriber and aligning
each coloured docx line onto the resulting word timings.

Why this exists: tests/eval/transcript_to_rttm.py turns THIS APP's own
exported transcript into ground truth, because the app already attaches
precise per-word timings to every bubble. A .docx a human typed up by hand
has no timings at all - only text, coloured by speaker, and a handful of
"M:SS - M:SS" block markers roughly every ~24s (a human glancing at a
player's clock every so often, not a timing log). This script is what
recovers usable turn timing from that: it transcribes the real audio itself
(Whisper's segment/word timestamps are precise even though the docx's own
timestamps are not), then, INSIDE each docx block's known ~20-30s window,
matches the block's coloured lines onto the transcribed words by text -
matching a sentence inside a known ~30s span is tractable; matching it
against an entire 5-30 minute recording with no window would not be.

Colour encoding (verified by hand against two real files, see the header
paragraph parsing below): a "הדוברים: NAME1 NAME2" paragraph whose runs
colour NAME1 purple (RGB A02B93) and leave NAME2 in the default run colour
(no w:color element at all - python-docx reports this as
run.font.color.type is None, not "the colour black"). Every speech
paragraph after it is coloured the same way, run by run. This is parsed
generically (colour -> name is read out of the header, not hardcoded) but
then ASSERTED against the one layout actually seen, so a differently
structured file fails loudly here instead of silently mis-attributing every
line to the wrong speaker.

Alignment approach: difflib.SequenceMatcher (stdlib, not a hand-rolled
matcher) over hebrew_metrics.tokens() - the same nikud/final-letter/
punctuation normalisation the WER harness uses, so "is this the same word"
means the same thing here as everywhere else in this project. Each block's
docx lines are flattened into one normalised token stream; the transcribed
words whose timestamps fall inside the block's window (padded by
--pad seconds each side, since a human's clock-glance is not frame-accurate)
are flattened into another. SequenceMatcher's *equal* opcodes are the only
ones trusted for timing - a "replace" opcode means the texts disagree at
that point (transcription slip, a doc typo, or genuinely misheard audio) and
contributes no timing evidence. A line whose matched-token coverage falls
below --min-line-coverage is dropped rather than guessed at (see
--min-line-coverage's help for why a low-confidence timestamp is worse than
no fixture).

Turn merging is NOT reimplemented here: aligned lines become
transcript_to_rttm.Bubble objects and are merged into turns by that module's
own merge_turns() (added in 5eed9e0, same 0.5s DIARIZATION_MIN_DURATION_OFF
rule), then rendered with its turns_to_rttm(). One RTTM writer, one merge
rule, for both this app's own exports and hand-typed .docx transcripts.
"""

from __future__ import annotations

import argparse
import difflib
import os
import re
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from tests.eval.hebrew_metrics import tokens as hebrew_tokens  # noqa: E402
from tests.eval.transcript_to_rttm import (  # noqa: E402
    DEFAULT_MAX_MERGE_GAP_SECONDS,
    Bubble,
    Turn,
    merge_turns,
    turns_to_rttm,
)

# Bidi isolate characters wrapping every "M:SS - M:SS" block marker in the
# source .docx (U+2066 LEFT-TO-RIGHT ISOLATE / U+2069 POP DIRECTIONAL
# ISOLATE) - Word wraps a left-to-right run embedded in RTL text in these so
# the digits and the dash render in the right order. They are not optional
# punctuation to strip; they are literally how the timestamp is delimited.
TIMESTAMP_RE = re.compile(r"⁦\s*(\d{1,3}):(\d{2})\s*-\s*(\d{1,3}):(\d{2})\s*⁩")

DEFAULT_PAD_SECONDS = 3.0
"""
The docx's own block timestamps are a human glancing at a player's clock,
not a timing log - they can be off by a second or two at either edge, and a
sentence can start just before or finish just after the stated window. This
pads the hard window so a word straddling the boundary is still visible to
the matcher, without opening the window so wide that it starts pulling in
the NEXT block's words too (blocks are ~20-30s apart; 3s of pad on each side
cannot bridge that gap).
"""

DEFAULT_MIN_LINE_COVERAGE = 0.5
"""
Fraction of a docx line's normalised tokens that must land in a SequenceMatcher
*equal* opcode against the windowed transcription before the line is trusted
enough to time. Below this, more than half the line did not match anything
the model transcribed in that window - transcription slip, a doc typo, or a
genuinely wrong block boundary - and guessing a timestamp from the minority
that did match would silently manufacture false precision. The line is
dropped and counted, not guessed.
"""


@dataclass
class Block:
    start: float
    end: float
    lines: list[tuple[str, str]] = field(default_factory=list)  # (speaker, text)


def _run_color(run) -> str:
    """'DEFAULT' when the run has no explicit colour (python-docx reports
    color.type as None in that case - there is no w:color element at all in
    the XML, not a colour of black), else the uppercase RGB hex string."""
    color = run.font.color
    if color is None or color.type is None or color.rgb is None:
        return "DEFAULT"
    return str(color.rgb).upper()


def parse_speaker_header(paragraph) -> dict[str, str]:
    """
    Parse a "הדוברים: NAME1 NAME2" header paragraph into {colour: name}.

    Generic by construction (reads whatever colours/names are actually
    there) but ASSERTED below, in parse_docx, against the one layout these
    two source files actually use - purple (A02B93) for the first-named
    speaker, DEFAULT for the second, named נאור. A file that doesn't match
    fails loudly instead of silently mislabelling every line.
    """
    mapping: dict[str, str] = {}
    for run in paragraph.runs:
        text = run.text.strip()
        if not text or text == "הדוברים:":
            continue
        color = _run_color(run)
        # A run can hold more than one whitespace-separated name only if
        # Word merged two identically-coloured names into one run - not seen
        # in either source file, but split defensively rather than silently
        # dropping a second name into the same colour bucket.
        for name in text.split():
            mapping.setdefault(color, name)
    return mapping


def _split_leading_timestamp(paragraph) -> tuple[tuple[float, float] | None, list[tuple[str, str]]]:
    """
    Return (block_times_or_None, [(text_fragment, colour), ...]).

    block_times is set when the paragraph starts with a "M:SS - M:SS" block
    marker (the normal case: an entire paragraph is just the marker). The
    fragment list holds whatever text follows the marker in the SAME
    paragraph - normally empty, but tests#3 has 2 lines where a marker is
    fused onto the front of the next speech line with no blank paragraph in
    between (see the module docstring's coverage note). Colour is read per
    fragment because a fused line's leading timestamp runs and its trailing
    speech runs are different runs with (usually) different colours - only
    the speech runs should count toward that line's majority colour.
    """
    runs = paragraph.runs
    full_text = "".join(r.text for r in runs)
    match = TIMESTAMP_RE.match(full_text)
    if not match:
        return None, [(r.text, _run_color(r)) for r in runs]

    minutes1, seconds1, minutes2, seconds2 = (int(g) for g in match.groups())
    times = (minutes1 * 60 + seconds1, minutes2 * 60 + seconds2)

    remainder_start = match.end()
    fragments: list[tuple[str, str]] = []
    offset = 0
    for run in runs:
        run_start, run_end = offset, offset + len(run.text)
        if run_end > remainder_start:
            piece = run.text[max(0, remainder_start - run_start) :]
            if piece:
                fragments.append((piece, _run_color(run)))
        offset = run_end
    return times, fragments


def _majority_color(fragments: list[tuple[str, str]]) -> str | None:
    """Colour with the most non-whitespace characters among a line's run
    fragments - the fallback for the (rare) line whose runs disagree, e.g.
    because a trailing punctuation run kept the paragraph's default colour
    instead of inheriting the sentence's speaker colour."""
    weights: dict[str, int] = {}
    for text, color in fragments:
        weight = len(text.strip())
        if weight:
            weights[color] = weights.get(color, 0) + weight
    if not weights:
        return None
    return max(weights.items(), key=lambda kv: kv[1])[0]


def parse_docx(path: str) -> tuple[dict[str, str], list[Block]]:
    """
    Parse a colour-coded .docx transcript into (colour -> speaker name,
    list of Block). See the module docstring for the format this expects.
    """
    import docx

    document = docx.Document(path)
    paragraphs = document.paragraphs
    if not paragraphs:
        raise ValueError(f"{path}: no paragraphs found")

    color_to_speaker = parse_speaker_header(paragraphs[0])

    # This is the hard-coded expectation from the module docstring, verified
    # against both real source files - asserted, not assumed, so a
    # differently-authored docx fails here instead of mis-attributing every
    # line silently.
    names = list(color_to_speaker.values())
    if (
        len(color_to_speaker) != 2
        or "DEFAULT" not in color_to_speaker
        or color_to_speaker["DEFAULT"] != "נאור"
        or "A02B93" not in color_to_speaker
        or names[0] == "נאור"
    ):
        raise ValueError(
            f"{path}: header speaker/colour mapping did not match the expected "
            f"layout (purple A02B93 = first-named speaker, DEFAULT = נאור). "
            f"Got: {color_to_speaker!r}"
        )

    blocks: list[Block] = []
    current: Block | None = None
    for paragraph in paragraphs[1:]:
        if not paragraph.text.strip():
            continue
        times, fragments = _split_leading_timestamp(paragraph)
        if times is not None:
            current = Block(start=float(times[0]), end=float(times[1]))
            blocks.append(current)
            remainder = "".join(text for text, _ in fragments).strip()
            if not remainder:
                continue
            fragments = [(t, c) for t, c in fragments if t.strip()]
        if current is None:
            raise ValueError(f"{path}: speech text before any block marker: {paragraph.text!r}")
        color = _majority_color(fragments)
        speaker = color_to_speaker.get(color)
        if speaker is None:
            raise ValueError(
                f"{path}: run colour {color!r} is not in the header's colour map "
                f"{color_to_speaker!r} - paragraph: {paragraph.text!r}"
            )
        text = "".join(t for t, _ in fragments).strip()
        if text:
            current.lines.append((speaker, text))

    return color_to_speaker, blocks


# --- alignment ---------------------------------------------------------


@dataclass
class _Word:
    start: float
    end: float
    text: str


def _flatten_words(segments) -> list[_Word]:
    return [_Word(w.start, w.end, w.text) for seg in segments for w in seg.words]


DEFAULT_MAX_INTRA_BLOCK_FILL_GAP = 0.0
"""
Tried and measured OFF by default: extending a matched line's end to meet
the next confident line's start at their midpoint (bridging the silence a
trailing unmatched filler word leaves uncovered) was tested against the
test#1 validation (Deliverable 2) and made reconstruction WORSE, not better
- missed_speech dropped modestly (112.06s -> 102.54s) but false_alarm more
than tripled (13.70s -> 47.84s), for a net DER of 0.3442 versus 0.2846
without it. Most inter-line gaps inside a block turn out to be real pauses
(a genuine silence, or the other speaker's own untranscribed murmur), not an
alignment artifact - bridging them manufactures speech that was never
spoken more often than it recovers speech that was. Left in as a documented,
disabled knob (0.0 disables it entirely) rather than deleted, so a future
attempt to fix the missed-speech gap doesn't have to rediscover that the
obvious fix does not work.
"""


def _match_block_lines(
    block: Block, window_words: list[_Word], min_line_coverage: float
) -> list[tuple[float, float] | None]:
    """
    SequenceMatcher a block's lines against its windowed words. Returns one
    (start, end) or None (below --min-line-coverage) per line, in line order.
    """
    doc_tokens: list[str] = []
    doc_line_of: list[int] = []
    line_token_counts: list[int] = []
    for line_index, (_speaker, text) in enumerate(block.lines):
        line_tokens = hebrew_tokens(text)
        line_token_counts.append(len(line_tokens))
        doc_tokens.extend(line_tokens)
        doc_line_of.extend([line_index] * len(line_tokens))

    # hyp_tokens: flat token stream tagged with the source word's span. A
    # single Whisper "word" can normalise to 0 tokens (pure punctuation) or,
    # rarely, more than 1 - either way every token it produces inherits that
    # same word's (start, end).
    hyp_tokens: list[str] = []
    hyp_span_of: list[tuple[float, float]] = []
    for word in window_words:
        for token in hebrew_tokens(word.text):
            hyp_tokens.append(token)
            hyp_span_of.append((word.start, word.end))

    line_spans: list[list[tuple[float, float]]] = [[] for _ in block.lines]
    line_matched_tokens = [0] * len(block.lines)
    if doc_tokens and hyp_tokens:
        matcher = difflib.SequenceMatcher(None, doc_tokens, hyp_tokens, autojunk=False)
        for opcode, a_lo, a_hi, b_lo, _b_hi in matcher.get_opcodes():
            if opcode != "equal":
                continue
            for offset in range(a_hi - a_lo):
                doc_index = a_lo + offset
                hyp_index = b_lo + offset
                line_index = doc_line_of[doc_index]
                line_spans[line_index].append(hyp_span_of[hyp_index])
                line_matched_tokens[line_index] += 1

    line_bounds: list[tuple[float, float] | None] = [None] * len(block.lines)
    for line_index in range(len(block.lines)):
        total = line_token_counts[line_index]
        spans = line_spans[line_index]
        coverage = (line_matched_tokens[line_index] / total) if total else 0.0
        if not spans or coverage < min_line_coverage:
            continue
        line_bounds[line_index] = (min(s for s, _e in spans), max(e for _s, e in spans))
    return line_bounds


def _fill_intra_block_gaps(line_bounds: list[tuple[float, float] | None], max_gap: float) -> None:
    """Midpoint gap-fill between adjacent confident lines, in place - see
    DEFAULT_MAX_INTRA_BLOCK_FILL_GAP for why this defaults to disabled."""
    for i in range(len(line_bounds) - 1):
        left, right = line_bounds[i], line_bounds[i + 1]
        if left is None or right is None:
            continue
        start_i, end_i = left
        start_j, end_j = right
        gap = start_j - end_i
        if 0 < gap <= max_gap:
            midpoint = end_i + gap / 2
            line_bounds[i] = (start_i, midpoint)
            line_bounds[i + 1] = (midpoint, end_j)


def align_blocks(
    blocks: list[Block],
    segments,
    pad: float = DEFAULT_PAD_SECONDS,
    min_line_coverage: float = DEFAULT_MIN_LINE_COVERAGE,
    max_intra_block_fill_gap: float = DEFAULT_MAX_INTRA_BLOCK_FILL_GAP,
) -> tuple[list[Bubble], int, int]:
    """
    Align every block's coloured lines onto transcribed word timings.

    Returns (bubbles, matched_line_count, dropped_line_count,
    scored_regions). See the
    module docstring for the SequenceMatcher approach and why only *equal*
    opcodes are trusted for timing, and DEFAULT_MAX_INTRA_BLOCK_FILL_GAP for
    why the midpoint gap-fill it also supports is disabled by default.
    """
    words = _flatten_words(segments)
    bubbles: list[Bubble] = []
    scored: list[tuple[float, float]] = []
    matched = 0
    dropped = 0

    for block in blocks:
        if not block.lines:
            continue
        window_lo, window_hi = block.start - pad, block.end + pad
        window_words = [w for w in words if w.end > window_lo and w.start < window_hi]

        line_bounds = _match_block_lines(block, window_words, min_line_coverage)
        _fill_intra_block_gaps(line_bounds, max_intra_block_fill_gap)

        block_dropped = 0
        for line_index, (speaker, _text) in enumerate(block.lines):
            bounds = line_bounds[line_index]
            if bounds is None:
                dropped += 1
                block_dropped += 1
                continue
            bubbles.append(Bubble(start=bounds[0], end=bounds[1], speaker=speaker))
            matched += 1

        # A block that lost a line has a HOLE: the human transcript says
        # somebody was speaking somewhere in this window, and the reference
        # cannot say where or who. Scoring it would count correctly-detected
        # speech as invented, so the whole block is withheld from scoring -
        # not just the missing line, because nothing identifies which part of
        # the window the dropped line occupied.
        if not block_dropped:
            scored.append((block.start - pad, block.end + pad))

    bubbles.sort(key=lambda b: b.start)
    return bubbles, matched, dropped, _merge_regions(scored)


def _merge_regions(regions: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sorted, non-overlapping scored regions, so clipping stays cheap."""
    merged: list[tuple[float, float]] = []
    for start, end in sorted(regions):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


# read_rttm (tests/eval/diarization_metrics.py) only recognises rows whose
# first field is exactly "SPEAKER", so these lines ride along harmlessly.
_HEADER_TEMPLATE = """# RTTM generated by tests/eval/docx_to_rttm.py - a hand-typed .docx
# transcript aligned onto this app's own transcription, NOT an export of
# this app. See that script's module docstring for the method.
# Source docx:  {docx}
# Source audio: {audio}
#
# TRUSTWORTHY: who said each line. The speakers come from the docx's own
# colour convention, typed by a human listening to the recording.
#
# APPROXIMATE: when. Turn boundaries are Whisper's word timings, matched to
# the docx text inside each of its ~24s block markers. That inflates absolute
# DER against a hand-drawn reference like AMI's, so compare configurations
# ON THIS FIXTURE against each other - do not compare these absolute numbers
# with AMI's.
#
# Coverage: {matched}/{total} lines matched ({coverage:.1%}); {dropped} dropped
# below --min-line-coverage={min_line_coverage}, rather than timed from a
# minority of matched tokens.
#
# SCORE THIS WITH THE .uem BESIDE IT. A block that lost a line is a hole -
# somebody spoke in that window and this file cannot say who or where - so
# the .uem withholds it. Scored as silence instead, speech the diarizer
# correctly found there counts as invented; measured at 218s of one of these
# two fixtures. compare_diarization.py picks the .uem up automatically.
#
# Consecutive same-speaker lines merge into one turn only across a gap of at
# most {max_merge_gap:.1f}s (DIARIZATION_MIN_DURATION_OFF, src/config/diarization.py).
"""


def build_rttm_from_blocks(
    blocks: list[Block],
    segments,
    file_id: str,
    docx_path: str = "",
    audio_path: str = "",
    pad: float = DEFAULT_PAD_SECONDS,
    min_line_coverage: float = DEFAULT_MIN_LINE_COVERAGE,
    max_merge_gap: float = DEFAULT_MAX_MERGE_GAP_SECONDS,
) -> tuple[str, int, int, list[tuple[float, float]]]:
    """Align + merge + render, provenance header included.

    Returns (rttm_text, matched, dropped, scored_regions). The regions are
    the blocks where every line matched - see align_blocks() for why a block
    that lost one is withheld from scoring entirely.

    The header is generated, not hand-written into the fixture afterwards:
    the first versions of these two fixtures carried provenance somebody
    typed in once, and regenerating them silently dropped it. A caveat that
    survives only until the next regeneration is not documentation.
    """
    bubbles, matched, dropped, scored = align_blocks(
        blocks, segments, pad=pad, min_line_coverage=min_line_coverage
    )
    turns: list[Turn] = merge_turns(bubbles, speaker_names={}, max_merge_gap=max_merge_gap)
    total = matched + dropped
    header = _HEADER_TEMPLATE.format(
        docx=docx_path,
        audio=audio_path,
        matched=matched,
        total=total,
        coverage=(matched / total if total else 0.0),
        dropped=dropped,
        min_line_coverage=min_line_coverage,
        max_merge_gap=max_merge_gap,
    )
    return header + turns_to_rttm(turns, file_id), matched, dropped, scored


# --- validation (Deliverable 2) -----------------------------------------


def build_synthetic_blocks(
    true_turns: list[tuple[float, float, str]],
    segments,
    block_seconds: float,
) -> list[Block]:
    """
    Reconstruct the SHAPE of a docx input from known-good RTTM turns, for
    validating the aligner against ground truth (Deliverable 2): bucket each
    true turn into the ~block_seconds window its start falls in (discarding
    its real start/end, exactly as a docx block marker would - we keep only
    which ~24s window it happened in), and recover its spoken text from the
    fresh transcription actually being aligned against, mirroring exactly
    what a real docx line supplies: text plus a coarse time window, nothing
    more.
    """
    words = _flatten_words(segments)
    blocks_by_index: dict[int, Block] = {}
    for start, end, speaker in sorted(true_turns, key=lambda t: t[0]):
        index = int(start // block_seconds)
        block = blocks_by_index.get(index)
        if block is None:
            block = Block(start=index * block_seconds, end=(index + 1) * block_seconds)
            blocks_by_index[index] = block
        text = " ".join(w.text for w in words if w.start < end and w.end > start)
        if text.strip():
            block.lines.append((speaker, text))
    return [blocks_by_index[i] for i in sorted(blocks_by_index)]


def run_validation(
    true_rttm_path: str,
    audio_path: str,
    block_seconds: float,
    pad: float,
    use_cache: bool = True,
) -> int:
    from tests.eval.diarization_metrics import compute_der, read_rttm, speaker_recall

    true_turns = read_rttm(true_rttm_path)
    if not true_turns:
        print(f"No turns in {true_rttm_path}", file=sys.stderr)
        return 1

    print(f"Transcribing {audio_path} for validation ...", flush=True)
    segments = _transcribe(audio_path, use_cache=use_cache)
    if segments is None:
        return 1

    synthetic_blocks = build_synthetic_blocks(true_turns, segments, block_seconds)
    total_lines = sum(len(b.lines) for b in synthetic_blocks)
    print(f"{len(synthetic_blocks)} synthetic block(s), {total_lines} synthetic line(s)")

    bubbles, matched, dropped, _scored = align_blocks(synthetic_blocks, segments, pad=pad)
    turns = merge_turns(bubbles, speaker_names={}, max_merge_gap=DEFAULT_MAX_MERGE_GAP_SECONDS)
    hypothesis = [(t.start, t.end, t.speaker) for t in turns]

    der_result = compute_der(true_turns, hypothesis)
    recall_result = speaker_recall(true_turns, hypothesis)

    print(f"\nReconstruction coverage: {matched}/{matched + dropped} lines matched")
    print(f"Reconstruction DER (hypothesis vs true RTTM): {der_result}")
    print(f"Per-speaker time agreement (speaker_recall): {recall_result}")
    return 0


# --- transcription + CLI -------------------------------------------------

_CACHE_DIR = os.path.join("eval_output", "transcribe_cache")
"""
Transcribing test#3 alone is ~22 minutes of CPU audio - re-running it on
every aligner tweak (pad, min-line-coverage, the gap-fill experiment above)
would burn far more wall clock than the alignment work it is meant to
support. Segment/word timings do not depend on anything downstream of
transcribe() (docx parsing, alignment, RTTM writing all consume the same
frozen Segment list), so they are cached to disk keyed by the audio file's
absolute path and the model repo actually used, and reused across runs
until --no-cache forces a fresh transcription (e.g. after a model change
that should NOT invalidate the cache key, such as compute_type).
"""


def _cache_path(audio_path: str, model_repo: str) -> str:
    import hashlib

    key = hashlib.sha256(f"{os.path.abspath(audio_path)}::{model_repo}".encode()).hexdigest()[:24]
    return os.path.join(_CACHE_DIR, f"{key}.json")


def _segments_to_jsonable(segments) -> list[dict]:
    return [
        {
            "start": seg.start,
            "end": seg.end,
            "text": seg.text,
            "words": [{"start": w.start, "end": w.end, "text": w.text} for w in seg.words],
        }
        for seg in segments
    ]


def _segments_from_jsonable(data: list[dict]):
    from core.segments import Segment, Word

    return [
        Segment(
            start=d["start"],
            end=d["end"],
            text=d["text"],
            words=[Word(start=w["start"], end=w["end"], text=w["text"]) for w in d["words"]],
        )
        for d in data
    ]


def _transcribe(audio_path: str, use_cache: bool = True):
    import json

    from core.transcriber import Transcriber

    transcriber = Transcriber()
    cache_path = _cache_path(audio_path, transcriber.model_repo)
    if use_cache and os.path.exists(cache_path):
        print(f"  cached transcription: {cache_path}", flush=True)
        with open(cache_path, encoding="utf-8") as handle:
            return _segments_from_jsonable(json.load(handle))

    print(f"  model: {transcriber.model_repo}, language: {transcriber.language}", flush=True)
    if not transcriber.load_model():
        print("Model failed to load.", file=sys.stderr)
        return None
    segments = transcriber.transcribe(audio_path)
    if segments is not None and use_cache:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as handle:
            json.dump(_segments_to_jsonable(segments), handle, ensure_ascii=False)
    return segments


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("docx", nargs="?", help="Colour-coded .docx transcript")
    parser.add_argument("audio", nargs="?", help="Matching audio file")
    parser.add_argument("output_rttm", nargs="?", help="Path to write the RTTM to")
    parser.add_argument("--file-id", default=None)
    parser.add_argument("--pad", type=float, default=DEFAULT_PAD_SECONDS)
    parser.add_argument("--min-line-coverage", type=float, default=DEFAULT_MIN_LINE_COVERAGE)
    parser.add_argument(
        "--max-merge-gap",
        type=float,
        default=DEFAULT_MAX_MERGE_GAP_SECONDS,
        help="Same as tests/eval/transcript_to_rttm.py's flag of the same name.",
    )
    parser.add_argument(
        "--validate-rttm",
        default=None,
        help="Deliverable 2 mode: validate the aligner against a KNOWN-GOOD rttm "
        "for --audio instead of converting a docx. docx/output_rttm are ignored.",
    )
    parser.add_argument(
        "--block-seconds",
        type=float,
        default=24.0,
        help="--validate-rttm only: synthetic block width (default: 24, matching the "
        "real docx files' observed block spacing).",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force a fresh transcription instead of reusing eval_output/transcribe_cache/.",
    )
    args = parser.parse_args(argv)
    use_cache = not args.no_cache

    if args.validate_rttm:
        if not args.audio:
            parser.error("--validate-rttm requires --audio's positional slot: audio path")
        return run_validation(
            args.validate_rttm, args.audio, args.block_seconds, args.pad, use_cache=use_cache
        )

    if not (args.docx and args.audio and args.output_rttm):
        parser.error("docx, audio and output_rttm are required unless --validate-rttm is used")

    color_to_speaker, blocks = parse_docx(args.docx)
    total_lines = sum(len(b.lines) for b in blocks)
    print(f"{len(blocks)} block(s), {total_lines} speech line(s), speakers: {color_to_speaker}")

    print(f"Transcribing {args.audio} ...", flush=True)
    segments = _transcribe(args.audio, use_cache=use_cache)
    if segments is None:
        return 1

    file_id = args.file_id or os.path.splitext(os.path.basename(args.output_rttm))[0]
    rttm, matched, dropped, scored = build_rttm_from_blocks(
        blocks,
        segments,
        file_id=file_id,
        docx_path=args.docx,
        audio_path=args.audio,
        pad=args.pad,
        min_line_coverage=args.min_line_coverage,
        max_merge_gap=args.max_merge_gap,
    )
    coverage = matched / total_lines if total_lines else 0.0
    print(f"Alignment coverage: {matched}/{total_lines} lines matched ({coverage:.1%})")
    print(f"Dropped {dropped} line(s) below --min-line-coverage={args.min_line_coverage}")

    with open(args.output_rttm, "w", encoding="utf-8") as handle:
        handle.write(rttm)
    print(f"Wrote {args.output_rttm}")

    # A .uem beside the .rttm, which compare_diarization picks up
    # automatically. Without it the blocks that lost a line are scored as
    # silence, and speech correctly detected there counts as invented - see
    # compute_der()'s `scored` parameter.
    uem_path = os.path.splitext(args.output_rttm)[0] + ".uem"
    with open(uem_path, "w", encoding="utf-8") as handle:
        handle.write(
            "# Scored regions for the RTTM beside this file: the docx blocks in\n"
            "# which EVERY line aligned. A block that lost a line is a hole - the\n"
            "# human transcript says somebody spoke somewhere in that window and\n"
            "# the reference cannot say where or who - so it is withheld rather\n"
            "# than scored as silence. See compute_der()'s `scored` parameter.\n"
        )
        for start, end in scored:
            handle.write(f"{file_id} 1 {start:.2f} {end:.2f}\n")
    total_scored = sum(end - start for start, end in scored)
    print(f"Wrote {uem_path} ({len(scored)} region(s), {total_scored:.0f}s scored)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
