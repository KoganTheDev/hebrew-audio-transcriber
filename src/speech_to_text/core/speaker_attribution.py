"""Turning speaker-labelled time spans into speaker-labelled transcript segments.

The diarizer (core/diarization.py) says who spoke when; the transcriber says
what was said when. Neither knows about the other, and their boundaries do
not line up, so joining them is its own problem with its own failure modes -
which is why it lives here rather than inside the engine module.

Nothing here imports an engine, a model or onnxruntime: it is arithmetic over
spans and word timings, so every decision below is unit-testable without a
model file.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING

from speech_to_text import config
from speech_to_text.core.segments import Segment, Word

if TYPE_CHECKING:
    # Type-only: core/diarization.py imports this module at runtime to
    # re-export assign_speakers, so a runtime import back would be a cycle.
    # Nothing here constructs a SpeakerSpan - it only reads .speaker and
    # calls .overlap() - so the annotation is all that is needed.
    from speech_to_text.core.diarization import SpeakerSpan

# Re-exported from config so the tuning value lives with the other
# diarization knobs, while this module-level name (which callers and tests
# already use) keeps working. The two must not drift - tests assert they are
# the same object.
MIN_SPEAKER_RUN_WORDS = config.DIARIZATION_MIN_SPEAKER_RUN_WORDS


def assign_speakers(
    segments: Sequence[Segment],
    spans: Sequence["SpeakerSpan"],
    min_run_words: int = MIN_SPEAKER_RUN_WORDS,
) -> list[Segment]:
    """Attach a speaker to each transcript segment, splitting where the speaker
    changes mid-segment.

    Works at word level, not segment level. Whisper's segment boundaries are
    decided by its decoder and have no relationship to who is talking, so a
    speaker change lands mid-segment routinely. Attributing whole segments by
    their overall time span would smear every such change across an entire
    turn, and even majority-voting the whole segment to one label throws the
    minority words' speaker away. Instead each word is matched to the span it
    overlaps most, and consecutive words that agree become one sub-segment -
    so a straddling segment is cut into two (or more) at the word boundary
    where the speaker actually changed, rather than losing that boundary.

    Segments with no word timings (or no overlapping span at all) fall back to
    matching on the segment's own span, and stay None if even that fails.
    Leaving a segment unattributed is better than guessing: the renderer simply
    omits the label.

    Mutation contract: the returned list is always new, and a split segment's
    pieces are new Segment objects, but an UNSPLIT segment has its `.speaker`
    set in place and is returned as the same object. So `segments is not
    result` always holds while `segments[i] is result[j]` may still be true.
    """
    if not spans:
        return list(segments)

    result: list[Segment] = []
    for segment in segments:
        result.extend(_split_segment(segment, spans, min_run_words))
    return result


def _split_segment(
    segment: Segment,
    spans: Sequence["SpeakerSpan"],
    min_run_words: int = MIN_SPEAKER_RUN_WORDS,
) -> list[Segment]:
    """Attribute one segment, splitting it if a real speaker change is found."""
    if not segment.words:
        # No word timings at all - the per-channel stereo path never carries
        # them, and neither does a segment faster-whisper emitted without
        # word_timestamps. Only the segment's own span is available.
        segment.speaker = _best_speaker(spans, segment.start, segment.end)
        return [segment]

    labels = [_best_speaker(spans, word.start, word.end) for word in segment.words]

    if all(label is None for label in labels):
        # Every word missed every span - e.g. the whole segment falls in a
        # gap min_duration_on/off dropped. Leave it unattributed rather than
        # inventing a label from nothing.
        segment.speaker = None
        return [segment]

    # A word with no overlap of its own (a rounding gap at a span boundary,
    # or a span dropped by min_duration_on) must not start a run or a
    # None-labelled sub-segment; it is filled in from its neighbours instead.
    filled = _fill_unmatched(labels, segment.words)
    runs = _coalesce_adjacent(_merge_short_runs(_runs(filled), min_run_words, segment.words, spans))

    if len(runs) == 1:
        segment.speaker = runs[0][2]
        return [segment]

    pieces: list[Segment] = []
    last_index = len(runs) - 1
    for i, (start_idx, end_idx, label) in enumerate(runs):
        run_words = segment.words[start_idx:end_idx]
        # Concatenating word texts reproduces the segment text exactly:
        # faster-whisper builds each word's text from tokenizer.decode() on
        # that word's token slice, so it already carries the leading space
        # separating it from its neighbour (verified against the installed
        # version). Strip the ends only - collapsing internal whitespace would
        # change spacing the model chose.
        text = "".join(word.text for word in run_words).strip()
        # Endpoints: the first piece keeps the segment's own start (which can
        # lead the first word, e.g. VAD padding) and the last piece keeps its
        # own end, for the same reason. Interior boundaries use the word
        # timings themselves, since that word boundary is the split point.
        start = segment.start if i == 0 else run_words[0].start
        end = segment.end if i == last_index else run_words[-1].end
        pieces.append(
            Segment(start=start, end=end, text=text, words=list(run_words), speaker=label)
        )
    return pieces


def _label_coverage(
    spans: Sequence["SpeakerSpan"], label: int | None, start: float, end: float
) -> float:
    """How much of [start, end) the given speaker's spans cover, in seconds."""
    if label is None:
        return 0.0
    return sum(span.overlap(start, end) for span in spans if span.speaker == label)


def _fill_unmatched(labels: Sequence[int | None], words: Sequence[Word]) -> list[int | None]:
    """Carry a real label over words that overlap no span, from whichever
    labelled neighbour is nearer IN TIME - and only across a short gap.

    Distance, not direction. Forward-filling from whoever spoke last is the
    obvious implementation and it is biased: it makes a transcript read as
    though one speaker does all the talking. A word 40ms after A stopped and
    900ms before B starts belongs with A; the same word 900ms after A and 40ms
    before B belongs with B, which forward-fill gets backwards every time.

    Neighbours are read from the ORIGINAL labels, never from ones this function
    has already filled in, so a borrowed label cannot chain across a run of gap
    words - each is decided on its own distance to real evidence.

    Beyond config.DIARIZATION_MAX_FILL_GAP_SECONDS the word keeps no label.
    Attributing across a two-second silence is guessing, and an unattributed
    word renders without a speaker rather than under the wrong one.
    """
    filled: list[int | None] = list(labels)

    # Nearest real label to each side, indices into the ORIGINAL labels.
    n = len(labels)
    left_of: list[int | None] = [None] * n
    right_of: list[int | None] = [None] * n
    seen: int | None = None
    for i in range(n):
        left_of[i] = seen
        if labels[i] is not None:
            seen = i
    seen = None
    for i in range(n - 1, -1, -1):
        right_of[i] = seen
        if labels[i] is not None:
            seen = i

    for i, label in enumerate(labels):
        if label is not None:
            continue
        li, ri = left_of[i], right_of[i]
        # A word can sit before every labelled word or after all of them, in
        # which case only one side is a candidate. float("inf") lets the same
        # comparison handle that without a special case - and if the only
        # candidate is too far away, the ceiling below still rejects it.
        gap_left = words[i].start - words[li].end if li is not None else float("inf")
        gap_right = words[ri].start - words[i].end if ri is not None else float("inf")
        # Negative gaps mean the word timings themselves overlap; clamp so
        # "touching" and "overlapping" both read as zero distance.
        gap_left = max(0.0, gap_left)
        gap_right = max(0.0, gap_right)

        if min(gap_left, gap_right) > config.DIARIZATION_MAX_FILL_GAP_SECONDS:
            continue
        # <= so an exact tie prefers the left.
        nearer = li if gap_left <= gap_right else ri
        if nearer is None:
            # Only reachable if the chosen side had no labelled neighbour at
            # all, whose gap is infinite and would have been rejected above.
            continue
        filled[i] = labels[nearer]

    return filled


def _runs(labels: Sequence[int | None]) -> list[list]:
    """Consecutive equal-label stretches, as mutable [start, end, label]."""
    runs: list[list] = []
    start = 0
    for i in range(1, len(labels) + 1):
        if i == len(labels) or labels[i] != labels[start]:
            runs.append([start, i, labels[start]])
            start = i
    return runs


def _is_real_interjection(
    run: Sequence, words: Sequence[Word], spans: Sequence["SpeakerSpan"]
) -> bool:
    """Whether a too-short run is a genuine short turn rather than a boundary slip.

    The run-length floor exists because one stray word usually means the
    diarizer clipped a span boundary by a few tens of milliseconds. But real
    conversation is full of one-word turns - "כן", "לא", "נכון" - and folding
    every one into the previous speaker is the most visible way attribution
    goes wrong: the interjecting speaker simply disappears.

    So a run keeps its place when the diarizer is positively asserting a
    different speaker across essentially the whole word rather than clipping
    its edge: long enough to carry a real utterance, and that speaker's spans
    cover nearly all of it.
    """
    start_idx, end_idx, label = run[0], run[1], run[2]
    if label is None:
        return False
    run_words = words[start_idx:end_idx]
    if not run_words:
        return False
    start, end = run_words[0].start, run_words[-1].end
    duration = end - start
    if duration < config.DIARIZATION_INTERJECTION_MIN_SECONDS:
        return False
    covered = _label_coverage(spans, label, start, end)
    return covered >= config.DIARIZATION_INTERJECTION_MIN_COVERAGE * duration


def _run_support(
    run: Sequence,
    label: int | None,
    words: Sequence[Word],
    spans: Sequence["SpeakerSpan"],
) -> float:
    """How much the run's own words support this label, in seconds."""
    if label is None or not words:
        return 0.0
    run_words = words[run[0] : run[1]]
    if not run_words:
        return 0.0
    return _label_coverage(spans, label, run_words[0].start, run_words[-1].end)


def _weakest_mergeable(
    runs: Sequence[Sequence],
    min_words: int,
    words: Sequence[Word],
    spans: Sequence["SpeakerSpan"],
) -> int | None:
    """Index of the shortest run that is too short to stand on its own, if any.

    Shortest first, ties by position, so which run gets absorbed is driven by
    how weak the evidence is rather than by where it sits in the segment - a
    left-to-right scan makes the outcome depend on position.
    """
    candidates = [
        i
        for i, run in enumerate(runs)
        if run[1] - run[0] < min_words
        and run[2] is not None
        and not _is_real_interjection(run, words, spans)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda k: (runs[k][1] - runs[k][0], k))


def _fold_left(
    runs: Sequence[Sequence],
    index: int,
    words: Sequence[Word],
    spans: Sequence["SpeakerSpan"],
) -> bool | None:
    """Which neighbour run at `index` to fold into: True left, False right.

    None means neither neighbour is eligible - absent or None-labelled - so the
    run stays put rather than being forced onto a None run.

    The run's own words are re-scored against each neighbour's label by real
    span overlap and the better-supported side wins; a tie goes to the longer
    neighbour, then to the left. Always folding left, the obvious
    implementation, biases every decision toward the earlier speaker.
    """
    left = runs[index - 1] if index > 0 else None
    right = runs[index + 1] if index + 1 < len(runs) else None
    if left is not None and left[2] is None:
        left = None
    if right is not None and right[2] is None:
        right = None

    if left is None and right is None:
        return None
    if left is None:
        return False
    if right is None:
        return True

    left_score = _run_support(runs[index], left[2], words, spans)
    right_score = _run_support(runs[index], right[2], words, spans)
    if left_score != right_score:
        return left_score > right_score
    return bool((left[1] - left[0]) >= (right[1] - right[0]))


def _merge_short_runs(
    runs: list[list],
    min_words: int,
    words: Sequence[Word] = (),
    spans: Sequence["SpeakerSpan"] = (),
) -> list[list]:
    """Fold any run shorter than min_words into a neighbour so it cannot, on its
    own, split the segment (see MIN_SPEAKER_RUN_WORDS) - unless it is a real
    interjection, which keeps its own run.

    None-labelled runs are left alone in both directions: they are words
    _fill_unmatched deliberately declined to attribute (see its docstring),
    and quietly merging them into a labelled neighbour would reinstate exactly
    the guess it refused to make.

    words/spans default to empty so a caller with neither still gets the
    length-based behaviour: no run can then qualify as an interjection, and
    overlap scoring falls back to the neighbour-length tie-break.
    """
    if len(runs) <= 1:
        return runs

    merged = [list(run) for run in runs]

    while len(merged) > 1:
        i = _weakest_mergeable(merged, min_words, words, spans)
        if i is None:
            break

        take_left = _fold_left(merged, i, words, spans)
        if take_left is None:
            break

        if take_left:
            merged[i - 1][1] = merged[i][1]
        else:
            merged[i + 1][0] = merged[i][0]
        del merged[i]

    return merged


def _coalesce_adjacent(runs: list[list]) -> list[list]:
    """Merge neighbouring runs that ended up with the same label."""
    if not runs:
        return runs
    out = [list(runs[0])]
    for start, end, label in runs[1:]:
        if label == out[-1][2]:
            out[-1][1] = end
        else:
            out.append([start, end, label])
    return out


def _best_speaker(spans: Sequence["SpeakerSpan"], start: float, end: float) -> int | None:
    """The speaker whose spans overlap [start, end] the most, if any."""
    totals: dict[int, float] = {}
    for span in spans:
        overlap = span.overlap(start, end)
        if overlap > 0:
            totals[span.speaker] = totals.get(span.speaker, 0.0) + overlap
    if not totals:
        return None
    return max(totals.items(), key=lambda kv: kv[1])[0]
